# Adapted from microsoft/qlib@d5379c520f66a39953bad76234a7019a72796fd0:qlib/contrib/data/handler.py
# (Apache-2.0). Copyright (c) Microsoft Corporation.
"""qlib158 RANK10: formula = \\mathrm{ts\\_rank}(\\mathrm{close}, 10)."""
from __future__ import annotations

import pandas as pd
from src.factors.base import ts_rank, rank

__alpha_meta__ = {
    'id': 'qlib158_rank10',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{ts\\\\_rank}(\\\\mathrm{close}, 10)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 RANK10 on the supplied OHLCV panel."""
    c = panel['close']
    return ts_rank(c, 10)
