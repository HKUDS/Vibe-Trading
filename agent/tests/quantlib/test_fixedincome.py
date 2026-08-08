"""Tests for src.quantlib.fixedincome.

Every sensitivity is checked against a finite-difference reprice of the pricing
function itself, so a change to `bond_price` cannot leave duration/convexity
quietly stale.
"""

import datetime as dt

import numpy as np
import pytest

from src.quantlib.fixedincome import (
    COMPOUNDING_CONVENTIONS,
    CurveFit,
    accrued_interest,
    bond_cashflows,
    bond_price,
    convexity,
    dv01,
    effective_duration,
    fit_yield_curve,
    macaulay_duration,
    modified_duration,
    nelson_siegel,
    svensson,
    year_fraction,
    ytm_solve,
)

BUMP_1BP = 1e-4


# --------------------------------------------------------------------------
# bond_price
# --------------------------------------------------------------------------


@pytest.mark.parametrize("freq", [1, 2, 4, 12])
@pytest.mark.parametrize("n_periods", [1, 5, 20])
@pytest.mark.parametrize("rate", [0.02, 0.05, 0.11])
def test_bond_prices_at_par_when_coupon_equals_ytm(freq, n_periods, rate):
    assert bond_price(100.0, rate, rate, n_periods, freq) == pytest.approx(100.0)


def test_markdown_worked_example_is_preserved():
    # The value printed in credit-analysis/SKILL.md for a 5y 5% bond at 4%.
    assert bond_price(100, 0.05, 0.04, 5) == pytest.approx(104.4518, abs=5e-5)


def test_premium_and_discount_ordering():
    assert bond_price(100, 0.06, 0.04, 10) > 100.0
    assert bond_price(100, 0.02, 0.04, 10) < 100.0


def test_zero_yield_returns_undiscounted_cashflows():
    _, amounts = bond_cashflows(100, 0.05, 6, freq=2)
    assert bond_price(100, 0.05, 0.0, 6, freq=2) == pytest.approx(amounts.sum())


def test_continuous_compounding_discounts_harder_than_discrete():
    discrete = bond_price(100, 0.05, 0.04, 10, 2, compounding="discrete")
    continuous = bond_price(100, 0.05, 0.04, 10, 2, compounding="continuous")
    assert continuous < discrete


def test_unknown_compounding_rejected():
    with pytest.raises(ValueError, match="unknown compounding"):
        bond_price(100, 0.05, 0.04, 5, compounding="annual-ish")


@pytest.mark.parametrize("bad", [0, -3])
def test_invalid_schedule_rejected(bad):
    with pytest.raises(ValueError):
        bond_price(100, 0.05, 0.04, bad)
    with pytest.raises(ValueError):
        bond_price(100, 0.05, 0.04, 5, freq=bad)


# --------------------------------------------------------------------------
# ytm_solve
# --------------------------------------------------------------------------


@pytest.mark.parametrize("compounding", COMPOUNDING_CONVENTIONS)
@pytest.mark.parametrize("coupon,ytm,n,freq", [
    (0.05, 0.04, 5, 1),
    (0.03, 0.065, 20, 2),
    (0.00, 0.05, 10, 1),
    (0.08, 0.005, 7, 4),
])
def test_price_ytm_round_trip(coupon, ytm, n, freq, compounding):
    price = bond_price(100, coupon, ytm, n, freq, compounding)
    assert ytm_solve(price, 100, coupon, n, freq, compounding) == pytest.approx(
        ytm, abs=1e-10
    )


def test_ytm_solve_raises_when_price_unreachable():
    with pytest.raises(ValueError, match="no yield in"):
        ytm_solve(1e9, 100, 0.05, 5)


def test_ytm_solve_rejects_inverted_bracket():
    with pytest.raises(ValueError, match="bracket must be increasing"):
        ytm_solve(100, 100, 0.05, 5, bracket=(1.0, 0.0))


# --------------------------------------------------------------------------
# duration / convexity / DV01 -- all against a reprice
# --------------------------------------------------------------------------


