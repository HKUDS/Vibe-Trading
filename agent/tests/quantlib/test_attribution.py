"""Tests for Brinson-Fachler attribution and Carino multi-period linking.

The four-sector fixture below is worked out by hand in the test itself: every
expected effect is written as the literal arithmetic from the model definition, so
a regression in the implementation cannot be absorbed by reusing the
implementation's own reasoning.
"""

from __future__ import annotations

import math

import pytest

from src.quantlib.attribution import (
    BrinsonResult,
    brinson_fachler,
    carino_factor,
    carino_link,
)

# Hand-built four-sector period.
#   R_p = .40*.12 + .10*.04 + .30*-.02 + .20*.07 = .048 + .004 - .006 + .014 = 0.060
#   R_b = .25*.10 + .30*.05 + .25*-.01 + .20*.06 = .025 + .015 - .0025 + .012 = 0.0495
#   active = 0.0105
PORTFOLIO_WEIGHTS = {"Tech": 0.40, "Financials": 0.10, "Energy": 0.30, "Health": 0.20}
BENCHMARK_WEIGHTS = {"Tech": 0.25, "Financials": 0.30, "Energy": 0.25, "Health": 0.20}
PORTFOLIO_RETURNS = {"Tech": 0.12, "Financials": 0.04, "Energy": -0.02, "Health": 0.07}
BENCHMARK_RETURNS = {"Tech": 0.10, "Financials": 0.05, "Energy": -0.01, "Health": 0.06}

EXACT = 1e-12


def _fixture() -> BrinsonResult:
    """Return the hand-built four-sector single-period attribution.

    Returns:
        The :class:`BrinsonResult` for the module-level fixture.
    """
    return brinson_fachler(PORTFOLIO_WEIGHTS, BENCHMARK_WEIGHTS, PORTFOLIO_RETURNS, BENCHMARK_RETURNS)


def test_totals_match_hand_computed_returns():
    """Portfolio, benchmark and active returns match the arithmetic above."""
    result = _fixture()
    assert result.portfolio_return == pytest.approx(0.060, abs=EXACT)
    assert result.benchmark_return == pytest.approx(0.0495, abs=EXACT)
    assert result.active_return == pytest.approx(0.0105, abs=EXACT)


def test_per_sector_effects_match_hand_computation():
    """Every sector's three effects equal the hand-evaluated formulas."""
    result = _fixture()
    by_sector = {effect.sector: effect for effect in result.sectors}
    benchmark_total = 0.0495

    expected = {
        # (w_p - w_b), (r_b - R_b), (r_p - r_b), w_b
        "Tech": (0.40 - 0.25, 0.10 - benchmark_total, 0.12 - 0.10, 0.25),
        "Financials": (0.10 - 0.30, 0.05 - benchmark_total, 0.04 - 0.05, 0.30),
        "Energy": (0.30 - 0.25, -0.01 - benchmark_total, -0.02 - -0.01, 0.25),
        "Health": (0.20 - 0.20, 0.06 - benchmark_total, 0.07 - 0.06, 0.20),
    }
    for sector, (active_weight, benchmark_excess, selection_excess, w_b) in expected.items():
        effect = by_sector[sector]
        assert effect.allocation == pytest.approx(active_weight * benchmark_excess, abs=EXACT)
        assert effect.selection == pytest.approx(w_b * selection_excess, abs=EXACT)
        assert effect.interaction == pytest.approx(active_weight * selection_excess, abs=EXACT)


def test_aggregate_effects_match_hand_computation():
    """The three aggregate effects equal the independently summed values."""
    result = _fixture()
    # Allocation: .15*.0505 + -.20*.0005 + .05*-.0595 + 0 = .007575 - .0001 - .002975 = 0.0045
    assert result.allocation == pytest.approx(0.0045, abs=EXACT)
    # Selection: .25*.02 + .30*-.01 + .25*-.01 + .20*.01 = .005 - .003 - .0025 + .002 = 0.0015
    assert result.selection == pytest.approx(0.0015, abs=EXACT)
    # Interaction: .15*.02 + -.20*-.01 + .05*-.01 + 0 = .003 + .002 - .0005 = 0.0045
    assert result.interaction == pytest.approx(0.0045, abs=EXACT)


