"""
Factor evaluation metrics: IC, IR, rolling correlation, forward returns.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


@dataclass
class FactorResult:
    factor: str
    horizon: str
    ic: float
    ir: float
    n_samples: int

    def predictive(self, threshold: float = 0.05) -> bool:
        return not np.isnan(self.ic) and abs(self.ic) > threshold


def add_forward_returns(df: pd.DataFrame, price_col: str, horizons_h: list) -> pd.DataFrame:
    """Append forward simple returns columns named ret_<h>h for each horizon in hours."""
    out = df.copy()
    for h in horizons_h:
        out[f"ret_{h}h"] = out[price_col].shift(-h) / out[price_col] - 1
    return out


def compute_ic(factor_series: pd.Series, return_series: pd.Series, method: str = "spearman") -> float:
    """Pairwise IC (drops NaNs). Returns spearman rho by default."""
    paired = pd.concat([factor_series, return_series], axis=1).dropna()
    if len(paired) < 20:
        return float("nan")
    if method == "spearman":
        rho, _ = spearmanr(paired.iloc[:, 0], paired.iloc[:, 1])
    else:
        rho = paired.iloc[:, 0].corr(paired.iloc[:, 1], method=method)
    return float(rho)


def rolling_ic(
    df: pd.DataFrame,
    factor_col: str,
    return_col: str,
    window_bars: int,
    step_bars: int = 24,
    min_samples: int = 200,
) -> np.ndarray:
    """Compute IC across rolling windows. Returns 1D array of IC values."""
    sub = df[[factor_col, return_col]].dropna()
    if len(sub) < window_bars:
        return np.array([])
    out: list = []
    for s in range(0, len(sub) - window_bars + 1, step_bars):
        w = sub.iloc[s : s + window_bars]
        if len(w) < min_samples:
            continue
        rho, _ = spearmanr(w.iloc[:, 0], w.iloc[:, 1])
        if not np.isnan(rho):
            out.append(rho)
    return np.array(out)


def evaluate_factor(
    df: pd.DataFrame,
    factor_col: str,
    horizons_h: list,
    rolling_window_days: int = 30,
    min_samples: int = 200,
) -> list:
    """Compute IC + IR for one factor across multiple forward-return horizons.

    Expects df to already contain ret_<h>h columns (use add_forward_returns first).
    """
    results: list = []
    for h in horizons_h:
        ret_col = f"ret_{h}h"
        if ret_col not in df.columns:
            raise KeyError(f"missing column {ret_col} (call add_forward_returns first)")
        sub = df[[factor_col, ret_col]].dropna()
        n = len(sub)
        if n < min_samples:
            results.append(FactorResult(factor_col, f"{h}h", float("nan"), float("nan"), n))
            continue
        ic, _ = spearmanr(sub[factor_col], sub[ret_col])
        rolling = rolling_ic(
            df,
            factor_col,
            ret_col,
            window_bars=rolling_window_days * 24,
            step_bars=24,
            min_samples=min_samples,
        )
        if rolling.size > 0 and rolling.std(ddof=0) > 0:
            ir = float(rolling.mean() / rolling.std(ddof=0))
        else:
            ir = float("nan")
        results.append(FactorResult(factor_col, f"{h}h", float(ic), ir, n))
    return results
