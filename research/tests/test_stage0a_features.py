"""
Unit tests for research/pipeline/stage0a_features.py

Covers:
  test_outputs_exist                  — parquet + meta.json + evidence.json all written
  test_evidence_count_equals_features_columns — evidence entry count == feature column count
  test_evidence_sorted_by_ic          — evidence is sorted by descending max |IC|
  test_evidence_contains_price_and_non_price  — at least one price-based AND one non-price feature entry
  test_evidence_caveat_field          — top-level caveat field present in JSON
  test_evidence_payload_structure     — symbol / generated_at / evidence keys present

All tests:
  - Network-free (synthetic data only).
  - Use tmp_path fixture to isolate file I/O.
  - Call pure-logic helpers directly (no subprocess / network).

Run from research/ directory:
    python -m pytest tests/test_stage0a_features.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ── Bootstrap sys.path ────────────────────────────────────────────────────────
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
if str(_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_DIR))

from pipeline.config import ResearchConfig, SymbolConfig, FeesConfig
from lib.factor_io import load_features, load_features_meta
from pipeline.stage0a_features import (
    build_feature_dict,
    compute_evidence_entries,
    sort_evidence_by_ic,
    build_evidence_payload,
    verify_outputs,
    compute_exit_code,
    apply_ic_eval_transform,
    _INDICATOR_CATEGORY,
    _NON_PRICE_FEATURES,
)
from lib.factor_io import dump_features, dump_evidence


# ─── Synthetic data fixtures ──────────────────────────────────────────────────


def make_candles(n: int = 700) -> pd.DataFrame:
    """Synthetic OHLCV DataFrame with UTC hourly DatetimeIndex.

    700 rows gives enough data for the min_samples=200 check in evaluate_factor.
    """
    np.random.seed(7)
    idx = pd.date_range("2023-01-01", periods=n, freq="1h", tz="UTC")
    close = pd.Series(np.cumsum(np.random.randn(n) * 0.5) + 30000.0, index=idx)
    return pd.DataFrame(
        {
            "open": close * 0.9995,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": np.abs(np.random.randn(n)) * 100 + 50.0,
        },
        index=idx,
    )


def make_config(**overrides) -> ResearchConfig:
    """Minimal ResearchConfig for tests (no YAML file needed)."""
    base = dict(
        symbols=(
            SymbolConfig(name="btc", okx_swap="BTC-USDT-SWAP", ccxt_bybit="BTC/USDT:USDT"),
        ),
        period=30,
        interval="1H",
        data_source="okx",
        engine="daily",
        fees=FeesConfig(maker_rate=0.0002, taker_rate=0.0005, slippage=0.001),
        horizons_h=(8, 24),
        # Small pool to keep tests fast
        indicator_pool=("rsi_14", "ema_cross_9_21", "atr_14", "volume_zscore_20"),
    )
    base.update(overrides)
    return ResearchConfig(**base)


def make_synthetic_funding(candles: pd.DataFrame) -> pd.DataFrame:
    """Synthetic funding rate DataFrame aligned (roughly) to candle index."""
    # 8h settlement cadence — sparse relative to hourly candles
    idx = candles.index[::8]
    rates = np.random.randn(len(idx)) * 0.0001
    return pd.DataFrame({"funding_rate": rates}, index=idx)


def make_synthetic_oi(candles: pd.DataFrame) -> pd.DataFrame:
    """Synthetic OI DataFrame aligned to candle index."""
    oi = np.cumsum(np.random.randn(len(candles)) * 1e6) + 5e9
    return pd.DataFrame({"open_interest": oi}, index=candles.index)


def make_synthetic_stablecoin(candles: pd.DataFrame) -> pd.DataFrame:
    """Synthetic stablecoin supply DataFrame (daily, resampled down from candle index)."""
    daily_idx = candles.index[::24]
    supply = np.cumsum(np.random.randn(len(daily_idx)) * 1e8) + 1e12
    return pd.DataFrame({"stablecoin_supply": supply}, index=daily_idx)


def make_spot_close(candles: pd.DataFrame) -> pd.Series:
    """Synthetic spot close slightly below perp close (positive basis)."""
    return candles["close"] * 0.999


# ─── Shared setup helper ──────────────────────────────────────────────────────


def run_full_pipeline(tmp_path: Path) -> tuple[dict, pd.DataFrame, ResearchConfig]:
    """Run build_feature_dict + compute_evidence_entries + dump_* for 'btc'.

    Returns (feature_dict, candles, config).
    """
    cfg = make_config()
    candles = make_candles()
    funding_df = make_synthetic_funding(candles)
    oi_df = make_synthetic_oi(candles)
    stablecoin_df = make_synthetic_stablecoin(candles)

    feature_dict = build_feature_dict(
        candles=candles,
        config=cfg,
        funding_df=funding_df,
        oi_df=oi_df,
        stablecoin_df=stablecoin_df,
    )

    # Write feature store
    dump_features("btc", feature_dict, tmp_path)

    # Compute + sort evidence
    entries = compute_evidence_entries(candles, feature_dict, cfg.horizons_h)
    sorted_entries = sort_evidence_by_ic(entries)
    evidence_payload = build_evidence_payload("btc", sorted_entries)

    # Write evidence JSON
    dump_evidence("btc", evidence_payload, tmp_path)

    return feature_dict, candles, cfg


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestOutputsExist:
    """Task 5.4 — test_outputs_exist."""

    def test_outputs_exist(self, tmp_path: Path):
        """features_btc.parquet, features_btc.meta.json, evidence_btc.json must all exist."""
        run_full_pipeline(tmp_path)

        assert (tmp_path / "features_btc.parquet").exists(), "features_btc.parquet missing"
        assert (tmp_path / "features_btc.meta.json").exists(), "features_btc.meta.json missing"
        assert (tmp_path / "evidence_btc.json").exists(), "evidence_btc.json missing"


class TestEvidenceCountEqualsFeatureColumns:
    """Task 5.4 — test_evidence_count_equals_features_columns."""

    def test_evidence_count_equals_features_columns(self, tmp_path: Path):
        """Evidence entry count == number of columns in the features parquet."""
        feature_dict, candles, cfg = run_full_pipeline(tmp_path)

        evidence_raw = json.loads((tmp_path / "evidence_btc.json").read_text(encoding="utf-8"))
        evidence_list = evidence_raw["evidence"]

        assert len(evidence_list) == len(feature_dict), (
            f"Evidence entries ({len(evidence_list)}) != feature columns ({len(feature_dict)})"
        )


class TestEvidenceSortedByIC:
    """Task 5.4 — test_evidence_sorted_by_ic."""

    def test_evidence_sorted_by_ic(self, tmp_path: Path):
        """Evidence list must be sorted by descending max |IC| across horizons."""
        run_full_pipeline(tmp_path)

        evidence_raw = json.loads((tmp_path / "evidence_btc.json").read_text(encoding="utf-8"))
        evidence_list = evidence_raw["evidence"]

        def max_abs_ic(entry: dict) -> float:
            ics = entry.get("ic_by_horizon", {}).values()
            valid = [abs(v) for v in ics if v is not None]
            return max(valid) if valid else 0.0

        ic_scores = [max_abs_ic(e) for e in evidence_list]
        assert ic_scores == sorted(ic_scores, reverse=True), (
            "Evidence list is not sorted by descending max |IC|"
        )

    def test_sort_evidence_by_ic_helper(self):
        """Unit test sort_evidence_by_ic directly."""
        entries = [
            {"feature_key": "a", "ic_by_horizon": {8: 0.01, 24: 0.02}},
            {"feature_key": "b", "ic_by_horizon": {8: 0.10, 24: 0.05}},
            {"feature_key": "c", "ic_by_horizon": {8: -0.15, 24: 0.03}},
        ]
        sorted_entries = sort_evidence_by_ic(entries)
        # c has max |IC| 0.15, b has 0.10, a has 0.02
        assert sorted_entries[0]["feature_key"] == "c"
        assert sorted_entries[1]["feature_key"] == "b"
        assert sorted_entries[2]["feature_key"] == "a"


class TestEvidenceContainsPriceAndNonPrice:
    """Task 5.4 — test_evidence_contains_price_and_non_price."""

    def test_evidence_contains_price_and_non_price(self, tmp_path: Path):
        """Evidence list must contain at least one price-based AND one non-price feature entry."""
        feature_dict, candles, cfg = run_full_pipeline(tmp_path)

        evidence_raw = json.loads((tmp_path / "evidence_btc.json").read_text(encoding="utf-8"))
        evidence_list = evidence_raw["evidence"]

        feature_keys = {e["feature_key"] for e in evidence_list}
        price_indicators = set(cfg.indicator_pool)

        price_entries = feature_keys & price_indicators
        assert len(price_entries) > 0, (
            f"No price-based indicator entries found in evidence. Keys: {feature_keys}"
        )

        non_price_keys = {"funding_rate_raw", "oi_change_24h", "stablecoin_supply_z"}
        non_price_entries = feature_keys & non_price_keys
        assert len(non_price_entries) > 0, (
            f"No non-price feature entries found in evidence. "
            f"Expected at least one of {non_price_keys}. Keys: {feature_keys}"
        )

    def test_non_price_features_present_when_data_provided(self, tmp_path: Path):
        """When synthetic non-price data is provided, those features appear in feature dict."""
        cfg = make_config()
        candles = make_candles()
        funding_df = make_synthetic_funding(candles)
        oi_df = make_synthetic_oi(candles)
        stablecoin_df = make_synthetic_stablecoin(candles)

        feature_dict = build_feature_dict(
            candles=candles,
            config=cfg,
            funding_df=funding_df,
            oi_df=oi_df,
            stablecoin_df=stablecoin_df,
        )

        assert "funding_rate_raw" in feature_dict, "funding_rate_raw missing from feature dict"
        assert "oi_change_24h" in feature_dict, "oi_change_24h missing from feature dict"
        assert "stablecoin_supply_z" in feature_dict, "stablecoin_supply_z missing from feature dict"

    def test_non_price_features_absent_when_no_data(self):
        """Without non-price data, no non-price features in feature dict."""
        cfg = make_config()
        candles = make_candles()

        feature_dict = build_feature_dict(
            candles=candles,
            config=cfg,
            funding_df=None,
            oi_df=None,
            stablecoin_df=None,
        )

        for key in _NON_PRICE_FEATURES:
            assert key not in feature_dict, f"{key} should not be in feature dict without data"


class TestEvidenceStructure:
    """Validate evidence JSON top-level structure and entry schema."""

    def test_evidence_caveat_field(self, tmp_path: Path):
        """Top-level caveat field must be present and non-empty."""
        run_full_pipeline(tmp_path)
        evidence_raw = json.loads((tmp_path / "evidence_btc.json").read_text(encoding="utf-8"))
        assert "caveat" in evidence_raw, "caveat field missing from evidence JSON"
        assert evidence_raw["caveat"], "caveat field must be non-empty"

    def test_evidence_payload_structure(self, tmp_path: Path):
        """symbol, generated_at, evidence keys must be present."""
        run_full_pipeline(tmp_path)
        evidence_raw = json.loads((tmp_path / "evidence_btc.json").read_text(encoding="utf-8"))
        for key in ("caveat", "symbol", "generated_at", "evidence"):
            assert key in evidence_raw, f"Missing key '{key}' in evidence JSON"
        assert evidence_raw["symbol"] == "btc"
        assert isinstance(evidence_raw["evidence"], list)

    def test_evidence_entry_schema(self, tmp_path: Path):
        """Each evidence entry must have feature_key, category, ic_by_horizon, ir, sample_size."""
        run_full_pipeline(tmp_path)
        evidence_raw = json.loads((tmp_path / "evidence_btc.json").read_text(encoding="utf-8"))
        for entry in evidence_raw["evidence"]:
            for field in ("feature_key", "category", "ic_by_horizon", "ir", "sample_size"):
                assert field in entry, f"Missing field '{field}' in evidence entry: {entry}"
            assert isinstance(entry["ic_by_horizon"], dict), "ic_by_horizon must be a dict"

    def test_evidence_category_mapping(self, tmp_path: Path):
        """Categories in evidence entries must be drawn from _INDICATOR_CATEGORY values."""
        run_full_pipeline(tmp_path)
        valid_categories = set(_INDICATOR_CATEGORY.values()) | {"unknown"}
        evidence_raw = json.loads((tmp_path / "evidence_btc.json").read_text(encoding="utf-8"))
        for entry in evidence_raw["evidence"]:
            assert entry["category"] in valid_categories, (
                f"Unknown category '{entry['category']}' for feature '{entry['feature_key']}'"
            )


class TestVerifyOutputsAndExitCode:
    """Test verify_outputs and compute_exit_code helpers."""

    def test_verify_outputs_all_present(self, tmp_path: Path):
        """verify_outputs returns empty list when all files exist."""
        run_full_pipeline(tmp_path)
        missing = verify_outputs(tmp_path, ["btc"])
        assert missing == [], f"Expected no missing files, got: {missing}"

    def test_verify_outputs_reports_missing(self, tmp_path: Path):
        """verify_outputs reports missing files when none exist."""
        missing = verify_outputs(tmp_path, ["btc"])
        assert len(missing) == 3, f"Expected 3 missing files, got {len(missing)}: {missing}"

    def test_compute_exit_code_all_success(self):
        assert compute_exit_code({"btc": True, "eth": True}) == 0

    def test_compute_exit_code_any_failure(self):
        assert compute_exit_code({"btc": True, "eth": False}) == 1

    def test_compute_exit_code_all_failure(self):
        assert compute_exit_code({"btc": False}) == 1

    def test_compute_exit_code_empty(self):
        assert compute_exit_code({}) == 0


class TestICEvalTransform:
    """Measurement-layer IC corrections: stationary transform + native-frequency
    subsample. These fix spurious/inflated IC without mutating stored features."""

    def test_obv_evaluated_as_zscore_not_raw_cumsum(self):
        """OBV IC must be measured on a stationary z-score, not the raw cumsum level."""
        from pipeline.stage0a_features import apply_ic_eval_transform

        # Monotonic cumulative series (mimics raw OBV drift).
        idx = pd.date_range("2023-01-01", periods=2000, freq="1h", tz="UTC")
        raw = pd.Series(np.cumsum(np.abs(np.random.RandomState(1).randn(2000))), index=idx)

        out, label = apply_ic_eval_transform("obv", raw)
        assert label == "zscore_720h"
        # z-score is stationary: bounded, centered near 0, unlike the drifting raw level.
        valid = out.dropna()
        assert valid.abs().mean() < 3.0
        assert abs(valid.mean()) < raw.mean()  # de-trended

    def test_funding_subsampled_to_native_change_points(self):
        """Funding IC must drop ffill repeats (evaluate only at settlement changes)."""
        from pipeline.stage0a_features import apply_ic_eval_transform

        idx = pd.date_range("2023-01-01", periods=80, freq="1h", tz="UTC")
        # 8h settlements ffilled to 1H: each value repeats 8x.
        native = pd.Series(np.repeat(np.arange(10) * 0.001, 8), index=idx)

        out, label = apply_ic_eval_transform("funding_rate_raw", native)
        assert label == "native_freq"
        # Only the 10 distinct settlement points survive as non-NaN.
        assert out.notna().sum() == 10

    def test_stablecoin_subsampled_to_daily(self):
        """Stablecoin IC must be measured on a daily grid, not the hourly-varying z."""
        from pipeline.stage0a_features import apply_ic_eval_transform

        idx = pd.date_range("2023-01-01", periods=240, freq="1h", tz="UTC")  # 10 days
        series = pd.Series(np.random.RandomState(2).randn(240), index=idx)

        out, label = apply_ic_eval_transform("stablecoin_supply_z", series)
        assert label == "native_1D"
        assert out.notna().sum() == 10  # one point per day

    def test_untouched_feature_returned_asis(self):
        """A stationary price feature (e.g. rsi_14) is evaluated unchanged."""
        from pipeline.stage0a_features import apply_ic_eval_transform

        idx = pd.date_range("2023-01-01", periods=50, freq="1h", tz="UTC")
        series = pd.Series(np.random.RandomState(3).randn(50), index=idx)
        out, label = apply_ic_eval_transform("rsi_14", series)
        assert label is None
        pd.testing.assert_series_equal(out, series)

    def test_evidence_entry_records_transform_label(self, tmp_path: Path):
        """Evidence entries expose which IC-eval transform was applied (transparency)."""
        cfg = make_config(indicator_pool=("rsi_14", "obv"))
        candles = make_candles()
        funding_df = make_synthetic_funding(candles)
        stablecoin_df = make_synthetic_stablecoin(candles)
        feature_dict = build_feature_dict(
            candles=candles, config=cfg, funding_df=funding_df,
            oi_df=None, stablecoin_df=stablecoin_df,
        )
        entries = compute_evidence_entries(candles, feature_dict, cfg.horizons_h)
        by_key = {e["feature_key"]: e for e in entries}

        assert by_key["obv"]["ic_eval_transform"] == "zscore_720h"
        assert by_key["funding_rate_raw"]["ic_eval_transform"] == "native_freq"
        assert by_key["stablecoin_supply_z"]["ic_eval_transform"] == "native_1D"
        assert by_key["rsi_14"]["ic_eval_transform"] is None


class TestBuildFeatureDictAlignedToCandles:
    """Feature series must be aligned to candles.index."""

    def test_all_series_aligned_to_candle_index(self):
        cfg = make_config()
        candles = make_candles()
        funding_df = make_synthetic_funding(candles)
        oi_df = make_synthetic_oi(candles)
        stablecoin_df = make_synthetic_stablecoin(candles)

        feature_dict = build_feature_dict(
            candles=candles,
            config=cfg,
            funding_df=funding_df,
            oi_df=oi_df,
            stablecoin_df=stablecoin_df,
        )

        for key, series in feature_dict.items():
            assert len(series) == len(candles), (
                f"Feature '{key}' length {len(series)} != candles length {len(candles)}"
            )


class TestDerivedFactors:
    """Tests for the 8 perp-derived factors: basis_*, funding_z/mom, oi_z/divergence/mom."""

    # ── Keys & categories ─────────────────────────────────────────────────────

    _DERIVED_KEYS = (
        "basis_rel", "basis_z", "basis_mom",
        "funding_z", "funding_mom",
        "oi_z", "oi_price_divergence", "oi_mom",
    )

    _EXPECTED_CATEGORIES = {
        "basis_rel": "basis",
        "basis_z": "basis",
        "basis_mom": "basis",
        "funding_z": "funding",
        "funding_mom": "funding",
        "oi_z": "oi",
        "oi_price_divergence": "oi",
        "oi_mom": "oi",
    }

    def test_build_feature_dict_emits_8_new_keys(self):
        """build_feature_dict with spot_close/funding_df/oi_df must emit all 8 derived keys."""
        cfg = make_config()
        candles = make_candles()
        funding_df = make_synthetic_funding(candles)
        oi_df = make_synthetic_oi(candles)

        feature_dict = build_feature_dict(
            candles=candles,
            config=cfg,
            funding_df=funding_df,
            oi_df=oi_df,
            stablecoin_df=None,
            spot_close=make_spot_close(candles),
        )

        for key in self._DERIVED_KEYS:
            assert key in feature_dict, (
                f"Derived factor '{key}' missing from feature_dict. "
                f"Present keys: {sorted(feature_dict.keys())}"
            )

    def test_apply_ic_eval_transform_funding_derived_returns_native_8h(self):
        """funding_z and funding_mom must be subsampled to 8h native frequency."""
        idx = pd.date_range("2023-01-01", periods=200, freq="1h", tz="UTC")
        series = pd.Series(np.random.randn(200) * 0.0001, index=idx)

        for feat_name in ("funding_z", "funding_mom"):
            result_series, label = apply_ic_eval_transform(feat_name, series)

            assert label == "native_8h", (
                f"{feat_name}: expected transform label 'native_8h', got {label!r}"
            )
            # The reindexed result has same length as input but fewer non-NaN rows
            # (only one point per 8h period is non-NaN after reindex).
            non_nan_count = result_series.notna().sum()
            assert non_nan_count < len(series), (
                f"{feat_name}: expected fewer non-NaN rows after 8h resample "
                f"({non_nan_count} is not < {len(series)})"
            )
            # With 200 hourly rows the 8h periods give at most ceil(200/8)=25 non-NaN points.
            assert non_nan_count <= 25, (
                f"{feat_name}: expected at most 25 non-NaN rows from 8h resample, "
                f"got {non_nan_count}"
            )

    def test_apply_ic_eval_transform_basis_oi_returns_none_transform(self):
        """basis_* and oi_* derived factors need no measurement-layer correction."""
        idx = pd.date_range("2023-01-01", periods=100, freq="1h", tz="UTC")
        series = pd.Series(np.random.randn(100), index=idx)

        no_correction_keys = (
            "basis_rel", "basis_z", "basis_mom",
            "oi_z", "oi_price_divergence", "oi_mom",
        )
        for feat_name in no_correction_keys:
            result_series, label = apply_ic_eval_transform(feat_name, series)

            assert label is None, (
                f"{feat_name}: expected transform label None, got {label!r}"
            )
            pd.testing.assert_series_equal(
                result_series, series,
                check_names=False,
                obj=f"apply_ic_eval_transform('{feat_name}') should return series unchanged",
            )

    def test_derived_keys_have_categories(self):
        """All 8 derived keys must be in _INDICATOR_CATEGORY with the correct category."""
        for key, expected_cat in self._EXPECTED_CATEGORIES.items():
            assert key in _INDICATOR_CATEGORY, (
                f"'{key}' missing from _INDICATOR_CATEGORY"
            )
            actual_cat = _INDICATOR_CATEGORY[key]
            assert actual_cat == expected_cat, (
                f"'{key}': expected category '{expected_cat}', got '{actual_cat}'"
            )
