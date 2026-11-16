# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: 变动率 10日
# 简要说明: close_{t-10} / close_t，10日前收盘价除以最新收盘价。
# 典型用途: 用于与 Qlib Alpha158 对齐的10日价格变化分析，不是常规收益率。
# ============================================================
"""qlib158 ROC10: formula = \\mathrm{close}_{{t-10}} / \\mathrm{close}_t."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div

__alpha_meta__ = {
    'id': 'qlib158_roc10',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{close}_{{t-10}} / \\\\mathrm{close}_t',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 11,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 ROC10 on the supplied OHLCV panel."""
    c = panel['close']
    return safe_div(c.shift(10), c)
