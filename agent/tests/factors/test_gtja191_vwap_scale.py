"""GTJA alphas that need VWAP must read it through ``base.vwap``.

Tushare's A-share ``amount`` is in thousand CNY and ``vol`` in lots of 100
shares, so ``amount / (vol * 100)`` is 1/1000 of the traded price. A VWAP
mixed with OPEN/LOW/CLOSE at that scale gives a different factor value.
"""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest

_ALPHAS = (
    "007", "008", "012", "013", "016", "017", "026", "036", "039", "041",
    "044", "045", "061", "064", "073", "074", "077", "087", "090", "092",
)


def _panels(n: int = 120) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2024-01-01", periods=n)
    cols = ["A", "B", "C", "D", "E", "F"]
    close = pd.DataFrame(20 + rng.normal(0, 0.5, (n, 6)).cumsum(axis=0), index=idx, columns=cols)
    open_ = close.shift(1).fillna(close) + rng.normal(0, 0.1, (n, 6))
    high = np.maximum(open_, close) + rng.uniform(0.05, 0.4, (n, 6))
    low = np.minimum(open_, close) - rng.uniform(0.05, 0.4, (n, 6))
    price = low + (high - low) * rng.uniform(0.2, 0.8, (n, 6))
    # Large lot counts keep the helper's +1 suspended-bar guard negligible.
    lots = pd.DataFrame(rng.uniform(1e8, 5e8, (n, 6)), index=idx, columns=cols)
    base = {"open": open_, "high": high, "low": low, "close": close, "volume": lots}
    tushare = {**base, "amount": price * lots * 100.0 / 1000.0}
    explicit = {**base, "amount": pd.DataFrame(np.nan, index=idx, columns=cols), "vwap": price}
    return tushare, explicit


@pytest.mark.parametrize("alpha", _ALPHAS)
def test_vwap_from_tushare_units_matches_the_traded_price(alpha):
    module = importlib.import_module(f"src.factors.zoo.gtja191.alpha_{alpha}")
    tushare, explicit = _panels(400 if alpha in {"026", "039", "045", "092"} else 120)

    got = module.compute(tushare)
    expected = module.compute(explicit)

    assert expected.iloc[-10:].notna().any().any()
    pd.testing.assert_frame_equal(got, expected, check_exact=False, rtol=1e-5, atol=1e-8)
