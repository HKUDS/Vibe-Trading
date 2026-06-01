# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
"""qlib158 KLEN: formula = (\\mathrm{high} - \\mathrm{low}) / \\mathrm{open}."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div

__alpha_meta__ = {
    'id': 'qlib158_klen',
    'theme': ['microstructure'],
    'formula_latex': '(\\\\mathrm{high} - \\\\mathrm{low}) / \\\\mathrm{open}',
    'columns_required': ['open', 'high', 'low'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 1,
    'min_warmup_bars': 1,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 KLEN on the supplied OHLCV panel."""
    o = panel['open']
    h = panel['high']
    lo = panel['low']
    return safe_div(h - lo, o)
