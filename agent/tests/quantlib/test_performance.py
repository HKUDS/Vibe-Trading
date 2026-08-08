"""Tests for client-cash-flow-aware performance measurement.

The load-bearing property is the one TWR exists for: chain-linking must be
invariant to the size and the date of an external contribution, while the
money-weighted return must *not* be. Both are asserted against the same
underlying return path, so a divergence can only come from the flow.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from src.entities.cashflow import CashFlow, CashFlowSeries
from src.quantlib.performance import (
    DEFAULT_EXTERNAL_KINDS,
    FLOW_TIMING_END,
    FLOW_TIMING_START,
    UnsolvableRateError,
    external_flows,
    modified_dietz_return,
    money_weighted_return,
    time_weighted_return,
    xirr,
)

USD = "USD"


def _build_valuations(
    dates: list[date],
    returns: list[float],
    flows: dict[date, float] | None = None,
) -> list[tuple[date, float]]:
    """Roll a known return path forward, injecting end-of-period client cash.

    ``V_k = V_{k-1} * (1 + r_k) + F_k`` is exactly the accounting the
    ``flow_timing="end"`` convention describes, so any TWR computed from the
    result must recover ``prod(1 + r_k) - 1`` no matter what ``F_k`` was.

    Args:
        dates: Valuation dates, earliest first; one more than ``returns``.
        returns: Return of each interval between consecutive dates.
        flows: Portfolio-perspective cash arriving on a valuation date.

    Returns:
        ``(date, value)`` pairs starting at 100.0.
    """
    injections = flows or {}
    value = 100.0
    series = [(dates[0], value)]
    for index, period_return in enumerate(returns, start=1):
        value = value * (1.0 + period_return) + injections.get(dates[index], 0.0)
        series.append((dates[index], value))
    return series


_PATH_DATES = [
    date(2024, 1, 1),
    date(2024, 4, 1),
    date(2024, 7, 1),
    date(2024, 10, 1),
    date(2024, 12, 31),
]
_PATH_RETURNS = [0.08, -0.05, 0.12, -0.03]


def _contribution(when: date, size: float) -> CashFlowSeries:
    """Wrap one client contribution of ``size`` in a series.

    The amount is negated because ``CashFlow`` is holder-perspective: money the
    client pays into the account leaves the client's pocket.

    Args:
        when: Date the contribution settles.
        size: Positive size of the money arriving in the portfolio.

    Returns:
        A single-flow ``CashFlowSeries`` in USD.
    """
    return CashFlowSeries((CashFlow(when, -size, "contribution", USD),))


# ─── The defining TWR property ───


def test_twr_is_invariant_to_the_size_and_date_of_a_contribution() -> None:
    """Same return path, three different flow schedules, one TWR."""
    expected = math.prod(1.0 + r for r in _PATH_RETURNS) - 1.0

    unflowed = time_weighted_return(_build_valuations(_PATH_DATES, _PATH_RETURNS))
    small_early = time_weighted_return(
        _build_valuations(_PATH_DATES, _PATH_RETURNS, {date(2024, 4, 1): 50.0}),
        _contribution(date(2024, 4, 1), 50.0),
    )
    huge_late = time_weighted_return(
        _build_valuations(_PATH_DATES, _PATH_RETURNS, {date(2024, 10, 1): 500_000.0}),
        _contribution(date(2024, 10, 1), 500_000.0),
    )

    assert unflowed.total_return == pytest.approx(expected, rel=1e-12)
    assert small_early.total_return == pytest.approx(expected, rel=1e-12)
    assert huge_late.total_return == pytest.approx(expected, rel=1e-12)
    # A 500k injection into a 100-unit account changes the end value by four
    # orders of magnitude and still cannot move the return.
    assert huge_late.end_value > 400_000.0
    assert unflowed.end_value < 200.0


def test_twr_and_mwr_provably_differ_when_money_arrives_before_a_drawdown() -> None:
    """A contribution timed into the loss hurts the client, not the manager."""
    valuations = [
        (date(2024, 1, 1), 100.0),
        (date(2024, 7, 1), 1010.0),  # +10% on 100, then 900 arrives
        (date(2024, 12, 31), 909.0),  # -10% on 1010
    ]
    flows = _contribution(date(2024, 7, 1), 900.0)

    twr = time_weighted_return(valuations, flows)
    mwr = money_weighted_return(valuations, flows)

    # 1.10 * 0.90 - 1 = -1% exactly, whatever the client did.
    assert twr.total_return == pytest.approx(-0.01, abs=1e-12)
    assert [period.period_return for period in twr.sub_periods] == pytest.approx(
        [0.10, -0.10], abs=1e-12
    )
    # The client had 100 in the gain and 1010 in the loss, so their own money
    # did far worse than the manager's unit of capital.
    assert mwr.annualized_return == pytest.approx(-0.15943701746, rel=1e-9)
    assert mwr.period_return < twr.total_return - 0.10
    assert mwr.net_external_flow == pytest.approx(900.0)


def test_twr_equals_the_simple_return_when_nothing_moves() -> None:
    """With no external flow the chain-link collapses to end over start."""
    valuations = [
        (date(2024, 1, 1), 250_000.0),
        (date(2024, 6, 30), 262_500.0),
        (date(2024, 12, 31), 300_000.0),
    ]
    simple = valuations[-1][1] / valuations[0][1] - 1.0

    twr = time_weighted_return(valuations)
    dietz = modified_dietz_return(valuations)

    assert twr.total_return == pytest.approx(simple, rel=1e-15)
    assert twr.net_external_flow == 0.0
    # Modified Dietz has no flows to weight, so its denominator is just V0 and
    # it must agree exactly with the same simple return.
    assert dietz.total_return == pytest.approx(simple, rel=1e-15)
    assert dietz.average_capital == 250_000.0


def test_two_point_no_flow_twr_is_exactly_the_price_relative() -> None:
    """A single interval must not introduce any compounding error at all."""
    valuations = [(date(2024, 1, 1), 400.0), (date(2024, 12, 31), 520.0)]
    twr = time_weighted_return(valuations)
    assert twr.total_return == 520.0 / 400.0 - 1.0


# ─── Modified Dietz ───


def test_modified_dietz_matches_the_hand_computed_example() -> None:
    """100k grows to 130k with 20k added on 1 Jul 2024; R = 9.088645%.

    By hand, on a 365-day period (1 Jan 2024 to 31 Dec 2024):
        D  = (1 Jul - 1 Jan) = 182 days, so w = (365 - 182) / 365 = 183/365
        F  = +20,000 into the portfolio
        R  = (130,000 - 100,000 - 20,000) / (100,000 + 20,000 * 183/365)
           = 10,000 / 110,027.39726027397
           = 0.09088645418326692
    """
    result = modified_dietz_return(
        [(date(2024, 1, 1), 100_000.0), (date(2024, 12, 31), 130_000.0)],
        _contribution(date(2024, 7, 1), 20_000.0),
    )

    weight = 183 / 365
    assert (date(2024, 12, 31) - date(2024, 1, 1)).days == 365
    assert result.flow_weights == ((date(2024, 7, 1), 20_000.0, weight),)
    assert result.weighted_external_flow == pytest.approx(20_000.0 * weight)
    assert result.average_capital == pytest.approx(100_000.0 + 20_000.0 * weight)
    assert result.total_return == pytest.approx(
        10_000.0 / (100_000.0 + 20_000.0 * weight), rel=1e-15
    )
    assert round(result.total_return, 8) == 0.09088645


def test_modified_dietz_weights_run_from_one_to_zero() -> None:
    """A flow on the opening day is fully invested; one on the closing day is not."""
    flows = CashFlowSeries(
        (
            CashFlow(date(2024, 1, 1), -1_000.0, "contribution", USD),
            CashFlow(date(2024, 12, 31), -1_000.0, "contribution", USD),
        )
    )
    result = modified_dietz_return(
        [(date(2024, 1, 1), 10_000.0), (date(2024, 12, 31), 12_000.0)], flows
    )
    assert [weight for _, _, weight in result.flow_weights] == [1.0, 0.0]
    assert result.average_capital == pytest.approx(11_000.0)


def test_modified_dietz_is_flow_timing_sensitive_where_twr_is_not() -> None:
    """The two measures must not agree once a mid-period flow exists."""
    valuations = [
        (date(2024, 1, 1), 100.0),
        (date(2024, 7, 1), 1010.0),
        (date(2024, 12, 31), 909.0),
    ]
    flows = _contribution(date(2024, 7, 1), 900.0)
    twr = time_weighted_return(valuations, flows)
    dietz = modified_dietz_return(valuations, flows)
    assert dietz.total_return != pytest.approx(twr.total_return, abs=1e-6)
    assert dietz.total_return < 0.0


# ─── Flow classification ───


def test_only_boundary_crossing_kinds_are_treated_as_external() -> None:
    """A dividend is already inside the valuation and must not be netted out."""
    flows = CashFlowSeries(
        (
            CashFlow(date(2024, 7, 1), -500.0, "contribution", USD),
            CashFlow(date(2024, 8, 1), 40.0, "dividend", USD),
            CashFlow(date(2024, 9, 1), -12.0, "fee", USD),
            CashFlow(date(2024, 10, 1), 250_000.0, "nav", USD),
        )
    )
    selected = external_flows(flows)
    assert selected == ((date(2024, 7, 1), 500.0),)
    assert "dividend" not in DEFAULT_EXTERNAL_KINDS


def test_an_unclassified_kind_is_refused_rather_than_assumed() -> None:
    """Silently ignoring an unknown kind would return a plausible wrong number."""
    flows = CashFlowSeries((CashFlow(date(2024, 7, 1), -500.0, "wire_in", USD),))
    with pytest.raises(ValueError, match="neither external nor internal"):
        external_flows(flows)

    reclassified = external_flows(flows, external_kinds=["wire_in"])
    assert reclassified == ((date(2024, 7, 1), 500.0),)


def test_a_kind_cannot_be_both_external_and_internal() -> None:
    """Contradictory classification is an error, not a precedence puzzle."""
    with pytest.raises(ValueError, match="cannot be both"):
        external_flows(
            CashFlowSeries(()),
            external_kinds=["contribution"],
            internal_kinds=["contribution"],
        )


# ─── Flow timing ───


def test_start_timing_invests_the_flow_for_the_whole_interval() -> None:
    """Under start timing the same numbers give a different, exact answer."""
    valuations = [(date(2024, 1, 1), 100.0), (date(2024, 7, 1), 220.0)]
    flows = CashFlowSeries((CashFlow(date(2024, 1, 1), -100.0, "contribution", USD),))
    result = time_weighted_return(valuations, flows, flow_timing=FLOW_TIMING_START)
    # 200 invested at the open, worth 220 at the close.
    assert result.total_return == pytest.approx(0.10, abs=1e-15)
    assert result.flow_timing == FLOW_TIMING_START


def test_a_flow_outside_the_valuation_window_is_an_error() -> None:
    """Dropping it would move client money into the manager's return."""
    valuations = [(date(2024, 1, 1), 100.0), (date(2024, 12, 31), 120.0)]
    flows = _contribution(date(2025, 3, 1), 10.0)
    with pytest.raises(ValueError, match="outside the valuation window"):
        time_weighted_return(valuations, flows)


