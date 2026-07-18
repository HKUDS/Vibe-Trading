"""Focused accounting and metric regressions for the options engine."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backtest.engines.options_portfolio import _calc_options_metrics


def test_empty_equity_returns_json_safe_undefined_metrics() -> None:
    metrics = _calc_options_metrics(pd.Series(dtype=float), 100.0, [])

    assert metrics["final_value"] is None
    assert metrics["annual_return"] is None
    assert metrics["warnings"]
    json.dumps(metrics, allow_nan=False)


def test_single_equity_point_reports_observed_final_value() -> None:
    metrics = _calc_options_metrics(pd.Series([99.0]), 100.0, [])

    assert metrics["final_value"] == 99.0
    assert metrics["total_return"] == -0.01
    assert metrics["annual_return"] is None
    json.dumps(metrics, allow_nan=False)


def test_zero_final_equity_has_real_annual_return() -> None:
    metrics = _calc_options_metrics(pd.Series([100.0, 0.0]), 100.0, [])

    assert metrics["final_value"] == 0.0
    assert metrics["total_return"] == -1.0
    assert metrics["annual_return"] == -1.0
    json.dumps(metrics, allow_nan=False)


def test_negative_final_equity_does_not_create_complex_annual_return() -> None:
    metrics = _calc_options_metrics(
        pd.Series([100.0, 100.0, 100.0, 100.0, -10.0]), 100.0, []
    )

    assert metrics["final_value"] == -10.0
    assert metrics["total_return"] == -1.1
    assert metrics["annual_return"] is None
    assert any("negative" in warning for warning in metrics["warnings"])
    json.dumps(metrics, allow_nan=False)


@pytest.mark.parametrize("terminal", [np.nan, np.inf, -np.inf])
def test_non_finite_final_equity_is_json_safe(terminal: float) -> None:
    metrics = _calc_options_metrics(pd.Series([100.0, terminal]), 100.0, [])

    assert metrics["final_value"] is None
    assert metrics["total_return"] is None
    assert metrics["annual_return"] is None
    json.dumps(metrics, allow_nan=False)


def test_normal_positive_equity_metrics_remain_finite() -> None:
    metrics = _calc_options_metrics(
        pd.Series([100.0, 110.0, 104.5, 115.0, 103.5, 120.0]),
        100.0,
        [],
    )

    assert metrics["final_value"] == 120.0
    assert metrics["annual_return"] is not None
    assert metrics["sharpe"] is not None
    assert metrics["max_drawdown"] is not None
    assert metrics["calmar"] is not None
    assert metrics["sortino"] is not None
    json.dumps(metrics, allow_nan=False)


def test_non_positive_bars_per_year_keeps_all_metrics_json_safe() -> None:
    metrics = _calc_options_metrics(
        pd.Series([100.0, 110.0, 104.5, 115.0]),
        100.0,
        [],
        bars_per_year=0,
    )

    assert metrics["annual_return"] is None
    assert metrics["sharpe"] is None
    assert metrics["sortino"] is None
    json.dumps(metrics, allow_nan=False)
