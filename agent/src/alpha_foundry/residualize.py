from __future__ import annotations

import numpy as np
import pandas as pd


def residualize_candidate_by_date(
    candidate: pd.DataFrame,
    bases: dict[str, pd.DataFrame],
    *,
    min_cross_section: int = 30,
    ridge: float = 0.0,
) -> pd.DataFrame:
    """Remove same-date linear exposure to base factor panels."""

    residual = pd.DataFrame(np.nan, index=candidate.index, columns=candidate.columns)
    if not bases:
        return candidate.astype(float).copy()

    for date in candidate.index:
        if not all(date in base.index for base in bases.values()):
            continue

        y = candidate.loc[date].astype(float)
        regressors = [
            base.loc[date].reindex(candidate.columns).astype(float)
            for base in bases.values()
        ]
        x_frame = pd.concat(regressors, axis=1)
        x_frame.columns = list(bases.keys())
        valid = y.notna() & x_frame.notna().all(axis=1)
        if int(valid.sum()) < min_cross_section:
            continue

        yv = y.loc[valid].to_numpy(dtype=float)
        xv = x_frame.loc[valid].to_numpy(dtype=float)
        design = np.column_stack([np.ones(len(yv)), xv])
        beta = _solve_linear(design, yv, ridge=ridge)
        fitted = design @ beta
        residual.loc[date, valid.index[valid]] = yv - fitted

    return residual


def _solve_linear(design: np.ndarray, target: np.ndarray, *, ridge: float) -> np.ndarray:
    if ridge <= 0:
        beta, *_ = np.linalg.lstsq(design, target, rcond=None)
        return beta

    penalty = np.eye(design.shape[1]) * ridge
    penalty[0, 0] = 0.0
    return np.linalg.solve(design.T @ design + penalty, design.T @ target)
