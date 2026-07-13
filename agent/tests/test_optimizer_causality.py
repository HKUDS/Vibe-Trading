"""Causality regression tests for portfolio optimizer lookback windows."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.optimizers.base import BaseOptimizer


class _LastObservationOptimizer(BaseOptimizer):
    """Allocate fully to the asset with the best last visible return."""

    def __init__(self, lookback: int = 5) -> None:
        super().__init__(lookback=lookback)
        self.windows: list[pd.DatetimeIndex] = []

    def _build_context(
        self,
        window: pd.DataFrame,
        active: list[str],
    ) -> dict[str, np.ndarray]:
        self.windows.append(window.index.copy())
        return {"last_return": window.iloc[-1].to_numpy(dtype=float)}

    def _calc_weights(self, ctx: dict[str, np.ndarray]) -> np.ndarray:
        weights = np.zeros(len(ctx["last_return"]), dtype=float)
        weights[int(np.argmax(ctx["last_return"]))] = 1.0
        return weights


def _inputs() -> tuple[pd.DatetimeIndex, pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2026-01-05", periods=6)
    returns = pd.DataFrame(
        {
            "A": [0.00, 0.01, 0.02, 0.03, 0.80, 0.00],
            "B": [0.00, 0.00, 0.01, 0.02, -0.80, 0.00],
        },
        index=dates,
    )
    positions = pd.DataFrame(1.0, index=dates, columns=["A", "B"])
    return dates, returns, positions


def test_optimizer_window_excludes_decision_bar() -> None:
    dates, returns, positions = _inputs()
    optimizer = _LastObservationOptimizer(lookback=5)

    optimizer.optimize(returns, positions, dates)

    assert len(optimizer.windows) == 1
    assert optimizer.windows[0].max() < dates[-1]
    assert optimizer.windows[0].max() == dates[-2]


def test_decision_bar_return_cannot_change_decision_bar_weights() -> None:
    dates, returns, positions = _inputs()
    altered = returns.copy()
    altered.loc[dates[-1], ["A", "B"]] = [-100.0, 100.0]

    baseline = _LastObservationOptimizer(lookback=5).optimize(returns, positions, dates)
    shocked = _LastObservationOptimizer(lookback=5).optimize(altered, positions, dates)

    pd.testing.assert_series_equal(baseline.loc[dates[-1]], shocked.loc[dates[-1]])
    assert baseline.loc[dates[-1]].to_dict() == {"A": 1.0, "B": 0.0}
