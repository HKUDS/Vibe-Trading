"""Turnover-aware optimizer: mean-variance utility with an L1 turnover penalty.

Solves, per rebalance date::

    min  -w'mu + lambda * w'Sigma w + gamma * ||w - w_prev||_1
    s.t. w >= 0, sum(w) = 1
         w_i <= max_per_name                          (per-name cap)
         sum_{i in group_g} w_i <= max_per_group[g]   (per-group cap)

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
on the instance for cost-adjusted analysis. This is a class-API affordance:
the engine's module-level ``optimize`` entry constructs a fresh instance and
returns only the positions frame, so callers who want the turnover series must
instantiate ``TurnoverAwareOptimizer`` directly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backtest.optimizers.base import BaseOptimizer


class TurnoverAwareOptimizer(BaseOptimizer):
    """Mean-variance weights penalized for turnover against prior weights.

    Attributes:
        risk_aversion: Weight on the variance term (lambda).
        turnover_penalty: Weight on the L1 turnover term (gamma). 0 reduces to
            the mean-variance baseline.
        max_per_name: Per-asset weight cap (None = no limit).
        groups: Asset-code → group-name mapping for per-group caps.
        max_per_group: Group-name → maximum total weight for that group.
        realized_turnover: Per-rebalance realized turnover collected during
            ``optimize`` (``0.5 * ||w_t - w_{t-1}||_1``).
    """

    def __init__(
        self,
        lookback: int = 60,
        risk_aversion: float = 1.0,
        turnover_penalty: float = 0.0,
        max_per_name: Optional[float] = None,
        groups: Optional[Dict[str, str]] = None,
        max_per_group: Optional[Dict[str, float]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(lookback=lookback, **kwargs)
        self.risk_aversion = float(risk_aversion)
        self.turnover_penalty = float(turnover_penalty)
        if isinstance(max_per_name, (bool, np.bool_)):
            raise ValueError("max_per_name must be numeric, not boolean")
        self.max_per_name = float(max_per_name) if max_per_name is not None else None
        self.groups: Dict[str, str] = dict(groups) if groups else {}
        self.max_per_group: Dict[str, float] = dict(max_per_group) if max_per_group else {}
        if self.max_per_name is not None and (
            not np.isfinite(self.max_per_name) or not 0.0 < self.max_per_name <= 1.0
        ):
            raise ValueError("max_per_name must be finite and in (0, 1]")
        if any(not isinstance(code, str) or not isinstance(group, str) for code, group in self.groups.items()):
            raise ValueError("groups must map string asset codes to string group names")
        unknown_groups = set(self.max_per_group) - set(self.groups.values())
        if unknown_groups:
            raise ValueError(
                "max_per_group references groups with no mapped assets: "
                + ", ".join(sorted(unknown_groups))
            )
        for group, cap in self.max_per_group.items():
            if isinstance(cap, (bool, np.bool_)):
                raise ValueError(f"cap for group {group!r} must be numeric, not boolean")
            try:
                numeric_cap = float(cap)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"cap for group {group!r} must be numeric") from exc
            if not np.isfinite(numeric_cap) or not 0.0 < numeric_cap <= 1.0:
                raise ValueError(f"cap for group {group!r} must be finite and in (0, 1]")
            self.max_per_group[group] = numeric_cap
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
        lam = self.risk_aversion
        gamma = self.turnover_penalty

        def objective(w: np.ndarray) -> float:
            ret = w @ mu
            var = w @ cov @ w
            turn = np.abs(w - w_prev).sum()
            return -ret + lam * var + gamma * turn

        # --- bounds: per-name cap ---
        upper = 1.0
        if self.max_per_name is not None:
            upper = min(1.0, float(self.max_per_name))
        bounds = [(0.0, upper)] * n

        # --- constraints: simplex + per-group caps ---
        constraints: list = [
            {"type": "eq", "fun": lambda w: w.sum() - 1.0},
        ]
        group_rows: list[np.ndarray] = []
        group_caps: list[float] = []
        group_constraint_indices: list[List[int]] = []

        group_indices: Dict[str, List[int]] = {}
        if self.groups and self.max_per_group:
            for i, code in enumerate(active):
                g = self.groups.get(code)
                if g is not None:
                    group_indices.setdefault(g, []).append(i)
            for g, cap in self.max_per_group.items():
                indices = group_indices.get(g, [])
                if not indices:
                    continue
                cap = float(cap)
                row = np.zeros(n)
                row[indices] = 1.0
                group_rows.append(row)
                group_caps.append(cap)
                group_constraint_indices.append(indices)
                constraints.append({
                    "type": "ineq",
                    "fun": lambda w, idx=indices, c=cap: c - w[np.array(idx)].sum(),
                })

        has_effective_caps = upper < 1.0 or any(cap < 1.0 for cap in group_caps)
        if not has_effective_caps:
            x0 = w_prev if w_prev.sum() > 1e-12 else self._equal_weight(n)
        elif (
            np.isfinite(w_prev).all()
            and (w_prev >= 0.0).all()
            and abs(w_prev.sum() - 1.0) <= 1e-12
            and (w_prev <= upper + 1e-12).all()
            and all(
                row @ w_prev <= cap + 1e-12
                for row, cap in zip(group_rows, group_caps)
            )
        ):
            x0 = w_prev
        else:
            # Groups are a single label per asset, so their caps are disjoint.
            # Allocate each bucket by capacity to obtain a feasible simplex point.
            buckets: list[tuple[List[int], float]] = []
            capped_indices: set[int] = set()
            for indices, cap in zip(group_constraint_indices, group_caps):
                capacity = min(cap, len(indices) * upper)
                buckets.append((indices, capacity))
                capped_indices.update(indices)
            uncapped = [i for i in range(n) if i not in capped_indices]
            if uncapped:
                buckets.append((uncapped, len(uncapped) * upper))
            total_capacity = sum(capacity for _, capacity in buckets)
            if total_capacity < 1.0 - 1e-12:
                raise ValueError(
                    "exposure caps are infeasible for active assets "
                    f"{active}: total capacity is {total_capacity:.6g}"
                )
            x0 = np.zeros(n)
            for indices, capacity in buckets:
                x0[indices] = capacity / total_capacity / len(indices)

        result = minimize(
            objective,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 200, "ftol": 1e-10},
        )

        if not result.success:
            raise RuntimeError(f"turnover-aware optimization failed: {result.message}")
        weights = np.maximum(np.asarray(result.x, dtype=float), 0.0)
        weights /= weights.sum()
        if (
            not np.isfinite(weights).all()
            or abs(weights.sum() - 1.0) > 1e-7
            or weights.max() > upper + 1e-7
            or any(row @ weights > cap + 1e-7 for row, cap in zip(group_rows, group_caps))
        ):
            raise RuntimeError("optimizer returned weights that violate exposure caps")
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
    max_per_name: Optional[float] = None,
    groups: Optional[Dict[str, str]] = None,
    max_per_group: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Module-level entry: turnover-penalized mean-variance positions."""
    return TurnoverAwareOptimizer(
        lookback=lookback,
        risk_aversion=risk_aversion,
        turnover_penalty=turnover_penalty,
        max_per_name=max_per_name,
        groups=groups,
        max_per_group=max_per_group,
    ).optimize(ret, pos, dates)
