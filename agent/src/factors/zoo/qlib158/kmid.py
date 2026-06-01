# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
"""qlib158 KMID: formula = (\\mathrm{close} - \\mathrm{open}) / \\mathrm{open}."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div

__alpha_meta__ = {
    'id': 'qlib158_kmid',
    'theme': ['microstructure'],
    'formula_latex': '(\\\\mathrm{close} - \\\\mathrm{open}) / \\\\mathrm{open}',
    'columns_required': ['open', 'close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 1,
    'min_warmup_bars': 1,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 KMID on the supplied OHLCV panel."""
    o = panel['open']
    c = panel['close']
    return safe_div(c - o, o)
