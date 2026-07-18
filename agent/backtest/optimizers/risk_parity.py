"""Long-only risk parity: equalize marginal risk contributions."""

from typing import Any, Dict

import numpy as np
import pandas as pd

from backtest.optimizers.base import BaseOptimizer


class RiskParityOptimizer(BaseOptimizer):
    """Equal-risk-contribution weights on the long-only simplex."""

    def _calc_weights(self, ctx: Dict[str, Any]) -> np.ndarray:
        """Equal risk contribution weights."""
        from scipy.optimize import minimize

        cov = ctx["cov"]
        n = cov.shape[0]
        if n == 0:
            return self._equal_weight(0)

        vols = np.sqrt(np.diag(cov))
        if not np.isfinite(cov).all() or np.any(vols < 1e-12):
            return self._equal_weight(n)

        inv_vol = 1.0 / vols
        seed = inv_vol / inv_vol.sum()

        def contribution_error(w: np.ndarray) -> float:
            variance = float(w @ cov @ w)
            if not np.isfinite(variance) or variance <= 1e-18:
                return 1e12
            contributions = w * (cov @ w)
            target = variance / n
            return float(np.sum((contributions - target) ** 2) / variance**2)

        result = minimize(
            contribution_error,
            seed,
            method="SLSQP",
            bounds=[(0.0, 1.0)] * n,
            constraints={"type": "eq", "fun": lambda w: w.sum() - 1.0},
            options={"maxiter": 200, "ftol": 1e-12},
        )

        if result.success and np.isfinite(result.x).all():
            return self._normalize(result.x)
        return self._normalize(seed)


def optimize(
    ret: pd.DataFrame,
    pos: pd.DataFrame,
    dates: pd.DatetimeIndex,
    lookback: int = 60,
) -> pd.DataFrame:
    """Module-level entry: risk-parity-adjusted positions."""
    return RiskParityOptimizer(lookback=lookback).optimize(ret, pos, dates)