def test_zero_coupon_macaulay_duration_equals_maturity():
    assert macaulay_duration(100, 0.0, 0.05, 10, freq=1) == pytest.approx(10.0)
    assert macaulay_duration(100, 0.0, 0.05, 20, freq=2) == pytest.approx(10.0)


def test_macaulay_duration_is_below_maturity_for_a_coupon_bond():
    assert macaulay_duration(100, 0.05, 0.04, 10) < 10.0


@pytest.mark.parametrize("compounding", COMPOUNDING_CONVENTIONS)
@pytest.mark.parametrize("coupon,ytm,n,freq", [
    (0.05, 0.04, 5, 1),
    (0.03, 0.06, 20, 2),
    (0.00, 0.05, 10, 1),
])
def test_modified_duration_matches_central_difference(coupon, ytm, n, freq, compounding):
    def price(y):
        return bond_price(100, coupon, y, n, freq, compounding)

    numeric = (price(ytm - BUMP_1BP) - price(ytm + BUMP_1BP)) / (
        2 * BUMP_1BP * price(ytm)
    )
    analytic = modified_duration(100, coupon, ytm, n, freq, compounding)
    # A central difference is third-order accurate, so at a 1bp half-width the
    # residual truncation error lands around 1e-6 relative for a 30y bond.
    assert analytic == pytest.approx(numeric, rel=1e-5)


def test_modified_duration_equals_macaulay_under_continuous_compounding():
    args = (100, 0.05, 0.04, 10, 2, "continuous")
    assert modified_duration(*args) == pytest.approx(macaulay_duration(*args))


def test_modified_duration_is_macaulay_over_one_plus_periodic_yield():
    d_mac = macaulay_duration(100, 0.05, 0.04, 10, 2)
    assert modified_duration(100, 0.05, 0.04, 10, 2) == pytest.approx(
        d_mac / (1 + 0.04 / 2)
    )


@pytest.mark.parametrize("coupon,ytm,n,freq", [
    (0.05, 0.04, 5, 1),
    (0.03, 0.06, 20, 2),
    (0.00, 0.05, 30, 1),
])
def test_dv01_matches_a_one_basis_point_reprice(coupon, ytm, n, freq):
    par_amount = 1_000_000.0
    base = bond_price(100, coupon, ytm, n, freq)
    bumped = bond_price(100, coupon, ytm + BUMP_1BP, n, freq)
    repriced = (base - bumped) * par_amount / 100.0

    analytic = dv01(100, coupon, ytm, n, freq, par_amount)
    assert analytic == pytest.approx(repriced, rel=3e-3)
    assert analytic > repriced  # duration alone ignores positive convexity

    # Almost all of that gap is the convexity term, so duration, convexity and
    # the reprice have to be mutually consistent to close it. What is left over
    # is the third-order term, worth ~1e-3 of the gap at a 1bp bump on 30y.
    cx = convexity(100, coupon, ytm, n, freq)
    expected_gap = 0.5 * cx * BUMP_1BP**2 * base * par_amount / 100.0
    assert analytic - repriced == pytest.approx(expected_gap, rel=3e-3)


def test_dv01_matches_a_symmetric_reprice_much_more_tightly():
    coupon, ytm, n, freq = 0.05, 0.04, 5, 1
    down = bond_price(100, coupon, ytm - BUMP_1BP, n, freq)
    up = bond_price(100, coupon, ytm + BUMP_1BP, n, freq)
    repriced = (down - up) / 2 * 1_000_000.0 / 100.0
    assert dv01(100, coupon, ytm, n, freq) == pytest.approx(repriced, rel=1e-6)


def test_dv01_scales_linearly_in_par_amount():
    one = dv01(100, 0.05, 0.04, 5, par_amount=1_000_000.0)
    ten = dv01(100, 0.05, 0.04, 5, par_amount=10_000_000.0)
    assert ten == pytest.approx(10 * one)


def test_dv01_rejects_zero_face():
    with pytest.raises(ValueError, match="face must be non-zero"):
        dv01(0, 0.05, 0.04, 5)


