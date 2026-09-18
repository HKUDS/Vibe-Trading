# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
# ============================================================
# 中文名称: 涨跌天数差 10日
# 简要说明: CNTP_10 - CNTN_10，10日内上涨天数与下跌天数之差。
# 典型用途: 综合衡量10日内的涨跌方向，正值表示多头天数占优。
# ============================================================
"""qlib158 CNTD10: formula = \\mathrm{CNTP}_10 - \\mathrm{CNTN}_10."""
from __future__ import annotations

import pandas as pd

__alpha_meta__ = {
    'id': 'qlib158_cntd10',
    'theme': ['reversal'],
    'formula_latex': '\\\\mathrm{CNTP}_10 - \\\\mathrm{CNTN}_10',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
    'notes': 'A missing close leaves window+1 rolling rows NaN; on sparse panels this can trigger the >95% NaN registry guard (from ~30% missing bars).',
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 CNTD10 on the supplied OHLCV panel."""
    c = panel['close']
    prev = c.shift(1)
    up = (c > prev).astype('float64').where(c.notna() & prev.notna())  # a missing close is not an up day
    dn = (c < prev).astype('float64').where(c.notna() & prev.notna())  # ...nor a down day
    up_w = up.rolling(window=10, min_periods=10).mean()
    dn_w = dn.rolling(window=10, min_periods=10).mean()
    return up_w - dn_w
