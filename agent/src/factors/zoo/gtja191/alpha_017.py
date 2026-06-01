"""GTJA Alpha #17.

Formula: (RANK(VWAP - MAX(VWAP,15))^DELTA(CLOSE,5))
Source: 国泰君安 191 alpha 研报 (2014), alpha 17."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import (
    decay_linear,
    delta,
    rank,
    safe_div,
    signed_power,
    ts_argmax,
    ts_argmin,
    ts_corr,
    ts_cov,
    ts_max,
    ts_mean,
    ts_min,
    ts_rank,
    ts_std,
)

__alpha_meta__ = {
    "id": "gtja191_017",
    "theme": ['reversal'],
    "formula_latex": '(RANK(VWAP - MAX(VWAP,15))^DELTA(CLOSE,5))',
    "columns_required": ['close', 'volume', 'amount'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 15,
    "min_warmup_bars": 16,
    "notes": 'rank(vwap - 15d max(vwap)) is non-positive; we use signed_power for safety.',
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]
    vw = safe_div(panel["amount"], v * 100.0 + 1.0)
    base = rank(vw - ts_max(vw, 15))
    expo = delta(c, 5)
    # Combine via signed_power(base, mean_exp): use elementwise sign-preserving |base|**expo proxy
    out_arr = np.sign(base.to_numpy(dtype=float, na_value=np.nan)) * np.power(
        np.abs(base.to_numpy(dtype=float, na_value=np.nan)),
        np.abs(expo.to_numpy(dtype=float, na_value=np.nan)),
    )
    return pd.DataFrame(out_arr, index=c.index, columns=c.columns)
