
# ============================================================
# 中文名称: GTJA Alpha #92
# 简要说明: 国泰君安191短周期交易型alpha因子第92号，详见公式定义。
# 典型用途: 在A股市场经中性化处理后用于选股或股指期货日内交易。
# ============================================================
"""GTJA Alpha #92.

Formula: (MAX(RANK(DECAYLINEAR(DELTA(((CLOSE*0.35)+(VWAP*0.65)),2),3)),TSRANK(DECAYLINEAR(ABS(CORR(MEAN(VOLUME,180),CLOSE,13)),5),15))*-1)
Source: 国泰君安 191 alpha 研报 (2017-06-15), alpha 92."""

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
    vwap,
)

__alpha_meta__ = {
    "id": "gtja191_092",
    "theme": ['volume'],
    "formula_latex": '(MAX(RANK(DECAYLINEAR(DELTA(((CLOSE*0.35)+(VWAP*0.65)),2),3)),TSRANK(DECAYLINEAR(ABS(CORR(MEAN(VOLUME,180),CLOSE,13)),5),15))*-1)',
    "columns_required": ['close', 'volume', 'amount'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 15,
    "min_warmup_bars": 210,
    "notes": "Original report windows; full nested-window coverage is required.",
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]
    vw = vwap(panel, "equity_cn")
    blend = c * 0.35 + vw * 0.65
    p1 = rank(decay_linear(delta(blend, 2), 3))
    p2 = ts_rank(decay_linear(ts_corr(ts_mean(v, 180), c, 13).abs(), 5), 15)
    return -1.0 * pd.DataFrame(np.maximum(p1.to_numpy(), p2.to_numpy()),
                               index=c.index, columns=c.columns)
