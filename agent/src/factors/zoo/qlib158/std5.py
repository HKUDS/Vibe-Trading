# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
"""qlib158 STD5: formula = \\mathrm{ts\\_std}(\\mathrm{close}, 5) / \\mathrm{close}."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div, ts_std

__alpha_meta__ = {
    'id': 'qlib158_std5',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{ts\\\\_std}(\\\\mathrm{close}, 5) / \\\\mathrm{close}',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 5,
    'min_warmup_bars': 5,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 STD5 on the supplied OHLCV panel."""
    c = panel['close']
    return safe_div(ts_std(c, 5), c)
