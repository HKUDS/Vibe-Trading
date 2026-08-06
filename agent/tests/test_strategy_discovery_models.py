"""Frozen-contract tests for ``src.strategy_discovery.models`` — issue #969.

The core-package contract (REGIMES, quality ladder, evidence thresholds,
``EvidenceRow`` / ``StrategySummary`` shapes, ``coverage_days_from_ranges``,
``classify_quality``, ``breakeven_fee_bps``, ``build_warnings``) is pinned
here verbatim. Pure logic: no network, no real stores, no wall-clock
dependence. AC5 (<10 trades insufficient), AC6 (sizing-corrected breakeven),
and part of AC7 (no bundled YAML next to the models) are covered here.
"""

from __future__ import annotations

import dataclasses
import inspect
import math
import pathlib

import pytest

try:
    from src.strategy_discovery import models as sd_models

    MODELS_AVAILABLE = True
except ImportError:
    sd_models = None
    MODELS_AVAILABLE = False

requires_models = pytest.mark.skipif(
    not MODELS_AVAILABLE,
    reason="waiting on sibling A: src.strategy_discovery.models not landed yet (issue #969)",
)


@requires_models
class TestConstants:
    def test_regimes_tuple_exact(self) -> None:
        assert sd_models.REGIMES == ("bear_market", "bull_market", "structural")

    def test_evidence_stages_vocabulary_exact(self) -> None:
        assert sd_models.EVIDENCE_STAGES == (
            "hypothesis",
            "backtest",
            "holdout",
            "shadow",
            "live_canary",
            "retired",
        )

    def test_quality_ladder_constants_and_order(self) -> None:
        assert sd_models.QUALITY_ADEQUATE == "adequate"
        assert sd_models.QUALITY_MARGINAL == "marginal"
        assert sd_models.QUALITY_INSUFFICIENT == "insufficient"
        order = sd_models.QUALITY_ORDER
        assert set(order) >= {"adequate", "marginal", "insufficient"}
        assert order["adequate"] > order["marginal"] > order["insufficient"]

    def test_evidence_threshold_and_borderline_constants(self) -> None:
        assert sd_models.MIN_TRADES == 10
        assert sd_models.MIN_COVERAGE_DAYS == 730
        assert sd_models.COST_SENSITIVE_BREAKEVEN_BPS == 5.0
        assert sd_models.BORDERLINE_TRADE_BUFFER == 5
        assert sd_models.BORDERLINE_BREAKEVEN_BPS == 10.0
        assert sd_models.BORDERLINE_COVERAGE_BUFFER_DAYS == 365


@requires_models
class TestEvidenceRow:
    def test_defaults_and_frozen(self) -> None:
        row = sd_models.EvidenceRow(
            strategy_id="alpha_zoo:x", regime="bear_market", trades_in_regime=12
        )
        assert row.position_size is None
        assert row.return_in_regime is None
        assert row.benchmark_in_regime is None
        assert row.excess_in_regime is None
        assert row.sharpe_in_regime is None
        assert row.max_drawdown_in_regime is None
        assert row.date_ranges == ()
        assert isinstance(row.date_ranges, tuple)
        assert row.breakeven_fee_bps is None
        assert row.cost_sensitive is False
        assert row.evidence_quality == "insufficient"
        assert row.warnings == ()
        assert row.last_verified == ""
        assert row.evidence_stage == "backtest"
        assert row.provenance == ""
        assert row.regime_definition == ""
        with pytest.raises(dataclasses.FrozenInstanceError):
            row.trades_in_regime = 99

    def test_invalid_regime_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            sd_models.EvidenceRow(
                strategy_id="s", regime="sideways", trades_in_regime=12
            )

    def test_invalid_evidence_stage_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            sd_models.EvidenceRow(
                strategy_id="s",
                regime="bear_market",
                trades_in_regime=12,
                evidence_stage="rumor",
            )

    def test_every_evidence_stage_is_accepted(self) -> None:
        for stage in sd_models.EVIDENCE_STAGES:
            row = sd_models.EvidenceRow(
                strategy_id="s",
                regime="bear_market",
                trades_in_regime=12,
                evidence_stage=stage,
            )
            assert row.evidence_stage == stage

    def test_full_construction_roundtrip(self) -> None:
        row = sd_models.EvidenceRow(
            strategy_id="sdm:abc",
            regime="bull_market",
            trades_in_regime=15,
            position_size=0.5,
            return_in_regime=0.12,
            benchmark_in_regime=-0.03,
            excess_in_regime=0.15,
            sharpe_in_regime=0.9,
            max_drawdown_in_regime=-0.08,
            date_ranges=("2019-03 to 2020-01",),
            breakeven_fee_bps=33.0,
            cost_sensitive=False,
            evidence_quality="adequate",
            warnings=("w1",),
            last_verified="2026-08-01",
        )
        assert row.sharpe_in_regime == 0.9
        assert row.date_ranges == ("2019-03 to 2020-01",)
        assert row.warnings == ("w1",)


