"""Tests for src.quantlib.risk.

The sign convention (a loss is a positive number) is asserted directly rather
than assumed, because a flipped sign in this family of functions is silent: the
number still looks plausible, it is just the wrong one.
"""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import genpareto, norm

from src.quantlib.risk import (
    analyze_mc_results,
    fit_gpd_tail,
    historical_cvar,
    historical_var,
    max_drawdown_analysis,
    monte_carlo_gbm,
    parametric_var,
)

# 20 observations, already ascending: -0.10, -0.09, ..., 0.09.
# The 95% VaR order statistic is index floor(0.05 * 20) = 1, i.e. -0.09.
FIXED_RETURNS = np.round(np.arange(-0.10, 0.10, 0.01), 10)


def test_fixture_is_the_array_the_hand_computations_assume():
    assert FIXED_RETURNS.size == 20
    assert FIXED_RETURNS[0] == pytest.approx(-0.10)
    assert FIXED_RETURNS[1] == pytest.approx(-0.09)
    assert FIXED_RETURNS[-1] == pytest.approx(0.09)


# --------------------------------------------------------------------------
# historical_var -- hand-computed order statistic
# --------------------------------------------------------------------------


def test_historical_var_is_the_hand_computed_order_statistic():
    # index floor((1 - 0.95) * 20) = 1 -> second smallest = -0.09 -> loss 0.09
    assert historical_var(FIXED_RETURNS, confidence=0.95) == pytest.approx(0.09)


def test_historical_var_at_99_takes_the_worst_observation():
    # index floor(0.01 * 20) = 0 -> smallest = -0.10 -> loss 0.10
    assert historical_var(FIXED_RETURNS, confidence=0.99) == pytest.approx(0.10)


def test_historical_var_is_insensitive_to_input_order_and_container():
    shuffled = np.random.default_rng(0).permutation(FIXED_RETURNS)
    expected = historical_var(FIXED_RETURNS, confidence=0.95)
    assert historical_var(shuffled, confidence=0.95) == pytest.approx(expected)
    assert historical_var(pd.Series(FIXED_RETURNS), confidence=0.95) == pytest.approx(expected)
    assert historical_var(list(FIXED_RETURNS), confidence=0.95) == pytest.approx(expected)


def test_historical_var_scales_with_square_root_of_time():
    one_day = historical_var(FIXED_RETURNS, confidence=0.95)
    assert historical_var(FIXED_RETURNS, confidence=0.95, horizon=4) == pytest.approx(2 * one_day)


def test_historical_var_ignores_nan():
    with_nan = np.concatenate([FIXED_RETURNS, [np.nan, np.inf, -np.inf]])
    assert historical_var(with_nan, confidence=0.95) == pytest.approx(0.09)


# --------------------------------------------------------------------------
# parametric_var -- closed-form normal quantile
# --------------------------------------------------------------------------


@pytest.mark.parametrize("confidence", [0.90, 0.95, 0.99])
def test_parametric_var_matches_the_closed_form_normal_quantile(confidence):
    mu = float(FIXED_RETURNS.mean())
    sigma = float(FIXED_RETURNS.std(ddof=1))
    expected = -(mu + norm.ppf(1 - confidence) * sigma)
    assert parametric_var(FIXED_RETURNS, confidence=confidence) == pytest.approx(expected, rel=1e-12)


def test_parametric_var_on_a_known_mean_and_sigma():
    # A two-point sample: mean 0, and sample std (ddof=1) = sqrt(2) * 0.01,
    # because the ddof=1 denominator is n - 1 = 1, not n.
    returns = np.array([-0.01, 0.01])
    sigma = 0.01 * np.sqrt(2)
    assert float(returns.std(ddof=1)) == pytest.approx(sigma, rel=1e-12)
    expected = -norm.ppf(0.05) * sigma  # mu = 0
    assert parametric_var(returns, confidence=0.95) == pytest.approx(expected, rel=1e-12)


def test_parametric_var_scales_with_square_root_of_time():
    one_day = parametric_var(FIXED_RETURNS)
    assert parametric_var(FIXED_RETURNS, horizon=9) == pytest.approx(3 * one_day)


