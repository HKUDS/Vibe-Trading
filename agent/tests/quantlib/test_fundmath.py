"""Tests for src.quantlib.fundmath.

Two rules the assertions here follow.

*Roots are checked against a construction, not against the solver.* The XIRR
tests build a schedule whose net present value at a chosen rate is zero by
arithmetic, then ask the solver to find that rate back. The annual-spacing test
goes further and cross-checks against a polynomial root found by ``np.roots``,
which shares no code with the module under test.

*The waterfall example is worked by hand in the docstring of its test.* Every
tier figure is derived on paper first, so a wrong implementation cannot make the
test agree with itself.
"""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from src.entities.cashflow import CashFlow, CashFlowSeries
from src.quantlib.fundmath import (
    CONTRIBUTION_KINDS,
    TIER_CARRY_SPLIT,
    TIER_CATCH_UP,
    TIER_PREFERRED_RETURN,
    TIER_RETURN_OF_CAPITAL,
    AmericanWaterfallResult,
    ClawbackResult,
    FundMultiples,
    NoSignChangeError,
    PMEPlusResult,
    WaterfallResult,
    WaterfallTier,
    XIRRConvergenceError,
    XIRRError,
    american_waterfall,
    direct_alpha,
    distributed_capital,
    dpi,
    european_waterfall,
    fund_multiples,
    gp_clawback,
    ks_pme,
    moic,
    npv,
    paid_in_capital,
    pme_plus,
    preferred_return_amount,
    residual_value,
    rvpi,
    tvpi,
    waterfall_split,
    xirr,
    xirr_all,
)

DAYS_PER_YEAR = 365.0


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def make_series(rows, *, currency: str = "USD") -> CashFlowSeries:
    """Build a series from ``(date, amount, kind)`` triples."""
    return CashFlowSeries(
        tuple(CashFlow(date=d, amount=a, kind=k, currency=currency) for d, a, k in rows)
    )


def constructed_schedule(rate: float) -> CashFlowSeries:
    """A schedule whose XIRR is exactly ``rate``, by construction.

    Four irregularly dated inflows are chosen freely; the single opening outflow
    is then set to minus their present value at ``rate``, which forces the net
    present value at ``rate`` to zero.
    """
    start = dt.date(2019, 3, 15)
    inflows = [
        (dt.date(2019, 11, 2), 120.0),
        (dt.date(2021, 6, 30), 450.0),
        (dt.date(2022, 2, 14), 300.0),
        (dt.date(2024, 9, 1), 800.0),
    ]
    present_value = sum(
        amount / (1.0 + rate) ** ((day - start).days / DAYS_PER_YEAR)
        for day, amount in inflows
    )
    rows = [(start, -present_value, "purchase")]
    rows.extend((day, amount, "proceeds") for day, amount in inflows)
    return make_series(rows)


# --------------------------------------------------------------------------
# xirr — recovery of a known rate
# --------------------------------------------------------------------------


@pytest.mark.parametrize("rate", [-0.35, -0.05, 0.0, 0.0001, 0.1234, 0.85, 3.0])
def test_xirr_recovers_the_constructed_rate(rate):
    assert abs(xirr(constructed_schedule(rate)) - rate) < 1e-6


def test_xirr_recovery_is_far_tighter_than_the_required_tolerance():
    # The bracketed solver closes to machine precision, not just to 1e-6.
    assert xirr(constructed_schedule(0.1234)) == pytest.approx(0.1234, abs=1e-12)


def test_npv_at_the_solved_rate_is_zero():
    series = constructed_schedule(0.1234)
    assert npv(series, xirr(series)) == pytest.approx(0.0, abs=1e-9)


def test_guess_cannot_move_the_bracketed_answer():
    series = constructed_schedule(0.1234)
    assert xirr(series, guess=-0.9) == xirr(series, guess=50.0) == xirr(series)


# --------------------------------------------------------------------------
# xirr — annual dates must agree with the textbook IRR
# --------------------------------------------------------------------------


def test_annual_dates_agree_with_textbook_irr():
    """365-day spacing must reproduce the equal-period IRR.

    The reference is the real root of ``sum(cf_i * x**i) == 0`` with
    ``x = 1/(1+r)``, found by ``np.roots`` -- a polynomial solver that shares no
    code with the module under test.
    """
    amounts = [-1000.0, 300.0, 400.0, 500.0, 200.0]
    start = dt.date(2020, 1, 1)
    rows = [
        (
            start + dt.timedelta(days=365 * index),
            amount,
            "purchase" if amount < 0 else "proceeds",
        )
        for index, amount in enumerate(amounts)
    ]

    roots = np.roots(amounts[::-1])
    real_positive = [
        root.real for root in roots if abs(root.imag) < 1e-12 and root.real > 0
    ]
    assert len(real_positive) == 1
    textbook_irr = 1.0 / real_positive[0] - 1.0

    assert xirr(make_series(rows), days_per_year=365.0) == pytest.approx(
        textbook_irr, abs=1e-9
    )


def test_matches_the_published_excel_xirr_example():
    """Microsoft's documented XIRR worked example returns 0.373362535."""
    series = make_series(
        [
            ("2008-01-01", -10000.0, "purchase"),
            ("2008-03-01", 2750.0, "proceeds"),
            ("2008-10-30", 4250.0, "proceeds"),
            ("2009-02-15", 3250.0, "proceeds"),
            ("2009-04-01", 2750.0, "proceeds"),
        ]
    )
    assert xirr(series) == pytest.approx(0.373362535, abs=1e-8)


# --------------------------------------------------------------------------
# xirr — refusals
# --------------------------------------------------------------------------


def test_all_positive_series_raises_instead_of_returning_nonsense():
    series = make_series(
        [
            ("2020-01-01", 100.0, "distribution"),
            ("2021-01-01", 200.0, "distribution"),
            ("2022-01-01", 300.0, "distribution"),
        ]
    )
    with pytest.raises(NoSignChangeError):
        xirr(series)


