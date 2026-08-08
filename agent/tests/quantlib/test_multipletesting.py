"""Tests for src.quantlib.multipletesting.

The load-bearing tests here are the ones that show a correction actually bites:
a Sharpe that passes uncorrected and fails once the trial count is admitted, and
a pure-noise strategy set whose PBO comes out near or above one half.
"""

import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from src.quantlib.multipletesting import (
    DEFAULT_CSCV_SPLITS,
    EULER_MASCHERONI,
    GAUSSIAN_KURTOSIS,
    MIN_OBSERVATIONS,
    benjamini_hochberg,
    deflated_sharpe_ratio,
    expected_maximum_sharpe,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
)


# --- sharpe helper ---


def test_sharpe_is_per_observation_not_annualised():
    rng = np.random.default_rng(0)
    daily = rng.normal(0.0005, 0.01, 5000)
    sr = sharpe_ratio(daily)
    assert sr == pytest.approx(0.05, abs=0.02)
    # An annualised reading would be ~sqrt(252) larger. It is not.
    assert sr < 0.5


def test_sharpe_ddof_is_exposed_because_the_repo_has_two_conventions():
    values = np.array([0.01, -0.005, 0.02, 0.0, 0.015])
    ratio = sharpe_ratio(values, ddof=1) / sharpe_ratio(values, ddof=0)
    assert ratio == pytest.approx(math.sqrt((len(values) - 1) / len(values)))


def test_sharpe_is_nan_without_dispersion():
    assert math.isnan(sharpe_ratio(np.full(50, 0.01)))


def test_sharpe_needs_two_observations():
    with pytest.raises(ValueError, match="at least 2"):
        sharpe_ratio([0.01])


# --- probabilistic Sharpe ---


def test_psr_matches_the_closed_form_under_gaussian_moments():
    sr, n = 0.10, 500
    expected = norm.cdf(sr * math.sqrt(n - 1) / math.sqrt(1 + 0.5 * sr**2))
    assert probabilistic_sharpe_ratio(sr, n) == pytest.approx(expected, rel=1e-12)


def test_psr_rises_with_sample_length():
    a = probabilistic_sharpe_ratio(0.05, 100)
    b = probabilistic_sharpe_ratio(0.05, 1000)
    assert b > a


def test_negative_skew_and_fat_tails_both_reduce_confidence():
    base = probabilistic_sharpe_ratio(0.10, 500, skew=0.0, kurtosis=GAUSSIAN_KURTOSIS)
    skewed = probabilistic_sharpe_ratio(0.10, 500, skew=-1.5, kurtosis=GAUSSIAN_KURTOSIS)
    fat = probabilistic_sharpe_ratio(0.10, 500, skew=0.0, kurtosis=12.0)

    assert skewed < base
    assert fat < base


def test_excess_kurtosis_passed_by_mistake_is_rejected_not_absorbed():
    # scipy.stats.kurtosis and pandas .kurt both return EXCESS kurtosis, which
    # is 0 for a Gaussian. Silently accepting 0 would shrink the variance term
    # and overstate confidence, so it must be an error.
    with pytest.raises(ValueError, match="non-excess"):
        probabilistic_sharpe_ratio(0.10, 500, kurtosis=0.0)


def test_psr_rejects_a_sample_too_short_for_its_own_moments():
    with pytest.raises(ValueError, match="at least"):
        probabilistic_sharpe_ratio(0.10, MIN_OBSERVATIONS - 1)


def test_psr_rejects_mutually_inconsistent_moments():
    with pytest.raises(ValueError, match="not\\s+positive|mutually inconsistent"):
        probabilistic_sharpe_ratio(2.0, 500, skew=5.0, kurtosis=1.0)


# --- expected maximum Sharpe ---


def test_expected_maximum_grows_with_the_number_of_trials():
    bars = [expected_maximum_sharpe(n, 0.1) for n in (2, 10, 100, 1000)]
    assert bars == sorted(bars)
    assert all(b > 0 for b in bars)


def test_expected_maximum_matches_the_closed_form():
    n, std = 462, 0.08
    expected = std * (
        (1 - EULER_MASCHERONI) * norm.ppf(1 - 1 / n)
        + EULER_MASCHERONI * norm.ppf(1 - 1 / (n * math.e))
    )
    assert expected_maximum_sharpe(n, std) == pytest.approx(expected, rel=1e-12)


def test_expected_maximum_is_zero_without_a_search():
    assert expected_maximum_sharpe(1, 0.1) == 0.0
    assert expected_maximum_sharpe(500, 0.0) == 0.0