def test_single_period_effects_tie_out_exactly():
    """HARD REQUIREMENT: allocation + selection + interaction == active return to 1e-12."""
    result = _fixture()
    residual = result.allocation + result.selection + result.interaction - result.active_return
    assert abs(residual) < EXACT, f"attribution does not tie out; residual={residual!r}"
    assert abs(result.total_effect - result.active_return) < EXACT


def test_sector_totals_tie_out_exactly():
    """Summing the per-sector totals also reproduces the active return."""
    result = _fixture()
    summed = math.fsum(effect.total for effect in result.sectors)
    assert abs(summed - result.active_return) < EXACT


@pytest.mark.parametrize(
    "w_p,w_b,r_p,r_b",
    [
        # Ordinary long-only book.
        (
            {"A": 0.5, "B": 0.3, "C": 0.2},
            {"A": 0.2, "B": 0.5, "C": 0.3},
            {"A": 0.11, "B": -0.04, "C": 0.07},
            {"A": 0.08, "B": 0.01, "C": 0.05},
        ),
        # Single sector: allocation and interaction must vanish, selection carries it.
        ({"A": 1.0}, {"A": 1.0}, {"A": 0.25}, {"A": 0.10}),
        # A short leg, so weights are not confined to [0, 1].
        (
            {"A": 0.7, "B": -0.2, "C": 0.5},
            {"A": 0.3, "B": 0.4, "C": 0.3},
            {"A": 0.03, "B": 0.09, "C": -0.15},
            {"A": 0.06, "B": 0.02, "C": -0.11},
        ),
        # Large negative returns, to exercise sign handling.
        (
            {"A": 0.6, "B": 0.4},
            {"A": 0.45, "B": 0.55},
            {"A": -0.30, "B": -0.12},
            {"A": -0.22, "B": -0.19},
        ),
    ],
)
def test_tie_out_holds_for_arbitrary_inputs(w_p, w_b, r_p, r_b):
    """The identity is structural: it holds for any weights that sum alike, shorts included."""
    result = brinson_fachler(w_p, w_b, r_p, r_b)
    assert abs(result.total_effect - result.active_return) < EXACT


def test_portfolio_identical_to_benchmark_produces_zero_effects():
    """A portfolio equal to the benchmark earns zero allocation, selection and interaction."""
    result = brinson_fachler(
        BENCHMARK_WEIGHTS,
        BENCHMARK_WEIGHTS,
        BENCHMARK_RETURNS,
        BENCHMARK_RETURNS,
    )
    assert result.active_return == pytest.approx(0.0, abs=EXACT)
    assert result.allocation == pytest.approx(0.0, abs=EXACT)
    assert result.selection == pytest.approx(0.0, abs=EXACT)
    assert result.interaction == pytest.approx(0.0, abs=EXACT)
    for effect in result.sectors:
        assert effect.allocation == pytest.approx(0.0, abs=EXACT)
        assert effect.selection == pytest.approx(0.0, abs=EXACT)
        assert effect.interaction == pytest.approx(0.0, abs=EXACT)


def test_same_weights_isolates_selection():
    """Matching the benchmark weights leaves allocation and interaction at zero."""
    result = brinson_fachler(BENCHMARK_WEIGHTS, BENCHMARK_WEIGHTS, PORTFOLIO_RETURNS, BENCHMARK_RETURNS)
    assert result.allocation == pytest.approx(0.0, abs=EXACT)
    assert result.interaction == pytest.approx(0.0, abs=EXACT)
    assert result.selection == pytest.approx(result.active_return, abs=EXACT)


def test_same_returns_isolates_allocation():
    """Holding benchmark returns leaves selection and interaction at zero."""
    result = brinson_fachler(PORTFOLIO_WEIGHTS, BENCHMARK_WEIGHTS, BENCHMARK_RETURNS, BENCHMARK_RETURNS)
    assert result.selection == pytest.approx(0.0, abs=EXACT)
    assert result.interaction == pytest.approx(0.0, abs=EXACT)
    assert result.allocation == pytest.approx(result.active_return, abs=EXACT)


