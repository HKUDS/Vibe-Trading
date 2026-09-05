"""FIFO short lots (#16) and corporate-action caliber restatement (#15).

Short sales used to vanish: the queue only modelled buy-first, so a sell
with no open long was skipped and the later cover queued as a phantom long
lot that poisoned every later match. And a split between buy and sell
fabricated a large fake loss, with cash dividends never entering fills.
"""

from __future__ import annotations

import pandas as pd

from src.tools.trade_journal_tool import build_frame_adjust, pair_trades_fifo


def _df(rows: list[tuple]) -> pd.DataFrame:
    frame = pd.DataFrame(
        rows,
        columns=["datetime", "symbol", "name", "side", "quantity", "price", "amount", "fee"],
    )
    return frame


def test_short_sale_and_cover_is_a_roundtrip_not_a_phantom_long() -> None:
    df = _df([
        ("2026-01-02 09:30:00", "AAPL.US", "Apple", "sell", 10.0, 100.0, 1000.0, 1.0),
        ("2026-01-05 09:30:00", "AAPL.US", "Apple", "buy", 10.0, 90.0, 900.0, 1.0),
    ])
    rts = pair_trades_fifo(df)
    assert len(rts) == 1
    rt = rts[0]
    assert rt["side"] == "short"
    # (100 - 90) * 10 - fees
    assert rt["pnl"] == 98.0
    assert rt["hold_days"] == 3.0


def test_cover_after_long_and_short_keeps_books_separate() -> None:
    df = _df([
        ("2026-01-02 09:30:00", "AAPL.US", "Apple", "buy", 5.0, 50.0, 250.0, 0.0),
        ("2026-01-03 09:30:00", "AAPL.US", "Apple", "sell", 10.0, 100.0, 1000.0, 0.0),
        ("2026-01-04 09:30:00", "AAPL.US", "Apple", "buy", 10.0, 90.0, 900.0, 0.0),
    ])
    rts = pair_trades_fifo(df)
    # 5-share long closed at 100, then a 5-share short covered at 90.
    assert len(rts) == 2
    assert rts[0]["side"] == "long" and rts[0]["pnl"] == 250.0
    assert rts[1]["side"] == "short" and rts[1]["pnl"] == 50.0


def _frames() -> dict[str, pd.DataFrame]:
    # 1:2 split between 2026-01-03 and 2026-01-06: the adjusted close halves
    # on the first post-split bar, so the factor from pre to post is 0.5.
    idx = pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-06"])
    return {"AAPL.US": pd.DataFrame({"close": [100.0, 100.0, 50.0]}, index=idx)}


def test_split_between_legs_no_longer_fabricates_a_loss() -> None:
    df = _df([
        ("2026-01-03 09:30:00", "AAPL.US", "Apple", "buy", 10.0, 100.0, 1000.0, 0.0),
        ("2026-01-06 09:30:00", "AAPL.US", "Apple", "sell", 20.0, 50.0, 1000.0, 0.0),
    ])
    raw = pair_trades_fifo(df)
    assert raw[0]["pnl"] == -500.0  # the fake loss this issue is about

    adjusted = pair_trades_fifo(df, adjust=build_frame_adjust(_frames()))
    # Buy leg restated to the post-split caliber: 100 * 0.5 = 50, pnl = 0.
    assert adjusted[0]["pnl"] == 0.0


def test_uncovered_symbol_stays_raw() -> None:
    df = _df([
        ("2026-01-03 09:30:00", "MSFT.US", "Microsoft", "buy", 10.0, 100.0, 1000.0, 0.0),
        ("2026-01-06 09:30:00", "MSFT.US", "Microsoft", "sell", 10.0, 50.0, 500.0, 0.0),
    ])
    rts = pair_trades_fifo(df, adjust=build_frame_adjust({}))
    assert rts[0]["pnl"] == -500.0


def test_split_between_legs_of_a_short_mirrors_the_long_case() -> None:
    """A short across a 1:2 split must net to zero, exactly like the long.

    The original short branch divided the entry price by the factor instead of
    multiplying (and never restated the share count), so the same split that
    nets a long to zero booked the short at +1500.
    """
    short_df = _df([
        ("2026-01-03 09:30:00", "AAPL.US", "Apple", "sell", 10.0, 100.0, 1000.0, 0.0),
        ("2026-01-06 09:30:00", "AAPL.US", "Apple", "buy", 20.0, 50.0, 1000.0, 0.0),
    ])
    long_df = _df([
        ("2026-01-03 09:30:00", "AAPL.US", "Apple", "buy", 10.0, 100.0, 1000.0, 0.0),
        ("2026-01-06 09:30:00", "AAPL.US", "Apple", "sell", 20.0, 50.0, 1000.0, 0.0),
    ])
    adjust = build_frame_adjust(_frames())

    short_rt = pair_trades_fifo(short_df, adjust=adjust)[0]
    long_rt = pair_trades_fifo(long_df, adjust=adjust)[0]

    assert short_rt["side"] == "short"
    assert short_rt["pnl"] == 0.0
    assert short_rt["pnl"] == long_rt["pnl"]
    # The cover consumes the whole restated position, not half of it.
    assert short_rt["qty"] == 20.0
    assert short_rt["qty"] == long_rt["qty"]


def test_short_without_adjust_is_unchanged() -> None:
    """No adjuster: the short stays on raw prices, byte-for-byte legacy."""
    df = _df([
        ("2026-01-03 09:30:00", "AAPL.US", "Apple", "sell", 10.0, 100.0, 1000.0, 0.0),
        ("2026-01-06 09:30:00", "AAPL.US", "Apple", "buy", 10.0, 80.0, 800.0, 0.0),
    ])
    rt = pair_trades_fifo(df)[0]
    assert rt["side"] == "short"
    assert rt["pnl"] == 200.0  # (100 - 80) * 10


def test_dividend_rows_do_not_open_or_close_positions() -> None:
    """A dividend cash row between the legs leaves the roundtrip untouched."""
    df = _df([
        ("2026-01-02 09:30:00", "AAPL.US", "Apple", "buy", 10.0, 100.0, 1000.0, 0.0),
        ("2026-01-03 09:30:00", "AAPL.US", "Apple", "dividend", 0.0, 0.0, 25.0, 0.0),
        ("2026-01-05 09:30:00", "AAPL.US", "Apple", "sell", 10.0, 110.0, 1100.0, 0.0),
    ])
    rts = pair_trades_fifo(df)
    assert len(rts) == 1
    assert rts[0]["side"] == "long"
    assert rts[0]["pnl"] == 100.0  # (110 - 100) * 10


def test_dividend_row_does_not_cover_an_open_short() -> None:
    df = _df([
        ("2026-01-02 09:30:00", "AAPL.US", "Apple", "sell", 10.0, 100.0, 1000.0, 0.0),
        ("2026-01-03 09:30:00", "AAPL.US", "Apple", "dividend", 0.0, 0.0, 25.0, 0.0),
        ("2026-01-05 09:30:00", "AAPL.US", "Apple", "buy", 10.0, 90.0, 900.0, 0.0),
    ])
    rts = pair_trades_fifo(df)
    assert len(rts) == 1
    assert rts[0]["side"] == "short"
    assert rts[0]["pnl"] == 100.0  # (100 - 90) * 10


def test_dividend_only_journal_yields_no_roundtrips() -> None:
    df = _df([
        ("2026-01-03 09:30:00", "AAPL.US", "Apple", "dividend", 0.0, 0.0, 25.0, 0.0),
    ])
    assert pair_trades_fifo(df) == []
