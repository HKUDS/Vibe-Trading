# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: 变动率 30日
# 简要说明: close_{t-30} / close_t，30日前收盘价除以最新收盘价。
# 典型用途: 用于与 Qlib Alpha158 对齐的30日价格变化分析，不是常规收益率。
# ============================================================
"""qlib158 ROC30: formula = \\mathrm{close}_{{t-30}} / \\mathrm{close}_t."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div

__alpha_meta__ = {
    'id': 'qlib158_roc30',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{close}_{{t-30}} / \\\\mathrm{close}_t',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 30,
    'min_warmup_bars': 31,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 ROC30 on the supplied OHLCV panel."""
    c = panel['close']
    return safe_div(c.shift(30), c)