def test_mismatched_weight_sums_are_rejected():
    """Unequal weight totals break the identity, so they must raise rather than mislead."""
    with pytest.raises(ValueError, match="same total"):
        brinson_fachler({"A": 0.9}, {"A": 1.0}, {"A": 0.05}, {"A": 0.04})


def test_weight_sum_tolerance_is_the_boundary_it_claims_to_be():
    """The tolerance gates on the weight-sum gap, strictly, in both directions."""
    args = ({"A": 0.5, "B": 0.5}, {"A": 0.5, "B": 0.4999}, {"A": 0.08, "B": 0.02}, {"A": 0.06, "B": 0.03})
    inside = brinson_fachler(*args, weight_sum_tolerance=1e-3)
    assert abs(inside.total_effect - inside.active_return) < 1e-4
    with pytest.raises(ValueError, match="same total"):
        brinson_fachler(*args, weight_sum_tolerance=1e-5)


def test_loosened_tolerance_leaks_exactly_the_documented_residual():
    """A weight-sum gap dW leaves a residual of -R_b * dW, as the docstring states.

    This is the cost of relaxing the precondition, and it is a real number in basis
    points rather than machine noise, so it is pinned rather than left to be
    rediscovered by whoever loosens the tolerance next.
    """
    portfolio = {"A": 0.6, "B": 0.4}
    benchmark = {"A": 0.5, "B": 0.49}
    result = brinson_fachler(
        portfolio,
        benchmark,
        {"A": 0.08, "B": 0.02},
        {"A": 0.06, "B": 0.03},
        weight_sum_tolerance=0.02,
    )
    weight_gap = math.fsum(portfolio.values()) - math.fsum(benchmark.values())
    residual = result.total_effect - result.active_return
    assert residual == pytest.approx(-result.benchmark_return * weight_gap, abs=EXACT)
    # ~4.5bp: large enough to corrupt a report, which is why the default is 1e-9.
    assert abs(residual) > 1e-4


def test_missing_return_for_a_held_sector_is_rejected():
    """A sector held with real weight must supply its return."""
    with pytest.raises(ValueError, match="no portfolio return"):
        brinson_fachler({"A": 0.5, "B": 0.5}, {"A": 0.5, "B": 0.5}, {"A": 0.05}, {"A": 0.04, "B": 0.02})


def test_benchmark_only_sector_charges_allocation_and_still_ties_out():
    """Not owning a benchmark sector is pure allocation, and the total still ties out."""
    result = brinson_fachler(
        {"A": 1.0, "B": 0.0},
        {"A": 0.6, "B": 0.4},
        {"A": 0.10},
        {"A": 0.10, "B": -0.05},
    )
    missed = next(effect for effect in result.sectors if effect.sector == "B")
    assert missed.selection == pytest.approx(0.0, abs=EXACT)
    assert missed.interaction == pytest.approx(0.0, abs=EXACT)
    assert missed.allocation != 0.0
    assert abs(result.total_effect - result.active_return) < EXACT


def test_empty_input_is_rejected():
    """An attribution over no sectors is meaningless."""
    with pytest.raises(ValueError, match="at least one sector"):
        brinson_fachler({}, {}, {}, {})


# --------------------------------------------------------------------------
# Carino multi-period linking
# --------------------------------------------------------------------------


def _three_periods() -> list[BrinsonResult]:
    """Return three single-period attributions with deliberately different signs.

    Returns:
        Three :class:`BrinsonResult` objects in chronological order.
    """
    return [
        _fixture(),
        brinson_fachler(
            {"Tech": 0.20, "Financials": 0.35, "Energy": 0.25, "Health": 0.20},
            BENCHMARK_WEIGHTS,
            {"Tech": -0.06, "Financials": 0.02, "Energy": 0.09, "Health": -0.03},
            {"Tech": -0.04, "Financials": 0.03, "Energy": 0.05, "Health": -0.02},
        ),
        brinson_fachler(
            {"Tech": 0.30, "Financials": 0.20, "Energy": 0.15, "Health": 0.35},
            BENCHMARK_WEIGHTS,
            {"Tech": 0.05, "Financials": -0.01, "Energy": 0.04, "Health": 0.08},
            {"Tech": 0.06, "Financials": 0.01, "Energy": 0.02, "Health": 0.05},
        ),
    ]


