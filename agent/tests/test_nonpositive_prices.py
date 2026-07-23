"""allow_nonpositive_prices: open on negative-price bars, still reject zero.

Markets like European day-ahead power clear negative routinely. The default
(flag off) still drops/rejects any non-positive price, so nothing changes for
existing markets; when the flag is on, negative prices flow through and only an
exactly-zero price is rejected (size = notional / price and margin are
undefined at zero, but well-defined for negatives via abs()).

Fixture `fixtures/negative_close_bars.csv` holds the five real bars from a
2025 NO2/DE-LU window whose close is non-positive (four negative, one exactly
zero). Source: ENTSO-E via Energy-Charts (Fraunhofer ISE),
Bundesnetzagentur | SMARD.de, CC BY 4.0.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.engines.base import BaseEngine
from backtest.loaders.base import validate_ohlc

FIXTURE = Path(__file__).parent / "fixtures" / "negative_close_bars.csv"


def _negative_close_frame() -> pd.DataFrame:
    df = pd.read_csv(FIXTURE, comment="#")
    df.index = pd.to_datetime(df.pop("trade_date"))
    df.index.name = "trade_date"
    return df


# ---------------------------------------------------------------------------
# loader: validate_ohlc positivity gate
# ---------------------------------------------------------------------------


def test_default_drops_every_nonpositive_bar() -> None:
    """Unchanged behavior: with the flag off, all five non-positive-close bars
    (and their sub-zero lows) are dropped."""
    frame = _negative_close_frame()
    assert len(frame) == 5
    cleaned = validate_ohlc(frame)
    assert cleaned.empty


def test_allow_keeps_negatives_rejects_exact_zero() -> None:
    """With the flag on, the four negative-close bars survive and only the
    exactly-zero close (DELU 2025-10-26) is dropped — structural invariants
    (high brackets low/open/close) still hold for all five real bars."""
    frame = _negative_close_frame()
    cleaned = validate_ohlc(frame, allow_nonpositive_prices=True)
    assert len(cleaned) == 4
    kept_closes = sorted(round(c, 2) for c in cleaned["close"])
    assert kept_closes == [-1.03, -0.09, -0.09, -0.02]
    assert 0.0 not in list(cleaned["close"])


def test_why_loader_drops_exact_zero_inf_downstream() -> None:
    """Pins *why* an exact-zero close is dropped at the loader, not kept.

    Both the benchmark (``benchmark.py``) and the position simulation
    (``engines/base.py``) compute per-bar returns as
    ``close.pct_change().fillna(0.0)`` over a *raw* close series. If a ``0.00``
    clear survived into that series, the bar *after* it divides by zero and
    yields ``inf`` — and ``fillna(0.0)`` does not neutralize it (it fills NaN,
    not inf), so the benchmark's ``(1 + r).prod()`` collapses to ``nan``.

    Negatives divide cleanly (engine sizing uses ``abs(price)``), so they are
    kept; exact zero is genuinely undefined and is therefore rejected at the
    loader *and* the engine. This test encodes that contract so the asymmetry
    is not silently "fixed" by later relaxing the loader. See #571.
    """
    idx = pd.to_datetime(["2025-10-24", "2025-10-25", "2025-10-26", "2025-10-27"])

    # If the loader had KEPT the 0.00 close, the raw return series blows up.
    kept = pd.Series([42.0, -1.03, 0.00, 42.0], index=idx)
    ret_if_kept = kept.pct_change().fillna(0.0)  # the exact downstream expression
    assert np.isinf(ret_if_kept.iloc[-1])                       # 0.00 -> inf next bar
    with np.errstate(invalid="ignore"):  # the nan-from-inf is the point, not a bug
        bench_total = float((1 + ret_if_kept).prod())
    assert not np.isfinite(bench_total)                         # benchmark total -> nan

    # The loader drops the exact-zero bar, so the surviving series is inf-free.
    frame = pd.DataFrame(
        {
            "open": kept,
            "high": kept.abs() + 1.0,
            "low": kept - 1.0,
            "close": kept,
        },
        index=idx,
    )
    cleaned = validate_ohlc(frame, allow_nonpositive_prices=True)
    assert 0.0 not in list(cleaned["close"])                    # zero bar removed
    safe_ret = cleaned["close"].pct_change().fillna(0.0)
    assert np.isfinite(safe_ret.to_numpy()).all()               # negatives stay finite


def test_allow_still_enforces_structural_invariants() -> None:
    """The flag relaxes only positivity, never the OHLC bracket invariants."""
    frame = pd.DataFrame(
        [(-5.0, -1.0, -8.0, -12.0, 0.0)],  # close -12 < low -8 -> invalid bracket
        columns=["open", "high", "low", "close", "volume"],
        index=pd.to_datetime(["2025-10-04"]),
    )
    assert validate_ohlc(frame, allow_nonpositive_prices=True).empty


# ---------------------------------------------------------------------------
# engine: opening / sizing / margin / pnl through zero
# ---------------------------------------------------------------------------


class _PlainEngine(BaseEngine):
    """Minimal concrete engine: identity slippage/rounding, zero commission,
    all trades allowed — isolates BaseEngine's price handling."""

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        return raw_size

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        return 0.0

    def apply_slippage(self, price: float, direction: int) -> float:
        return price