def test_end_timing_refuses_a_flow_on_the_opening_valuation() -> None:
    """It would already be inside V0, so counting it again double-counts."""
    valuations = [(date(2024, 1, 1), 100.0), (date(2024, 12, 31), 120.0)]
    flows = _contribution(date(2024, 1, 1), 10.0)
    with pytest.raises(ValueError, match="coincides with the opening valuation"):
        time_weighted_return(valuations, flows, flow_timing=FLOW_TIMING_END)


def test_an_unknown_flow_timing_token_is_rejected() -> None:
    """A typo must not silently select the default convention."""
    with pytest.raises(ValueError, match="flow_timing must be"):
        time_weighted_return(
            [(date(2024, 1, 1), 100.0), (date(2024, 12, 31), 120.0)],
            flow_timing="middle",
        )


# ─── Validation ───


def test_a_single_valuation_cannot_produce_a_return() -> None:
    """An opening and a closing mark are both required."""
    with pytest.raises(ValueError, match="opening and a closing valuation"):
        time_weighted_return([(date(2024, 1, 1), 100.0)])


def test_duplicate_valuation_dates_are_rejected() -> None:
    """Two marks for one day have no defensible ordering."""
    with pytest.raises(ValueError, match="share the date"):
        time_weighted_return(
            [
                (date(2024, 1, 1), 100.0),
                (date(2024, 1, 1), 101.0),
                (date(2024, 6, 1), 110.0),
            ]
        )


