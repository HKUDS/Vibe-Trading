from __future__ import annotations

from src.reliability.quant.overfit import build_overfit_experimental_metrics


def test_dsr_pbo_experimental_only() -> None:
    result = build_overfit_experimental_metrics(
        observed_sharpe=1.0,
        benchmark_sharpe=0.0,
        sharpe_std=0.5,
        n_observations=252,
        n_trials=20,
    )

    assert "dsr" in result.experimental_metrics
    assert "pbo" in result.experimental_metrics
    assert result.experimental_metrics["dsr"]["experimental"] is True
    assert result.experimental_metrics["pbo"]["experimental"] is True
    assert result.hard_failures == []


def test_dsr_missing_trial_count_warns_without_calculation() -> None:
    result = build_overfit_experimental_metrics(
        observed_sharpe=1.0,
        benchmark_sharpe=0.0,
        sharpe_std=0.5,
        n_observations=252,
        n_trials=None,
    )

    assert "dsr" not in result.experimental_metrics
    assert any(
        issue.code == "QUANT_TRIAL_COUNT_MISSING_FOR_DSR"
        for issue in result.warnings
    )
