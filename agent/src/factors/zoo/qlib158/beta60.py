# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: Beta系数 60日
# 简要说明: Slope(close, 60) / close，收盘价对时间的60日线性回归斜率，按最新收盘价归一化。
# 典型用途: 衡量60日价格趋势的速度和方向，正值表示上涨趋势。
# ============================================================
"""qlib158 BETA60: formula = \\mathrm{Slope}(\\mathrm{close}, 60) / \\mathrm{close}."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div, ts_slope

__alpha_meta__ = {
    'id': 'qlib158_beta60',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{Slope}(\\\\mathrm{close}, 60) / \\\\mathrm{close}',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 BETA60 on the supplied OHLCV panel."""
    c = panel['close']
    return safe_div(ts_slope(c, 60), c)