@pytest.mark.parametrize("compounding", COMPOUNDING_CONVENTIONS)
@pytest.mark.parametrize("coupon,ytm,n,freq", [
    (0.05, 0.04, 5, 1),
    (0.03, 0.06, 20, 2),
    (0.00, 0.05, 10, 1),
])
def test_convexity_is_positive_and_matches_second_difference(
    coupon, ytm, n, freq, compounding
):
    def price(y):
        return bond_price(100, coupon, y, n, freq, compounding)

    h = 1e-4
    numeric = (price(ytm + h) - 2 * price(ytm) + price(ytm - h)) / (h**2 * price(ytm))
    analytic = convexity(100, coupon, ytm, n, freq, compounding)
    assert analytic > 0.0
    assert analytic == pytest.approx(numeric, rel=1e-5)


def test_continuous_zero_coupon_convexity_is_maturity_squared():
    assert convexity(100, 0.0, 0.04, 10, 1, "continuous") == pytest.approx(100.0)


def test_convexity_grows_with_maturity():
    short = convexity(100, 0.05, 0.04, 3)
    long = convexity(100, 0.05, 0.04, 25)
    assert long > short > 0.0


def test_second_order_expansion_beats_duration_alone_on_a_large_shock():
    coupon, ytm, n = 0.05, 0.04, 20
    shock = 0.01
    base = bond_price(100, coupon, ytm, n)
    actual = bond_price(100, coupon, ytm + shock, n)

    d_mod = modified_duration(100, coupon, ytm, n)
    cx = convexity(100, coupon, ytm, n)
    first_order = base * (1 - d_mod * shock)
    second_order = base * (1 - d_mod * shock + 0.5 * cx * shock**2)

    assert abs(second_order - actual) < abs(first_order - actual)


# --------------------------------------------------------------------------
# effective_duration
# --------------------------------------------------------------------------


def test_effective_duration_matches_analytic_duration_for_a_bullet_bond():
    def reprice(y):
        return bond_price(100, 0.05, y, 10, 2)

    assert effective_duration(reprice, 0.04) == pytest.approx(
        modified_duration(100, 0.05, 0.04, 10, 2), rel=1e-5
    )


def test_effective_duration_rejects_a_non_positive_bump():
    with pytest.raises(ValueError, match="bump must be positive"):
        effective_duration(lambda y: 100.0, 0.04, bump=0.0)


def test_effective_duration_rejects_a_zero_base_price():
    with pytest.raises(ValueError, match="base price is zero"):
        effective_duration(lambda y: 0.0, 0.04)


# --------------------------------------------------------------------------
# day count / accrued interest
# --------------------------------------------------------------------------


def test_act_365f_and_act_360_use_their_stated_bases():
    start, end = dt.date(2023, 1, 1), dt.date(2023, 7, 1)
    days = (end - start).days
    assert year_fraction(start, end, "ACT/365F") == pytest.approx(days / 365)
    assert year_fraction(start, end, "ACT/360") == pytest.approx(days / 360)


def test_30_360_treats_every_month_as_thirty_days():
    assert year_fraction(dt.date(2024, 1, 31), dt.date(2024, 7, 31), "30/360") == (
        pytest.approx(0.5)
    )
    assert year_fraction(dt.date(2024, 1, 1), dt.date(2025, 1, 1), "30/360") == (
        pytest.approx(1.0)
    )


def test_30_360_us_and_eurobond_differ_when_only_the_end_leg_is_the_31st():
    start, end = dt.date(2024, 1, 15), dt.date(2024, 3, 31)
    # US basis leaves D2 = 31 because D1 was not clipped to 30; 30E/360 clips it.
    assert year_fraction(start, end, "30/360") == pytest.approx((60 + 16) / 360)
    assert year_fraction(start, end, "30E/360") == pytest.approx((60 + 15) / 360)