@requires_models
class TestStrategySummary:
    def test_defaults_and_frozen(self) -> None:
        s = sd_models.StrategySummary(
            strategy_id="alpha_zoo:a", name="A", source="alpha_zoo"
        )
        assert s.description is None
        assert s.status is None
        assert s.universe is None
        assert s.has_evidence is False
        assert s.regimes_with_evidence == ()
        full = sd_models.StrategySummary(
            strategy_id="sdm:b",
            name="B",
            source="sdm",
            description="d",
            status="active",
            universe="csi300",
            has_evidence=True,
            regimes_with_evidence=("bear_market",),
        )
        assert full.regimes_with_evidence == ("bear_market",)
        with pytest.raises(dataclasses.FrozenInstanceError):
            full.has_evidence = False


@requires_models
class TestCoverageDays:
    def test_two_disjoint_windows_span(self) -> None:
        # 2018-01-01 .. 2022-12-31 = 1825 days.
        assert (
            sd_models.coverage_days_from_ranges(
                ["2018-01 to 2018-12", "2022-01 to 2022-12"]
            )
            == 1825
        )

    def test_single_year_malformed_entries_and_empty(self) -> None:
        assert sd_models.coverage_days_from_ranges(["2018-01 to 2018-12"]) == 364
        assert (
            sd_models.coverage_days_from_ranges(
                ["garbage", "2018-01 to 2018-12", "2018-99 to nope"]
            )
            == 364
        )
        assert sd_models.coverage_days_from_ranges([]) == 0


@requires_models
class TestClassifyQuality:
    def test_few_trades_is_insufficient_even_with_long_coverage(self) -> None:
        # AC5: <10 trades is insufficient regardless of coverage.
        assert sd_models.classify_quality(9, 9999) == "insufficient"
        assert (
            sd_models.classify_quality(
                sd_models.MIN_TRADES - 1, sd_models.MIN_COVERAGE_DAYS
            )
            == "insufficient"
        )

    def test_short_coverage_is_marginal(self) -> None:
        assert sd_models.classify_quality(12, 400) == "marginal"
        assert (
            sd_models.classify_quality(
                sd_models.MIN_TRADES, sd_models.MIN_COVERAGE_DAYS - 1
            )
            == "marginal"
        )

    def test_adequate_when_both_thresholds_met(self) -> None:
        assert sd_models.classify_quality(12, 800) == "adequate"
        # Issue #969 flags "trades < 10" and "span < 2 years", so exactly
        # MIN_TRADES and exactly MIN_COVERAGE_DAYS must pass.
        assert (
            sd_models.classify_quality(
                sd_models.MIN_TRADES, sd_models.MIN_COVERAGE_DAYS
            )
            == "adequate"
        )


@requires_models
class TestBreakevenFeeBps:
    def test_formula_exact(self) -> None:
        # breakeven_fee_bps == ln(1+g) / (2*n*s) * 10_000, s defaulting to 1.0
        expected = math.log(1 + 0.20) / (2 * 10 * 1.0) * 10_000
        assert sd_models.breakeven_fee_bps(0.20, 10) == pytest.approx(
            expected, rel=1e-12
        )
        assert sd_models.breakeven_fee_bps(0.20, 10, 1.0) == pytest.approx(
            expected, rel=1e-12
        )

    def test_half_position_size_doubles_breakeven(self) -> None:
        # Reviewer-pinned AC6 sizing correction: at s=0.5 the breakeven fee is
        # exactly 2x the full-position value.
        full = sd_models.breakeven_fee_bps(0.20, 10, 1.0)
        half = sd_models.breakeven_fee_bps(0.20, 10, 0.5)
        assert full > 0
        assert half == pytest.approx(2.0 * full, rel=1e-12)

    def test_none_for_unusable_return_or_trade_count(self) -> None:
        assert sd_models.breakeven_fee_bps(0.20, 0) is None
        assert sd_models.breakeven_fee_bps(0.20, -3) is None
        assert sd_models.breakeven_fee_bps(-1.0, 10) is None
        assert sd_models.breakeven_fee_bps(-1.5, 10) is None

    def test_none_for_nonpositive_size_and_non_finite_inputs(self) -> None:
        assert sd_models.breakeven_fee_bps(0.20, 10, 0.0) is None
        assert sd_models.breakeven_fee_bps(0.20, 10, -0.5) is None
        assert sd_models.breakeven_fee_bps(float("nan"), 10) is None
        assert sd_models.breakeven_fee_bps(float("inf"), 10) is None
        assert sd_models.breakeven_fee_bps(0.20, 10, float("nan")) is None


