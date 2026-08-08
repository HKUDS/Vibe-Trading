"""Tests for src.quantlib.timeseries.

Every test builds its data from a seeded generator with a known ground truth, so
an assertion failure means the estimator moved, not that the market did. The
null-hypothesis cases are parametrised across eight seeds rather than run on one
hand-picked seed, so a lucky draw cannot make them pass.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from src.quantlib.timeseries import (
    adf_test,
    autocorrelation_test,
    bootstrap_sharpe,
    bootstrap_statistic,
    cointegration_test,
    compute_half_life,
    find_hedge_ratio,
    fit_garch,
    fit_markov_regime,
    granger_test,
    heteroscedasticity_test,
    vif_test,
)

pytestmark = pytest.mark.unit

# The functions under test lazy-import statsmodels and raise an actionable
# ImportError on a base install (that path has its own test below), so every
# test that calls one must skip -- not fail -- when the 'stats' extra is
# absent. CI installs the extra, so there these tests actually run.
requires_statsmodels = pytest.mark.skipif(
    importlib.util.find_spec("statsmodels") is None,
    reason="the optional 'statsmodels' package is not installed",
)

NULL_CASE_SEEDS = [0, 1, 2, 3, 4, 5, 6, 7]


def ar1(phi: float, n: int, seed: int, sigma: float = 1.0) -> np.ndarray:
    """Generate a mean-zero AR(1) series, the discrete analogue of an OU process.

    Args:
        phi: Persistence coefficient; |phi| < 1 gives a stationary series.
        n: Number of observations.
        seed: Seed for the random generator.
        sigma: Standard deviation of the innovations.

    Returns:
        The generated series as a 1-D numpy array.
    """
    rng = np.random.default_rng(seed)
    shocks = rng.standard_normal(n) * sigma
    out = np.empty(n)
    out[0] = shocks[0]
    for i in range(1, n):
        out[i] = phi * out[i - 1] + shocks[i]
    return out


def random_walk(n: int, seed: int) -> np.ndarray:
    """Generate a driftless random walk (a unit-root, non-stationary series).

    Args:
        n: Number of observations.
        seed: Seed for the random generator.

    Returns:
        The cumulative-sum series as a 1-D numpy array.
    """
    return np.cumsum(np.random.default_rng(seed).standard_normal(n))


# ─── ADF ───


@requires_statsmodels
def test_adf_rejects_unit_root_on_stationary_series():
    result = adf_test(pd.Series(ar1(phi=0.5, n=1500, seed=0)))

    assert result["is_stationary"] is True
    assert result["p_value"] < 0.01
    assert result["adf_statistic"] < result["critical_values"]["1%"]


@requires_statsmodels
@pytest.mark.parametrize("seed", NULL_CASE_SEEDS)
def test_adf_fails_to_reject_on_random_walk(seed):
    result = adf_test(pd.Series(random_walk(1500, seed)))

    assert result["is_stationary"] is False
    assert result["p_value"] > 0.05


@requires_statsmodels
def test_adf_significance_level_is_configurable():
    walk = pd.Series(random_walk(1500, seed=7))  # p ≈ 0.0625, straddles the two levels

    assert adf_test(walk, significance=0.05)["is_stationary"] is False
    assert adf_test(walk, significance=0.10)["is_stationary"] is True


@requires_statsmodels
def test_adf_return_shape():
    result = adf_test(pd.Series(ar1(0.5, 500, seed=1)))

    assert set(result) == {"adf_statistic", "p_value", "lags_used", "is_stationary", "critical_values"}
    assert set(result["critical_values"]) == {"1%", "5%", "10%"}
    assert isinstance(result["lags_used"], int)


@requires_statsmodels
def test_adf_rejects_too_short_a_series():
    with pytest.raises(ValueError, match="at least 2"):
        adf_test(pd.Series([1.0]))


# ─── Cointegration ───


@requires_statsmodels
def test_cointegration_found_on_constructed_pair():
    # y and x are both I(1) random walks, but y - 2.5x is a stationary AR(1),
    # so the pair is cointegrated by construction.
    x = random_walk(1500, seed=10)
    y = 2.5 * x + 1.0 + ar1(phi=0.9, n=1500, seed=11)

    result = cointegration_test(pd.Series(y), pd.Series(x))

    assert result["is_cointegrated"] is True
    assert result["p_value"] < 0.01


@requires_statsmodels
@pytest.mark.parametrize("seed", NULL_CASE_SEEDS)
def test_cointegration_not_found_on_independent_walks(seed):
    rng = np.random.default_rng(seed)
    a = np.cumsum(rng.standard_normal(1500))
    b = np.cumsum(rng.standard_normal(1500))

    result = cointegration_test(pd.Series(a), pd.Series(b))

    assert result["is_cointegrated"] is False
    assert result["p_value"] > 0.05


@requires_statsmodels
def test_cointegration_return_shape():
    x = random_walk(400, seed=12)
    result = cointegration_test(pd.Series(2.0 * x + ar1(0.5, 400, 13)), pd.Series(x))

    assert set(result) == {"test_statistic", "p_value", "is_cointegrated", "critical_values"}
    assert set(result["critical_values"]) == {"1%", "5%", "10%"}


@requires_statsmodels
def test_cointegration_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="equal-length"):
        cointegration_test(pd.Series(np.arange(10.0)), pd.Series(np.arange(11.0)))


@requires_statsmodels
def test_cointegration_refuses_to_join_two_different_indices_positionally():
    # Two same-length legs on disjoint indices used to be zipped positionally,
    # which reports a spurious cointegration on data that never overlapped. The
    # pair workflow runs this and find_hedge_ratio on the same two legs, so both
    # must enforce the same contract.
    a = pd.Series(random_walk(200, seed=14), index=pd.RangeIndex(0, 200))
    b = pd.Series(random_walk(200, seed=15), index=pd.RangeIndex(500, 700))

    with pytest.raises(ValueError, match="sharing one index"):
        cointegration_test(a, b)
    with pytest.raises(ValueError, match="sharing one index"):
        find_hedge_ratio(a, b)


@requires_statsmodels
def test_cointegration_still_accepts_a_shared_non_default_index():
    dates = pd.date_range("2020-01-01", periods=400, freq="D")
    x = random_walk(400, seed=16)
    y = 2.0 * x + ar1(0.5, 400, 17)

    result = cointegration_test(pd.Series(y, index=dates), pd.Series(x, index=dates))

    assert result["is_cointegrated"] is True
    # And matches the plain positional call on the same numbers.
    assert result["test_statistic"] == pytest.approx(
        cointegration_test(pd.Series(y), pd.Series(x))["test_statistic"]
    )


# ─── Hedge ratio and half-life ───


@requires_statsmodels
def test_find_hedge_ratio_recovers_known_beta():
    true_beta, true_alpha = 2.5, 1.0
    x = random_walk(3000, seed=20)
    y = true_alpha + true_beta * x + ar1(phi=0.9, n=3000, seed=21)

    result = find_hedge_ratio(pd.Series(y), pd.Series(x))

    assert result["hedge_ratio"] == pytest.approx(true_beta, abs=0.05)
    assert result["intercept"] == pytest.approx(true_alpha, abs=0.5)
    # spread = y - beta*x is the OLS residual plus the intercept, so its mean
    # sits at alpha and its dispersion is the AR(1) noise, not the walk's.
    assert result["spread_std"] < 10.0
    assert result["half_life"] > 0


@requires_statsmodels
def test_find_hedge_ratio_matches_the_closed_form_ols():
    # Independent reference, not a statsmodels round-trip: the simple-regression
    # slope is cov(x, y) / var(x) and the intercept is ybar - beta * xbar.
    x = random_walk(600, seed=24)
    y = 1.7 + 3.1 * x + ar1(0.4, 600, 25)

    result = find_hedge_ratio(pd.Series(y), pd.Series(x))

    beta = np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1)
    assert result["hedge_ratio"] == pytest.approx(beta, rel=1e-12)
    assert result["intercept"] == pytest.approx(y.mean() - beta * x.mean(), rel=1e-10)
    assert result["spread_std"] == pytest.approx((y - beta * x).std(ddof=1), rel=1e-12)


@requires_statsmodels
def test_find_hedge_ratio_return_shape():
    x = random_walk(500, seed=22)
    result = find_hedge_ratio(pd.Series(1.5 * x + ar1(0.5, 500, 23)), pd.Series(x))

    assert set(result) == {"hedge_ratio", "intercept", "spread_mean", "spread_std", "half_life"}
    assert all(isinstance(v, float) for v in result.values())


@requires_statsmodels
def test_compute_half_life_recovers_ou_process():
    # For an AR(1) with coefficient phi the continuous-time half-life is
    # -ln(2)/ln(phi); the delta-regression estimator targets -ln(2)/(phi-1),
    # which differs by ~5% at phi=0.9. Tolerance spans both conventions.
    phi = 0.9
    expected = -np.log(2) / np.log(phi)

    estimated = compute_half_life(pd.Series(ar1(phi=phi, n=20000, seed=30)))

    assert estimated == pytest.approx(expected, rel=0.15)


@requires_statsmodels
def test_compute_half_life_is_infinite_for_a_random_walk():
    # A random walk never reverts; the estimated reversion coefficient hovers
    # around zero, and a non-negative one means "no reversion", not "instant".
    values = [compute_half_life(pd.Series(random_walk(2000, seed))) for seed in NULL_CASE_SEEDS]

    assert all(v > 100 for v in values), values


@requires_statsmodels
def test_compute_half_life_aligns_around_interior_nans():
    # Dropping levels and deltas independently would mis-pair rows after a gap.
    series = pd.Series(ar1(phi=0.9, n=800, seed=31))
    series.iloc[400] = np.nan

    assert compute_half_life(series) == pytest.approx(-np.log(2) / np.log(0.9), rel=0.35)


@requires_statsmodels
def test_compute_half_life_rejects_too_short_a_series():
    with pytest.raises(ValueError, match="at least 3"):
        compute_half_life(pd.Series([1.0, 2.0]))


@requires_statsmodels
def test_degenerate_flat_regressors_raise_instead_of_leaking_an_index_error():
    # `sm.add_constant` defaults to has_constant='skip', so a already-constant
    # column leaves the design one column wide and the slope lookup used to blow
    # up with a bare `IndexError: index 1 is out of bounds`. Both entry points
    # must refuse the input by contract instead.
    with pytest.raises(ValueError, match="constant"):
        compute_half_life(pd.Series(np.full(50, 2.0)))
    with pytest.raises(ValueError, match="constant"):
        find_hedge_ratio(pd.Series(ar1(0.5, 50, seed=32)), pd.Series(np.full(50, 3.0)))


# ─── Granger ───


@requires_statsmodels
def test_granger_detects_a_lagged_driver():
    rng = np.random.default_rng(40)
    n = 600
    x = rng.standard_normal(n)
    y = np.roll(x, 1) * 0.8 + rng.standard_normal(n) * 0.3
    frame = pd.DataFrame({"y": y[1:], "x": x[1:]})

    result = granger_test(frame, x_col="x", y_col="y", max_lag=3)

    assert set(result) == {1, 2, 3}
    assert result[1] < 0.01


@requires_statsmodels
def test_granger_finds_nothing_between_independent_noise():
    rng = np.random.default_rng(41)
    frame = pd.DataFrame({"y": rng.standard_normal(600), "x": rng.standard_normal(600)})

    result = granger_test(frame, x_col="x", y_col="y", max_lag=3)

    assert all(p > 0.05 for p in result.values()), result


@requires_statsmodels
def test_granger_stays_silent_on_stdout(capsys):
    # statsmodels >= 0.14 prints its whole test table unconditionally.
    rng = np.random.default_rng(42)
    frame = pd.DataFrame({"y": rng.standard_normal(200), "x": rng.standard_normal(200)})

    granger_test(frame, x_col="x", y_col="y", max_lag=2)

    assert capsys.readouterr().out == ""


@requires_statsmodels
def test_granger_rejects_a_missing_column():
    frame = pd.DataFrame({"y": [1.0, 2.0, 3.0]})
    with pytest.raises(KeyError, match="not in data"):
        granger_test(frame, x_col="absent", y_col="y")


# ─── Regression diagnostics ───


def test_heteroscedasticity_detected_when_variance_scales_with_x():
    sm = pytest.importorskip("statsmodels.api")
    rng = np.random.default_rng(50)
    x = np.linspace(1, 10, 500)
    y = 2 * x + rng.standard_normal(500) * x  # noise grows with x
    fitted = sm.OLS(y, sm.add_constant(x)).fit()

    result = heteroscedasticity_test(fitted)

    assert result["has_heteroscedasticity"] is True
    assert result["white_p"] < 0.05
    assert "HAC" in result["fix"]


def test_heteroscedasticity_absent_under_constant_variance():
    sm = pytest.importorskip("statsmodels.api")
    rng = np.random.default_rng(51)
    x = np.linspace(1, 10, 500)
    fitted = sm.OLS(2 * x + rng.standard_normal(500), sm.add_constant(x)).fit()

    result = heteroscedasticity_test(fitted)

    assert result["has_heteroscedasticity"] is False
    assert result["fix"] == "No adjustment needed"


def test_heteroscedasticity_advice_never_contradicts_the_verdict():
    # Keying `fix` off white_p alone -- as the skill's markdown did -- returns
    # "No adjustment needed" next to has_heteroscedasticity=True whenever only
    # the BP test rejects. Seed 157 below is exactly that case: white_p 0.0572,
    # bp_p 0.0196. Scan a band of seeds so the pairing is asserted, not the seed.
    sm = pytest.importorskip("statsmodels.api")
    saw_bp_only = False
    for seed in range(200):
        rng = np.random.default_rng(seed)
        x = np.linspace(1, 10, 120)
        y = 2 * x + rng.standard_normal(120) * (1 + 0.35 * x)
        result = heteroscedasticity_test(sm.OLS(y, sm.add_constant(x)).fit())

        expected = "Use HAC" if result["has_heteroscedasticity"] else "No adjustment needed"
        assert result["fix"].startswith(expected), (seed, result)
        saw_bp_only |= result["bp_p"] < 0.05 <= result["white_p"]

    assert saw_bp_only, "no BP-only rejection in 200 seeds; the regression is not being exercised"


@requires_statsmodels
def test_autocorrelation_detected_in_ar1_residuals():
    result = autocorrelation_test(pd.Series(ar1(phi=0.8, n=1000, seed=60)), lags=10)

    assert result["has_autocorrelation"] is True
    assert result["durbin_watson"] < 1.5
    assert result["dw_interpretation"] == "positive autocorrelation"
    assert len(result["ljung_box_p"]) == 10


@requires_statsmodels
def test_autocorrelation_absent_in_white_noise():
    # `has_autocorrelation` is any-of-`lags`, so on white noise it fires on a
    # minority of seeds by construction (see the calibration test below).
    # Assert the rate across seeds instead of picking one lucky path.
    flagged = 0
    for seed in range(40):
        noise = pd.Series(np.random.default_rng(3000 + seed).standard_normal(2000))
        result = autocorrelation_test(noise, lags=10)
        flagged += result["has_autocorrelation"]
        assert 1.5 <= result["durbin_watson"] < 2.5
        assert result["dw_interpretation"] == "no autocorrelation"

    assert flagged <= 12, f"{flagged}/40 white-noise paths flagged; expected roughly 5"


@requires_statsmodels
def test_ljung_box_any_lag_rule_inflates_the_false_positive_rate():
    # Characterisation, not aspiration: the promoted `any(p < significance)`
    # rule runs `lags` hypothesis tests at once, so its family-wise error rate
    # sits well above the nominal level. Callers must know this before reading
    # a single flag as a 5%-level rejection.
    lag1_flags = lag10_flags = 0
    for seed in range(120):
        noise = pd.Series(np.random.default_rng(5000 + seed).standard_normal(1500))
        lag1_flags += autocorrelation_test(noise, lags=1)["has_autocorrelation"]
        lag10_flags += autocorrelation_test(noise, lags=10)["has_autocorrelation"]

    assert lag1_flags <= 15, f"lag-1 false positives {lag1_flags}/120 should sit near the nominal 5%"
    assert lag10_flags > lag1_flags, (lag1_flags, lag10_flags)


@requires_statsmodels
def test_autocorrelation_flags_alternating_series_as_negative():
    alternating = pd.Series(np.tile([1.0, -1.0], 200) + np.random.default_rng(62).standard_normal(400) * 0.1)

    assert autocorrelation_test(alternating, lags=5)["dw_interpretation"] == "negative autocorrelation"


@requires_statsmodels
def test_vif_flags_a_collinear_column():
    rng = np.random.default_rng(70)
    a = rng.standard_normal(500)
    frame = pd.DataFrame({"a": a, "b": a + rng.standard_normal(500) * 0.01, "c": rng.standard_normal(500)})

    result = vif_test(frame)

    assert list(result.columns) == ["feature", "VIF", "concern"]
    assert list(result["feature"]) == ["a", "b", "c"]
    by_feature = dict(zip(result["feature"], result["concern"]))
    assert by_feature["a"] == "severe"
    assert by_feature["b"] == "severe"
    assert by_feature["c"] == "normal"


@requires_statsmodels
def test_vif_thresholds_are_configurable():
    rng = np.random.default_rng(71)
    frame = pd.DataFrame({"a": rng.standard_normal(300), "b": rng.standard_normal(300)})

    # Independent columns have VIF ≈ 1; a threshold below 1 must flag them.
    relaxed = vif_test(frame, severe_threshold=0.5, watch_threshold=0.1)

    assert set(relaxed["concern"]) == {"severe"}
    assert set(vif_test(frame)["concern"]) == {"normal"}


@requires_statsmodels
def test_vif_thresholds_are_strict_inequalities():
    # A VIF landing exactly on the threshold is NOT flagged. Pinned because the
    # docstring previously said "at or above", which is the opposite rule.
    rng = np.random.default_rng(72)
    frame = pd.DataFrame({"a": rng.standard_normal(300), "b": rng.standard_normal(300)})
    exact = float(vif_test(frame)["VIF"].iloc[0])

    on_threshold = vif_test(frame, severe_threshold=exact, watch_threshold=exact)
    assert on_threshold["concern"].iloc[0] == "normal"
    assert vif_test(frame, severe_threshold=exact / 2, watch_threshold=exact / 4)["concern"].iloc[0] == "severe"


@requires_statsmodels
def test_vif_rejects_an_empty_frame():
    with pytest.raises(ValueError, match="at least one column"):
        vif_test(pd.DataFrame())


# ─── Bootstrap ───


def test_bootstrap_ci_covers_the_true_mean():
    true_mean = 0.5
    data = np.random.default_rng(80).standard_normal(500) + true_mean

    result = bootstrap_statistic(data, np.mean, n_bootstrap=2000, confidence=0.95, seed=1)

    assert result["ci_lower"] < true_mean < result["ci_upper"]
    assert result["point_estimate"] == pytest.approx(float(np.mean(data)))
    assert result["bootstrap_mean"] == pytest.approx(result["point_estimate"], abs=0.02)
    assert result["confidence"] == 0.95


def test_bootstrap_ci_coverage_is_near_nominal():
    # A 95% interval should cover the truth on the large majority of draws. The
    # floor is loose enough not to be flaky, tight enough to catch a broken CI.
    true_mean = 0.5
    covered = 0
    for seed in range(40):
        data = np.random.default_rng(100 + seed).standard_normal(200) + true_mean
        result = bootstrap_statistic(data, np.mean, n_bootstrap=300, seed=seed)
        covered += result["ci_lower"] < true_mean < result["ci_upper"]

    assert covered >= 34, f"only {covered}/40 intervals covered the true mean"


def test_bootstrap_interval_widens_with_confidence():
    data = np.random.default_rng(81).standard_normal(300)

    narrow = bootstrap_statistic(data, np.mean, n_bootstrap=500, confidence=0.80, seed=2)
    wide = bootstrap_statistic(data, np.mean, n_bootstrap=500, confidence=0.99, seed=2)

    assert (wide["ci_upper"] - wide["ci_lower"]) > (narrow["ci_upper"] - narrow["ci_lower"])


def test_bootstrap_is_reproducible_with_a_seed():
    data = np.random.default_rng(82).standard_normal(200)

    first = bootstrap_statistic(data, np.mean, n_bootstrap=200, seed=7)
    second = bootstrap_statistic(data, np.mean, n_bootstrap=200, seed=7)

    assert first == second


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"n_bootstrap": 0}, "n_bootstrap >= 1"),
        ({"confidence": 1.0}, "confidence in"),
        ({"confidence": 0.0}, "confidence in"),
    ],
)
def test_bootstrap_rejects_bad_arguments(kwargs, message):
    with pytest.raises(ValueError, match=message):
        bootstrap_statistic(np.arange(10.0), np.mean, **kwargs)


def test_bootstrap_rejects_an_empty_sample():
    with pytest.raises(ValueError, match="non-empty"):
        bootstrap_statistic(np.array([]), np.mean)


def test_bootstrap_sharpe_flags_a_real_edge_as_significant():
    # Daily mean 0.001 with sd 0.01 is an annualised Sharpe of ~1.6 over 4
    # years of bars -- comfortably distinguishable from zero.
    returns = pd.Series(np.random.default_rng(90).standard_normal(1000) * 0.01 + 0.001)

    result = bootstrap_sharpe(returns, n_bootstrap=1000, seed=3)

    assert result["is_significant"] is True
    assert result["ci_lower"] > 0
    assert result["point_estimate"] == pytest.approx(1.6, abs=0.6)


def test_bootstrap_sharpe_calls_pure_noise_insignificant():
    # The realised Sharpe of 1000 zero-mean draws has sd sqrt(252/1000) ≈ 0.50,
    # so a single noise path can genuinely show Sharpe ≈ 1.0 (seed 91 does).
    # Seed 3021 draws a realised Sharpe of ~0.008, which must straddle zero.
    returns = pd.Series(np.random.default_rng(3021).standard_normal(1000) * 0.01)

    result = bootstrap_sharpe(returns, n_bootstrap=1000, seed=4)

    assert result["is_significant"] is False
    assert result["ci_lower"] < 0 < result["ci_upper"]


def test_bootstrap_sharpe_false_positive_rate_stays_near_nominal():
    flagged = 0
    for seed in range(40):
        returns = pd.Series(np.random.default_rng(3000 + seed).standard_normal(1000) * 0.01)
        flagged += bootstrap_sharpe(returns, n_bootstrap=300, seed=seed)["is_significant"]

    assert flagged <= 5, f"{flagged}/40 pure-noise paths called significant at 95%"


def test_bootstrap_sharpe_annualisation_is_configurable():
    returns = pd.Series(np.random.default_rng(92).standard_normal(600) * 0.01 + 0.001)

    daily = bootstrap_sharpe(returns, n_bootstrap=200, periods_per_year=252, seed=5)
    monthly = bootstrap_sharpe(returns, n_bootstrap=200, periods_per_year=12, seed=5)

    assert daily["point_estimate"] == pytest.approx(monthly["point_estimate"] * np.sqrt(252 / 12))


def test_bootstrap_sharpe_uses_the_sample_standard_deviation():
    # The skill's markdown fed `returns.values` to a numpy `.std()`, i.e. ddof=0,
    # and `backtest.validation._sharpe` still does. This function deliberately
    # uses ddof=1. Pin the convention and the size of the resulting divergence so
    # nobody "reconciles" the two by accident.
    returns = pd.Series(np.random.default_rng(94).standard_normal(252) * 0.01 + 0.001)
    values = returns.to_numpy()

    point = bootstrap_sharpe(returns, n_bootstrap=50, seed=8)["point_estimate"]

    ddof1 = values.mean() / values.std(ddof=1) * np.sqrt(252)
    ddof0 = values.mean() / values.std(ddof=0) * np.sqrt(252)
    assert point == pytest.approx(ddof1, rel=1e-12)
    assert point != pytest.approx(ddof0, rel=1e-6)
    assert ddof0 / ddof1 == pytest.approx(np.sqrt(252 / 251), rel=1e-12)


def test_bootstrap_sharpe_return_shape():
    returns = pd.Series(np.random.default_rng(93).standard_normal(200) * 0.01)

    result = bootstrap_sharpe(returns, n_bootstrap=100, seed=6)

    assert set(result) == {
        "point_estimate",
        "bootstrap_mean",
        "bootstrap_std",
        "ci_lower",
        "ci_upper",
        "confidence",
        "is_significant",
    }


# ─── GARCH (optional 'arch' backend) ───


def test_fit_garch_recovers_volatility_clustering():
    pytest.importorskip("arch", reason="the optional 'arch' package is not installed")

    # Simulate GARCH(1,1) with known parameters, in percent units.
    omega, alpha, beta = 0.05, 0.10, 0.85
    rng = np.random.default_rng(200)
    n = 4000
    var = np.empty(n)
    eps = np.empty(n)
    var[0] = omega / (1 - alpha - beta)
    for i in range(n):
        if i > 0:
            var[i] = omega + alpha * eps[i - 1] ** 2 + beta * var[i - 1]
        eps[i] = np.sqrt(var[i]) * rng.standard_normal()
    returns = pd.Series(eps / 100)  # fit_garch rescales by 100 internally

    result = fit_garch(returns, horizon=5)

    assert result["alpha"] == pytest.approx(alpha, abs=0.05)
    assert result["beta"] == pytest.approx(beta, abs=0.08)
    assert result["persistence"] == pytest.approx(alpha + beta, abs=0.05)
    assert len(result["forecast_vol"]) == 5
    assert result["horizon"] == 5
    # conditional_volatility is already a std dev; a stray sqrt would land this
    # near 0.02 (sqrt of ~0.006) instead of in the plausible daily-vol range.
    assert 0.001 < result["current_vol"] < 0.20


def test_fit_garch_return_shape():
    pytest.importorskip("arch", reason="the optional 'arch' package is not installed")

    returns = pd.Series(np.random.default_rng(201).standard_normal(600) * 0.01)
    result = fit_garch(returns, horizon=3)

    assert set(result) == {
        "omega", "alpha", "beta", "persistence", "long_run_vol",
        "current_vol", "forecast_vol", "horizon", "aic", "bic",
    }
    assert len(result["forecast_vol"]) == 3


def test_fit_garch_rejects_a_non_positive_horizon():
    pytest.importorskip("arch", reason="the optional 'arch' package is not installed")

    with pytest.raises(ValueError, match="horizon >= 1"):
        fit_garch(pd.Series(np.random.default_rng(202).standard_normal(200) * 0.01), horizon=0)


# ─── Optional-dependency degradation ───


def test_missing_optional_backend_names_the_package_and_the_install_command():
    from src.quantlib import timeseries

    with pytest.raises(ImportError) as excinfo:
        timeseries._require("definitely_not_a_real_module", "arch", "fit_garch")

    message = str(excinfo.value)
    assert "fit_garch" in message
    assert "'arch'" in message
    assert "pip install" in message


def test_fit_garch_raises_an_actionable_error_when_arch_is_absent():
    pytest.importorskip("pandas")
    try:
        import arch  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("'arch' is installed, so the missing-dependency path cannot be exercised")

    with pytest.raises(ImportError, match="pip install"):
        fit_garch(pd.Series(np.random.default_rng(203).standard_normal(100) * 0.01))


def test_importing_the_module_does_not_require_the_optional_backends():
    # The module must import cleanly even with no statsmodels and no arch, so
    # the pure-numpy bootstrap helpers stay usable on a bare install.
    import importlib

    module = importlib.import_module("src.quantlib.timeseries")

    assert len(module.__all__) == 12
    assert "statsmodels" not in module.__dict__
    assert "arch" not in module.__dict__


# --- Markov regime switching ---


def _two_regime_series(seed=3, calm_len=200, turbulent_len=50, cycles=3,
                       calm_vol=0.005, turbulent_vol=0.03, start_calm=True):
    """Build a series alternating between a calm and a turbulent regime."""
    rng = np.random.default_rng(seed)
    segments = []
    truth = []
    for cycle in range(cycles * 2):
        calm = (cycle % 2 == 0) == start_calm
        length = calm_len if calm else turbulent_len
        vol = calm_vol if calm else turbulent_vol
        segments.append(rng.normal(0.0, vol, length))
        truth += [0 if calm else 1] * length
    return pd.Series(np.concatenate(segments)), np.array(truth)


@requires_statsmodels
def test_markov_regime_recovers_known_volatilities():
    series, _ = _two_regime_series(seed=3)
    result = fit_markov_regime(series)

    assert result["converged"]
    assert result["regime_vols"][0] == pytest.approx(0.005, rel=0.15)
    assert result["regime_vols"][1] == pytest.approx(0.030, rel=0.15)


@requires_statsmodels
def test_markov_regimes_are_ordered_calmest_first_regardless_of_fit_order():
    # Label switching is the classic reproducibility trap: the EM fit returns
    # states in an arbitrary order. Starting the series in the turbulent regime
    # instead of the calm one must not change which index means "calm".
    calm_first, _ = _two_regime_series(seed=11, start_calm=True)
    turbulent_first, _ = _two_regime_series(seed=11, start_calm=False)

    a = fit_markov_regime(calm_first)
    b = fit_markov_regime(turbulent_first)

    for result in (a, b):
        vols = result["regime_vols"]
        assert np.all(np.diff(vols) >= 0), f"regimes not ascending in vol: {vols}"
        assert vols[0] < vols[1]


@requires_statsmodels
def test_markov_transition_matrix_is_row_stochastic():
    series, _ = _two_regime_series(seed=5)
    transition = fit_markov_regime(series)["transition_matrix"]

    assert transition.shape == (2, 2)
    assert transition.sum(axis=1) == pytest.approx(np.ones(2))
    assert np.all(transition >= 0.0)


@requires_statsmodels
def test_markov_transition_rows_read_from_today_to_tomorrow():
    # The calm regime here lasts 200 periods and the turbulent one 50, so the
    # calm row's diagonal must be the larger of the two. Reading the matrix
    # transposed would swap these and silently mislabel which state is sticky.
    series, _ = _two_regime_series(seed=7, calm_len=200, turbulent_len=50)
    result = fit_markov_regime(series)
    transition = result["transition_matrix"]

    assert transition[0][0] > transition[1][1]
    assert result["expected_durations"][0] > result["expected_durations"][1]


@requires_statsmodels
def test_markov_expected_durations_track_the_true_segment_lengths():
    series, _ = _two_regime_series(seed=13, calm_len=180, turbulent_len=60)
    durations = fit_markov_regime(series)["expected_durations"]

    assert durations[0] == pytest.approx(180, rel=0.5)
    assert durations[1] == pytest.approx(60, rel=0.5)


@requires_statsmodels
def test_markov_identifies_the_regime_the_series_ends_in():
    # Ends in a turbulent segment.
    series, truth = _two_regime_series(seed=17, start_calm=True)
    result = fit_markov_regime(series)

    assert result["current_regime"] == int(truth[-1])
    assert result["current_regime_probability"] > 0.8


@requires_statsmodels
def test_markov_smoothed_probabilities_are_a_distribution_on_the_input_index():
    series, _ = _two_regime_series(seed=19)
    result = fit_markov_regime(series)
    smoothed = result["smoothed_probabilities"]

    assert list(smoothed.index) == list(series.index)
    assert list(smoothed.columns) == ["regime_0", "regime_1"]
    assert smoothed.sum(axis=1).to_numpy() == pytest.approx(np.ones(len(series)), abs=1e-8)


@requires_statsmodels
def test_markov_smoothed_probabilities_track_the_true_state():
    series, truth = _two_regime_series(seed=23)
    smoothed = fit_markov_regime(series)["smoothed_probabilities"]
    inferred = smoothed.to_numpy().argmax(axis=1)

    # Not every boundary period is classifiable, but the bulk must be.
    assert (inferred == truth).mean() > 0.9


@requires_statsmodels
def test_markov_rejects_a_single_regime():
    series, _ = _two_regime_series(seed=29)
    with pytest.raises(ValueError, match="at least 2"):
        fit_markov_regime(series, n_regimes=1)


@requires_statsmodels
def test_markov_rejects_a_series_too_short_to_mean_anything():
    with pytest.raises(ValueError, match="at least 50"):
        fit_markov_regime(pd.Series(np.random.default_rng(31).normal(0, 0.01, 40)))


def test_markov_raises_an_actionable_error_when_statsmodels_is_absent():
    try:
        import statsmodels  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("'statsmodels' is installed, so the missing-dependency path cannot be exercised")

    with pytest.raises(ImportError, match="pip install"):
        fit_markov_regime(pd.Series(np.random.default_rng(37).normal(0, 0.01, 100)))
