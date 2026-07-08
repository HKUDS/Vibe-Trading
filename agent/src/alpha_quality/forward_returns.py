from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


def compute_forward_return(
    close: pd.DataFrame,
    horizon: int,
    *,
    execution_lag: int = 1,
    method: Literal["close_to_close", "vwap_to_vwap"] = "close_to_close",
) -> pd.DataFrame:
    """Return from t+execution_lag to t+execution_lag+horizon."""
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    if execution_lag < 1:
        raise ValueError("execution_lag must be >= 1")
    if method != "close_to_close":
        raise ValueError(f"unsupported forward return method: {method}")
    entry = close.shift(-execution_lag)
    exit_ = close.shift(-(execution_lag + horizon))
    result = exit_ / entry - 1.0
    return result.replace([np.inf, -np.inf], np.nan)
