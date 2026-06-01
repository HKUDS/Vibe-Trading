# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
"""qlib158 BETA30: formula = (\\mathrm{close}_t - \\mathrm{close}_{{t-30}}) / (30\\,\\mathrm{close})."""
from __future__ import annotations

import pandas as pd
from src.factors.base import safe_div, delta

__alpha_meta__ = {
    'id': 'qlib158_beta30',
    'theme': ['momentum'],
    'formula_latex': '(\\\\mathrm{close}_t - \\\\mathrm{close}_{{t-30}}) / (30\\\\,\\\\mathrm{close})',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 30,
    'min_warmup_bars': 30,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 BETA30 on the supplied OHLCV panel."""
    c = panel['close']
    return safe_div(delta(c, 30), c) / float(30)