def _engine(*, allow: bool) -> _PlainEngine:
    return _PlainEngine({"initial_cash": 1_000_000, "allow_nonpositive_prices": allow})


def _bar_df(open_px: float, ts: str = "2025-10-04") -> tuple[pd.DataFrame, pd.Timestamp]:
    idx = pd.to_datetime([ts])
    df = pd.DataFrame(
        {"open": [open_px], "high": [max(open_px, 1.0)], "low": [open_px], "close": [open_px]},
        index=idx,
    )
    return df, idx[0]


def test_opens_on_negative_price_bar_when_allowed() -> None:
    eng = _engine(allow=True)
    df, ts = _bar_df(-5.0)  # DELU 2025-10-04 opened at -0.01; use -5 for headroom
    order = eng._plan_open_order("POWER-DA-DELU", 0.5, df, ts, equity=1_000_000)
    assert order is not None
    assert order.direction == 1
    # Size is a positive magnitude despite the negative price (abs-based).
    assert order.size == pytest.approx(0.5 * 1_000_000 / 5.0)
    # Margin (collateral) is positive, not negated by the negative price.
    assert order.margin == pytest.approx(order.size * 5.0)
    assert order.cost > 0


def test_default_still_rejects_negative_open() -> None:
    eng = _engine(allow=False)
    df, ts = _bar_df(-5.0)
    assert eng._plan_open_order("POWER-DA-DELU", 0.5, df, ts, equity=1_000_000) is None


def test_zero_price_rejected_even_when_allowed() -> None:
    """DELU 2025-10-26 cleared at exactly 0 — undefined sizing, always rejected."""
    eng = _engine(allow=True)
    df, ts = _bar_df(0.0)
    assert eng._plan_open_order("POWER-DA-DELU", 0.5, df, ts, equity=1_000_000) is None


def test_margin_and_pnl_well_defined_through_zero() -> None:
    """Collateral positive at a negative entry; PnL correct crossing zero."""
    eng = _engine(allow=True)
    size = 1_000.0
    margin = eng._calc_margin("POWER-DA-DELU", size, price=-5.0, leverage=1.0)
    assert margin == pytest.approx(5_000.0)  # abs(price), positive collateral

    # Long from -5 to +3: gains the full 8 EUR/MWh move.
    long_pnl = eng._calc_pnl("POWER-DA-DELU", 1, size, entry_price=-5.0, exit_price=3.0)
    assert long_pnl == pytest.approx(size * 8.0)
    # Short from -5 to -8 (price falls further negative): profits.
    short_pnl = eng._calc_pnl("POWER-DA-DELU", -1, size, entry_price=-5.0, exit_price=-8.0)
    assert short_pnl == pytest.approx(size * 3.0)


def test_raw_size_positive_for_negative_price() -> None:
    eng = _engine(allow=True)
    size = eng._calc_raw_size("POWER-DA-DELU", target_notional=500_000.0, price=-5.0)
    assert size == pytest.approx(100_000.0)  # not -100_000
