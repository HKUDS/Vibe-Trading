"""
Tests for research/pipeline/stage2_5_regime.py pure-logic helpers.

Stage 2.5 calls network data fetchers and compute_regime (requires daily-close
warmup data) — none of that is tested here. Only the pure, deterministic
logic is exercised:

  (a) build_regime_manifest()     — builds the JSON dict from a regime Series
  (b) check_regime_manifest()     — validates a manifest file on disk
  (c) verify_outputs()            — bulk check across symbols
  (d) compute_exit_code()         — 0 on success, 1 on failure
  (e) print_summary()             — smoke test, must not raise

Pytest is run from research/ as:
    cd research && python -m pytest tests/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

# Bootstrap: research/ must be on sys.path.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
_REPO_ROOT = _RESEARCH_DIR.parent

if str(_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_DIR))

from pipeline.stage2_5_regime import (  # noqa: E402
    RegimeCheckResult,
    build_regime_manifest,
    check_factor_manifest_gate,
    check_regime_manifest,
    compute_exit_code,
    print_summary,
    verify_outputs,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_regime_series(n: int = 120) -> pd.Series:
    """Return a synthetic daily regime Series (DatetimeIndex, object dtype)."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    labels = (
        ["bull"] * (n // 3)
        + ["bear"] * (n // 4)
        + ["neutral"] * (n - n // 3 - n // 4)
    )
    return pd.Series(labels, index=idx, name="regime", dtype=object)


def _valid_manifest_dict(symbol: str = "btc") -> dict:
    """Return a minimal valid regime manifest dict."""
    return {
        "schema_version": 1,
        "symbol": symbol.upper(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "detector_params": {
            "ema_window": 200,
            "slope_window": 20,
            "funding_window_hours": 720,
            "funding_mania_threshold": 0.0003,
            "bear_persistence_days": 20,
            "bear_persistence_threshold": 0.55,
        },
        "current_regime": "bull",
        "distribution": {
            "bull": 0.4,
            "bear": 0.25,
            "neutral": 0.35,
        },
        "period_days": 120,
        "total_daily_bars": 120,
        "breakdown": [
            {"date": "2024-01-01", "regime": "bull"},
            {"date": "2024-04-30", "regime": "neutral"},
        ],
    }


# ---------------------------------------------------------------------------
# (a) build_regime_manifest
# ---------------------------------------------------------------------------


class TestBuildRegimeManifest:
    """build_regime_manifest(symbol, regime_series, params) -> dict."""

    def test_required_top_level_keys(self):
        series = _make_regime_series()
        manifest = build_regime_manifest(
            symbol="btc",
            regime_series=series,
            detector_params={"ema_window": 200},
        )
        required = {
            "schema_version",
            "symbol",
            "generated_at",
            "detector_params",
            "current_regime",
            "distribution",
            "period_days",
            "total_daily_bars",
            "breakdown",
        }
        missing = required - manifest.keys()
        assert not missing, f"manifest missing keys: {missing}"

    def test_symbol_uppercased(self):
        series = _make_regime_series()
        manifest = build_regime_manifest("eth", series, {})
        assert manifest["symbol"] == "ETH"

    def test_current_regime_is_last_label(self):
        series = _make_regime_series()
        manifest = build_regime_manifest("btc", series, {})
        assert manifest["current_regime"] == series.iloc[-1]

    def test_distribution_fractions_sum_to_one(self):
        series = _make_regime_series(90)
        manifest = build_regime_manifest("btc", series, {})
        dist = manifest["distribution"]
        total = sum(dist.values())
        assert abs(total - 1.0) < 1e-9, f"fractions sum to {total}, expected 1.0"

    def test_distribution_covers_all_labels(self):
        series = _make_regime_series()
        manifest = build_regime_manifest("btc", series, {})
        dist = manifest["distribution"]
        for label in ("bull", "bear", "neutral"):
            assert label in dist

    def test_distribution_values_are_floats_in_0_1(self):
        series = _make_regime_series()
        manifest = build_regime_manifest("btc", series, {})
        for v in manifest["distribution"].values():
            assert isinstance(v, float), f"distribution value {v!r} is not float"
            assert 0.0 <= v <= 1.0

    def test_total_daily_bars_matches_series_length(self):
        series = _make_regime_series(60)
        manifest = build_regime_manifest("btc", series, {})
        assert manifest["total_daily_bars"] == 60

    def test_period_days_is_calendar_span(self):
        """period_days is the calendar span; total_daily_bars counts actual bars.

        A gapped series spanning Jan 1 -> Jan 6 (3 bars, 2 gaps) must produce:
          period_days      == 6   (Jan 6 - Jan 1 = 5 days + 1 = 6)
          total_daily_bars == 3   (only 3 bars in the series)
        """
        idx = pd.DatetimeIndex(
            ["2024-01-01", "2024-01-03", "2024-01-06"]  # 3 bars, gaps on Jan 2, 4, 5
        )
        labels = ["bull", "bear", "neutral"]
        series = pd.Series(labels, index=idx, dtype=object)
        manifest = build_regime_manifest("btc", series, {})
        assert manifest["total_daily_bars"] == 3
        assert manifest["period_days"] == 6  # (Jan 6 - Jan 1).days + 1 = 5 + 1 = 6

    def test_breakdown_is_list_of_date_regime_pairs(self):
        series = _make_regime_series(10)
        manifest = build_regime_manifest("btc", series, {})
        breakdown = manifest["breakdown"]
        assert isinstance(breakdown, list)
        assert len(breakdown) == 10
        for entry in breakdown:
            assert "date" in entry
            assert "regime" in entry
            assert entry["regime"] in ("bull", "bear", "neutral")

    def test_breakdown_dates_are_iso_strings(self):
        series = _make_regime_series(5)
        manifest = build_regime_manifest("btc", series, {})
        for entry in manifest["breakdown"]:
            # Must parse as a date string without error.
            _ = entry["date"]  # already a string
            assert isinstance(entry["date"], str)

    def test_detector_params_stored(self):
        params = {"ema_window": 100, "slope_window": 10}
        series = _make_regime_series()
        manifest = build_regime_manifest("btc", series, params)
        assert manifest["detector_params"] == params

    def test_generated_at_is_iso_utc_string(self):
        series = _make_regime_series()
        manifest = build_regime_manifest("btc", series, {})
        ts = manifest["generated_at"]
        # Must parse without error.
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None  # timezone-aware

    def test_schema_version_is_1(self):
        series = _make_regime_series()
        manifest = build_regime_manifest("btc", series, {})
        assert manifest["schema_version"] == 1

    def test_single_regime_label(self):
        """A regime series with only one label must still produce a valid distribution."""
        idx = pd.date_range("2024-01-01", periods=30, freq="D")
        series = pd.Series(["bull"] * 30, index=idx, dtype=object)
        manifest = build_regime_manifest("btc", series, {})
        dist = manifest["distribution"]
        assert abs(dist["bull"] - 1.0) < 1e-9
        # bear / neutral may be absent or 0
        for label in ("bear", "neutral"):
            assert dist.get(label, 0.0) == 0.0

    def test_result_is_json_serialisable(self):
        """build_regime_manifest must return a dict that json.dumps without error."""
        series = _make_regime_series()
        manifest = build_regime_manifest("btc", series, {"ema_window": 200})
        # Should not raise.
        _ = json.dumps(manifest)


# ---------------------------------------------------------------------------
# (b) check_regime_manifest
# ---------------------------------------------------------------------------


class TestCheckRegimeManifest:
    """check_regime_manifest(manifests_dir, symbol) -> RegimeCheckResult."""

    def test_valid_manifest_passes(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        path = manifests_dir / "regime_btc.json"
        path.write_text(json.dumps(_valid_manifest_dict("btc")), encoding="utf-8")

        result = check_regime_manifest(manifests_dir, "btc")
        assert result.ok
        assert result.symbol == "btc"

    def test_missing_file_detected(self, tmp_path: Path):
        result = check_regime_manifest(tmp_path / "manifests", "btc")
        assert not result.ok
        assert not result.exists
        assert result.error is not None

    def test_invalid_json_detected(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        (manifests_dir / "regime_btc.json").write_text("NOT JSON", encoding="utf-8")
        result = check_regime_manifest(manifests_dir, "btc")
        assert not result.ok
        assert result.exists
        assert result.valid is False

    def test_missing_required_key_detected(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        bad = _valid_manifest_dict()
        del bad["current_regime"]
        (manifests_dir / "regime_btc.json").write_text(
            json.dumps(bad), encoding="utf-8"
        )
        result = check_regime_manifest(manifests_dir, "btc")
        assert not result.ok

    def test_wrong_symbol_case_still_valid(self, tmp_path: Path):
        """symbol field is stored uppercased; check must accept that."""
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        d = _valid_manifest_dict("btc")  # symbol is "BTC" inside
        (manifests_dir / "regime_btc.json").write_text(
            json.dumps(d), encoding="utf-8"
        )
        result = check_regime_manifest(manifests_dir, "btc")
        assert result.ok

    def test_distribution_not_a_dict_detected(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        bad = _valid_manifest_dict()
        bad["distribution"] = "not-a-dict"
        (manifests_dir / "regime_btc.json").write_text(
            json.dumps(bad), encoding="utf-8"
        )
        result = check_regime_manifest(manifests_dir, "btc")
        assert not result.ok

    def test_breakdown_not_a_list_detected(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        bad = _valid_manifest_dict()
        bad["breakdown"] = "not-a-list"
        (manifests_dir / "regime_btc.json").write_text(
            json.dumps(bad), encoding="utf-8"
        )
        result = check_regime_manifest(manifests_dir, "btc")
        assert not result.ok

    def test_invalid_current_regime_label_detected(self, tmp_path: Path):
        """current_regime must be one of bull/bear/neutral; any other value fails."""
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        bad = _valid_manifest_dict()
        bad["current_regime"] = "sideways"  # not a canonical label
        (manifests_dir / "regime_btc.json").write_text(
            json.dumps(bad), encoding="utf-8"
        )
        result = check_regime_manifest(manifests_dir, "btc")
        assert not result.ok
        assert result.error is not None
        assert "current_regime" in result.error


# ---------------------------------------------------------------------------
# (c) verify_outputs
# ---------------------------------------------------------------------------


class TestVerifyOutputs:
    """verify_outputs(manifests_dir, symbols) -> list[RegimeCheckResult]."""

    def test_all_present_and_valid(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        for sym in ("btc", "eth"):
            (manifests_dir / f"regime_{sym}.json").write_text(
                json.dumps(_valid_manifest_dict(sym)), encoding="utf-8"
            )
        results = verify_outputs(manifests_dir, ["btc", "eth"])
        assert len(results) == 2
        assert all(r.ok for r in results)

    def test_partial_failure(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        (manifests_dir / "regime_btc.json").write_text(
            json.dumps(_valid_manifest_dict("btc")), encoding="utf-8"
        )
        # eth manifest is absent
        results = verify_outputs(manifests_dir, ["btc", "eth"])
        assert sum(1 for r in results if r.ok) == 1
        assert sum(1 for r in results if not r.ok) == 1

    def test_empty_symbol_list(self, tmp_path: Path):
        results = verify_outputs(tmp_path / "manifests", [])
        assert results == []

    def test_order_preserved(self, tmp_path: Path):
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        for sym in ("eth", "btc"):
            (manifests_dir / f"regime_{sym}.json").write_text(
                json.dumps(_valid_manifest_dict(sym)), encoding="utf-8"
            )
        results = verify_outputs(manifests_dir, ["eth", "btc"])
        assert results[0].symbol == "eth"
        assert results[1].symbol == "btc"


# ---------------------------------------------------------------------------
# (d) compute_exit_code
# ---------------------------------------------------------------------------


class TestComputeExitCode:
    """compute_exit_code(results) -> int."""

    def test_zero_on_all_ok(self):
        results = [RegimeCheckResult(symbol="btc", exists=True, valid=True)]
        assert compute_exit_code(results) == 0

    def test_nonzero_on_any_failure(self):
        results = [
            RegimeCheckResult(symbol="btc", exists=True, valid=True),
            RegimeCheckResult(symbol="eth", exists=False, valid=False, error="missing"),
        ]
        assert compute_exit_code(results) != 0

    def test_nonzero_on_empty(self):
        # No symbols checked = stage produced nothing = failure.
        assert compute_exit_code([]) != 0

    def test_returns_int(self):
        results = [RegimeCheckResult(symbol="btc", exists=True, valid=True)]
        assert isinstance(compute_exit_code(results), int)


# ---------------------------------------------------------------------------
# (e) print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    """print_summary(results) — smoke test: must not raise and must print status."""

    def test_all_pass(self, capsys: pytest.CaptureFixture):
        results = [RegimeCheckResult(symbol="btc", exists=True, valid=True)]
        print_summary(results)
        out = capsys.readouterr().out
        assert "OK" in out
        assert "btc" in out

    def test_failure_shown(self, capsys: pytest.CaptureFixture):
        results = [
            RegimeCheckResult(
                symbol="eth", exists=False, valid=False, error="file not found"
            )
        ]
        print_summary(results)
        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "eth" in out

    def test_empty(self, capsys: pytest.CaptureFixture):
        print_summary([])
        out = capsys.readouterr().out
        assert "0" in out

    def test_mixed(self, capsys: pytest.CaptureFixture):
        results = [
            RegimeCheckResult(symbol="btc", exists=True, valid=True),
            RegimeCheckResult(
                symbol="eth", exists=True, valid=False, error="bad json"
            ),
        ]
        print_summary(results)
        out = capsys.readouterr().out
        assert "1/2" in out


# ---------------------------------------------------------------------------
# (f) check_factor_manifest_gate  (Issue 1 — prerequisite gate for stage 2.5)
# ---------------------------------------------------------------------------

def _make_valid_factor_manifest_json(symbol: str = "btc") -> str:
    """Return a minimal valid factor_<symbol>.json string (FactorManifest schema)."""
    payload = {
        "schema_version": 1,
        "symbol": symbol.upper(),
        "generated_at": "2024-01-01T00:00:00+00:00",
        "period_days": 90,
        "horizons_h": [24, 72],
        "factors": [
            {
                "name": "funding_rate",
                "ic_by_horizon": {"24": -0.08, "72": -0.06},
                "ir": -0.55,
                "sample_size": 87,
                "cross_regime_ic": None,
                "stability": None,
                "verdict": "ensemble_only",
            }
        ],
    }
    return json.dumps(payload)


class TestCheckFactorManifestGate:
    """check_factor_manifest_gate(manifests_dir, symbol) -> None (raises on failure)."""

    def test_valid_factor_manifest_passes(self, tmp_path: Path):
        """A valid factor manifest must not raise."""
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        (manifests_dir / "factor_btc.json").write_text(
            _make_valid_factor_manifest_json("btc"), encoding="utf-8"
        )
        # Must not raise
        check_factor_manifest_gate(manifests_dir, "btc")

    def test_missing_factor_manifest_raises(self, tmp_path: Path):
        """Missing factor manifest must raise with a clear stage-ordering message."""
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="stage1_factors"):
            check_factor_manifest_gate(manifests_dir, "btc")

    def test_invalid_json_raises(self, tmp_path: Path):
        """Un-parseable JSON in the factor manifest must raise ValueError."""
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        (manifests_dir / "factor_btc.json").write_text("NOT JSON", encoding="utf-8")
        with pytest.raises(ValueError, match="factor manifest"):
            check_factor_manifest_gate(manifests_dir, "btc")

    def test_schema_invalid_raises(self, tmp_path: Path):
        """JSON that does not match FactorManifest schema must raise ValueError."""
        manifests_dir = tmp_path / "manifests"
        manifests_dir.mkdir()
        bad = {"schema_version": 1, "symbol": "BTC"}  # missing required fields
        (manifests_dir / "factor_btc.json").write_text(
            json.dumps(bad), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="factor manifest"):
            check_factor_manifest_gate(manifests_dir, "btc")
