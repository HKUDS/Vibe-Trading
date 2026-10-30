"""A-share buy orders follow each board's order-size grid.

The STAR Market (688xxx, 689xxx CDRs) accepts a buy of at least 200 shares and
the Beijing exchange at least 100, each then in 1-share steps. The main board
and ChiNext trade 100-share lots.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.china_a import ChinaAEngine
from backtest.engines.composite import CompositeEngine


def _rounded(symbol: str, raw: float) -> float:
    engine = ChinaAEngine({"initial_cash": 1_000_000})
    engine._active_symbol = symbol
    return engine.round_size(raw, 10.0)


@pytest.mark.parametrize(
    ("symbol", "raw", "expected"),
    [
        ("688256.SH", 199.9, 0),  # STAR Market: below the 200-share minimum
        ("688256.SH", 200.0, 200),
        ("688256.SH", 253.7, 253),  # then 1-share steps
        ("689009.SH", 253.7, 253),  # STAR Market CDR
        ("920002.BJ", 99.9, 0),  # Beijing: below the 100-share minimum
        ("920002.BJ", 153.7, 153),
        ("830799.BJ", 153.7, 153),  # Beijing legacy 8xxxxx code
        ("600519.SH", 253.7, 200),  # main board: 100-share lots
        ("300750.SZ", 253.7, 200),  # ChiNext: 100-share lots
    ],
)
def test_round_size_follows_the_board_grid(
    symbol: str, raw: float, expected: int
) -> None:
    assert _rounded(symbol, raw) == expected


def test_negative_size_clamps_to_zero_on_one_share_boards() -> None:
    assert _rounded("688256.SH", -250.0) == 0
    assert _rounded("920002.BJ", -150.0) == 0


def _opened(symbol: str, price: float, weight: float, initial_cash: float) -> float:
    """Shares opened through the engine's own sizing path."""
    engine = ChinaAEngine({"initial_cash": initial_cash})
    dates = pd.date_range("2026-01-05", periods=2, freq="B")
    close = pd.DataFrame({symbol: [price, price]}, index=dates)
    data_map = {symbol: pd.DataFrame({"open": close[symbol], "close": close[symbol]})}
    weights = pd.DataFrame({symbol: [0.0, weight]}, index=dates)
    engine._execute_bars(dates, data_map, close, weights, [symbol])
    opens = [fill for fill in engine.fill_records if fill.action == "open"]
    return sum(abs(fill.signed_quantity) for fill in opens)


def test_star_buy_below_200_shares_is_not_filled() -> None:
    # 200,000 at 1,300 plus slippage buys about 153 shares: a legal 100-share
    # lot on the main board, but below the STAR Market's 200-share minimum.
    assert _opened("688256.SH", 1_300.0, 1.0, 200_000) == 0


def test_star_buy_fills_in_one_share_steps() -> None:
    # 100,000 at 80 plus 0.1% slippage is 1,248.75 shares.
    assert _opened("688256.SH", 80.0, 0.1, 1_000_000) == 1_248
    # The same order on the main board rounds down to a 100-share lot.
    assert _opened("600519.SH", 80.0, 0.1, 1_000_000) == 1_200


def test_composite_sizes_star_symbols_on_the_star_grid() -> None:
    engine = CompositeEngine({}, ["688256.SH", "600519.SH"])
    engine._active_symbol = "688256.SH"
    assert engine.round_size(253.7, 10.0) == 253
    engine._active_symbol = "600519.SH"
    assert engine.round_size(253.7, 10.0) == 200
