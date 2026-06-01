"""GTJA Alpha #6.

Formula: (RANK(SIGN(DELTA((OPEN*0.85+HIGH*0.15), 4))) * -1)
Source: 国泰君安 191 alpha 研报 (2014), alpha 6."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import (
    decay_linear,
    delta,
    rank,
    safe_div,
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

__alpha_meta__ = {
    "id": "gtja191_006",
    "theme": ['reversal'],
    "formula_latex": '(RANK(SIGN(DELTA((OPEN*0.85+HIGH*0.15), 4))) * -1)',
    "columns_required": ['open', 'high'],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 4,
    "min_warmup_bars": 5,
    "notes": 'Sign of 4d change of weighted price; cross-sectionally ranked, negated.',
}

def compute(panel: dict) -> pd.DataFrame:
    o = panel["open"]
    h = panel["high"]
    x = o * 0.85 + h * 0.15
    return -1.0 * rank(np.sign(delta(x, 4)))
