"""
Tests for factor_regime.py pure-logic helpers.

Covers:
  (a) compute_regime_ic()        — factor+return+regime_labels -> {regime: IC}
  (b) classify_stability()       — {regime: IC} -> regime_stable/conditional
  (c) refine_verdict()           — base verdict + stability -> refined verdict
  (d) enrich_manifest()          — FactorManifest + cross-regime data -> enriched manifest

These tests are network-free; main() is NOT tested here.

Stability rule (documented):
    A factor is `regime_stable` if ALL of the following hold:
      1. IC signs are consistent (all positive or all non-positive) across every
         regime that has a non-NaN IC.
      2. At least two regimes have |IC| > 0.02 (non-trivial signal in multiple
         regimes — prevents a factor with tiny ICs in every regime from being
         called stable).
      3. The spread (max |IC| - min |IC|) among non-NaN, non-trivial regimes
         is <= 0.15 (consistent magnitude — a factor that is 0.25 in bull but
         0.01 in bear is "conditional on bull", not "stable").
    Otherwise the factor is `conditional`.

Verdict-refinement rule (documented):
    If stability is `conditional`, the factor MUST NOT be `single_use`.
    Downgrade: single_use -> ensemble_only; ensemble_only/reject stay unchanged.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

# Bootstrap path so factor_regime (and schemas) are importable when pytest is
# run from research/ as documented in task description.
_RESEARCH_DIR = Path(__file__).resolve().parents[1]  # research/
_REPO_ROOT = _RESEARCH_DIR.parent
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (_RESEARCH_DIR, _DASHBOARD_SCHEMAS):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from factor_regime import (
    classify_stability,
    compute_regime_ic,
    enrich_manifest,
    refine_verdict,
)
from schemas import FactorEntry, FactorManifest, FactorStability, FactorVerdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_manifest(
    factors: list[FactorEntry],
    symbol: str = "BTC",
    period_days: int = 730,
    horizons_h: list[int] | None = None,
) -> FactorManifest:
    return FactorManifest(
        schema_version=1,
        symbol=symbol,
        generated_at=_now(),
        period_days=period_days,
        horizons_h=horizons_h or [8, 24],
        factors=factors,
    )


def _make_entry(
    name: str = "funding_rate",
    ic_by_horizon: dict[int, float] | None = None,
    verdict: FactorVerdict = FactorVerdict.SINGLE_USE,
    cross_regime_ic: dict[str, float] | None = None,
    stability: FactorStability | None = None,
) -> FactorEntry:
    return FactorEntry(
        name=name,
        ic_by_horizon=ic_by_horizon or {8: 0.12},
        ir=0.5,
        sample_size=1000,
        cross_regime_ic=cross_regime_ic,
        stability=stability,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# (a) compute_regime_ic — per-regime Spearman IC
# ---------------------------------------------------------------------------


class TestComputeRegimeIc:
    """compute_regime_ic(factor, returns, regime_labels) -> {regime: IC}"""

    def _make_series(self, n=200):
        """Return synthetic correlated factor + return + regime_labels series."""
        import numpy as np

        rng = np.random.default_rng(42)
        idx = pd.date_range("2023-01-01", periods=n, freq="h")

        factor = pd.Series(rng.normal(0, 1, n), index=idx)
        # Make returns weakly positively correlated with factor
        ret = factor * 0.2 + rng.normal(0, 1, n)
        ret = pd.Series(ret.values, index=idx)

        # Three regimes: alternate in chunks
        regime_cycle = (["bull"] * 70 + ["bear"] * 70 + ["neutral"] * 60)
        regimes = pd.Series(regime_cycle, index=idx)
        return factor, ret, regimes

    def test_returns_dict_with_all_regime_keys(self):
        factor, ret, regimes = self._make_series()
        result = compute_regime_ic(factor, ret, regimes)
        assert isinstance(result, dict)
        assert set(result.keys()) == {"bull", "bear", "neutral"}

    def test_ic_values_are_floats(self):
        factor, ret, regimes = self._make_series()
        result = compute_regime_ic(factor, ret, regimes)
        for v in result.values():
            assert isinstance(v, float)

    def test_ic_values_in_valid_range(self):
        """IC must be between -1 and 1 (or NaN for tiny slices)."""
        factor, ret, regimes = self._make_series()
        result = compute_regime_ic(factor, ret, regimes)
        for v in result.values():
            if not math.isnan(v):
                assert -1.0 <= v <= 1.0

    def test_empty_regime_slice_returns_nan(self):
        """A regime that appears zero times yields NaN IC, not an error."""
        import numpy as np

        rng = np.random.default_rng(0)
        idx = pd.date_range("2023-01-01", periods=200, freq="h")
        factor = pd.Series(rng.normal(0, 1, 200), index=idx)
        ret = pd.Series(rng.normal(0, 1, 200), index=idx)
        # Only bull and bear — no neutral rows at all
        regimes = pd.Series(["bull"] * 100 + ["bear"] * 100, index=idx)
        result = compute_regime_ic(factor, ret, regimes)
        # neutral was not in data but should still be present as NaN
        # OR the function only returns regimes present in data — either is
        # acceptable; if neutral is absent, no error should be raised.
        # If it IS present, it must be NaN.
        if "neutral" in result:
            assert math.isnan(result["neutral"])

    def test_tiny_regime_slice_returns_nan(self):
        """A regime with fewer than 20 paired observations returns NaN (matches compute_ic threshold)."""
        import numpy as np

        rng = np.random.default_rng(7)
        idx = pd.date_range("2023-01-01", periods=210, freq="h")
        factor = pd.Series(rng.normal(0, 1, 210), index=idx)
        ret = pd.Series(rng.normal(0, 1, 210), index=idx)
        # neutral has only 10 rows — below the 20-row threshold
        regimes = pd.Series(["bull"] * 100 + ["bear"] * 100 + ["neutral"] * 10, index=idx)
        result = compute_regime_ic(factor, ret, regimes)
        if "neutral" in result:
            assert math.isnan(result["neutral"])

    def test_sign_reflects_correlation(self):
        """A factor perfectly positively correlated with returns should show positive IC in all regimes."""
        import numpy as np

        rng = np.random.default_rng(1)
        idx = pd.date_range("2023-01-01", periods=300, freq="h")
        factor = pd.Series(rng.normal(0, 1, 300), index=idx)
        # Perfect positive correlation (within each regime)
        ret = factor.copy()
        regimes = pd.Series(["bull"] * 100 + ["bear"] * 100 + ["neutral"] * 100, index=idx)
        result = compute_regime_ic(factor, ret, regimes)
        for regime, ic in result.items():
            if not math.isnan(ic):
                assert ic > 0, f"Expected positive IC in {regime}, got {ic}"

    def test_nan_rows_are_dropped_per_regime(self):
        """NaN values in factor or returns should be excluded without raising."""
        import numpy as np

        rng = np.random.default_rng(3)
        idx = pd.date_range("2023-01-01", periods=200, freq="h")
        factor = pd.Series(rng.normal(0, 1, 200), index=idx)
        ret = pd.Series(rng.normal(0, 1, 200), index=idx)
        # Inject some NaNs
        factor.iloc[:10] = float("nan")
        ret.iloc[190:] = float("nan")
        regimes = pd.Series(["bull"] * 70 + ["bear"] * 70 + ["neutral"] * 60, index=idx)
        # Should not raise
        result = compute_regime_ic(factor, ret, regimes)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# (b) classify_stability — regime_stable / conditional
# ---------------------------------------------------------------------------


class TestClassifyStability:
    """classify_stability({regime: IC}) -> FactorStability

    Rule (documented in module docstring of factor_regime.py):
      regime_stable if:
        1. IC signs are consistent across non-NaN regimes (all >= 0 or all <= 0).
        2. At least 2 regimes have |IC| > 0.02 (non-trivial in multiple regimes).
        3. max(|IC|) - min(|IC|) <= 0.15 among non-NaN, non-trivial regimes.
      conditional otherwise.
    """

    def test_consistent_positive_sign_two_regimes_regime_stable(self):
        ic = {"bull": 0.12, "bear": 0.09, "neutral": 0.07}
        assert classify_stability(ic) == FactorStability.REGIME_STABLE

    def test_consistent_negative_sign_two_regimes_regime_stable(self):
        ic = {"bull": -0.12, "bear": -0.09, "neutral": -0.07}
        assert classify_stability(ic) == FactorStability.REGIME_STABLE

    def test_sign_flip_is_conditional(self):
        """Positive IC in bull, negative in bear — clearly conditional."""
        ic = {"bull": 0.12, "bear": -0.09, "neutral": 0.07}
        assert classify_stability(ic) == FactorStability.CONDITIONAL

    def test_only_one_regime_has_nontrivial_ic_is_conditional(self):
        """Factor only works in one regime — should be conditional."""
        ic = {"bull": 0.18, "bear": 0.005, "neutral": 0.004}
        assert classify_stability(ic) == FactorStability.CONDITIONAL

    def test_large_magnitude_spread_is_conditional(self):
        """spread = |0.22 - 0.06| = 0.16 > 0.15 -> conditional."""
        ic = {"bull": 0.22, "bear": 0.06, "neutral": float("nan")}
        assert classify_stability(ic) == FactorStability.CONDITIONAL

    def test_small_spread_consistent_sign_regime_stable(self):
        """spread = |0.12 - 0.10| = 0.02 <= 0.15 and consistent sign -> stable."""
        ic = {"bull": 0.12, "bear": 0.10, "neutral": 0.11}
        assert classify_stability(ic) == FactorStability.REGIME_STABLE

    def test_all_nan_is_conditional(self):
        """No data at all — cannot be stable."""
        ic = {"bull": float("nan"), "bear": float("nan"), "neutral": float("nan")}
        assert classify_stability(ic) == FactorStability.CONDITIONAL

    def test_all_trivial_ic_is_conditional(self):
        """All ICs near zero (all < 0.02) — not non-trivial in 2+ regimes."""
        ic = {"bull": 0.01, "bear": 0.01, "neutral": 0.01}
        assert classify_stability(ic) == FactorStability.CONDITIONAL

    def test_exactly_two_nontrivial_regimes_stable(self):
        """Exactly 2 non-trivial regimes with consistent sign and small spread."""
        ic = {"bull": 0.10, "bear": 0.08, "neutral": float("nan")}
        assert classify_stability(ic) == FactorStability.REGIME_STABLE

    def test_spread_exactly_at_boundary_is_stable(self):
        """Spread exactly 0.15 -> stable (boundary is inclusive)."""
        ic = {"bull": 0.22, "bear": 0.07, "neutral": float("nan")}
        # spread = 0.22 - 0.07 = 0.15 -> stable
        assert classify_stability(ic) == FactorStability.REGIME_STABLE

    def test_spread_just_above_boundary_is_conditional(self):
        """Spread 0.16 -> conditional."""
        ic = {"bull": 0.23, "bear": 0.07, "neutral": float("nan")}
        # spread = 0.23 - 0.07 = 0.16 > 0.15 -> conditional
        assert classify_stability(ic) == FactorStability.CONDITIONAL


# ---------------------------------------------------------------------------
# (c) refine_verdict — conditional must not be single_use
# ---------------------------------------------------------------------------


class TestRefineVerdict:
    """refine_verdict(base_verdict, stability) -> FactorVerdict

    Rule:
      If stability is `conditional`, single_use -> ensemble_only.
      Otherwise the verdict is unchanged.
    """

    def test_conditional_downgrades_single_use_to_ensemble_only(self):
        v = refine_verdict(FactorVerdict.SINGLE_USE, FactorStability.CONDITIONAL)
        assert v == FactorVerdict.ENSEMBLE_ONLY

    def test_conditional_keeps_ensemble_only(self):
        v = refine_verdict(FactorVerdict.ENSEMBLE_ONLY, FactorStability.CONDITIONAL)
        assert v == FactorVerdict.ENSEMBLE_ONLY

    def test_conditional_keeps_reject(self):
        v = refine_verdict(FactorVerdict.REJECT, FactorStability.CONDITIONAL)
        assert v == FactorVerdict.REJECT

    def test_regime_stable_keeps_single_use(self):
        v = refine_verdict(FactorVerdict.SINGLE_USE, FactorStability.REGIME_STABLE)
        assert v == FactorVerdict.SINGLE_USE

    def test_regime_stable_keeps_ensemble_only(self):
        v = refine_verdict(FactorVerdict.ENSEMBLE_ONLY, FactorStability.REGIME_STABLE)
        assert v == FactorVerdict.ENSEMBLE_ONLY

    def test_regime_stable_keeps_reject(self):
        v = refine_verdict(FactorVerdict.REJECT, FactorStability.REGIME_STABLE)
        assert v == FactorVerdict.REJECT


# ---------------------------------------------------------------------------
# (d) enrich_manifest — fill cross_regime_ic, stability, verdict
# ---------------------------------------------------------------------------


class TestEnrichManifest:
    """enrich_manifest(manifest, cross_regime_data) -> FactorManifest

    cross_regime_data: dict[factor_name -> {regime: IC}]
    """

    def test_returns_factor_manifest_instance(self):
        entry = _make_entry("funding_rate", verdict=FactorVerdict.SINGLE_USE)
        manifest = _make_manifest([entry])
        enriched = enrich_manifest(manifest, {"funding_rate": {"bull": 0.12, "bear": 0.10, "neutral": 0.11}})
        assert isinstance(enriched, FactorManifest)

    def test_cross_regime_ic_filled(self):
        entry = _make_entry("funding_rate", verdict=FactorVerdict.SINGLE_USE)
        manifest = _make_manifest([entry])
        data = {"funding_rate": {"bull": 0.12, "bear": 0.10, "neutral": 0.11}}
        enriched = enrich_manifest(manifest, data)
        fe = enriched.factors[0]
        assert fe.cross_regime_ic is not None
        assert fe.cross_regime_ic["bull"] == pytest.approx(0.12)

    def test_stability_filled(self):
        entry = _make_entry("funding_rate", verdict=FactorVerdict.SINGLE_USE)
        manifest = _make_manifest([entry])
        data = {"funding_rate": {"bull": 0.12, "bear": 0.10, "neutral": 0.11}}
        enriched = enrich_manifest(manifest, data)
        assert enriched.factors[0].stability is not None

    def test_stable_factor_keeps_single_use(self):
        """A regime_stable factor with base single_use keeps single_use."""
        entry = _make_entry("funding_rate", verdict=FactorVerdict.SINGLE_USE)
        manifest = _make_manifest([entry])
        # Consistent positive, small spread -> regime_stable
        data = {"funding_rate": {"bull": 0.12, "bear": 0.10, "neutral": 0.11}}
        enriched = enrich_manifest(manifest, data)
        assert enriched.factors[0].verdict == FactorVerdict.SINGLE_USE

    def test_conditional_factor_downgraded_from_single_use(self):
        """A conditional factor originally single_use is downgraded to ensemble_only."""
        entry = _make_entry("funding_rate", verdict=FactorVerdict.SINGLE_USE)
        manifest = _make_manifest([entry])
        # Sign flip -> conditional
        data = {"funding_rate": {"bull": 0.15, "bear": -0.12, "neutral": 0.08}}
        enriched = enrich_manifest(manifest, data)
        fe = enriched.factors[0]
        assert fe.stability == FactorStability.CONDITIONAL
        assert fe.verdict == FactorVerdict.ENSEMBLE_ONLY

    def test_conditional_reject_stays_reject(self):
        entry = _make_entry("fng", verdict=FactorVerdict.REJECT)
        manifest = _make_manifest([entry])
        # Sign flip -> conditional, but base is already reject
        data = {"fng": {"bull": 0.04, "bear": -0.03, "neutral": 0.01}}
        enriched = enrich_manifest(manifest, data)
        assert enriched.factors[0].verdict == FactorVerdict.REJECT

    def test_multiple_factors_all_enriched(self):
        entries = [
            _make_entry("funding_rate", verdict=FactorVerdict.SINGLE_USE),
            _make_entry("fng", verdict=FactorVerdict.ENSEMBLE_ONLY),
        ]
        manifest = _make_manifest(entries)
        data = {
            "funding_rate": {"bull": 0.12, "bear": 0.10, "neutral": 0.11},
            "fng": {"bull": 0.06, "bear": 0.05, "neutral": 0.07},
        }
        enriched = enrich_manifest(manifest, data)
        for fe in enriched.factors:
            assert fe.cross_regime_ic is not None
            assert fe.stability is not None

    def test_factor_missing_from_data_keeps_null(self):
        """If a factor has no cross-regime data, its fields remain null."""
        entries = [
            _make_entry("funding_rate", verdict=FactorVerdict.SINGLE_USE),
            _make_entry("oi_change_24h", verdict=FactorVerdict.ENSEMBLE_ONLY),
        ]
        manifest = _make_manifest(entries)
        # Only funding_rate in data
        data = {"funding_rate": {"bull": 0.12, "bear": 0.10, "neutral": 0.11}}
        enriched = enrich_manifest(manifest, data)
        oi_entry = next(fe for fe in enriched.factors if fe.name == "oi_change_24h")
        assert oi_entry.cross_regime_ic is None
        assert oi_entry.stability is None

    def test_output_validates_against_schema(self):
        """Round-trip serialization must succeed."""
        entries = [
            _make_entry("funding_rate", verdict=FactorVerdict.SINGLE_USE),
        ]
        manifest = _make_manifest(entries)
        data = {"funding_rate": {"bull": 0.12, "bear": 0.10, "neutral": 0.11}}
        enriched = enrich_manifest(manifest, data)
        json_str = enriched.model_dump_json()
        m2 = FactorManifest.model_validate_json(json_str)
        assert m2.factors[0].cross_regime_ic is not None

    def test_non_modified_fields_preserved(self):
        """Fields not touched by this task (ic_by_horizon, ir, sample_size) are unchanged."""
        entry = _make_entry(
            "funding_rate",
            ic_by_horizon={8: 0.15, 24: 0.11},
            verdict=FactorVerdict.SINGLE_USE,
        )
        manifest = _make_manifest([entry], period_days=500)
        data = {"funding_rate": {"bull": 0.12, "bear": 0.10, "neutral": 0.11}}
        enriched = enrich_manifest(manifest, data)
        fe = enriched.factors[0]
        assert fe.ic_by_horizon == {8: pytest.approx(0.15), 24: pytest.approx(0.11)}
        assert enriched.period_days == 500
        assert enriched.symbol == "BTC"

    def test_stability_consistency_invariant_holds(self):
        """Schema invariant: stability must not be null if cross_regime_ic is not null."""
        entry = _make_entry("funding_rate", verdict=FactorVerdict.SINGLE_USE)
        manifest = _make_manifest([entry])
        data = {"funding_rate": {"bull": 0.12, "bear": 0.10, "neutral": 0.11}}
        enriched = enrich_manifest(manifest, data)
        fe = enriched.factors[0]
        # This would raise ValueError if violated (schema validator)
        assert not (fe.cross_regime_ic is not None and fe.stability is None)