def test_parametric_var_is_not_uniformly_below_historical_var():
    """The 'normal fit always understates risk' folklore is false at 95%.

    A fat tail inflates the fitted sigma, which pushes the normal quantile
    outward at moderate confidence while the empirical quantile is still in the
    body. The understatement only appears deep in the tail. Pinned here because
    both the module docstring and SKILL.md previously stated it as absolute.
    """
    above = {c: 0 for c in (0.90, 0.95, 0.99)}
    trials = 120
    for seed in range(trials):
        returns = np.random.default_rng(seed).standard_t(4, 750) * 0.011 - 0.0004
        for confidence in above:
            above[confidence] += parametric_var(returns, confidence) >= historical_var(
                returns, confidence
            )
    assert above[0.90] == trials  # parametric is ALWAYS the higher one here
    assert above[0.95] / trials > 0.85  # and usually higher at the 95% default
    assert above[0.99] / trials < 0.15  # only deep in the tail does it understate


def test_parametric_var_needs_two_observations():
    with pytest.raises(ValueError, match="at least 2 observations"):
        parametric_var([0.01])


# --------------------------------------------------------------------------
# Sign convention -- a loss is positive
# --------------------------------------------------------------------------


def test_var_of_a_losing_series_is_positive():
    losses = np.linspace(-0.20, -0.01, 50)  # every observation is a loss
    assert historical_var(losses) > 0
    assert parametric_var(losses) > 0
    assert historical_cvar(losses) > 0


def test_var_of_a_uniformly_profitable_series_is_negative():
    # Sign convention is not clipped: no loss in the tail reports a negative
    # "loss", i.e. a gain. Asserting this pins the direction of the convention.
    gains = np.linspace(0.01, 0.20, 50)
    assert historical_var(gains) < 0
    assert parametric_var(gains) < 0
    assert historical_cvar(gains) < 0


def test_the_documented_invariant_is_cvar_ge_var_and_not_var_ge_zero():
    # The module docstring used to claim `cvar >= var >= 0` "by construction".
    # The right half is false and the left half is the one worth relying on:
    # ordering always holds, non-negativity does not.
    gains = np.linspace(0.01, 0.20, 50)
    assert historical_cvar(gains) >= historical_var(gains)
    assert historical_var(gains) < 0.0  # refutes `var >= 0`
    summary = analyze_mc_results(_paths_with_terminal_returns(gains))
    assert summary["cvar"] >= summary["var"]
    assert summary["var"] < 0.0


def test_max_drawdown_is_reported_as_a_positive_fraction():
    equity = pd.Series([100.0, 50.0, 60.0])
    assert max_drawdown_analysis(equity)["max_drawdown"] == pytest.approx(0.5)


def test_a_bigger_loss_is_a_bigger_number_for_every_measure():
    mild = FIXED_RETURNS
    severe = FIXED_RETURNS * 2.0
    assert historical_var(severe) > historical_var(mild)
    assert parametric_var(severe) > parametric_var(mild)
    assert historical_cvar(severe) > historical_cvar(mild)


# --------------------------------------------------------------------------
# historical_cvar -- hand-computed, and cvar >= var always
# --------------------------------------------------------------------------


def test_historical_cvar_is_the_hand_computed_tail_mean():
    # Tail at 95% is everything at or below the VaR order statistic (-0.09),
    # i.e. {-0.10, -0.09}; mean -0.095 -> loss 0.095.
    assert historical_cvar(FIXED_RETURNS, confidence=0.95) == pytest.approx(0.095)


def test_historical_cvar_at_99_is_the_single_worst_observation():
    assert historical_cvar(FIXED_RETURNS, confidence=0.99) == pytest.approx(0.10)


@pytest.mark.parametrize("confidence", [0.80, 0.90, 0.95, 0.975, 0.99])
@pytest.mark.parametrize("seed", range(8))
def test_cvar_is_never_below_var(confidence, seed):
    rng = np.random.default_rng(seed)
    # Skewed, fat-tailed draws -- the regime where a naive tail mask breaks.
    returns = rng.standard_t(df=3, size=500) * 0.01 - 0.002
    var = historical_var(returns, confidence=confidence)
    cvar = historical_cvar(returns, confidence=confidence)
    assert cvar >= var