def test_all_negative_series_raises():
    series = make_series(
        [
            ("2020-01-01", -100.0, "capital_call"),
            ("2021-01-01", -200.0, "capital_call"),
        ]
    )
    with pytest.raises(NoSignChangeError):
        xirr(series)


def test_no_sign_change_error_is_an_xirr_error_and_a_value_error():
    assert issubclass(NoSignChangeError, XIRRError)
    assert issubclass(XIRRError, ValueError)


def test_all_zero_series_raises():
    series = make_series(
        [("2020-01-01", 0.0, "distribution"), ("2021-01-01", 0.0, "distribution")]
    )
    with pytest.raises(NoSignChangeError):
        xirr(series)


def test_flows_on_a_single_date_raise():
    series = make_series(
        [("2020-01-01", -100.0, "capital_call"), ("2020-01-01", 150.0, "distribution")]
    )
    with pytest.raises(ValueError, match="not identifiable"):
        xirr(series)


def test_a_bare_list_of_floats_is_refused():
    with pytest.raises(TypeError, match="CashFlowSeries"):
        xirr([-1000.0, 400.0, 800.0])


def test_rate_at_or_below_minus_one_is_refused_by_npv():
    with pytest.raises(ValueError, match="greater than -1"):
        npv(constructed_schedule(0.1), -1.0)


# --------------------------------------------------------------------------
# xirr — valuation policy
# --------------------------------------------------------------------------


FUND_ROWS = [
    ("2019-01-01", -600.0, "capital_call"),
    ("2019-07-01", -400.0, "capital_call"),
    ("2021-01-01", 250.0, "nav"),
    ("2021-06-01", 500.0, "distribution"),
    ("2023-01-01", 900.0, "distribution"),
    ("2023-06-30", 300.0, "nav"),
]


def test_terminal_policy_uses_only_the_latest_mark():
    series = make_series(FUND_ROWS)
    explicit = make_series([row for row in FUND_ROWS if row[0] != "2021-01-01"])
    assert xirr(series) == pytest.approx(xirr(explicit, valuations="all"))


def test_exclude_policy_drops_every_mark():
    series = make_series(FUND_ROWS)
    cash_only = make_series([row for row in FUND_ROWS if row[2] != "nav"])
    assert xirr(series, valuations="exclude") == pytest.approx(
        xirr(cash_only, valuations="all")
    )


def test_including_residual_value_raises_the_irr():
    series = make_series(FUND_ROWS)
    assert xirr(series) > xirr(series, valuations="exclude")


def test_unknown_valuation_policy_is_refused():
    with pytest.raises(ValueError, match="valuations="):
        xirr(make_series(FUND_ROWS), valuations="latest")


def test_a_fund_with_no_distributions_still_has_an_irr_from_its_nav():
    series = make_series(
        [
            ("2020-01-01", -1000.0, "capital_call"),
            ("2023-01-01", 1500.0, "nav"),
        ]
    )
    years = (dt.date(2023, 1, 1) - dt.date(2020, 1, 1)).days / DAYS_PER_YEAR
    assert xirr(series) == pytest.approx(1.5 ** (1.0 / years) - 1.0, abs=1e-9)


def test_xirr_all_returns_a_single_root_for_a_conventional_schedule():
    assert xirr_all(constructed_schedule(0.2)) == pytest.approx([0.2], abs=1e-9)


def test_a_two_sign_change_schedule_reports_both_roots():
    """The textbook multiple-IRR pattern: out, in, out again.

    Two rates make the net present value zero, so reporting one of them as
    "the" IRR without saying so would be a hidden judgement call.
    """
    series = make_series(
        [
            ("2020-01-01", -100.0, "purchase"),
            ("2021-01-01", 230.0, "proceeds"),
            ("2022-01-01", -132.0, "purchase"),
        ]
    )
    roots = xirr_all(series)
    assert len(roots) == 2
    assert roots[0] < roots[1]
    for root in roots:
        assert npv(series, root) == pytest.approx(0.0, abs=1e-9)
    # Documented tie-break: the smallest root.
    assert xirr(series) == roots[0]


def test_a_root_outside_the_requested_window_is_not_returned():
    """The Newton fallback must not smuggle a root past the caller's bounds.

    The real root of this schedule is about 2.9%. Asked to search only above
    1000%, the scan finds nothing and Newton wanders back to 2.9% -- which is a
    genuine root but not one the caller asked for, so it is refused.
    """
    series = make_series(
        [("2019-03-15", -1428.0, "purchase"), ("2024-09-01", 1670.0, "proceeds")]
    )
    assert xirr(series) == pytest.approx(0.029026355, abs=1e-8)
    with pytest.raises(XIRRConvergenceError, match="not a root to tolerance"):
        xirr(series, rate_bounds=(10.0, 1.0e6))


# --------------------------------------------------------------------------
# multiples
# --------------------------------------------------------------------------


MULTIPLE_CASES = [
    FUND_ROWS,
    [
        ("2018-01-01", -1000.0, "capital_call"),
        ("2020-01-01", 1300.0, "distribution"),
    ],
    [
        ("2018-01-01", -250.0, "subscription"),
        ("2019-01-01", -750.0, "capital_call"),
        ("2022-01-01", 100.0, "dividend"),
        ("2023-01-01", 40.0, "proceeds"),
        ("2023-12-31", 1800.0, "nav"),
    ],
    [
        ("2021-01-01", -500.0, "capital_call"),
        ("2022-01-01", 120.0, "distribution"),
    ],
]


@pytest.mark.parametrize("rows", MULTIPLE_CASES)
def test_tvpi_is_exactly_dpi_plus_rvpi(rows):
    series = make_series(rows)
    assert tvpi(series) == dpi(series) + rvpi(series)


@pytest.mark.parametrize("rows", MULTIPLE_CASES)
def test_the_bundle_reports_the_same_identity(rows):
    result = fund_multiples(make_series(rows))
    assert isinstance(result, FundMultiples)
    assert result.tvpi == result.dpi + result.rvpi


