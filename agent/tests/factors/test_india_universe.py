"""India (equity_in) factor-universe coverage against the bundled zoo.

Verifies that the ``equity_in`` universe was wired end-to-end:
  - Alpha101 (OHLCV-generic) and QLib158 (multi-market) factors are listed
    for ``equity_in``.
  - GTJA191 (China-scale, Tushare-specific) is NOT exposed for India.
  - A representative alpha computes cleanly on a synthetic NSE-shape panel
    whose ``vwap`` is built the India way (typical price, no Tushare scaling).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.factors.base import vwap
from src.factors.registry import Registry


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry()


def _india_panel(n_rows: int = 40, symbols=("RELIANCE.NS", "TCS.NS")) -> dict:
    """Synthetic NSE-shape OHLCV panel; vwap injected as India typical price."""
    rng = np.random.RandomState(7)
    idx = pd.bdate_range("2024-01-01", periods=n_rows)
    cols = list(symbols)
    close = pd.DataFrame(
        100.0 + np.cumsum(rng.randn(n_rows, len(cols)), axis=0), index=idx, columns=cols
    ).abs() + 1.0
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.DataFrame(
        np.maximum(close.to_numpy(), open_.to_numpy()) + rng.rand(n_rows, len(cols)),
        index=idx, columns=cols,
    )
    low = (
        pd.DataFrame(
            np.minimum(close.to_numpy(), open_.to_numpy()) - rng.rand(n_rows, len(cols)),
            index=idx, columns=cols,
        ).abs()
        + 0.01
    )
    volume = pd.DataFrame(
        rng.randint(1_000, 100_000, size=(n_rows, len(cols))).astype(float),
        index=idx, columns=cols,
    )
    panel = {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    panel["vwap"] = vwap(panel, "equity_in")  # typical price; no amount needed
    return panel


def test_alpha101_and_qlib158_listed_for_india(registry: Registry) -> None:
    listed = set(registry.list(universe="equity_in"))
    assert sum(a.startswith("alpha101_") for a in listed) == 101
    assert sum(a.startswith("qlib158_") for a in listed) == 154


def test_china_scale_gtja191_not_listed_for_india(registry: Registry) -> None:
    listed = set(registry.list(universe="equity_in"))
    assert not any(a.startswith("gtja191_") for a in listed)


def test_india_vwap_uses_typical_price() -> None:
    panel = _india_panel()
    expected = (panel["open"] + panel["high"] + panel["low"] + panel["close"]) / 4.0
    pd.testing.assert_frame_equal(panel["vwap"], expected)


@pytest.mark.parametrize("alpha_id", ["alpha101_001", "alpha101_054", "qlib158_kmid"])
def test_representative_factor_computes_on_india_panel(
    registry: Registry, alpha_id: str
) -> None:
    listed = set(registry.list(universe="equity_in"))
    assert alpha_id in listed
    out = registry.compute(alpha_id, _india_panel())
    assert out.shape[1] == 2  # two NSE symbols
    assert np.isfinite(out.to_numpy()[~pd.isna(out.to_numpy())]).all()
