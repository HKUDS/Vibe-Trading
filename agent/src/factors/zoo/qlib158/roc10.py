# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: 变动率 10日
# 简要说明: close_t / close_{t-10}，Qlib 原版 10 日价格比（无 -1 偏移）。
# 典型用途: 经典的10日动量因子，正值为上涨趋势，负值为下跌趋势。
# ============================================================
"""qlib158 ROC10: formula = \\mathrm{close}_t / \\mathrm{close}_{{t-10}}."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div

__alpha_meta__ = {
    'id': 'qlib158_roc10',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{close}_t / \\\\mathrm{close}_{{t-10}}',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 ROC10 on the supplied OHLCV panel."""
    c = panel['close']
    return safe_div(c, c.shift(10))