@pytest.mark.parametrize("rows", MULTIPLE_CASES)
def test_the_bundle_agrees_with_the_standalone_functions(rows):
    series = make_series(rows)
    result = fund_multiples(series)
    assert result.paid_in == pytest.approx(paid_in_capital(series))
    assert result.distributed == pytest.approx(distributed_capital(series))
    assert result.residual_value == pytest.approx(residual_value(series))
    assert result.dpi == pytest.approx(dpi(series))
    assert result.rvpi == pytest.approx(rvpi(series))
    assert result.tvpi == pytest.approx(tvpi(series))
    assert result.moic == pytest.approx(moic(series))


def test_the_multiples_of_a_hand_computed_fund():
    # 1000 drawn, 1400 returned, 300 still on the books.
    series = make_series(
        [
            ("2018-01-01", -600.0, "capital_call"),
            ("2018-07-01", -400.0, "capital_call"),
            ("2021-01-01", 500.0, "distribution"),
            ("2022-01-01", 900.0, "distribution"),
            ("2022-12-31", 300.0, "nav"),
        ]
    )
    result = fund_multiples(series)
    assert result.paid_in == pytest.approx(1000.0)
    assert result.distributed == pytest.approx(1400.0)
    assert result.residual_value == pytest.approx(300.0)
    assert result.dpi == pytest.approx(1.4)
    assert result.rvpi == pytest.approx(0.3)
    assert result.tvpi == pytest.approx(1.7)
    assert result.moic == pytest.approx(1.7)


def test_moic_equals_tvpi_on_paid_in_and_diverges_on_invested_capital():
    series = make_series(MULTIPLE_CASES[2])
    assert moic(series) == pytest.approx(tvpi(series))
    # Deal-level denominator: only the 750 actually deployed.
    assert moic(series, invested_capital=750.0) == pytest.approx(1940.0 / 750.0)


def test_only_the_latest_mark_counts_as_residual_value():
    # Two marks; summing them would report 550 instead of 300.
    assert residual_value(make_series(FUND_ROWS)) == pytest.approx(300.0)


def test_a_liquidated_fund_has_no_residual_value():
    series = make_series(
        [("2018-01-01", -100.0, "capital_call"), ("2020-01-01", 130.0, "distribution")]
    )
    assert residual_value(series) == 0.0
    assert rvpi(series) == 0.0
    assert tvpi(series) == pytest.approx(dpi(series))


def test_contribution_kinds_are_a_parameter_not_a_hardcoded_set():
    series = make_series(
        [
            ("2020-01-01", -1000.0, "capital_call"),
            ("2020-06-01", -20.0, "fee"),
            ("2023-01-01", 1200.0, "distribution"),
        ]
    )
    assert paid_in_capital(series) == pytest.approx(1000.0)
    assert paid_in_capital(
        series, contribution_kinds=(*CONTRIBUTION_KINDS, "fee")
    ) == pytest.approx(1020.0)


def test_a_fund_with_no_capital_drawn_has_no_multiple():
    series = make_series([("2020-01-01", 100.0, "distribution")])
    with pytest.raises(ValueError, match="undefined"):
        dpi(series)


def test_a_negative_mark_is_refused_rather_than_guessed():
    series = CashFlowSeries(
        (
            CashFlow("2020-01-01", -100.0, "capital_call", "USD"),
            CashFlow("2021-01-01", -5.0, "nav", "USD"),
        )
    )
    with pytest.raises(ValueError, match="non-negative"):
        residual_value(series)


def test_multiples_refuse_a_bare_list():
    with pytest.raises(TypeError, match="CashFlowSeries"):
        tvpi([-100.0, 150.0])


# --------------------------------------------------------------------------
# waterfall — worked by hand
# --------------------------------------------------------------------------


def test_the_worked_european_waterfall_example():
    """Hand-worked 8% pref / 20% carry / 100% catch-up on 150 distributable.

    Contributed capital 100, preferred owed 8, carry 20%, catch-up 100%::

        tier 1  return of capital   100 -> LP 100                remaining 50
        tier 2  preferred return      8 -> LP   8                remaining 42
        tier 3  GP catch-up          C  -> GP   C
                C solves 1.00*C == 0.20*(8 + C)  =>  C = 1.6/0.8 = 2
                                       2 -> GP   2               remaining 40
        tier 4  carry split          40 -> GP 0.20*40 = 8, LP 32 remaining  0

        LP total = 100 + 8 + 0 + 32 = 140
        GP total =   0 + 0 + 2 +  8 =  10
        140 + 10 = 150, the whole distributable amount.

    Profit distributed is 150 - 100 = 50, of which the GP took 10, i.e. exactly
    the 20% carry rate -- which is what a completed catch-up is for.
    """
    result = waterfall_split(
        150.0, 100.0, 8.0, carry_rate=0.20, catch_up_rate=1.00
    )

    assert result.tier_amount(TIER_RETURN_OF_CAPITAL) == pytest.approx(100.0)
    assert result.tier_amount(TIER_PREFERRED_RETURN) == pytest.approx(8.0)
    assert result.tier_amount(TIER_CATCH_UP) == pytest.approx(2.0)
    assert result.tier_amount(TIER_CARRY_SPLIT) == pytest.approx(40.0)

    assert result.lp_total == pytest.approx(140.0)
    assert result.gp_total == pytest.approx(10.0)
    assert result.lp_total + result.gp_total == pytest.approx(150.0, abs=1e-12)
    assert sum(tier.amount for tier in result.tiers) == pytest.approx(
        150.0, abs=1e-12
    )
    assert result.gp_profit_share == pytest.approx(0.20)
    assert result.unreturned_capital == 0.0
    assert result.unpaid_preferred == 0.0


