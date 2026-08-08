"""Tests for src.quantlib.var_backtest.

Every guard here is two-sided: a well-calibrated model must NOT be rejected and
a miscalibrated one MUST be. A one-sided guard can always be satisfied by making
the test weaker, which is exactly the failure mode these tests exist to prevent.
"""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import chi2

from src.quantlib.var_backtest import (
    BASEL_SCALING_FACTORS,
    basel_traffic_light,
    christoffersen_conditional_coverage,
    christoffersen_independence,
    kupiec_pof,
    var_backtest,
    violation_indicator,
)


# --- breach definition and sign convention ---


def test_breach_is_loss_strictly_exceeding_var():
    returns = np.array([-0.031, -0.028, -0.019, 0.05])
    breaches = violation_indicator(returns, 0.028)
    # -0.031 breaches; -0.028 exactly equals the promised level and does not.
    assert breaches.tolist() == [True, False, False, False]


def test_var_is_a_positive_loss_magnitude_not_a_signed_return():
    # A caller who passes a negative VaR gets an implausible breach count, not a
    # silently corrected input.
    returns = np.array([-0.01, -0.02, -0.03])
    assert violation_indicator(returns, 0.05).sum() == 0
    assert violation_indicator(returns, -0.05).sum() == 3


def test_scalar_var_broadcasts_over_returns():
    returns = np.array([-0.05, 0.01, -0.06])
    assert violation_indicator(returns, 0.04).tolist() == [True, False, True]


# --- alignment ---


def test_mismatched_series_labels_are_an_error_not_a_partial_join():
    idx_a = pd.date_range("2024-01-01", periods=5, freq="D")
    idx_b = pd.date_range("2024-01-02", periods=5, freq="D")
    returns = pd.Series(np.full(5, -0.01), index=idx_a)
    var = pd.Series(np.full(5, 0.02), index=idx_b)
    with pytest.raises(ValueError, match="exactly the same labels"):
        violation_indicator(returns, var)


def test_length_mismatch_rejected():
    with pytest.raises(ValueError, match="same length"):
        violation_indicator(np.zeros(5), np.zeros(4))


def test_non_finite_pairs_are_dropped_and_counted():
    returns = pd.Series([-0.05, np.nan, -0.06, 0.01])
    var = pd.Series([0.02, 0.02, np.nan, 0.02])
    report = var_backtest(returns, var, confidence=0.95)
    assert report.observations == 2
    assert report.dropped_observations == 2


def test_all_non_finite_is_an_error():
    with pytest.raises(ValueError, match="no observation"):
        violation_indicator([np.nan, np.nan], 0.02)


# --- Kupiec unconditional coverage ---


def test_kupiec_perfect_calibration_gives_zero_statistic():
    result = kupiec_pof(violations=10, observations=1000, confidence=0.99)
    assert result.statistic == pytest.approx(0.0, abs=1e-12)
    assert result.p_value == pytest.approx(1.0)
    assert not result.rejected


def test_kupiec_rejects_a_model_breached_far_too_often():
    # 50 breaches where 10 were promised.
    result = kupiec_pof(violations=50, observations=1000, confidence=0.99)
    assert result.rejected
    assert result.violation_rate == pytest.approx(0.05)
    assert result.expected_violations == pytest.approx(10.0)


def test_kupiec_rejects_a_model_that_never_breaches_when_it_should():
    # Zero breaches over 1000 days at 99% is a far too conservative model, and
    # over-conservatism is a real finding: it means capital is over-held.
    result = kupiec_pof(violations=0, observations=1000, confidence=0.99)
    assert result.rejected
    assert np.isfinite(result.statistic)


def test_kupiec_matches_the_closed_form_likelihood_ratio():
    n, x, p = 250, 7, 0.01
    pi = x / n
    expected = -2.0 * (
        (n - x) * np.log(1 - p)
        + x * np.log(p)
        - (n - x) * np.log(1 - pi)
        - x * np.log(pi)
    )
    result = kupiec_pof(violations=x, observations=n, confidence=1 - p)
    assert result.statistic == pytest.approx(expected, rel=1e-12)
    assert result.p_value == pytest.approx(chi2.sf(expected, df=1), rel=1e-12)