def test_cvar_is_never_below_var_on_the_fixed_array():
    for confidence in (0.5, 0.8, 0.9, 0.95, 0.99):
        assert historical_cvar(FIXED_RETURNS, confidence) >= historical_var(FIXED_RETURNS, confidence)


# --------------------------------------------------------------------------
# Input validation shared by the VaR family
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fn", [historical_var, parametric_var, historical_cvar])
@pytest.mark.parametrize("confidence", [0.0, 1.0, -0.1, 1.5])
def test_confidence_must_be_a_strict_probability(fn, confidence):
    with pytest.raises(ValueError, match="confidence"):
        fn(FIXED_RETURNS, confidence=confidence)


@pytest.mark.parametrize("fn", [historical_var, parametric_var, historical_cvar])
def test_horizon_must_be_at_least_one(fn):
    with pytest.raises(ValueError, match="horizon"):
        fn(FIXED_RETURNS, horizon=0)


@pytest.mark.parametrize("fn", [historical_var, parametric_var, historical_cvar])
def test_empty_input_is_rejected(fn):
    with pytest.raises(ValueError, match="no finite observation"):
        fn([np.nan, np.nan])


# --------------------------------------------------------------------------
# max_drawdown_analysis -- hand-built path, known peak / trough / recovery
# --------------------------------------------------------------------------


def _dated(values):
    """Attach consecutive calendar days starting 2024-01-01 to a value list."""
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="D"))


def test_max_drawdown_finds_the_hand_built_peak_trough_and_recovery():
    #        01-01  01-02  01-03  01-04  01-05  01-06
    # value    100    110    120     90    100    121
    # peak     100    110    120    120    120    121
    # dd         0      0      0  -0.25 -0.1667     0
    equity = _dated([100.0, 110.0, 120.0, 90.0, 100.0, 121.0])
    result = max_drawdown_analysis(equity)

    assert result["max_drawdown"] == pytest.approx(0.25)
    assert result["peak_date"] == pd.Timestamp("2024-01-03")
    assert result["trough_date"] == pd.Timestamp("2024-01-04")
    assert result["recovery_date"] == pd.Timestamp("2024-01-06")
    assert result["recovered"] is True
    assert result["peak_to_trough_periods"] == 1
    assert result["trough_to_recovery_periods"] == 2
    assert result["underwater_days"] == 1
    assert result["recovery_days"] == 2


def test_max_drawdown_recovery_needs_the_peak_value_not_a_partial_bounce():
    # Bounces to 119.99, one cent short of the 120 peak -> still underwater.
    equity = _dated([100.0, 120.0, 90.0, 119.99])
    result = max_drawdown_analysis(equity)
    assert result["max_drawdown"] == pytest.approx(0.25)
    assert result["recovery_date"] is None
    assert result["recovered"] is False
    assert result["trough_to_recovery_periods"] is None
    assert result["recovery_days"] is None


def test_max_drawdown_picks_the_deepest_of_two_drawdowns():
    # First drawdown 100 -> 80 (20%), second 130 -> 91 (30%).
    equity = _dated([100.0, 80.0, 100.0, 130.0, 91.0, 140.0])
    result = max_drawdown_analysis(equity)
    assert result["max_drawdown"] == pytest.approx(0.30)
    assert result["peak_date"] == pd.Timestamp("2024-01-04")
    assert result["trough_date"] == pd.Timestamp("2024-01-05")
    assert result["recovery_date"] == pd.Timestamp("2024-01-06")


def test_max_drawdown_of_a_monotonically_rising_curve_is_zero():
    result = max_drawdown_analysis(_dated([100.0, 101.0, 102.0]))
    assert result["max_drawdown"] == pytest.approx(0.0)
    assert result["recovered"] is True
    assert result["recovery_days"] == 0


def test_max_drawdown_without_a_datetime_index_omits_calendar_days():
    result = max_drawdown_analysis([100.0, 120.0, 90.0, 130.0])
    assert result["max_drawdown"] == pytest.approx(0.25)
    assert result["peak_date"] == 1
    assert result["trough_date"] == 2
    assert result["recovery_date"] == 3
    assert result["underwater_days"] is None
    assert result["recovery_days"] is None
    assert result["peak_to_trough_periods"] == 1


