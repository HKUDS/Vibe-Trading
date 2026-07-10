"""Turnover-aware optimizer: max-Sharpe objective with an L1 turnover penalty.

Solves, per rebalance date::

    min  -w'mu + lambda * w'Sigma w + gamma * ||w - w_prev||_1
    s.t. w >= 0, sum(w) = 1

where ``w_prev`` is the weight vector applied at the previous rebalance,
restricted to the current active set (assets absent last time have prior
weight 0, so entries and exits both count as turnover). With ``gamma == 0``
the objective reduces to the mean-variance utility baseline.

The penalty ``gamma`` is scale-sensitive: it is measured against the return
term ``w'mu``, so an appropriate magnitude depends on the return units of the
input window. For daily returns (~1e-3), even ``gamma`` around 0.5 makes the
optimizer strongly prefer holding still. Callers should tune ``gamma`` relative
to their data frequency.

Realized per-rebalance turnover (``0.5 * ||w_t - w_{t-1}||_1``) is accumulated
on the instance for cost-adjusted analysis.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from backtest.optimizers.base import BaseOptimizer


class TurnoverAwareOptimizer(BaseOptimizer):
    """Mean-variance weights penalized for turnover against prior weights.

    Attributes:
        risk_aversion: Weight on the variance term (lambda).
        turnover_penalty: Weight on the L1 turnover term (gamma). 0 reduces to
            the mean-variance baseline.
        risk_free: Risk-free rate subtracted from mean returns.
        realized_turnover: Per-rebalance realized turnover collected during
            ``optimize`` (``0.5 * ||w_t - w_{t-1}||_1``).
    """

    def __init__(
        self,
        lookback: int = 60,
        risk_aversion: float = 1.0,
        turnover_penalty: float = 0.0,
        risk_free: float = 0.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(lookback=lookback, **kwargs)
        self.risk_aversion = float(risk_aversion)
        self.turnover_penalty = float(turnover_penalty)
        self.risk_free = float(risk_free)
        self._prev: Dict[str, float] = {}
        self.realized_turnover: List[float] = []

    def _build_context(
        self, window: pd.DataFrame, active: List[str]
    ) -> "Dict[str, Any] | None":
        """Mean vector, covariance, and active codes for the current window."""
        mu = window.mean().values
        cov = window.cov().values
        if np.isnan(cov).any() or np.isnan(mu).any():
            return None
        return {"cov": cov, "mu": mu, "active": list(active)}

    def _calc_weights(self, ctx: Dict[str, Any]) -> np.ndarray:
        """SLSQP weights for the penalized objective; updates turnover state."""
        from scipy.optimize import minimize

        mu = np.asarray(ctx["mu"], dtype=float)
        cov = np.asarray(ctx["cov"], dtype=float)
        active: List[str] = ctx["active"]
        n = len(mu)
        if n == 0:
            return self._equal_weight(0)

        w_prev = np.array([self._prev.get(code, 0.0) for code in active], dtype=float)
        rf = self.risk_free
        lam = self.risk_aversion
        gamma = self.turnover_penalty

        def objective(w: np.ndarray) -> float:
            ret = w @ mu - rf
            var = w @ cov @ w
            turn = np.abs(w - w_prev).sum()
            return -ret + lam * var + gamma * turn

        x0 = w_prev if w_prev.sum() > 1e-12 else self._equal_weight(n)
        result = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=[(0.0, 1.0)] * n,
            constraints={"type": "eq", "fun": lambda w: w.sum() - 1.0},
            options={"maxiter": 200, "ftol": 1e-10},
        )

        weights = self._normalize(result.x) if result.success else self._equal_weight(n)
        self._record_turnover(active, weights)
        return weights

    def _record_turnover(self, active: List[str], weights: np.ndarray) -> None:
        """Accumulate realized turnover and roll prior weights forward."""
        codes = set(active) | set(self._prev)
        new_map = {code: float(weights[i]) for i, code in enumerate(active)}
        turnover = 0.5 * sum(
            abs(new_map.get(code, 0.0) - self._prev.get(code, 0.0)) for code in codes
        )
        self.realized_turnover.append(turnover)
        self._prev = new_map


def optimize(
    ret: pd.DataFrame,
    pos: pd.DataFrame,
    dates: pd.DatetimeIndex,
    lookback: int = 60,
    risk_aversion: float = 1.0,
    turnover_penalty: float = 0.0,
    risk_free: float = 0.0,
) -> pd.DataFrame:
    """Module-level entry: turnover-penalized mean-variance positions."""
    return TurnoverAwareOptimizer(
        lookback=lookback,
        risk_aversion=risk_aversion,
        turnover_penalty=turnover_penalty,
        risk_free=risk_free,
    ).optimize(ret, pos, dates)