def test_kupiec_zero_and_full_breach_counts_are_finite():
    assert np.isfinite(kupiec_pof(0, 100, 0.99).statistic)
    assert np.isfinite(kupiec_pof(100, 100, 0.99).statistic)


@pytest.mark.parametrize(
    "violations, observations, confidence",
    [(-1, 100, 0.99), (101, 100, 0.99), (5, 0, 0.99), (5, 100, 1.0), (5, 100, 0.0)],
)
def test_kupiec_rejects_impossible_inputs(violations, observations, confidence):
    with pytest.raises(ValueError):
        kupiec_pof(violations, observations, confidence)


# --- Christoffersen independence ---


def test_independence_not_rejected_when_breaches_are_independent():
    # The true null is Bernoulli draws, not a tidy pattern.
    rng = np.random.default_rng(31)
    breaches = rng.random(2000) < 0.05
    result = christoffersen_independence(breaches)
    assert result.identified
    assert not result.rejected


def test_perfect_periodicity_is_dependence_and_is_rejected():
    # Every 10th day, exactly. The breach count is right and nothing clusters,
    # but a breach still predicts tomorrow perfectly: it says "not tomorrow".
    # Anti-clustering is dependence, and the test is supposed to catch it.
    breaches = np.zeros(500, dtype=bool)
    breaches[::10] = True
    result = christoffersen_independence(breaches)
    assert result.identified
    assert result.rejected
    assert result.prob_breach_after_breach == 0.0
    assert result.prob_breach_after_calm > 0.0


def test_independence_rejected_when_breaches_cluster():
    # Same breach count as the scattered case, all consecutive.
    breaches = np.zeros(500, dtype=bool)
    breaches[100:150] = True
    result = christoffersen_independence(breaches)
    assert result.identified
    assert result.rejected
    assert result.prob_breach_after_breach > result.prob_breach_after_calm


def test_clustering_is_invisible_to_kupiec_which_is_why_both_tests_exist():
    rng = np.random.default_rng(41)
    scattered = np.zeros(500, dtype=bool)
    scattered[rng.choice(500, size=50, replace=False)] = True
    clustered = np.zeros(500, dtype=bool)
    clustered[100:150] = True

    # Identical counts, so Kupiec cannot tell them apart at all.
    k_scattered = kupiec_pof(int(scattered.sum()), scattered.size, 0.90)
    k_clustered = kupiec_pof(int(clustered.sum()), clustered.size, 0.90)
    assert k_scattered.statistic == pytest.approx(k_clustered.statistic)

    # Independence separates them.
    assert not christoffersen_independence(scattered).rejected
    assert christoffersen_independence(clustered).rejected


def test_independence_is_unidentified_with_no_breaches():
    result = christoffersen_independence(np.zeros(100, dtype=bool))
    assert not result.identified
    assert result.statistic == 0.0
    assert not result.rejected


def test_independence_is_unidentified_when_the_only_breach_is_last():
    breaches = np.zeros(50, dtype=bool)
    breaches[-1] = True
    result = christoffersen_independence(breaches)
    assert not result.identified
    assert result.statistic == 0.0


def test_independence_transition_counts_are_exact():
    breaches = np.array([False, True, True, False, False], dtype=bool)
    result = christoffersen_independence(breaches)
    # transitions: F->T, T->T, T->F, F->F
    assert result.transitions == (1, 1, 1, 1)


def test_independence_needs_two_observations():
    with pytest.raises(ValueError, match="at least 2"):
        christoffersen_independence(np.array([True]))


# --- conditional coverage ---


def test_conditional_coverage_is_exactly_the_sum_of_its_components():
    rng = np.random.default_rng(20260806)
    breaches = rng.random(600) < 0.03
    result = christoffersen_conditional_coverage(breaches, confidence=0.99)
    assert result.statistic == pytest.approx(
        result.kupiec.statistic + result.independence.statistic, rel=1e-12
    )
    assert result.p_value == pytest.approx(chi2.sf(result.statistic, df=2), rel=1e-12)


def test_conditional_coverage_passes_a_correctly_calibrated_model():
    rng = np.random.default_rng(7)
    breaches = rng.random(5000) < 0.01
    result = christoffersen_conditional_coverage(breaches, confidence=0.99)
    assert not result.rejected


