
# ============================================================
# 中文名称: GTJA #26 - 条件SMA差值
# 简要说明: (-1*TSMAX(CORR(TSRANK(VOLUME,5), TSRANK(HIGH,5),5),3))，成交量与最高价5日秩相关的3日最大值取负。
# 典型用途: 量价同步性达到极值后的反转信号。
# ============================================================
"""GTJA Alpha #26.

Formula: ((((SUM(CLOSE,7)/7)-CLOSE))+((CORR(VWAP,DELAY(CLOSE,5),230))))
Source: 国泰君安 191 alpha 研报 (2017-06-15), alpha 26."""

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
    "id": "gtja191_026",
    "theme": ['momentum', 'microstructure'],
    "formula_latex": '((((SUM(CLOSE,7)/7)-CLOSE))+((CORR(VWAP,DELAY(CLOSE,5),230))))',
    "columns_required": ['close', 'volume', 'amount'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 7,
    "min_warmup_bars": 235,
    "notes": "Original report windows; full nested-window coverage is required.",
}

def compute(panel: dict) -> pd.DataFrame:
    c = panel["close"]
    v = panel["volume"]
    vw = vwap(panel, "equity_cn")
    term1 = ts_mean(c, 7) - c
    term2 = ts_corr(vw, c.shift(5), 230)
    return term1 + term2