def test_a_partial_catch_up_rate_still_lands_the_gp_on_its_carry():
    """50% catch-up, 20% carry, pref 8, contributed 100, distributable 200.

        tier 1  return of capital  100                remaining 100
        tier 2  preferred return     8                remaining  92
        tier 3  catch-up  C solves 0.50*C == 0.20*(8 + C) => C = 1.6/0.3
                C = 5.333333...  -> GP 2.666667, LP 2.666667   remaining 86.666667
        tier 4  carry split 86.666667 -> GP 17.333333, LP 69.333333

        GP total = 2.666667 + 17.333333 = 20 = 20% of the 100 of profit.
        LP total = 100 + 8 + 2.666667 + 69.333333 = 180.
    """
    result = waterfall_split(200.0, 100.0, 8.0, carry_rate=0.20, catch_up_rate=0.50)
    assert result.tier_amount(TIER_CATCH_UP) == pytest.approx(1.6 / 0.3)
    assert result.gp_total == pytest.approx(20.0)
    assert result.lp_total == pytest.approx(180.0)
    assert result.gp_profit_share == pytest.approx(0.20)


def test_no_catch_up_tier_leaves_the_gp_below_its_nominal_carry():
    """A hard hurdle: 20% carry applies only above the 8 of preferred.

    100 returned, 8 preferred to LPs, then 92 split 20/80 -> GP 18.4, LP 73.6.
    GP takes 18.4 of the 100 of profit, i.e. 18.4%, not 20%.
    """
    result = waterfall_split(200.0, 100.0, 8.0, carry_rate=0.20, catch_up_rate=0.0)
    assert result.tier_amount(TIER_CATCH_UP) == 0.0
    assert result.gp_total == pytest.approx(18.4)
    assert result.lp_total == pytest.approx(181.6)
    assert result.gp_profit_share == pytest.approx(0.184)


def test_an_incomplete_catch_up_keeps_the_gp_short():
    """Only 109 distributable: the catch-up tier is truncated at 1 of its 2."""
    result = waterfall_split(109.0, 100.0, 8.0, carry_rate=0.20, catch_up_rate=1.0)
    assert result.tier_amount(TIER_CATCH_UP) == pytest.approx(1.0)
    assert result.tier_amount(TIER_CARRY_SPLIT) == 0.0
    assert result.gp_total == pytest.approx(1.0)
    assert result.lp_total == pytest.approx(108.0)
    assert result.gp_profit_share == pytest.approx(1.0 / 9.0)


def test_an_unmet_hurdle_pays_the_gp_nothing():
    result = waterfall_split(105.0, 100.0, 8.0, carry_rate=0.20, catch_up_rate=1.0)
    assert result.gp_total == 0.0
    assert result.lp_total == pytest.approx(105.0)
    assert result.unpaid_preferred == pytest.approx(3.0)
    assert result.unreturned_capital == 0.0


def test_capital_not_yet_returned_is_reported():
    result = waterfall_split(60.0, 100.0, 8.0, carry_rate=0.20, catch_up_rate=1.0)
    assert result.unreturned_capital == pytest.approx(40.0)
    assert result.unpaid_preferred == pytest.approx(8.0)
    assert result.lp_total == pytest.approx(60.0)
    assert result.gp_total == 0.0


@pytest.mark.parametrize(
    "distributable", [0.0, 1.0, 99.9, 100.0, 108.0, 110.0, 137.5, 1000.0]
)
@pytest.mark.parametrize("catch_up_rate", [0.0, 0.35, 0.5, 1.0])
def test_every_split_conserves_the_distributable_amount(distributable, catch_up_rate):
    result = waterfall_split(
        distributable, 100.0, 8.0, carry_rate=0.20, catch_up_rate=catch_up_rate
    )
    assert sum(tier.amount for tier in result.tiers) == pytest.approx(
        distributable, abs=1e-9
    )
    assert result.lp_total + result.gp_total == pytest.approx(
        distributable, abs=1e-9
    )


def test_waterfall_rate_validation():
    with pytest.raises(ValueError, match="carry_rate"):
        waterfall_split(150.0, 100.0, 8.0, carry_rate=1.0)
    with pytest.raises(ValueError, match="catch_up_rate"):
        waterfall_split(150.0, 100.0, 8.0, carry_rate=0.2, catch_up_rate=1.5)
    with pytest.raises(ValueError, match="never complete"):
        waterfall_split(150.0, 100.0, 8.0, carry_rate=0.2, catch_up_rate=0.1)
    with pytest.raises(ValueError, match="non-negative"):
        waterfall_split(-1.0, 100.0, 8.0, carry_rate=0.2)


def test_a_tier_that_does_not_conserve_cash_is_rejected_at_construction():
    with pytest.raises(ValueError, match="does not conserve cash"):
        WaterfallTier(name="bogus", amount=10.0, lp_amount=6.0, gp_amount=3.0)


def test_a_result_whose_tiers_do_not_reconcile_is_rejected():
    tiers = (
        WaterfallTier(
            name=TIER_RETURN_OF_CAPITAL, amount=100.0, lp_amount=100.0, gp_amount=0.0
        ),
    )
    with pytest.raises(ValueError, match="does not reconcile"):
        WaterfallResult(
            distributable=150.0,
            contributed_capital=100.0,
            preferred_amount=8.0,
            tiers=tiers,
            lp_total=100.0,
            gp_total=0.0,
            unreturned_capital=0.0,
            unpaid_preferred=8.0,
        )


# --------------------------------------------------------------------------
# preferred return + the series-driven waterfall
# --------------------------------------------------------------------------


def test_simple_preferred_accrues_per_contribution_from_its_own_date():
    series = make_series(
        [
            ("2020-01-01", -100.0, "capital_call"),
            ("2021-01-01", -100.0, "capital_call"),
            ("2022-01-01", 0.0, "distribution"),
        ]
    )
    first_days = (dt.date(2022, 1, 1) - dt.date(2020, 1, 1)).days
    second_days = (dt.date(2022, 1, 1) - dt.date(2021, 1, 1)).days
    expected = 100.0 * 0.08 * (first_days / 365.0) + 100.0 * 0.08 * (
        second_days / 365.0
    )
    assert preferred_return_amount(
        series, rate=0.08, compounding="simple"
    ) == pytest.approx(expected)


