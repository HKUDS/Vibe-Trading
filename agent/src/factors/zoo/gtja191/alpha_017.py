
# ============================================================
# 中文名称: GTJA #17 - VWAP回撤排名的价格变化幂
# 简要说明: RANK(VWAP - MAX(VWAP,15)) ^ DELTA(CLOSE,5)，幂指数保留涨跌方向。
# 典型用途: 衡量VWAP回撤横截面排名与五日价格变化的非线性关系。
# ============================================================
"""GTJA Alpha #17.

Formula: (RANK(VWAP - MAX(VWAP,15))^DELTA(CLOSE,5))
Source: 国泰君安 191 alpha 研报 (2014), alpha 17."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import (
    delta,
    rank,
    ts_max,
    vwap,
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
    "notes": 'The base is a percentile rank in (0, 1], so a negative 5-day close change is a real power, not a complex one.',
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    vw = vwap(panel, "equity_cn")
    base = rank(vw - ts_max(vw, 15))
    expo = delta(c, 5)
    # rank() is a percentile in (0, 1], so the report's power is real even when
    # the 5-day close change is negative. Dropping the sign of that change
    # turned 0.5 ** -2 into 0.25 instead of 4.
    out_arr = np.power(
        base.to_numpy(dtype=float, na_value=np.nan),
        expo.to_numpy(dtype=float, na_value=np.nan),
    )
    return pd.DataFrame(out_arr, index=c.index, columns=c.columns)