def _call_build_warnings(scenario: dict) -> tuple:
    """Call ``build_warnings`` tolerantly across plausible signatures.

    The contract pins behavior (tuple with stable prefixes), not the exact
    parameter list; this helper tries keyword mapping by known aliases first,
    then positional shapes. A signature that beats every shape fails loudly.
    """
    assert MODELS_AVAILABLE, "src.strategy_discovery.models not importable"
    bw = sd_models.build_warnings
    aliases = {
        "trades": ("trades", "trades_in_regime", "n_trades", "trade_count"),
        "coverage_days": ("coverage_days", "coverage", "total_coverage_days"),
        "breakeven_fee_bps": ("breakeven_fee_bps", "breakeven", "breakeven_bps"),
        "quality": ("quality", "evidence_quality"),
        "cost_sensitive": ("cost_sensitive",),
    }
    try:
        sig = inspect.signature(bw)
    except (TypeError, ValueError):
        sig = None

    if sig is not None:
        kwargs = {}
        for param in sig.parameters.values():
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            for key, names in aliases.items():
                if param.name in names and key in scenario:
                    kwargs[param.name] = scenario[key]
        required = [
            p
            for p in sig.parameters.values()
            if p.default is p.empty and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
        ]
        if len(kwargs) >= len(required):
            try:
                out = bw(**kwargs)
                if isinstance(out, tuple):
                    return out
            except TypeError:
                pass

    fallbacks = [
        lambda: bw(
            scenario["trades"],
            scenario["coverage_days"],
            scenario["breakeven_fee_bps"],
            scenario["quality"],
            scenario["cost_sensitive"],
        ),
        lambda: bw(
            scenario["trades"], scenario["coverage_days"], scenario["breakeven_fee_bps"]
        ),
        lambda: bw(
            scenario["trades"],
            scenario["coverage_days"],
            scenario["breakeven_fee_bps"],
            scenario["cost_sensitive"],
        ),
    ]
    for shape in fallbacks:
        try:
            out = shape()
        except TypeError:
            continue
        if isinstance(out, tuple):
            return out

    pytest.fail(
        "contract drift: build_warnings could not be called with "
        f"{{trades, coverage_days, breakeven_fee_bps, quality, cost_sensitive}} — scenario={scenario}"
    )


@requires_models
class TestBuildWarnings:
    def test_insufficient_trades_prefix(self) -> None:
        warns = _call_build_warnings(
            {
                "trades": 5,
                "coverage_days": 2000,
                "breakeven_fee_bps": 50.0,
                "quality": "insufficient",
                "cost_sensitive": False,
            }
        )
        assert isinstance(warns, tuple)
        assert any(
            isinstance(w, str) and w.startswith("insufficient-trades:") for w in warns
        ), f"expected an 'insufficient-trades:' warning for 5 trades, got {warns!r}"

    def test_short_coverage_prefix(self) -> None:
        warns = _call_build_warnings(
            {
                "trades": 50,
                "coverage_days": 200,
                "breakeven_fee_bps": 50.0,
                "quality": "marginal",
                "cost_sensitive": False,
            }
        )
        assert any(
            isinstance(w, str) and w.startswith("short-coverage:") for w in warns
        ), f"expected a 'short-coverage:' warning for 200 days coverage, got {warns!r}"

    def test_cost_sensitive_prefix(self) -> None:
        warns = _call_build_warnings(
            {
                "trades": 50,
                "coverage_days": 2000,
                "breakeven_fee_bps": 2.0,
                "quality": "adequate",
                "cost_sensitive": True,
            }
        )
        assert any(
            isinstance(w, str) and w.startswith("cost-sensitive:") for w in warns
        ), f"expected a 'cost-sensitive:' warning for breakeven 2.0 bps, got {warns!r}"

    def test_clean_evidence_yields_empty_tuple(self) -> None:
        warns = _call_build_warnings(
            {
                "trades": 200,
                "coverage_days": 2200,
                "breakeven_fee_bps": 120.0,
                "quality": "adequate",
                "cost_sensitive": False,
            }
        )
        assert warns == ()


@requires_models
class TestNoSeedCorpusInModels:
    def test_no_yaml_bundled_next_to_models(self) -> None:
        # AC7: the core package ships no seed corpus.
        pkg_dir = pathlib.Path(sd_models.__file__).resolve().parent
        yaml_files = sorted(
            p.name for pattern in ("*.yaml", "*.yml") for p in pkg_dir.glob(pattern)
        )
        assert (
            yaml_files == []
        ), f"AC7 violation: seed-corpus YAML files found in src/strategy_discovery: {yaml_files}"