def test_max_drawdown_drops_nan_and_keeps_the_surviving_index_labels():
    equity = _dated([100.0, np.nan, 120.0, 90.0, 130.0])
    result = max_drawdown_analysis(equity)
    assert result["max_drawdown"] == pytest.approx(0.25)
    assert result["peak_date"] == pd.Timestamp("2024-01-03")
    assert result["trough_date"] == pd.Timestamp("2024-01-04")
    assert result["recovery_date"] == pd.Timestamp("2024-01-05")
    # Period counts are in surviving observations; calendar days use the index.
    assert result["peak_to_trough_periods"] == 1
    assert result["underwater_days"] == 1


def test_max_drawdown_rejects_an_all_nan_series():
    with pytest.raises(ValueError, match="no finite observation"):
        max_drawdown_analysis([np.nan, np.nan])


def test_max_drawdown_rejects_non_positive_equity():
    with pytest.raises(ValueError, match="strictly positive"):
        max_drawdown_analysis([100.0, 0.0, 50.0])


# --------------------------------------------------------------------------
# monte_carlo_gbm -- reproducibility and drift
# --------------------------------------------------------------------------


def test_gbm_is_reproducible_under_a_fixed_seed():
    a = monte_carlo_gbm(100.0, 0.08, 0.20, n_steps=30, n_paths=200, seed=42)
    b = monte_carlo_gbm(100.0, 0.08, 0.20, n_steps=30, n_paths=200, seed=42)
    assert np.array_equal(a, b)


def test_gbm_differs_under_a_different_seed():
    a = monte_carlo_gbm(100.0, 0.08, 0.20, n_steps=30, n_paths=200, seed=42)
    c = monte_carlo_gbm(100.0, 0.08, 0.20, n_steps=30, n_paths=200, seed=43)
    assert not np.array_equal(a, c)


def test_gbm_shape_starts_at_s0():
    paths = monte_carlo_gbm(50.0, 0.05, 0.15, n_steps=10, n_paths=7, seed=1)
    assert paths.shape == (7, 11)
    assert np.all(paths[:, 0] == 50.0)
    assert np.all(paths > 0)


def test_gbm_with_zero_volatility_is_the_deterministic_drift_path():
    s0, mu, n_steps = 100.0, 0.10, 252
    paths = monte_carlo_gbm(s0, mu, 0.0, n_steps=n_steps, n_paths=3, seed=0)
    expected_terminal = s0 * np.exp((mu - 0.0) * n_steps / 252)
    assert paths[:, -1] == pytest.approx(expected_terminal, rel=1e-12)


def test_gbm_mean_terminal_price_drifts_as_expected_over_many_paths():
    s0, mu, sigma, n_steps, n_paths = 100.0, 0.10, 0.20, 63, 60_000
    paths = monte_carlo_gbm(s0, mu, sigma, n_steps=n_steps, n_paths=n_paths, seed=2026)
    # E[S_T] = S0 * exp(mu * T) with T in years.
    years = n_steps / 252
    expected = s0 * np.exp(mu * years)
    observed = float(paths[:, -1].mean())
    # Monte Carlo standard error of the mean, times 4 -> a ~1-in-16k false alarm.
    stderr = expected * np.sqrt(np.exp(sigma**2 * years) - 1) / np.sqrt(n_paths)
    assert abs(observed - expected) < 4 * stderr


def test_gbm_median_terminal_price_follows_the_log_drift():
    s0, mu, sigma, n_steps, n_paths = 100.0, 0.10, 0.20, 252, 40_000
    paths = monte_carlo_gbm(s0, mu, sigma, n_steps=n_steps, n_paths=n_paths, seed=7)
    expected_median = s0 * np.exp((mu - 0.5 * sigma**2) * n_steps / 252)
    assert float(np.median(paths[:, -1])) == pytest.approx(expected_median, rel=0.02)


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"s0": 0.0}, "s0"),
        ({"sigma": -0.1}, "sigma"),
        ({"n_steps": 0}, "n_steps"),
        ({"n_paths": 0}, "n_paths"),
        ({"steps_per_year": 0}, "steps_per_year"),
    ],
)
def test_gbm_rejects_impossible_parameters(kwargs, match):
    args = {"s0": 100.0, "mu": 0.05, "sigma": 0.2, "n_steps": 10, "n_paths": 5}
    args.update(kwargs)
    with pytest.raises(ValueError, match=match):
        monte_carlo_gbm(**args, seed=0)