def test_act_act_uses_a_366_day_basis_inside_a_leap_year():
    assert year_fraction(
        dt.date(2024, 1, 1), dt.date(2025, 1, 1), "ACT/ACT"
    ) == pytest.approx(1.0)
    assert year_fraction(
        dt.date(2024, 1, 1), dt.date(2024, 3, 1), "ACT/ACT"
    ) == pytest.approx(60 / 366)


def test_year_fraction_is_antisymmetric():
    a, b = dt.date(2024, 3, 1), dt.date(2024, 9, 1)
    assert year_fraction(b, a) == pytest.approx(-year_fraction(a, b))


def test_unknown_day_count_rejected():
    with pytest.raises(ValueError, match="unknown day_count"):
        year_fraction(dt.date(2024, 1, 1), dt.date(2024, 2, 1), "ACT/ACT-ICMA")


def test_accrued_interest_is_zero_on_a_coupon_date_and_full_at_the_next():
    last, nxt = dt.date(2024, 1, 15), dt.date(2024, 7, 15)
    assert accrued_interest(100, 0.05, 2, last, last, nxt) == pytest.approx(0.0)
    assert accrued_interest(100, 0.05, 2, last, nxt, nxt) == pytest.approx(2.5)


def test_accrued_interest_is_linear_in_elapsed_time_under_30_360():
    last, mid, nxt = dt.date(2024, 1, 15), dt.date(2024, 4, 15), dt.date(2024, 7, 15)
    assert accrued_interest(
        100, 0.05, 2, last, mid, nxt, day_count="30/360"
    ) == pytest.approx(1.25)


def test_accrued_interest_rejects_settlement_outside_the_period():
    last, nxt = dt.date(2024, 1, 15), dt.date(2024, 7, 15)
    with pytest.raises(ValueError, match="settlement must fall inside"):
        accrued_interest(100, 0.05, 2, last, dt.date(2024, 8, 1), nxt)


def test_accrued_interest_rejects_unordered_coupon_dates():
    with pytest.raises(ValueError, match="last_coupon must precede next_coupon"):
        accrued_interest(
            100, 0.05, 2, dt.date(2024, 7, 15), dt.date(2024, 7, 15), dt.date(2024, 1, 15)
        )


# --------------------------------------------------------------------------
# curve models
# --------------------------------------------------------------------------


def test_nelson_siegel_limits():
    beta0, beta1, beta2, lam = 0.045, -0.02, 0.03, 2.5
    # tau -> 0 is the instantaneous short rate beta0 + beta1.
    assert nelson_siegel(0.0, beta0, beta1, beta2, lam) == pytest.approx(beta0 + beta1)
    assert nelson_siegel(1e-9, beta0, beta1, beta2, lam) == pytest.approx(
        beta0 + beta1, abs=1e-8
    )
    # tau -> infinity decays to the level factor.
    assert nelson_siegel(1e6, beta0, beta1, beta2, lam) == pytest.approx(beta0, abs=1e-5)


def test_nelson_siegel_returns_a_float_for_scalar_input_and_an_array_otherwise():
    assert isinstance(nelson_siegel(5.0, 0.04, -0.01, 0.01, 2.0), float)
    out = nelson_siegel([1.0, 5.0], 0.04, -0.01, 0.01, 2.0)
    assert isinstance(out, np.ndarray) and out.shape == (2,)


def test_svensson_reduces_to_nelson_siegel_when_the_second_hump_is_flat():
    tau = np.array([0.5, 1.0, 3.0, 10.0])
    assert np.allclose(
        svensson(tau, 0.04, -0.02, 0.01, 0.0, 1.5, 6.0),
        nelson_siegel(tau, 0.04, -0.02, 0.01, 1.5),
    )


def test_curve_models_reject_a_non_positive_decay():
    with pytest.raises(ValueError, match="decay parameter must be positive"):
        nelson_siegel(1.0, 0.04, -0.01, 0.01, 0.0)
    with pytest.raises(ValueError, match="decay parameter must be positive"):
        svensson(1.0, 0.04, -0.01, 0.01, 0.0, 1.5, -1.0)


