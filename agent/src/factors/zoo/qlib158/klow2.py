# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
"""qlib158 KLOW2: formula = (\\min(\\mathrm{open}, \\mathrm{close}) - \\mathrm{low}) / (\\mathrm{high} - \\mathrm{low})."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div

__alpha_meta__ = {
    'id': 'qlib158_klow2',
    'theme': ['microstructure'],
    'formula_latex': '(\\\\min(\\\\mathrm{open}, \\\\mathrm{close}) - \\\\mathrm{low}) / (\\\\mathrm{high} - \\\\mathrm{low})',
    'columns_required': ['open', 'high', 'low', 'close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 1,
    'min_warmup_bars': 1,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 KLOW2 on the supplied OHLCV panel."""
    o = panel['open']
    c = panel['close']
    h = panel['high']
    lo = panel['low']
    lower = o.where(o <= c, c)
    return safe_div(lower - lo, h - lo)
