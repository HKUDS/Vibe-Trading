"""GTJA Alpha 122 (国泰君安 191 短周期交易型 alpha 因子, 2014).

Formula (verbatim from the report):
    (SMA(SMA(SMA(LOG(CLOSE),13,2),13,2),13,2)-DELAY(...,1))/DELAY(...,1)

Notes: Triple SMA of log close.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import (
    decay_linear,
    delta,
    rank,
    safe_div,
    scale,
    signed_power,
    ts_argmax,
    ts_argmin,
    ts_corr,
    ts_cov,
    ts_max,
    ts_mean,
    ts_min,
    ts_rank,
    ts_std,
)

ALPHA_ID = "gtja191_122"

__alpha_meta__ = {
    'id': 'gtja191_122',
    'theme': ['momentum'],
    'formula_latex': 'see body',
    'columns_required': ['close'],
    'extras_required': [],
    'universe': ['equity_cn'],
    'frequency': ['1d'],
    'decay_horizon': 13,
    'min_warmup_bars': 40,
    'notes': 'Triple SMA of log close.',
}


def compute(panel):
    """Compute gtja191_122.

    Args:
        panel: dict[str, pd.DataFrame] with at least the required columns.

    Returns:
        pd.DataFrame with index = panel["close"].index, columns = panel["close"].columns.
    """
    def _sma(x, n, m):
        """SMA(x, n, m) per GTJA convention -> ewm with alpha = m/n."""
        return x.ewm(alpha=m / n, adjust=False).mean()
    c = panel["close"]
    s = _sma(_sma(_sma(np.log(c), 13, 2), 13, 2), 13, 2)
    out = safe_div(s - s.shift(1), s.shift(1))
    return out