def test_curve_models_reject_negative_maturities():
    with pytest.raises(ValueError, match="maturities must be non-negative"):
        nelson_siegel([-1.0, 2.0], 0.04, -0.01, 0.01, 2.0)


TENORS = np.array([0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 30.0])
OFF_GRID = np.array([0.75, 4.0, 8.5, 15.0, 25.0])


def test_fit_recovers_a_nelson_siegel_curve_it_generated():
    truth = (0.045, -0.02, 0.03, 2.5)
    fit = fit_yield_curve(TENORS, nelson_siegel(TENORS, *truth), model="nelson_siegel")

    assert fit.model == "nelson_siegel"
    assert fit.rmse < 1e-10
    assert len(fit.params) == 4
    assert fit.params == pytest.approx(truth, rel=1e-6)
    assert np.allclose(fit(TENORS), nelson_siegel(TENORS, *truth), atol=1e-10)
    assert np.allclose(fit(OFF_GRID), nelson_siegel(OFF_GRID, *truth), atol=1e-10)


def test_fit_recovers_a_svensson_curve_it_generated():
    truth = (0.05, -0.03, 0.04, -0.02, 1.2, 8.0)
    fit = fit_yield_curve(TENORS, svensson(TENORS, *truth), model="svensson")

    assert fit.model == "svensson"
    assert fit.rmse < 1e-10
    assert len(fit.params) == 6
    # Curve values are the identifiable object; the parameterisation is not
    # unique, so the curve is what is asserted here.
    assert np.allclose(fit(TENORS), svensson(TENORS, *truth), atol=1e-10)
    assert np.allclose(fit(OFF_GRID), svensson(OFF_GRID, *truth), atol=1e-10)


def test_svensson_fit_is_at_least_as_good_as_nelson_siegel_on_the_same_data():
    truth = (0.05, -0.03, 0.04, -0.02, 1.2, 8.0)
    observed = svensson(TENORS, *truth)
    ns = fit_yield_curve(TENORS, observed, model="nelson_siegel")
    sv = fit_yield_curve(TENORS, observed, model="svensson")
    assert sv.rmse <= ns.rmse


def test_fit_is_robust_to_noise_and_stays_close_to_the_generating_curve():
    truth = (0.045, -0.02, 0.03, 2.5)
    clean = nelson_siegel(TENORS, *truth)
    noisy = clean + np.random.default_rng(20260806).normal(0.0, 2e-4, TENORS.size)
    fit = fit_yield_curve(TENORS, noisy, model="nelson_siegel")
    assert np.max(np.abs(fit(TENORS) - clean)) < 5e-4


def test_curve_fit_is_frozen_and_callable():
    fit = fit_yield_curve(TENORS, nelson_siegel(TENORS, 0.04, -0.01, 0.01, 2.0),
                          model="nelson_siegel")
    assert isinstance(fit, CurveFit)
    with pytest.raises(Exception):
        fit.rmse = 0.5  # type: ignore[misc]


def test_curve_fit_rejects_an_unknown_stored_model():
    with pytest.raises(ValueError, match="unknown curve model"):
        CurveFit(model="cubic-spline", params=(0.0,))(1.0)


def test_fit_yield_curve_rejects_an_unknown_model():
    with pytest.raises(ValueError, match="unknown model"):
        fit_yield_curve(TENORS, nelson_siegel(TENORS, 0.04, -0.01, 0.01, 2.0), "cubic")


def test_fit_yield_curve_rejects_mismatched_or_thin_inputs():
    with pytest.raises(ValueError, match="same length"):
        fit_yield_curve([1.0, 2.0, 3.0], [0.01, 0.02])
    with pytest.raises(ValueError, match="only 3 observations"):
        fit_yield_curve([1.0, 2.0, 3.0], [0.01, 0.02, 0.03], model="nelson_siegel")


def test_fit_yield_curve_rejects_non_positive_maturities():
    with pytest.raises(ValueError, match="strictly positive"):
        fit_yield_curve(np.zeros(10), np.zeros(10), model="nelson_siegel")
