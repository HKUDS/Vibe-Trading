# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
"""qlib158 SUMP10: formula = \\sum \\max(\\Delta\\mathrm{close}, 0) / \\sum |\\Delta\\mathrm{close}|."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div

__alpha_meta__ = {
    'id': 'qlib158_sump10',
    'theme': ['reversal'],
    'formula_latex': '\\\\sum \\\\max(\\\\Delta\\\\mathrm{close}, 0) / \\\\sum |\\\\Delta\\\\mathrm{close}|',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 SUMP10 on the supplied OHLCV panel."""
    c = panel['close']
    diff = c - c.shift(1)
    pos = diff.where(diff > 0, 0.0)
    absd = diff.abs()
    num = pos.rolling(window=10, min_periods=10).sum()
    den = absd.rolling(window=10, min_periods=10).sum()
    return safe_div(num, den)
