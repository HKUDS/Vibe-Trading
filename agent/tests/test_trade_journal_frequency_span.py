"""Trade frequency uses the elapsed span, not a truncated day count."""

from __future__ import annotations

from src.tools.trade_journal_parsers import TradeRecord, records_to_dataframe
from src.tools.trade_journal_tool import _compute_profile


def _rec(dt: str) -> TradeRecord:
    return TradeRecord(
        datetime=dt,
        symbol="0700.HK",
        name="",
        side="buy",
        quantity=100,
        price=300.0,
        amount=30_000.0,
        fee=0.0,
        market="other",
    )


def test_frequency_uses_the_fractional_span() -> None:
    # Monday 09:30 through Wednesday 21:30 is 2.5 days. Truncating to 2 days
    # reported 7.0 trades/week for these two fills; the elapsed span is 5.6.
    df = records_to_dataframe([
        _rec("2026-01-05 09:30:00"),
        _rec("2026-01-07 21:30:00"),
    ])
    assert _compute_profile(df)["trade_frequency_per_week"] == 5.6


def test_a_same_timestamp_journal_does_not_divide_by_zero() -> None:
    df = records_to_dataframe([
        _rec("2026-01-05 09:30:00"),
        _rec("2026-01-05 09:30:00"),
    ])
    assert _compute_profile(df)["trade_frequency_per_week"] == 14.0