def test_a_non_positive_invested_base_has_no_honest_return() -> None:
    """An account at zero did not 'return' anything on the way back."""
    with pytest.raises(ValueError, match="invested base"):
        time_weighted_return(
            [(date(2024, 1, 1), 0.0), (date(2024, 6, 1), 50.0)]
        )


def test_iso_strings_and_mappings_are_accepted_like_dates() -> None:
    """Normalisation is reused from the entity spine, not re-implemented."""
    from_pairs = time_weighted_return(
        [("2024-01-01", 100.0), ("2024-12-31", 130.0)]
    )
    from_mapping = time_weighted_return(
        {date(2024, 12, 31): 130.0, date(2024, 1, 1): 100.0}
    )
    assert from_pairs.total_return == pytest.approx(0.30)
    assert from_mapping.total_return == pytest.approx(0.30)
    assert from_mapping.start_date == date(2024, 1, 1)


# ─── XIRR ───


def test_xirr_recovers_a_known_flat_rate() -> None:
    """Pay 1000, receive 1100 exactly one year later: 10%."""
    rate = xirr([(date(2024, 1, 1), -1000.0), (date(2024, 12, 31), 1100.0)])
    # 365 days on a 365-day basis is exactly one year.
    assert rate == pytest.approx(0.10, abs=1e-9)