def test_conditional_coverage_catches_a_model_that_only_fails_on_timing():
    # Correct 10% breach rate, but delivered in one block.
    breaches = np.zeros(500, dtype=bool)
    breaches[200:250] = True
    result = christoffersen_conditional_coverage(breaches, confidence=0.90)
    assert not result.kupiec.rejected  # level is right
    assert result.independence.rejected  # timing is not
    assert result.rejected  # joint test catches it


# --- Basel traffic light ---


@pytest.mark.parametrize(
    "violations, zone",
    [(0, "green"), (4, "green"), (5, "yellow"), (9, "yellow"), (10, "red"), (25, "red")],
)
def test_basel_zones_reproduce_the_official_250_day_table(violations, zone):
    result = basel_traffic_light(violations, observations=250, confidence=0.99)
    assert result.zone == zone


@pytest.mark.parametrize("violations, factor", sorted(BASEL_SCALING_FACTORS.items()))
def test_basel_scaling_factors_match_the_1996_table(violations, factor):
    result = basel_traffic_light(violations, observations=250, confidence=0.99)
    assert result.scaling_factor == factor


def test_basel_red_zone_scaling_factor_is_flat_at_four():
    for violations in (10, 15, 30):
        assert basel_traffic_light(violations, 250, 0.99).scaling_factor == 4.00


def test_basel_scaling_factor_withheld_off_the_tabulated_basis():
    # The zone still means something at 60 days; the multiplier does not.
    result = basel_traffic_light(violations=3, observations=60, confidence=0.99)
    assert result.zone in {"green", "yellow", "red"}
    assert result.scaling_factor is None
    assert "250" in result.scaling_factor_basis

    wrong_confidence = basel_traffic_light(violations=3, observations=250, confidence=0.95)
    assert wrong_confidence.scaling_factor is None


def test_basel_cumulative_probability_is_reported_so_the_cut_is_auditable():
    result = basel_traffic_light(violations=5, observations=250, confidence=0.99)
    assert 0.95 <= result.cumulative_probability < 0.9999


# --- end-to-end report ---


def test_var_backtest_end_to_end_on_a_calibrated_model():
    rng = np.random.default_rng(11)
    n = 2000
    returns = pd.Series(
        rng.normal(0.0, 0.01, n), index=pd.date_range("2018-01-01", periods=n, freq="B")
    )
    # A correctly specified parametric VaR for this generating process.
    var = 0.01 * 2.3263478740408408  # z_{0.99}
    report = var_backtest(returns, var, confidence=0.99)

    assert report.observations == n
    assert not report.conditional_coverage.rejected
    assert report.traffic_light.zone == "green"
    assert report.breach_dates is not None
    assert len(report.breach_dates) == report.violations


def test_var_backtest_end_to_end_on_an_understated_model():
    rng = np.random.default_rng(12)
    n = 1000
    returns = pd.Series(rng.normal(0.0, 0.02, n))
    # VaR built for half the true volatility: breaches far too often.
    report = var_backtest(returns, 0.01 * 2.3263478740408408, confidence=0.99)

    assert report.kupiec.rejected
    assert report.conditional_coverage.rejected
    assert report.traffic_light.zone == "red"


def test_var_backtest_breach_dates_are_the_actual_breach_labels():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    returns = pd.Series([-0.10, 0.01, -0.20, 0.02, -0.005], index=idx)
    report = var_backtest(returns, 0.05, confidence=0.95)
    assert report.breach_dates == (idx[0], idx[2])


def test_var_backtest_without_an_index_reports_no_dates():
    report = var_backtest(np.array([-0.10, 0.01, -0.20, 0.02]), 0.05, confidence=0.95)
    assert report.breach_dates is None


def test_var_backtest_needs_two_observations():
    with pytest.raises(ValueError, match="at least 2"):
        var_backtest(np.array([-0.05]), 0.02)


def test_time_varying_var_series_is_compared_day_by_day():
    returns = pd.Series([-0.03, -0.03, -0.03])
    var = pd.Series([0.02, 0.05, 0.02])
    report = var_backtest(returns, var, confidence=0.95)
    assert report.violations == 2