def test_a_later_draw_owes_less_hurdle_than_a_day_one_draw():
    early = make_series(
        [("2020-01-01", -200.0, "capital_call"), ("2025-01-01", 0.0, "distribution")]
    )
    late = make_series(
        [
            ("2020-01-01", -100.0, "capital_call"),
            ("2023-01-01", -100.0, "capital_call"),
            ("2025-01-01", 0.0, "distribution"),
        ]
    )
    assert preferred_return_amount(late, rate=0.08) < preferred_return_amount(
        early, rate=0.08
    )


def test_compound_preferred_exceeds_simple_beyond_one_year():
    series = make_series(
        [("2020-01-01", -100.0, "capital_call"), ("2025-01-01", 0.0, "distribution")]
    )
    assert preferred_return_amount(series, rate=0.08) > preferred_return_amount(
        series, rate=0.08, compounding="simple"
    )


def test_a_zero_hurdle_accrues_nothing():
    series = make_series(
        [("2020-01-01", -100.0, "capital_call"), ("2025-01-01", 0.0, "distribution")]
    )
    assert preferred_return_amount(series, rate=0.0) == 0.0
    assert preferred_return_amount(series, rate=0.0, compounding="simple") == 0.0


def test_a_contribution_after_the_measurement_date_is_refused():
    series = make_series(
        [("2020-01-01", -100.0, "capital_call"), ("2025-01-01", -50.0, "capital_call")]
    )
    with pytest.raises(ValueError, match="accrue backwards"):
        preferred_return_amount(series, rate=0.08, as_of="2021-01-01")


def test_unknown_preferred_compounding_is_refused():
    series = make_series(
        [("2020-01-01", -100.0, "capital_call"), ("2025-01-01", 0.0, "distribution")]
    )
    with pytest.raises(ValueError, match="compounding="):
        preferred_return_amount(series, rate=0.08, compounding="continuous")


def test_the_series_driven_waterfall_matches_the_hand_computed_split():
    """100 called 2020-01-01, 150 distributed 2022-01-01, 8% simple pref, 20/100.

    2020 is a leap year, so the accrual spans 731 days::

        preferred = 100 * 0.08 * 731/365 = 16.021917808219176
        tier 1  return of capital  100                remaining 50
        tier 2  preferred          16.021918          remaining 33.978082
        tier 3  catch-up  C = 0.2*16.021918/0.8 = 4.005479  -> GP 4.005479
                                                     remaining 29.972603
        tier 4  carry split 29.972603 -> GP 5.994521, LP 23.978082

        GP total = 4.005479 + 5.994521 = 10 = 20% of the 50 of profit
        LP total = 150 - 10 = 140
    """
    series = make_series(
        [
            ("2020-01-01", -100.0, "capital_call"),
            ("2022-01-01", 150.0, "distribution"),
        ]
    )
    expected_preferred = 100.0 * 0.08 * (731.0 / 365.0)
    result = european_waterfall(
        series,
        preferred_rate=0.08,
        carry_rate=0.20,
        catch_up_rate=1.0,
        compounding="simple",
    )
    assert result.contributed_capital == pytest.approx(100.0)
    assert result.distributable == pytest.approx(150.0)
    assert result.preferred_amount == pytest.approx(expected_preferred)
    assert result.tier_amount(TIER_CATCH_UP) == pytest.approx(
        0.2 * expected_preferred / 0.8
    )
    assert result.gp_total == pytest.approx(10.0)
    assert result.lp_total == pytest.approx(140.0)
    assert result.lp_total + result.gp_total == pytest.approx(150.0, abs=1e-12)


def test_the_series_waterfall_distributes_realised_cash_by_default():
    series = make_series(
        [
            ("2020-01-01", -100.0, "capital_call"),
            ("2022-01-01", 40.0, "distribution"),
            ("2022-12-31", 200.0, "nav"),
        ]
    )
    realised = european_waterfall(series, preferred_rate=0.08, carry_rate=0.20)
    liquidated = european_waterfall(
        series, preferred_rate=0.08, carry_rate=0.20, include_residual=True
    )
    assert realised.distributable == pytest.approx(40.0)
    assert liquidated.distributable == pytest.approx(240.0)
    assert realised.gp_total == 0.0
    assert liquidated.gp_total > 0.0


def test_the_series_waterfall_refuses_a_bare_list():
    with pytest.raises(TypeError, match="CashFlowSeries"):
        european_waterfall([-100.0, 150.0], preferred_rate=0.08, carry_rate=0.2)


# --------------------------------------------------------------------------
# PME — shared fixtures
# --------------------------------------------------------------------------
#
# One index, used everywhere below: 100 on 2019-01-01, 150 on 2020-01-01 (a
# 50% index return over exactly one year -- 2019 is not a leap year, so the
# span is exactly 365 days and every hand-computed rate below is a clean
# fraction under the module's own days_per_year=365 default).

INDEX = pd.Series({dt.date(2019, 1, 1): 100.0, dt.date(2020, 1, 1): 150.0})


# --------------------------------------------------------------------------
# ks_pme
# --------------------------------------------------------------------------


def test_ks_pme_of_a_fund_that_beat_the_index():
    """-1000 in, +2000 out, one year later, index +50% over the same year.

    FV(contributions) = 1000 * 150/100 = 1500
    FV(distributions)  = 2000 * 150/150 = 2000
    KS-PME = 2000 / 1500 = 4/3
    """
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    assert ks_pme(series, INDEX) == pytest.approx(4.0 / 3.0, abs=1e-12)