def test_expected_maximum_scales_linearly_in_trial_dispersion():
    assert expected_maximum_sharpe(100, 0.2) == pytest.approx(
        2 * expected_maximum_sharpe(100, 0.1)
    )


def test_expected_maximum_rejects_impossible_inputs():
    with pytest.raises(ValueError, match="n_trials"):
        expected_maximum_sharpe(0, 0.1)
    with pytest.raises(ValueError, match="trial_sharpe_std"):
        expected_maximum_sharpe(10, -0.1)


# --- deflated Sharpe: the correction has to actually bite ---


def test_a_sharpe_that_passes_uncorrected_fails_once_the_search_is_admitted():
    # This is the whole point of the module. Same observed Sharpe, same sample:
    # one trial and it is convincing, 462 trials and it is not.
    observed, n_obs, dispersion = 0.09, 1000, 0.06

    undeflated = probabilistic_sharpe_ratio(observed, n_obs)
    assert undeflated > 0.99

    deflated = deflated_sharpe_ratio(
        observed_sharpe=observed,
        n_trials=462,
        n_observations=n_obs,
        trial_sharpe_std=dispersion,
    )
    assert deflated.expected_maximum_sharpe > 0.15
    assert deflated.deflated_sharpe_ratio < 0.05
    assert not deflated.survives


def test_a_genuinely_strong_result_still_survives_the_correction():
    # Two-sided: the correction must not reject everything, or it is useless.
    strong = deflated_sharpe_ratio(
        observed_sharpe=0.30,
        n_trials=462,
        n_observations=2000,
        trial_sharpe_std=0.06,
    )
    assert strong.survives
    assert strong.deflated_sharpe_ratio > 0.95


def test_deflation_bar_is_exactly_the_expected_maximum():
    result = deflated_sharpe_ratio(0.2, n_trials=100, n_observations=500, trial_sharpe_std=0.05)
    assert result.expected_maximum_sharpe == pytest.approx(
        expected_maximum_sharpe(100, 0.05)
    )
    assert result.deflated_sharpe_ratio == pytest.approx(
        probabilistic_sharpe_ratio(0.2, 500, benchmark_sharpe=result.expected_maximum_sharpe)
    )


def test_more_trials_monotonically_lowers_the_deflated_ratio():
    values = [
        deflated_sharpe_ratio(0.15, n, 1000, 0.05).deflated_sharpe_ratio
        for n in (1, 10, 100, 1000)
    ]
    assert values == sorted(values, reverse=True)


def test_deflated_result_carries_the_inputs_it_was_judged_on():
    result = deflated_sharpe_ratio(0.15, 50, 800, 0.04, skew=-0.4, kurtosis=6.0)
    assert result.n_trials == 50
    assert result.n_observations == 800
    assert result.skew == -0.4
    assert result.kurtosis == 6.0
    assert result.confidence == 0.95


def test_deflated_rejects_a_bad_confidence():
    with pytest.raises(ValueError, match="confidence"):
        deflated_sharpe_ratio(0.1, 10, 500, 0.05, confidence=1.5)


# --- Benjamini-Hochberg ---


def test_bh_rejects_nothing_when_every_null_is_true():
    rng = np.random.default_rng(1)
    p_values = rng.uniform(0, 1, 1000)  # uniform under the null
    result = benjamini_hochberg(p_values, fdr=0.05)
    assert result.n_rejected <= 50  # expected false discoveries bounded by fdr


def test_bh_finds_the_planted_signals():
    rng = np.random.default_rng(2)
    p_values = np.r_[rng.uniform(0, 1e-6, 20), rng.uniform(0, 1, 480)]
    result = benjamini_hochberg(p_values, fdr=0.05)
    assert result.n_rejected >= 20
    assert result.rejected[:20].all()


def test_bh_is_less_strict_than_bonferroni():
    # Fifty p-values just under 0.001 with n=1000: Bonferroni (0.05/1000 =
    # 5e-5) rejects none of them, BH rejects them all.
    p_values = np.r_[np.full(50, 9e-4), np.full(950, 0.5)]
    result = benjamini_hochberg(p_values, fdr=0.05)
    assert (p_values[:50] > 0.05 / 1000).all()
    assert result.n_rejected == 50


def test_bh_adjusted_p_values_are_monotone_in_the_raw_ones():
    rng = np.random.default_rng(3)
    p_values = rng.uniform(0, 1, 200)
    result = benjamini_hochberg(p_values)
    order = np.argsort(p_values)
    adjusted_sorted = result.adjusted_p_values[order]
    assert np.all(np.diff(adjusted_sorted) >= -1e-15)
    assert (result.adjusted_p_values <= 1.0).all()
    assert (result.adjusted_p_values >= 0.0).all()


