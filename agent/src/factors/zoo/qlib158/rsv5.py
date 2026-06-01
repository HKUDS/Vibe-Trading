# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
"""qlib158 RSV5: formula = (\\mathrm{close} - \\mathrm{ts\\_min}(\\mathrm{low}, 5)) / (\\mathrm{ts\\_max}(\\mathrm{high}, 5) - \\mathrm{ts\\_min}(\\mathrm{low}, 5))."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div, ts_max, ts_min

__alpha_meta__ = {
    'id': 'qlib158_rsv5',
    'theme': ['momentum'],
    'formula_latex': '(\\\\mathrm{close} - \\\\mathrm{ts\\\\_min}(\\\\mathrm{low}, 5)) / (\\\\mathrm{ts\\\\_max}(\\\\mathrm{high}, 5) - \\\\mathrm{ts\\\\_min}(\\\\mathrm{low}, 5))',
    'columns_required': ['high', 'low', 'close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 5,
    'min_warmup_bars': 5,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 RSV5 on the supplied OHLCV panel."""
    c = panel['close']
    h = panel['high']
    lo = panel['low']
    hh = ts_max(h, 5)
    ll = ts_min(lo, 5)
    return safe_div(c - ll, hh - ll)