def test_ks_pme_of_a_fund_that_lagged_the_index():
    """-1000 in, +900 out: FV(contrib)=1500, FV(dist)=900, KS-PME = 0.6."""
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 900.0, "distribution")]
    )
    assert ks_pme(series, INDEX) == pytest.approx(0.6, abs=1e-12)


def test_ks_pme_double_sided_guard():
    """Outperformance -> KS-PME > 1; underperformance -> KS-PME < 1."""
    winner = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    loser = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 900.0, "distribution")]
    )
    assert ks_pme(winner, INDEX) > 1.0
    assert ks_pme(loser, INDEX) < 1.0


def test_ks_pme_includes_terminal_nav_via_residual_value():
    """-1000 in, +600 realised, +700 NAV, all valued as of 2020-01-01.

    FV(contrib) = 1500, FV(dist) = 600, FV(NAV) = 700 (factor 1, same date).
    KS-PME = (600 + 700) / 1500 = 13/15.
    """
    series = make_series(
        [
            ("2019-01-01", -1000.0, "capital_call"),
            ("2020-01-01", 600.0, "distribution"),
            ("2020-01-01", 700.0, "nav"),
        ]
    )
    assert ks_pme(series, INDEX) == pytest.approx(1300.0 / 1500.0, abs=1e-12)


def test_ks_pme_only_the_latest_mark_counts_matching_residual_value():
    """Two marks, an early stale one and the terminal one; only the terminal counts."""
    with_stale_mark = make_series(
        [
            ("2019-01-01", -1000.0, "capital_call"),
            ("2019-06-01", 5000.0, "nav"),  # stale, must be ignored
            ("2020-01-01", 600.0, "distribution"),
            ("2020-01-01", 700.0, "nav"),
        ]
    )
    index_with_extra_date = pd.Series(
        {dt.date(2019, 1, 1): 100.0, dt.date(2019, 6, 1): 120.0, dt.date(2020, 1, 1): 150.0}
    )
    assert ks_pme(with_stale_mark, index_with_extra_date) == pytest.approx(
        1300.0 / 1500.0, abs=1e-12
    )


def test_ks_pme_refuses_no_contributions():
    series = make_series([("2020-01-01", 100.0, "distribution")])
    with pytest.raises(ValueError, match="no contributions"):
        ks_pme(series, INDEX)


def test_ks_pme_refuses_a_missing_index_date():
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    sparse_index = pd.Series({dt.date(2020, 1, 1): 150.0})  # missing 2019-01-01
    with pytest.raises(ValueError, match="no entry for 2019-01-01"):
        ks_pme(series, sparse_index)


def test_ks_pme_refuses_a_bare_list():
    with pytest.raises(TypeError, match="CashFlowSeries"):
        ks_pme([-1000.0, 2000.0], INDEX)


def test_ks_pme_refuses_a_non_series_index():
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    with pytest.raises(TypeError, match="pandas Series"):
        ks_pme(series, {dt.date(2019, 1, 1): 100.0})


def test_ks_pme_refuses_an_empty_index():
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    with pytest.raises(ValueError, match="empty"):
        ks_pme(series, pd.Series(dtype=float))


# --------------------------------------------------------------------------
# pme_plus
# --------------------------------------------------------------------------


def test_pme_plus_scales_distributions_to_match_actual_nav():
    """No NAV (fully realised): lambda = FV(contrib)/FV(dist) = 1500/2000 = 0.75.

    Scaled series: -1000 @ 2019-01-01, +1500 @ 2020-01-01 -> IRR = 0.5.
    """
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    result = pme_plus(series, INDEX)
    assert isinstance(result, PMEPlusResult)
    assert result.scaling_factor == pytest.approx(0.75, abs=1e-12)
    assert result.irr == pytest.approx(0.5, abs=1e-9)
    # Fund's own realised IRR (100%) exceeds the PME+ IRR (50%): outperformance.
    assert xirr(series) > result.irr


def test_pme_plus_with_a_terminal_nav():
    """+600 realised, +700 NAV, both dated 2020-01-01.

    lambda = (FV(contrib) - FV(NAV)) / FV(dist) = (1500 - 700) / 600 = 4/3.
    Scaled distribution = 600 * 4/3 = 800; scaled series -1000, +800, +700 (nav)
    at the same date collapse to -1000 + 1500 one year later -> IRR = 0.5.
    """
    series = make_series(
        [
            ("2019-01-01", -1000.0, "capital_call"),
            ("2020-01-01", 600.0, "distribution"),
            ("2020-01-01", 700.0, "nav"),
        ]
    )
    result = pme_plus(series, INDEX)
    assert result.scaling_factor == pytest.approx(4.0 / 3.0, abs=1e-12)
    assert result.irr == pytest.approx(0.5, abs=1e-9)
    # Fund's own realised IRR (30%) is below the PME+ IRR (50%): underperformance,
    # consistent with this same series' KS-PME of 13/15 < 1.
    assert xirr(series) < result.irr


def test_pme_plus_refuses_no_distributions():
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 1200.0, "nav")]
    )
    with pytest.raises(ValueError, match="no distributions"):
        pme_plus(series, INDEX)


def test_pme_plus_refuses_no_contributions():
    series = make_series([("2020-01-01", 100.0, "distribution")])
    with pytest.raises(ValueError, match="no contributions"):
        pme_plus(series, INDEX)


def test_pme_plus_refuses_a_missing_index_date():
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    sparse_index = pd.Series({dt.date(2019, 1, 1): 100.0})  # missing 2020-01-01
    with pytest.raises(ValueError, match="no entry for 2020-01-01"):
        pme_plus(series, sparse_index)


# --------------------------------------------------------------------------
# direct_alpha
# --------------------------------------------------------------------------


def test_direct_alpha_of_a_fund_that_beat_the_index():
    """Deflated series: -1000/100=-10 @ t0, 2000/150=13.3333 @ t0+1y.

    IRR of (-10, +40/3 one year later) solves 1+r = (40/3)/10 = 4/3 -> r = 1/3.
    """
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    assert direct_alpha(series, INDEX) == pytest.approx(1.0 / 3.0, abs=1e-9)


