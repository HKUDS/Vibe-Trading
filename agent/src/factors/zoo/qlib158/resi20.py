# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: 残差 20日
# 简要说明: Resi(close, 20) / close，最新收盘价相对20日线性回归拟合值的残差。
# 典型用途: 衡量价格偏离趋势线的程度，用于均值回复策略。
# ============================================================
"""qlib158 RESI20: formula = \\mathrm{Resi}(\\mathrm{close}, 20) / \\mathrm{close}."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div, ts_resi

__alpha_meta__ = {
    'id': 'qlib158_resi20',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{Resi}(\\\\mathrm{close}, 20) / \\\\mathrm{close}',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 20,
    'min_warmup_bars': 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 RESI20 on the supplied OHLCV panel."""
    c = panel['close']
    return safe_div(ts_resi(c, 20), c)
