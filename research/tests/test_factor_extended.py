"""
Tests for the refactored factor_extended.py pure-logic helpers.

Covers:
  (a) verdict_from_ic() — threshold logic at boundary values
  (b) build_factor_manifest() — pydantic validation by construction
  (c) resolve_manifests_dir() — repo-relative path (no Windows absolute paths)

These tests are network-free; main() is NOT tested here.

Note: These tests exercise pure-logic helpers only. The HARDCODED_LIST of factors
(funding_rate, oi_change_24h, fng) is used exclusively via the legacy path
(_run_symbol_legacy), which is invoked when RESEARCH_LEGACY_FACTORS=1.
Dynamic factor loading via candidates manifests is tested in
test_factor_extended_dynamic.py.
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# factor_extended lives in research/; pytest is run from research/ so it is
# importable directly after sys.path adjustment done in conftest or inline.
# We also need dashboard/server/schemas which factor_extended sets up on import.
# Import the functions we want to test:
from factor_extended import (
    build_factor_manifest,
    resolve_manifests_dir,
    verdict_from_ic,
)

# Import FactorManifest so we can validate returned objects
from pipeline.config import _REPO_ROOT

# Schemas are importable because factor_extended adds the dashboard path to sys.path.
# After importing factor_extended the path is already set.
from schemas import FactorManifest, FactorVerdict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# (a) verdict_from_ic — boundary tests
# ---------------------------------------------------------------------------


class TestVerdictFromIc:
    """Verdict threshold logic (loosened 2026-05-27):
        |IC| >= 0.10  -> single_use
        0.03 <= |IC| < 0.10 -> ensemble_only
        |IC| < 0.03   -> reject
    """

    # --- reject zone ---
    def test_zero_ic_is_reject(self):
        assert verdict_from_ic(0.0) == FactorVerdict.REJECT

    def test_small_positive_below_threshold_is_reject(self):
        assert verdict_from_ic(0.02) == FactorVerdict.REJECT

    def test_small_negative_below_threshold_is_reject(self):
        assert verdict_from_ic(-0.02) == FactorVerdict.REJECT

    def test_just_below_0_03_is_reject(self):
        # 0.0299... < 0.03 -> reject
        assert verdict_from_ic(0.0299) == FactorVerdict.REJECT

    # --- ensemble_only zone: [0.03, 0.10) ---
    def test_exactly_0_03_positive_is_ensemble_only(self):
        assert verdict_from_ic(0.03) == FactorVerdict.ENSEMBLE_ONLY

    def test_exactly_0_03_negative_is_ensemble_only(self):
        assert verdict_from_ic(-0.03) == FactorVerdict.ENSEMBLE_ONLY

    def test_old_0_05_threshold_now_ensemble_only(self):
        """Previously REJECT under the 0.05 floor; now ENSEMBLE_ONLY under 0.03 floor."""
        assert verdict_from_ic(0.04) == FactorVerdict.ENSEMBLE_ONLY

    def test_mid_ensemble_zone_is_ensemble_only(self):
        assert verdict_from_ic(0.075) == FactorVerdict.ENSEMBLE_ONLY

    def test_negative_mid_ensemble_zone_is_ensemble_only(self):
        assert verdict_from_ic(-0.075) == FactorVerdict.ENSEMBLE_ONLY

    def test_just_below_0_10_is_ensemble_only(self):
        # 0.0999 < 0.10 -> ensemble_only
        assert verdict_from_ic(0.0999) == FactorVerdict.ENSEMBLE_ONLY

    # --- single_use zone: >= 0.10 ---
    def test_exactly_0_10_positive_is_single_use(self):
        assert verdict_from_ic(0.10) == FactorVerdict.SINGLE_USE

    def test_exactly_0_10_negative_is_single_use(self):
        assert verdict_from_ic(-0.10) == FactorVerdict.SINGLE_USE

    def test_large_positive_ic_is_single_use(self):
        assert verdict_from_ic(0.35) == FactorVerdict.SINGLE_USE

    def test_large_negative_ic_is_single_use(self):
        assert verdict_from_ic(-0.35) == FactorVerdict.SINGLE_USE

    # --- NaN edge case ---
    def test_nan_ic_is_reject(self):
        assert verdict_from_ic(float("nan")) == FactorVerdict.REJECT


# ---------------------------------------------------------------------------
# (b) build_factor_manifest — pydantic validation by construction
# ---------------------------------------------------------------------------


class TestBuildFactorManifest:
    """build_factor_manifest(symbol, period_days, horizons_h, factor_results)
    must return a FactorManifest that validates against the schema.
    """

    def _make_results(self, ics: dict[str, dict[int, float]], ir: float = 0.5, n: int = 5000):
        """
        Build a list of FactorResult-like namedtuples from a dict of
        {factor_name: {horizon_h: ic_value}}.
        """
        from lib.factor_metrics import FactorResult
        results = []
        for factor_name, horizon_map in ics.items():
            for h, ic_val in horizon_map.items():
                results.append(FactorResult(
                    factor=factor_name,
                    horizon=f"{h}h",
                    ic=ic_val,
                    ir=ir,
                    n_samples=n,
                ))
        return results

    def test_returns_factor_manifest_instance(self):
        results = self._make_results({"funding_rate": {8: 0.12, 24: 0.08}})
        manifest = build_factor_manifest(
            symbol="btc",
            period_days=730,
            horizons_h=[8, 24],
            factor_results=results,
            generated_at=_now(),
        )
        assert isinstance(manifest, FactorManifest)

    def test_schema_version_is_1(self):
        results = self._make_results({"funding_rate": {8: 0.06}})
        m = build_factor_manifest("btc", 730, [8], results, _now())
        assert m.schema_version == 1

    def test_symbol_is_uppercased(self):
        """symbol in manifest should be the uppercase trading symbol, e.g. 'BTC'."""
        results = self._make_results({"funding_rate": {8: 0.06}})
        m = build_factor_manifest("btc", 730, [8], results, _now())
        assert m.symbol == "BTC"

    def test_horizons_h_matches_input(self):
        results = self._make_results({"funding_rate": {8: 0.06, 24: 0.04}})
        m = build_factor_manifest("btc", 730, [8, 24], results, _now())
        assert m.horizons_h == [8, 24]

    def test_factors_count_matches_unique_factor_names(self):
        results = self._make_results({
            "funding_rate": {8: 0.12, 24: 0.07},
            "fng": {8: 0.03, 24: 0.04},
        })
        m = build_factor_manifest("btc", 730, [8, 24], results, _now())
        assert len(m.factors) == 2

    def test_ic_by_horizon_populated(self):
        results = self._make_results({"funding_rate": {8: 0.12, 24: 0.07}})
        m = build_factor_manifest("btc", 730, [8, 24], results, _now())
        entry = m.factors[0]
        assert entry.ic_by_horizon == {8: pytest.approx(0.12), 24: pytest.approx(0.07)}

    def test_verdict_single_use_when_max_ic_gte_0_10(self):
        # max |IC| across horizons = 0.12 -> single_use
        results = self._make_results({"funding_rate": {8: 0.12, 24: 0.04}})
        m = build_factor_manifest("btc", 730, [8, 24], results, _now())
        assert m.factors[0].verdict == FactorVerdict.SINGLE_USE

    def test_verdict_ensemble_only_when_max_ic_in_middle_zone(self):
        # max |IC| = 0.07 -> ensemble_only
        results = self._make_results({"funding_rate": {8: 0.07, 24: 0.03}})
        m = build_factor_manifest("btc", 730, [8, 24], results, _now())
        assert m.factors[0].verdict == FactorVerdict.ENSEMBLE_ONLY

    def test_verdict_reject_when_max_ic_below_0_03(self):
        # max |IC| = 0.02 -> reject (post 0.05 → 0.03 gate loosening)
        results = self._make_results({"fng": {8: 0.02, 24: 0.01}})
        m = build_factor_manifest("btc", 730, [8, 24], results, _now())
        assert m.factors[0].verdict == FactorVerdict.REJECT

    def test_cross_regime_ic_is_null(self):
        """Task 2.2 must leave cross_regime_ic as None (task 2.3 fills it)."""
        results = self._make_results({"funding_rate": {8: 0.15}})
        m = build_factor_manifest("btc", 730, [8], results, _now())
        assert m.factors[0].cross_regime_ic is None

    def test_stability_is_null(self):
        """Task 2.2 must leave stability as None (task 2.3 fills it)."""
        results = self._make_results({"funding_rate": {8: 0.15}})
        m = build_factor_manifest("btc", 730, [8], results, _now())
        assert m.factors[0].stability is None

    def test_manifest_serializes_to_valid_json(self):
        """Pydantic model_dump_json must not raise."""
        results = self._make_results({
            "funding_rate": {8: 0.12, 24: 0.07},
            "oi_change_24h": {8: -0.06, 24: -0.03},
            "fng": {8: 0.02, 24: 0.01},
        })
        m = build_factor_manifest("btc", 730, [8, 24], results, _now())
        json_str = m.model_dump_json()
        assert '"schema_version"' in json_str
        assert '"factors"' in json_str

    def test_manifest_roundtrip_validates(self):
        """Deserializing the JSON back into FactorManifest must succeed."""
        results = self._make_results({"funding_rate": {8: 0.12}})
        m = build_factor_manifest("btc", 730, [8], results, _now())
        json_str = m.model_dump_json()
        m2 = FactorManifest.model_validate_json(json_str)
        assert m2.symbol == m.symbol
        assert m2.factors[0].verdict == m.factors[0].verdict

    def test_skipped_factors_with_all_nan_are_excluded(self):
        """Factors skipped during evaluation (all-NaN) don't appear in results."""
        from lib.factor_metrics import FactorResult
        results = [
            FactorResult("funding_rate", "8h", 0.12, 0.5, 5000),
            # oi_change_24h was skipped, so it never appears in factor_results
        ]
        m = build_factor_manifest("btc", 730, [8], results, _now())
        names = [e.name for e in m.factors]
        assert "funding_rate" in names
        assert "oi_change_24h" not in names

    def test_period_days_stored_correctly(self):
        results = self._make_results({"funding_rate": {8: 0.06}})
        m = build_factor_manifest("btc", 730, [8], results, _now())
        assert m.period_days == 730


# ---------------------------------------------------------------------------
# (c) resolve_manifests_dir — repo-relative path, never a Windows absolute path
# ---------------------------------------------------------------------------


class TestResolveManifestsDir:
    def test_returns_path_object(self):
        d = resolve_manifests_dir()
        assert isinstance(d, Path)

    def test_ends_with_research_manifests(self):
        d = resolve_manifests_dir()
        # Normalise to forward slashes for comparison
        parts = d.parts
        assert parts[-1] == "manifests"
        assert parts[-2] == "research"

    def test_is_inside_repo_root(self):
        """The manifests dir must be under the repo root, not a user's home."""
        d = resolve_manifests_dir()
        assert d == _REPO_ROOT / "research" / "manifests"

    def test_no_hardcoded_windows_user_path(self):
        """The path must NOT contain 'Users' from a hardcoded Windows path."""
        d = resolve_manifests_dir()
        # The REPO_ROOT may legitimately contain Users if the project is checked
        # out in the user's home, BUT it must equal _REPO_ROOT/research/manifests
        # exactly (tested above). This test guards against a different hardcoded path.
        assert d == (_REPO_ROOT / "research" / "manifests")