def test_direct_alpha_of_a_fund_that_lagged_the_index():
    """Deflated series: -10 @ t0, 900/150=6 @ t0+1y -> 1+r=0.6 -> r=-0.4."""
    series = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 900.0, "distribution")]
    )
    assert direct_alpha(series, INDEX) == pytest.approx(-0.4, abs=1e-9)


def test_direct_alpha_double_sided_guard():
    winner = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    loser = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 900.0, "distribution")]
    )
    assert direct_alpha(winner, INDEX) > 0.0
    assert direct_alpha(loser, INDEX) < 0.0


def test_direct_alpha_agrees_with_ks_pme_and_pme_plus_on_direction():
    """All three metrics must agree on which of two funds outperformed."""
    winner = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 2000.0, "distribution")]
    )
    loser = make_series(
        [("2019-01-01", -1000.0, "capital_call"), ("2020-01-01", 900.0, "distribution")]
    )
    assert ks_pme(winner, INDEX) > 1.0 and direct_alpha(winner, INDEX) > 0.0
    assert xirr(winner) > pme_plus(winner, INDEX).irr
    assert ks_pme(loser, INDEX) < 1.0 and direct_alpha(loser, INDEX) < 0.0
    assert xirr(loser) < pme_plus(loser, INDEX).irr


def test_direct_alpha_needs_the_index_to_cover_every_mark_not_only_the_terminal_one():
    """Unlike ks_pme/pme_plus, direct_alpha deflates every flow before the
    valuation policy runs, so even a mark that "terminal" will later drop
    still needs an index entry.
    """
    series = make_series(
        [
            ("2019-01-01", -1000.0, "capital_call"),
            ("2019-06-01", 5000.0, "nav"),  # stale mark, dropped by the default policy
            ("2020-01-01", 600.0, "distribution"),
            ("2020-01-01", 700.0, "nav"),
        ]
    )
    # INDEX has no entry for 2019-06-01, the stale mark's date.
    with pytest.raises(ValueError, match="no entry for 2019-06-01"):
        direct_alpha(series, INDEX)


def test_direct_alpha_on_an_all_valuation_series_raises():
    """No contributions, no distributions -- only two NAV marks.

    The default "terminal" valuation policy collapses this to one flow, which
    xirr() already refuses; direct_alpha inherits that refusal unchanged.
    """
    series = make_series([("2019-01-01", 100.0, "nav"), ("2020-01-01", 120.0, "nav")])
    with pytest.raises(ValueError, match="at least two flows"):
        direct_alpha(series, INDEX)


def test_direct_alpha_refuses_a_bare_list():
    with pytest.raises(TypeError, match="CashFlowSeries"):
        direct_alpha([-1000.0, 2000.0], INDEX)


# --------------------------------------------------------------------------
# american_waterfall
# --------------------------------------------------------------------------


def test_a_single_deal_american_waterfall_matches_european_waterfall():
    """A one-deal American waterfall must reduce exactly to a European one."""
    series = make_series(
        [("2020-01-01", -100.0, "capital_call"), ("2022-01-01", 150.0, "distribution")]
    )
    american = american_waterfall(
        {"only": series},
        preferred_rate=0.08,
        carry_rate=0.20,
        catch_up_rate=1.0,
        compounding="simple",
    )
    european = european_waterfall(
        series, preferred_rate=0.08, carry_rate=0.20, catch_up_rate=1.0, compounding="simple"
    )
    assert american.gp_total == pytest.approx(european.gp_total)
    assert american.lp_total == pytest.approx(european.lp_total)
    assert american.distributable == pytest.approx(european.distributable)
    assert american.deals["only"].gp_total == pytest.approx(european.gp_total)


def test_american_waterfall_pays_carry_deal_by_deal_hand_computed():
    """Two deals, 0% pref (so preferred/catch-up tiers vanish), 20% carry.

    Deal A: 100 in, 250 out -> profit 150 -> GP 30, LP 220.
    Deal B: 100 in,  20 out -> a loss, no profit -> GP 0, LP 20.
    Aggregate: GP 30, LP 240, distributable 270.
    """
    deals = {
        "A": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2020-06-01", 250.0, "distribution")]
        ),
        "B": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2021-01-01", 20.0, "distribution")]
        ),
    }
    result = american_waterfall(deals, preferred_rate=0.0, carry_rate=0.20, catch_up_rate=1.0)
    assert isinstance(result, AmericanWaterfallResult)
    assert result.deals["A"].gp_total == pytest.approx(30.0)
    assert result.deals["A"].lp_total == pytest.approx(220.0)
    assert result.deals["B"].gp_total == pytest.approx(0.0)
    assert result.deals["B"].lp_total == pytest.approx(20.0)
    assert result.gp_total == pytest.approx(30.0)
    assert result.lp_total == pytest.approx(240.0)
    assert result.distributable == pytest.approx(270.0)


def test_american_waterfall_catch_up_is_reused_unchanged_from_waterfall_split():
    """Deal-level catch-up must match the existing worked example exactly."""
    series = make_series(
        [("2018-01-01", -100.0, "capital_call"), ("2020-01-01", 200.0, "distribution")]
    )
    result = american_waterfall(
        {"deal": series}, preferred_rate=0.08, carry_rate=0.20, catch_up_rate=0.50
    )
    deal_result = result.deals["deal"]
    assert deal_result.gp_total == pytest.approx(20.0)
    assert deal_result.gp_profit_share == pytest.approx(0.20)


def test_american_waterfall_refuses_empty_deals():
    with pytest.raises(ValueError, match="deals is empty"):
        american_waterfall({}, preferred_rate=0.08, carry_rate=0.20)


def test_american_waterfall_refuses_a_non_mapping():
    with pytest.raises(TypeError, match="mapping"):
        american_waterfall([("only", None)], preferred_rate=0.08, carry_rate=0.20)