def test_xirr_discounts_by_actual_days() -> None:
    """Half the elapsed time at the same multiple must roughly square the rate."""
    half_year = xirr([(date(2024, 1, 1), -1000.0), (date(2024, 7, 1), 1100.0)])
    assert (1.0 + half_year) ** (182 / 365) == pytest.approx(1.10, rel=1e-6)


def test_a_one_directional_stream_has_no_irr() -> None:
    """Refusing is correct; there is no rate that zeroes an all-negative NPV."""
    with pytest.raises(UnsolvableRateError, match="one-directional"):
        xirr([(date(2024, 1, 1), -1000.0), (date(2024, 12, 31), -500.0)])


def test_money_weighted_return_with_no_flows_is_just_annualised_growth() -> None:
    """With no client activity the IRR reduces to the account's own growth."""
    result = money_weighted_return(
        [(date(2024, 1, 1), 1000.0), (date(2024, 12, 31), 1210.0)]
    )
    assert result.annualized_return == pytest.approx(0.21, abs=1e-9)
    assert result.period_return == pytest.approx(0.21, abs=1e-9)
    assert result.net_external_flow == 0.0


def test_money_weighted_return_ignores_interim_marks() -> None:
    """An IRR is determined by cash; revaluing midway cannot change it."""
    flows = _contribution(date(2024, 7, 1), 500.0)
    sparse = money_weighted_return(
        [(date(2024, 1, 1), 1000.0), (date(2024, 12, 31), 1800.0)], flows
    )
    dense = money_weighted_return(
        [
            (date(2024, 1, 1), 1000.0),
            (date(2024, 5, 1), 1234.0),
            (date(2024, 9, 30), 1700.0),
            (date(2024, 12, 31), 1800.0),
        ],
        flows,
    )
    assert dense.annualized_return == pytest.approx(sparse.annualized_return, rel=1e-9)


# ─── Annualisation ───


def test_a_sub_year_window_is_not_annualised() -> None:
    """Stating a full-year figure that was never observed is extrapolation."""
    short = time_weighted_return(
        [(date(2024, 1, 1), 100.0), (date(2024, 3, 31), 110.0)]
    )
    assert short.total_return == pytest.approx(0.10)
    assert short.annualized_return is None


def test_a_multi_year_window_is_annualised_geometrically() -> None:
    """Two years of doubling annualises to sqrt(2) - 1."""
    result = time_weighted_return(
        [(date(2023, 1, 1), 100.0), (date(2025, 1, 1), 200.0)]
    )
    days = (date(2025, 1, 1) - date(2023, 1, 1)).days
    assert result.annualized_return == pytest.approx(2.0 ** (365 / days) - 1.0)