def test_carino_factor_limit_when_returns_coincide():
    """With equal returns the factor collapses to its analytic limit 1/(1+R)."""
    assert carino_factor(0.07, 0.07) == pytest.approx(1.0 / 1.07, abs=EXACT)


def test_carino_factor_is_continuous_at_the_limit():
    """The closed form and the limit agree as the two returns converge."""
    near = carino_factor(0.07 + 1e-7, 0.07)
    assert near == pytest.approx(1.0 / 1.07, abs=1e-7)


def test_carino_factor_matches_its_definition():
    """Away from the limit the factor is the plain difference of logarithms."""
    expected = (math.log(1.10) - math.log(1.04)) / (0.10 - 0.04)
    assert carino_factor(0.10, 0.04) == pytest.approx(expected, abs=EXACT)


def test_carino_factor_rejects_total_loss():
    """Returns at or below -100% have no logarithm."""
    with pytest.raises(ValueError, match="above -100%"):
        carino_factor(-1.0, 0.02)


def test_linked_returns_compound():
    """Linked totals are the compounded, not summed, period returns."""
    periods = _three_periods()
    linked = carino_link(periods)
    expected_portfolio = math.prod(1.0 + period.portfolio_return for period in periods) - 1.0
    expected_benchmark = math.prod(1.0 + period.benchmark_return for period in periods) - 1.0
    assert linked.portfolio_return == pytest.approx(expected_portfolio, abs=EXACT)
    assert linked.benchmark_return == pytest.approx(expected_benchmark, abs=EXACT)
    assert linked.active_return == pytest.approx(expected_portfolio - expected_benchmark, abs=EXACT)


def test_linked_effects_sum_to_multi_period_active_return():
    """The headline requirement: linked effects tie out to the compounded active return."""
    linked = carino_link(_three_periods())
    residual = linked.allocation + linked.selection + linked.interaction - linked.active_return
    assert abs(residual) < EXACT, f"linked attribution does not tie out; residual={residual!r}"


def test_linked_sector_totals_tie_out():
    """Summing the linked per-sector totals also reproduces the compounded active return."""
    linked = carino_link(_three_periods())
    summed = math.fsum(sector.total for sector in linked.sectors)
    assert abs(summed - linked.active_return) < EXACT


def test_naive_summation_leaves_a_residual_that_carino_removes():
    """Carino is not cosmetic: plain addition genuinely misses the compounded target."""
    periods = _three_periods()
    linked = carino_link(periods)
    naive = math.fsum(period.active_return for period in periods)
    assert abs(naive - linked.active_return) > EXACT
    assert abs(linked.total_effect - linked.active_return) < EXACT


def test_single_period_link_is_the_identity():
    """Linking one period must not disturb its effects."""
    period = _fixture()
    linked = carino_link([period])
    assert linked.scaling_factors == pytest.approx((1.0,), abs=EXACT)
    assert linked.allocation == pytest.approx(period.allocation, abs=EXACT)
    assert linked.selection == pytest.approx(period.selection, abs=EXACT)
    assert linked.interaction == pytest.approx(period.interaction, abs=EXACT)


def test_linking_identical_portfolio_and_benchmark_yields_zero():
    """Zero active return in every period links to zero overall."""
    flat = brinson_fachler(BENCHMARK_WEIGHTS, BENCHMARK_WEIGHTS, BENCHMARK_RETURNS, BENCHMARK_RETURNS)
    linked = carino_link([flat, flat, flat])
    assert linked.active_return == pytest.approx(0.0, abs=EXACT)
    assert linked.allocation == pytest.approx(0.0, abs=EXACT)
    assert linked.selection == pytest.approx(0.0, abs=EXACT)
    assert linked.interaction == pytest.approx(0.0, abs=EXACT)


def test_link_reports_one_scaling_factor_per_period():
    """Scaling factors are exposed so a report can be audited."""
    periods = _three_periods()
    linked = carino_link(periods)
    assert len(linked.scaling_factors) == len(periods)
    assert all(factor > 0.0 for factor in linked.scaling_factors)


def test_empty_period_list_is_rejected():
    """Linking nothing is an error, not an empty result."""
    with pytest.raises(ValueError, match="at least one period"):
        carino_link([])