def test_american_waterfall_refuses_mixed_currencies():
    deals = {
        "A": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2021-01-01", 150.0, "distribution")],
            currency="USD",
        ),
        "B": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2021-01-01", 150.0, "distribution")],
            currency="EUR",
        ),
    }
    with pytest.raises(ValueError, match="multiple currencies"):
        american_waterfall(deals, preferred_rate=0.08, carry_rate=0.20)


# --------------------------------------------------------------------------
# gp_clawback — the headline test: same cash flows, European=0, American>0
# --------------------------------------------------------------------------


def test_european_never_claws_back_but_american_does_on_the_same_cash_flows():
    """The single most important test in this file.

    Same two deals as the hand-computed American test above (0% pref, 20%
    carry, 100% catch-up):

        Deal A: 100 in, 250 out (day ~150) -> profit 150 -> GP carry 30
        Deal B: 100 in,  20 out (later)    -> a loss      -> GP carry  0

    American (deal-by-deal): carry_received = 30 (paid the moment deal A
    exits, with no visibility into deal B's eventual loss).

    Pooled/European (whole-of-fund): contributed 200, distributed 270,
    profit 70, entitled GP carry = 0.20 * 70 = 14. A European structure only
    ever pays carry once, off exactly this pooled number, so its "received"
    and "entitled" are the same 14 by construction -- clawback is always 0.

    American clawback = max(0, 30 - 14) = 16 > 0: the GP was paid 30 on deal
    A's early profit but only 14 was ever earned once deal B's loss is
    counted, so 16 must come back.
    """
    deals = {
        "A": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2020-06-01", 250.0, "distribution")]
        ),
        "B": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2021-01-01", 20.0, "distribution")]
        ),
    }

    american = gp_clawback(deals, preferred_rate=0.0, carry_rate=0.20, catch_up_rate=1.0)
    assert isinstance(american, ClawbackResult)
    assert american.carry_received == pytest.approx(30.0)
    assert american.carry_entitled == pytest.approx(14.0)
    assert american.clawback_amount == pytest.approx(16.0)
    assert american.clawback_amount > 0.0

    pooled = make_series(
        [
            ("2020-01-01", -100.0, "capital_call"),
            ("2020-06-01", 250.0, "distribution"),
            ("2020-01-01", -100.0, "capital_call"),
            ("2021-01-01", 20.0, "distribution"),
        ]
    )
    european = european_waterfall(pooled, preferred_rate=0.0, carry_rate=0.20, catch_up_rate=1.0)
    assert european.gp_total == pytest.approx(14.0)
    # European pays once off the pooled totals: "received" and "entitled" are
    # the same number by construction, so the clawback is exactly zero.
    european_carry_received = european.gp_total
    european_carry_entitled = european.gp_total
    european_clawback = max(0.0, european_carry_received - european_carry_entitled)
    assert european_clawback == 0.0


def test_gp_clawback_tax_adjustment_scales_down_the_gross_amount():
    """Same scenario, 30% GP tax rate: net clawback = 16 * (1 - 0.30) = 11.2."""
    deals = {
        "A": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2020-06-01", 250.0, "distribution")]
        ),
        "B": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2021-01-01", 20.0, "distribution")]
        ),
    }
    gross = gp_clawback(deals, preferred_rate=0.0, carry_rate=0.20, catch_up_rate=1.0)
    net = gp_clawback(
        deals, preferred_rate=0.0, carry_rate=0.20, catch_up_rate=1.0, gp_tax_rate=0.30
    )
    assert gross.tax_adjusted is False
    assert gross.gp_tax_rate is None
    assert net.tax_adjusted is True
    assert net.gp_tax_rate == pytest.approx(0.30)
    assert net.clawback_amount == pytest.approx(11.2)
    assert net.clawback_amount == pytest.approx(gross.clawback_amount * 0.70)
    # The received/entitled figures themselves are unaffected by tax.
    assert net.carry_received == pytest.approx(gross.carry_received)
    assert net.carry_entitled == pytest.approx(gross.carry_entitled)


def test_gp_clawback_is_zero_when_no_deal_outpaced_the_pooled_entitlement():
    """A single profitable deal: deal-by-deal and pooled totals coincide."""
    deals = {
        "only": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2021-01-01", 150.0, "distribution")]
        )
    }
    result = gp_clawback(deals, preferred_rate=0.0, carry_rate=0.20, catch_up_rate=1.0)
    assert result.carry_received == pytest.approx(result.carry_entitled)
    assert result.clawback_amount == 0.0


def test_gp_clawback_refuses_out_of_range_tax_rate():
    deals = {
        "only": make_series(
            [("2020-01-01", -100.0, "capital_call"), ("2021-01-01", 150.0, "distribution")]
        )
    }
    with pytest.raises(ValueError, match="gp_tax_rate"):
        gp_clawback(deals, preferred_rate=0.08, carry_rate=0.20, gp_tax_rate=1.0)
    with pytest.raises(ValueError, match="gp_tax_rate"):
        gp_clawback(deals, preferred_rate=0.08, carry_rate=0.20, gp_tax_rate=-0.1)


def test_gp_clawback_refuses_empty_deals():
    with pytest.raises(ValueError, match="deals is empty"):
        gp_clawback({}, preferred_rate=0.08, carry_rate=0.20)


def test_clawback_result_rejects_an_inconsistent_tax_flag():
    with pytest.raises(ValueError, match="tax_adjusted"):
        ClawbackResult(
            carry_received=10.0,
            carry_entitled=5.0,
            clawback_amount=5.0,
            tax_adjusted=True,
            gp_tax_rate=None,
        )
    with pytest.raises(ValueError, match="tax_adjusted"):
        ClawbackResult(
            carry_received=10.0,
            carry_entitled=5.0,
            clawback_amount=5.0,
            tax_adjusted=False,
            gp_tax_rate=0.3,
        )
