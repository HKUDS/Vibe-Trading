# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
"""qlib158 CNTN20: formula = \\mathrm{rolling\\_mean}(\\mathrm{1}[\\mathrm{close}<\\mathrm{close}_{{-1}}], 20)."""
from __future__ import annotations

import pandas as pd

__alpha_meta__ = {
    'id': 'qlib158_cntn20',
    'theme': ['reversal'],
    'formula_latex': '\\\\mathrm{rolling\\\\_mean}(\\\\mathrm{1}[\\\\mathrm{close}<\\\\mathrm{close}_{{-1}}], 20)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 20,
    'min_warmup_bars': 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 CNTN20 on the supplied OHLCV panel."""
    c = panel['close']
    dn = (c < c.shift(1)).astype('float64')
    return dn.rolling(window=20, min_periods=20).mean()