def test_bh_results_come_back_in_the_callers_order():
    p_values = np.array([0.9, 1e-8, 0.4, 2e-8])
    result = benjamini_hochberg(p_values, fdr=0.05)
    assert result.rejected.tolist() == [False, True, False, True]


def test_bh_rejection_set_is_exactly_the_step_up_rule():
    p_values = np.array([0.001, 0.008, 0.039, 0.041, 0.042, 0.6])
    n, fdr = len(p_values), 0.05
    ranks = np.arange(1, n + 1)
    expected_cutoff = int(ranks[np.sort(p_values) <= ranks / n * fdr].max())
    result = benjamini_hochberg(p_values, fdr=fdr)
    assert result.n_rejected == expected_cutoff


@pytest.mark.parametrize("bad", [[], [0.5, 1.5], [0.5, -0.1], [0.5, np.nan]])
def test_bh_rejects_impossible_p_values(bad):
    with pytest.raises(ValueError):
        benjamini_hochberg(bad)


def test_bh_rejects_a_bad_fdr():
    with pytest.raises(ValueError, match="fdr"):
        benjamini_hochberg([0.01, 0.02], fdr=0.0)


# --- CSCV / PBO ---


def test_pure_noise_strategies_give_a_pbo_around_one_half():
    # No strategy has any edge, so in-sample selection carries no information
    # and the winner lands either side of the OOS median about equally often.
    rng = np.random.default_rng(4)
    noise = pd.DataFrame(rng.normal(0.0, 0.01, (960, 12)))
    result = probability_of_backtest_overfitting(noise, n_splits=8)

    assert 0.3 < result.pbo < 0.75
    assert result.n_strategies == 12


def test_a_genuinely_superior_strategy_drives_pbo_down():
    # One strategy really is better in every period, so the in-sample winner is
    # the same strategy out-of-sample and PBO collapses.
    rng = np.random.default_rng(5)
    data = rng.normal(0.0, 0.01, (960, 12))
    data[:, 3] += 0.004  # a large, persistent edge
    result = probability_of_backtest_overfitting(pd.DataFrame(data), n_splits=8)

    assert result.pbo < 0.05


def test_performance_degradation_is_negative_when_selection_fits_noise():
    rng = np.random.default_rng(6)
    noise = pd.DataFrame(rng.normal(0.0, 0.01, (960, 15)))
    result = probability_of_backtest_overfitting(noise, n_splits=8)
    assert result.performance_degradation < 0


def test_cscv_reports_rows_it_trimmed_rather_than_dropping_them_silently():
    rng = np.random.default_rng(7)
    # 1000 rows over 8 subsets leaves a remainder of 0; 1005 leaves 5.
    data = pd.DataFrame(rng.normal(0, 0.01, (1005, 5)))
    result = probability_of_backtest_overfitting(data, n_splits=8)
    assert result.dropped_observations == 1005 - (1005 // 8) * 8
    assert result.n_observations == (1005 // 8) * 8


def test_cscv_split_count_is_the_full_combination_set():
    rng = np.random.default_rng(8)
    data = pd.DataFrame(rng.normal(0, 0.01, (480, 4)))
    result = probability_of_backtest_overfitting(data, n_splits=6)
    assert result.n_splits == math.comb(6, 3)


def test_cscv_default_split_count_is_even_and_usable():
    assert DEFAULT_CSCV_SPLITS % 2 == 0
    assert DEFAULT_CSCV_SPLITS >= 4


def test_cscv_rejects_an_odd_split_count():
    rng = np.random.default_rng(9)
    with pytest.raises(ValueError, match="even"):
        probability_of_backtest_overfitting(pd.DataFrame(rng.normal(0, 1, (200, 3))), n_splits=7)


def test_cscv_needs_competing_strategies():
    rng = np.random.default_rng(10)
    with pytest.raises(ValueError, match="at least 2"):
        probability_of_backtest_overfitting(pd.DataFrame(rng.normal(0, 1, (200, 1))))


def test_cscv_rejects_a_sample_too_short_for_its_subsets():
    rng = np.random.default_rng(11)
    with pytest.raises(ValueError, match="at least 2"):
        probability_of_backtest_overfitting(
            pd.DataFrame(rng.normal(0, 1, (10, 3))), n_splits=8
        )


def test_cscv_logits_and_pbo_agree():
    rng = np.random.default_rng(12)
    data = pd.DataFrame(rng.normal(0, 0.01, (480, 6)))
    result = probability_of_backtest_overfitting(data, n_splits=6)
    assert result.pbo == pytest.approx((result.logits <= 0).mean())
    assert result.logits.size == result.n_splits
