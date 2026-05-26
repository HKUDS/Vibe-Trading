"""
Tests for the new dynamic-path functions in factor_extended.py:
  - _load_candidates
  - _compute_candidate_series
  - run_symbol decision-table (legacy env / missing candidates)

All tests are network-free; real fetchers are mocked or bypassed.

Pytest is run from research/ as:
    cd research && python -m pytest tests/
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Bootstrap: research/ and dashboard/server/ must be on sys.path.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
_REPO_ROOT = _RESEARCH_DIR.parent
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (_RESEARCH_DIR, _DASHBOARD_SCHEMAS):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from factor_extended import _compute_candidate_series, _load_candidates, _run_symbol_dynamic, run_symbol
from schemas import CandidatesManifest, FactorCandidate


# ---------------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------------


def make_candles(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"close": rng.standard_normal(n).cumsum() + 100, "volume": 1000}, index=idx)


def make_funding(n: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="8h", tz="UTC")
    return pd.DataFrame({"funding_rate": rng.standard_normal(n) * 0.001}, index=idx)


def make_oi_hist(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"oi": rng.random(n) * 1e9, "oi_usd": rng.random(n) * 1e10},
        index=idx,
    )


def _valid_candidates_manifest_json(sym: str = "eth") -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "symbol": sym,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_swarm_run": None,
            "candidates": [
                {
                    "name": "funding_z_30d",
                    "formula": "z-score of 30d rolling funding rate",
                    "data_source": "okx_funding",
                    "transform": "z_30d",
                    "expected_ic_sign": "+",
                    "economic_logic": "High funding → crowded longs → mean-revert",
                    "horizons_h": [8, 24],
                    "category": "funding",
                }
            ],
        }
    )


def _make_factor_candidate(**kwargs) -> FactorCandidate:
    defaults = dict(
        name="funding_z_30d",
        formula="z-score of 30d rolling funding rate",
        data_source="okx_funding",
        transform="z_30d",
        expected_ic_sign="+",
        economic_logic="High funding means crowded longs",
        horizons_h=[8, 24],
        category="funding",
    )
    defaults.update(kwargs)
    return FactorCandidate.model_validate(defaults)


# ---------------------------------------------------------------------------
# _load_candidates
# ---------------------------------------------------------------------------


class TestLoadCandidates:
    """_load_candidates(manifests_dir, sym) -> CandidatesManifest | None"""

    # (a) file doesn't exist → returns None
    def test_missing_file_returns_none(self, tmp_path: Path):
        result = _load_candidates(tmp_path, "eth")
        assert result is None

    # (b) valid CandidatesManifest JSON → returns CandidatesManifest
    def test_valid_manifest_returns_object(self, tmp_path: Path):
        path = tmp_path / "candidates_eth.json"
        path.write_text(_valid_candidates_manifest_json("eth"), encoding="utf-8")
        result = _load_candidates(tmp_path, "eth")
        assert isinstance(result, CandidatesManifest)
        assert result.symbol == "eth"
        assert len(result.candidates) == 1

    def test_loaded_candidate_has_expected_fields(self, tmp_path: Path):
        path = tmp_path / "candidates_eth.json"
        path.write_text(_valid_candidates_manifest_json("eth"), encoding="utf-8")
        result = _load_candidates(tmp_path, "eth")
        assert result is not None
        cand = result.candidates[0]
        assert cand.data_source == "okx_funding"
        assert cand.transform == "z_30d"

    def test_uses_sym_name_in_filename(self, tmp_path: Path):
        """If we write eth manifest but query for btc, returns None."""
        path = tmp_path / "candidates_eth.json"
        path.write_text(_valid_candidates_manifest_json("eth"), encoding="utf-8")
        assert _load_candidates(tmp_path, "btc") is None
        assert _load_candidates(tmp_path, "eth") is not None


# ---------------------------------------------------------------------------
# _compute_candidate_series
# ---------------------------------------------------------------------------


class TestComputeCandidateSeries:
    """_compute_candidate_series(cand, candles, funding, oi_hist) -> pd.Series | None"""

    def setup_method(self):
        self.candles = make_candles(200)
        self.funding = make_funding(100)
        self.oi_hist = make_oi_hist(200)

    # (e) data_source="okx_funding", transform="raw" → returns a pd.Series
    def test_okx_funding_raw_returns_series(self):
        cand = _make_factor_candidate(data_source="okx_funding", transform="raw")
        result = _compute_candidate_series(cand, self.candles, self.funding, self.oi_hist)
        assert isinstance(result, pd.Series)
        assert len(result) == len(self.candles)

    # (f) data_source="okx_funding", transform="z_30d" → returns a pd.Series (may have NaN prefix)
    def test_okx_funding_z_30d_returns_series_with_possible_nan(self):
        # z_30d uses rolling(90) on 8h data → needs ~90 funding rows to produce any
        # non-NaN values; with a small window of hourly candles almost all values
        # will be NaN after forward-fill, which is the correct behaviour.
        cand = _make_factor_candidate(data_source="okx_funding", transform="z_30d")
        result = _compute_candidate_series(cand, self.candles, self.funding, self.oi_hist)
        assert isinstance(result, pd.Series)
        assert len(result) == len(self.candles)
        # All-NaN is acceptable for a short window with z_30d (needs 90 periods = 30 days)

    # (g) unknown transform → raises ValueError
    def test_unknown_transform_raises_value_error(self):
        cand = _make_factor_candidate(data_source="okx_funding", transform="exotic_transform")
        with pytest.raises(ValueError, match="transform"):
            _compute_candidate_series(cand, self.candles, self.funding, self.oi_hist)

    def test_okx_candles_raw_returns_series(self):
        cand = _make_factor_candidate(data_source="okx_candles", transform="raw", category="basis")
        result = _compute_candidate_series(cand, self.candles, self.funding, self.oi_hist)
        assert isinstance(result, pd.Series)
        assert len(result) == len(self.candles)

    def test_bybit_oi_raw_returns_series(self):
        cand = _make_factor_candidate(data_source="bybit_oi", transform="raw", category="oi")
        result = _compute_candidate_series(cand, self.candles, self.funding, self.oi_hist)
        assert isinstance(result, pd.Series)

    def test_bybit_oi_empty_returns_none(self):
        """When oi_hist is empty, _compute_candidate_series should return None."""
        cand = _make_factor_candidate(data_source="bybit_oi", transform="raw", category="oi")
        empty_oi = pd.DataFrame(columns=["oi", "oi_usd"])
        result = _compute_candidate_series(cand, self.candles, self.funding, empty_oi)
        assert result is None

    def test_unavailable_data_source_returns_none(self):
        """Sources with status='unavailable' in SOURCE_REGISTRY → returns None."""
        cand = _make_factor_candidate(data_source="coinglass_liq", transform="raw", category="oi")
        result = _compute_candidate_series(cand, self.candles, self.funding, self.oi_hist)
        assert result is None

    def test_result_index_matches_candles_index(self):
        """The returned Series should be aligned to the candle index."""
        cand = _make_factor_candidate(data_source="okx_funding", transform="raw")
        result = _compute_candidate_series(cand, self.candles, self.funding, self.oi_hist)
        assert result is not None
        pd.testing.assert_index_equal(result.index, self.candles.index)


# ---------------------------------------------------------------------------
# run_symbol decision-table (c) and (d)
# ---------------------------------------------------------------------------


def _make_sym_config():
    """Return a minimal SymbolConfig."""
    from pipeline.config import SymbolConfig
    return SymbolConfig(
        name="eth",
        okx_swap="ETH-USDT-SWAP",
        ccxt_bybit="ETHUSDT",
    )


def _make_research_config():
    """Return a minimal ResearchConfig with all required fields."""
    from pipeline.config import FeesConfig, ResearchConfig, SymbolConfig
    return ResearchConfig(
        symbols=(_make_sym_config(),),
        period=30,
        interval="1H",
        data_source="okx",
        engine="daily",
        fees=FeesConfig(maker_rate=0.0002, taker_rate=0.0005, slippage=0.0001),
        horizons_h=(8, 24),
        discovery_cache_days=7,
    )


class TestRunSymbolDecisionTable:
    """run_symbol() decision-table tests — use mocks to avoid network calls."""

    # (c) RESEARCH_LEGACY_FACTORS=1 → calls legacy path, prints "LEGACY MODE (forced via env)"
    def test_legacy_forced_by_env_prints_message(self, tmp_path: Path, capsys, monkeypatch):
        monkeypatch.setenv("RESEARCH_LEGACY_FACTORS", "1")

        sym = _make_sym_config()
        cfg = _make_research_config()

        mock_candles = make_candles(200)
        mock_funding = make_funding(100)
        mock_oi = make_oi_hist(200)
        mock_fng = pd.DataFrame(
            {"fng": np.ones(30)},
            index=pd.date_range("2024-01-01", periods=30, freq="1D", tz="UTC"),
        )
        mock_legacy_results = []

        with (
            patch("factor_extended.fetch_funding_history", return_value=mock_funding),
            patch("factor_extended.fetch_candles", return_value=mock_candles),
            patch("factor_extended.fetch_oi_history_bybit", return_value=mock_oi),
            patch("factor_extended.fetch_fear_greed", return_value=mock_fng),
            patch("factor_extended._run_symbol_legacy", return_value=mock_legacy_results) as mock_legacy,
            patch("factor_extended.build_factor_manifest") as mock_build,
            patch("factor_extended.build_factor_report", return_value="# report"),
        ):
            # build_factor_manifest needs to return a mock that has model_dump_json
            mock_manifest = MagicMock()
            mock_manifest.model_dump_json.return_value = '{"schema_version": 1}'
            mock_build.return_value = mock_manifest

            run_symbol(sym, cfg, tmp_path)

        captured = capsys.readouterr()
        assert "LEGACY MODE (forced via env)" in captured.out
        mock_legacy.assert_called_once()

    # (d) RESEARCH_LEGACY_FACTORS=0 and no candidates file → raises FileNotFoundError
    def test_dynamic_required_but_no_candidates_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("RESEARCH_LEGACY_FACTORS", "0")

        sym = _make_sym_config()
        cfg = _make_research_config()

        mock_candles = make_candles(200)
        mock_funding = make_funding(100)
        mock_oi = make_oi_hist(200)
        mock_fng = pd.DataFrame(
            {"fng": np.ones(30)},
            index=pd.date_range("2024-01-01", periods=30, freq="1D", tz="UTC"),
        )

        with (
            patch("factor_extended.fetch_funding_history", return_value=mock_funding),
            patch("factor_extended.fetch_candles", return_value=mock_candles),
            patch("factor_extended.fetch_oi_history_bybit", return_value=mock_oi),
            patch("factor_extended.fetch_fear_greed", return_value=mock_fng),
        ):
            with pytest.raises(FileNotFoundError, match="candidates_eth.json"):
                run_symbol(sym, cfg, tmp_path)

    # (e) env unset + no candidates file → legacy fallback with "candidates missing" warning
    def test_missing_candidates_falls_back_to_legacy(self, tmp_path: Path, capsys, monkeypatch):
        """When env is unset and no candidates file → legacy fallback with warning."""
        monkeypatch.delenv("RESEARCH_LEGACY_FACTORS", raising=False)
        # No candidates file created in tmp_path

        sym = _make_sym_config()
        cfg = _make_research_config()

        mock_candles = make_candles(200)
        mock_funding = make_funding(100)
        mock_oi = make_oi_hist(200)
        mock_fng = pd.DataFrame(
            {"fng": np.ones(30)},
            index=pd.date_range("2024-01-01", periods=30, freq="1D", tz="UTC"),
        )

        with (
            patch("factor_extended.fetch_funding_history", return_value=mock_funding),
            patch("factor_extended.fetch_candles", return_value=mock_candles),
            patch("factor_extended.fetch_oi_history_bybit", return_value=mock_oi),
            patch("factor_extended.fetch_fear_greed", return_value=mock_fng),
            patch("factor_extended._run_symbol_legacy", return_value=[]) as mock_legacy,
            patch("factor_extended.build_factor_manifest") as mock_build,
            patch("factor_extended.build_factor_report", return_value="# report"),
        ):
            mock_manifest = MagicMock()
            mock_manifest.model_dump_json.return_value = '{"schema_version": 1}'
            mock_build.return_value = mock_manifest

            run_symbol(sym, cfg, tmp_path)

        mock_legacy.assert_called_once()
        captured = capsys.readouterr()
        assert "candidates missing" in captured.out or "LEGACY MODE" in captured.out


# ---------------------------------------------------------------------------
# _run_symbol_dynamic: multiple candidates produce proportional FactorResult output
# ---------------------------------------------------------------------------


def test_dynamic_mode_5_candidates_produce_results(tmp_path: Path):
    """_run_symbol_dynamic processes all candidates and returns FactorResult for each."""
    from lib.factor_metrics import add_forward_returns

    n = 300
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(7)
    candles = pd.DataFrame({"close": rng.standard_normal(n).cumsum() + 100, "volume": 1000}, index=idx)
    funding_idx = pd.date_range("2024-01-01", periods=n // 3, freq="8h", tz="UTC")
    funding = pd.DataFrame({"funding_rate": rng.standard_normal(n // 3) * 0.001}, index=funding_idx)
    oi_hist = pd.DataFrame(columns=["oi", "oi_usd"])  # empty — bybit_oi candidates will be skipped

    # Build df like run_symbol does
    df = pd.DataFrame(index=candles.index)
    df["close"] = candles["close"]
    fund_h = funding.reindex(candles.index, method="ffill").bfill()
    df["funding_rate"] = fund_h["funding_rate"]
    df["oi_change_24h"] = pd.NA
    df["fng"] = 50.0
    cfg = _make_research_config()
    df = add_forward_returns(df, "close", list(cfg.horizons_h))

    candidates = CandidatesManifest(
        schema_version=1,
        symbol="eth",
        generated_at=datetime.now(timezone.utc),
        source_swarm_run=None,
        candidates=[
            _make_factor_candidate(
                name=f"funding_raw_{i}",
                formula="raw funding",
                data_source="okx_funding",
                transform="raw",
                expected_ic_sign="?",
                economic_logic="test",
                horizons_h=[8],
                category="funding",
            )
            for i in range(5)
        ],
    )

    sym = _make_sym_config()
    results = _run_symbol_dynamic(sym, cfg, tmp_path, candidates, funding, candles, oi_hist, df)

    # 5 candidates × 2 horizons (from cfg.horizons_h = (8, 24)) = 10 FactorResult entries
    assert len(results) == 10
    names_returned = {r.factor for r in results}
    assert names_returned == {f"funding_raw_{i}" for i in range(5)}


# ---------------------------------------------------------------------------
# Integration test: parquet + meta exist after dynamic flow
# (skip by default — requires real OKX/Bybit network access)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_dynamic_flow_writes_factor_parquet(tmp_path: Path):
    """After _run_symbol_dynamic, factor_values parquet and meta.json are written.

    This is a skip-by-default integration test.  Run explicitly with:
        pytest -m integration tests/test_factor_extended_dynamic.py
    """
    from lib.factor_metrics import add_forward_returns

    n = 300
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    rng = np.random.default_rng(99)
    candles = pd.DataFrame({"close": rng.standard_normal(n).cumsum() + 100, "volume": 1000}, index=idx)
    funding_idx = pd.date_range("2024-01-01", periods=n // 3, freq="8h", tz="UTC")
    funding = pd.DataFrame({"funding_rate": rng.standard_normal(n // 3) * 0.001}, index=funding_idx)
    oi_hist = pd.DataFrame(columns=["oi", "oi_usd"])

    df = pd.DataFrame(index=candles.index)
    df["close"] = candles["close"]
    fund_h = funding.reindex(candles.index, method="ffill").bfill()
    df["funding_rate"] = fund_h["funding_rate"]
    df["oi_change_24h"] = pd.NA
    df["fng"] = 50.0
    cfg = _make_research_config()
    df = add_forward_returns(df, "close", list(cfg.horizons_h))

    candidates = CandidatesManifest(
        schema_version=1,
        symbol="eth",
        generated_at=datetime.now(timezone.utc),
        source_swarm_run=None,
        candidates=[
            _make_factor_candidate(
                name="funding_raw_0",
                formula="raw funding",
                data_source="okx_funding",
                transform="raw",
                expected_ic_sign="?",
                economic_logic="test",
                horizons_h=[8],
                category="funding",
            )
        ],
    )

    sym = _make_sym_config()
    _run_symbol_dynamic(sym, cfg, tmp_path, candidates, funding, candles, oi_hist, df)

    parquet_path = tmp_path / "factor_values_eth.parquet"
    meta_path = tmp_path / "factor_values_eth.meta.json"

    assert parquet_path.exists(), f"Expected parquet at {parquet_path}"
    assert meta_path.exists(), f"Expected meta.json at {meta_path}"

    import json as _json
    meta = _json.loads(meta_path.read_text())
    assert meta["schema_version"] == 1
    assert "funding_raw_0" in meta["factor_names"]
    assert meta["n_rows"] == n

    import pandas as _pd
    loaded = _pd.read_parquet(parquet_path, engine="pyarrow")
    assert "funding_raw_0" in loaded.columns
    assert len(loaded) == n
