"""Sortino uses zero-target downside RMS over all observed return periods."""

import math

import pandas as pd
import pytest

from backtest.metrics import calc_metrics


@pytest.mark.parametrize(
    "equity, mean_return, downside_mean_square",
    [
        # Returns include the existing initial zero: [0, -.01, -.01, .03].
        ([100.0, 99.0, 98.01, 100.9503], 0.0025, 0.0002 / 4),
        # One loss is enough to define downside risk: [0, -.01, .03].
        ([100.0, 99.0, 101.97], 0.02 / 3, 0.0001 / 3),
        # Upside periods still count in the denominator: [0, -.01, -.02, .06].
        ([100.0, 99.0, 97.02, 102.8412], 0.03 / 4, 0.0005 / 4),
        # Equal losses have real risk even though their standard deviation is zero.
        ([100.0, 99.0, 98.01], -0.02 / 3, 0.0002 / 3),
    ],
    ids=["equal-losses", "single-loss", "unequal-losses", "only-losses"],
)
@pytest.mark.parametrize("bars_per_year", [1, 252])
def test_sortino_uses_full_sample_downside_deviation(
    equity: list[float],
    mean_return: float,
    downside_mean_square: float,
    bars_per_year: int,
) -> None:
    result = calc_metrics(pd.Series(equity), [], 100.0, bars_per_year)
    expected = mean_return / math.sqrt(downside_mean_square) * math.sqrt(bars_per_year)
    assert result["sortino"] == pytest.approx(expected, abs=1e-4)


def test_sortino_preserves_no_downside_convention() -> None:
    # Zero downside retains the existing finite fallback, not a defined ratio.
    equity = pd.Series([100.0, 110.0, 121.0])
    result = calc_metrics(equity, [], 100.0, bars_per_year=1)
    assert result["sortino"] == pytest.approx((0.2 / 3) / 2e-10)


@pytest.mark.parametrize("equity", [[], [100.0], [100.0, 100.0], [100.0, 0.0, 50.0]])
def test_sortino_preserves_degenerate_path_conventions(equity: list[float]) -> None:
    result = calc_metrics(pd.Series(equity, dtype=float), [], 100.0)
    assert result["sortino"] == 0.0


def test_sortino_preserves_calendar_annualization() -> None:
    # Four bars across 366 days resolve to int(4 / (366 / 365.25)) == 3 bars/year.
    equity = pd.Series(
        [100.0, 99.0, 98.01, 100.9503],
        index=pd.to_datetime(["2024-01-01", "2024-05-01", "2024-09-01", "2025-01-01"]),
    )
    result = calc_metrics(equity, [], 100.0, bars_per_year=None)
    assert result["sortino"] == pytest.approx(
        0.0025 / math.sqrt(0.00005) * math.sqrt(3), abs=1e-4
    )