# --------------------------------------------------------------------------
# analyze_mc_results
# --------------------------------------------------------------------------


def _paths_with_terminal_returns(returns):
    """Build a two-column price matrix whose terminal returns are exactly `returns`."""
    returns = np.asarray(returns, dtype=float)
    return np.column_stack([np.ones_like(returns), 1.0 + returns])


def test_analyze_mc_results_reuses_the_var_convention():
    summary = analyze_mc_results(_paths_with_terminal_returns(FIXED_RETURNS), confidence=0.95)
    assert summary["var"] == pytest.approx(0.09)
    assert summary["cvar"] == pytest.approx(0.095)
    assert summary["cvar"] >= summary["var"]
    assert summary["mean_return"] == pytest.approx(FIXED_RETURNS.mean())
    assert summary["median_return"] == pytest.approx(np.median(FIXED_RETURNS))
    assert summary["prob_loss"] == pytest.approx(0.5)  # 10 of 20 are negative
    # Signed return percentiles, linear interpolation: -0.10 + 0.95 * 0.01.
    assert summary["worst_5pct_return"] == pytest.approx(-0.0905)
    assert summary["best_5pct_return"] == pytest.approx(0.0805)


def test_analyze_mc_results_tail_mask_is_not_fooled_by_an_all_negative_sample():
    # The classic bug is comparing returns against +VaR instead of -VaR, which
    # on an all-loss sample selects nearly every path and understates the tail.
    returns = np.linspace(-0.50, -0.01, 100)
    summary = analyze_mc_results(_paths_with_terminal_returns(returns), confidence=0.95)
    assert summary["prob_loss"] == pytest.approx(1.0)
    assert summary["cvar"] >= summary["var"] > 0
    # Tail of 5 worst of 100: index floor(0.05 * 100) = 5 -> 6 observations.
    assert summary["cvar"] == pytest.approx(-np.sort(returns)[:6].mean())


def test_analyze_mc_results_on_a_simulated_run():
    paths = monte_carlo_gbm(100.0, 0.10, 0.20, n_steps=252, n_paths=20_000, seed=11)
    summary = analyze_mc_results(paths, confidence=0.95)
    assert summary["mean_return"] == pytest.approx(np.exp(0.10) - 1, rel=0.05)
    assert summary["cvar"] >= summary["var"] > 0
    assert 0.0 < summary["prob_loss"] < 1.0
    assert summary["worst_5pct_return"] < summary["median_return"] < summary["best_5pct_return"]


def test_analyze_mc_results_rejects_a_one_column_matrix():
    with pytest.raises(ValueError, match=">= 2 columns"):
        analyze_mc_results(np.ones((5, 1)))


# --------------------------------------------------------------------------
# fit_gpd_tail -- recover a generated shape parameter
# --------------------------------------------------------------------------


def _series_with_gpd_left_tail(shape, scale, n_tail, seed):
    """Return a series whose worst 5% are exactly GPD(shape, scale) losses.

    The body sits just above zero and the tail just below it, so the 5th
    percentile lands at the boundary and the exceedances recovered by
    fit_gpd_tail are the generated GPD draws.
    """
    rng = np.random.default_rng(seed)
    losses = genpareto.rvs(shape, loc=0.0, scale=scale, size=n_tail, random_state=rng)
    body = rng.uniform(1e-9, 0.05, size=n_tail * 19)  # tail is 5% of the total
    return np.concatenate([-losses, body])


@pytest.mark.parametrize("true_shape", [0.30, 0.10, -0.20])
def test_fit_gpd_tail_recovers_the_generated_shape(true_shape):
    returns = _series_with_gpd_left_tail(true_shape, scale=0.02, n_tail=4000, seed=5)
    fit = fit_gpd_tail(returns, threshold_pct=5.0)
    assert fit["shape_xi"] == pytest.approx(true_shape, abs=0.06)
    assert fit["scale_sigma"] == pytest.approx(0.02, rel=0.15)
    assert fit["n_exceedances"] == 4000
    assert fit["exceedance_rate"] == pytest.approx(0.05, abs=0.001)


