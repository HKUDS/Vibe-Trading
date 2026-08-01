"""Regression test for pair_trades_fifo handling string datetime columns in trade_journal_tool.

Locks out a bug where pair_trades_fifo raised TypeError: unsupported operand type(s)
for -: 'str' and 'str' when df["datetime"] contained string timestamps instead of Timestamps.
"""

import pandas as pd
from src.tools.trade_journal_tool import pair_trades_fifo


def test_pair_trades_fifo_supports_string_datetime_column():
    """Prove that pair_trades_fifo handles string datetime values without raising TypeError."""
    df = pd.DataFrame([
        {
            "datetime": "2026-01-01 09:30:00",
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10.0,
            "price": 150.0,
            "fee": 1.0,
        },
        {
            "datetime": "2026-01-03 09:30:00",
            "symbol": "AAPL",
            "side": "sell",
            "quantity": 10.0,
            "price": 160.0,
            "fee": 1.0,
        },
    ])

    # On un-fixed code, subtracting string datetimes in pair_trades_fifo raised TypeError.
    # On fixed code, it correctly calculates roundtrip hold_days = 2.0 and pnl.
    rts = pair_trades_fifo(df)
    assert len(rts) == 1
    assert rts[0]["symbol"] == "AAPL"
    assert rts[0]["hold_days"] == 2.0
    assert rts[0]["pnl"] == 98.0