def test_fit_gpd_tail_labels_a_fat_tail():
    returns = _series_with_gpd_left_tail(0.40, scale=0.02, n_tail=3000, seed=9)
    assert fit_gpd_tail(returns)["tail_type"] == "fat"


def test_fit_gpd_tail_labels_a_bounded_tail():
    returns = _series_with_gpd_left_tail(-0.35, scale=0.02, n_tail=3000, seed=9)
    assert fit_gpd_tail(returns)["tail_type"] == "bounded"


def test_fit_gpd_tail_labels_a_true_exponential_tail_exponential():
    # Regression: classifying on `shape > 0.0` made "exponential" unreachable,
    # because a float MLE is never exactly zero. A true exponential tail was
    # then labelled "fat" (i.e. dangerous) on the sign of estimation noise.
    labels = []
    for seed in range(12):
        rng = np.random.default_rng(100 + seed)
        losses = rng.exponential(0.02, size=2000)  # GPD with shape exactly 0
        body = rng.uniform(1e-9, 0.05, size=2000 * 19)
        labels.append(fit_gpd_tail(np.concatenate([-losses, body]))["tail_type"])
    # Measured coverage of the 2-sigma band on this generator is 96.5% over 200
    # refits; 11 of 12 is the conservative assertion for a 12-refit sample.
    assert labels.count("exponential") >= 11, labels


def test_fit_gpd_tail_reports_a_shape_stderr_matching_the_refit_spread():
    # The classification band must be a real standard error, not a magic
    # constant: refit the same shape 12 times and compare the spread.
    shapes, reported = [], []
    for seed in range(12):
        rng = np.random.default_rng(200 + seed)
        losses = genpareto.rvs(0.20, loc=0.0, scale=0.02, size=2000, random_state=rng)
        body = rng.uniform(1e-9, 0.05, size=2000 * 19)
        fit = fit_gpd_tail(np.concatenate([-losses, body]))
        shapes.append(fit["shape_xi"])
        reported.append(fit["shape_stderr"])
    assert float(np.std(shapes)) == pytest.approx(float(np.mean(reported)), rel=0.35)
    # And the closed form it claims to be.
    assert reported[0] == pytest.approx(abs(1.0 + shapes[0]) / np.sqrt(2000), rel=1e-12)


def test_fit_gpd_tail_still_calls_an_unambiguous_shape_by_its_name():
    # The band must not swallow shapes that are many standard errors from zero.
    fat = fit_gpd_tail(_series_with_gpd_left_tail(0.40, scale=0.02, n_tail=3000, seed=9))
    bounded = fit_gpd_tail(_series_with_gpd_left_tail(-0.35, scale=0.02, n_tail=3000, seed=9))
    assert fat["tail_type"] == "fat"
    assert bounded["tail_type"] == "bounded"
    assert fat["shape_xi"] > 5 * fat["shape_stderr"]
    assert bounded["shape_xi"] < -5 * bounded["shape_stderr"]


def test_fit_gpd_tail_threshold_is_the_requested_percentile():
    returns = np.linspace(-0.10, 0.10, 1001)
    fit = fit_gpd_tail(returns, threshold_pct=10.0)
    assert fit["threshold"] == pytest.approx(np.percentile(returns, 10.0))
    assert fit["n_exceedances"] == 100


def test_fit_gpd_tail_rejects_a_threshold_with_too_few_exceedances():
    with pytest.raises(ValueError, match="at least 2 exceedances"):
        fit_gpd_tail(np.linspace(-0.1, 0.1, 20), threshold_pct=1.0)


@pytest.mark.parametrize("threshold_pct", [0.0, 100.0, -5.0, 120.0])
def test_fit_gpd_tail_rejects_an_out_of_range_threshold(threshold_pct):
    with pytest.raises(ValueError, match="threshold_pct"):
        fit_gpd_tail(FIXED_RETURNS, threshold_pct=threshold_pct)
