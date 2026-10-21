"""Equal timestamps must retain source order before FIFO pairing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools.trade_journal_parsers import TradeRecord, records_to_dataframe
from src.tools.trade_journal_tool import analyze_trade_journal


@pytest.mark.parametrize("pattern", ["equal", "groups", "interleaved"])
def test_timestamp_sort_keeps_each_groups_source_order(pattern: str) -> None:
    records = []
    for i in range(20):
        day = (
            1 if pattern == "equal" else (i // 10 if pattern == "groups" else i % 2) + 1
        )
        records.append(
            TradeRecord(
                datetime=f"2026-01-{day:02d} 10:00:00",
                symbol="AAPL",
                name=str(i),
                side="buy",
                quantity=1,
                price=100 + i,
                amount=100 + i,
                fee=1,
                market="us",
            )
        )

    # Python's stable sort supplies an independent ordering oracle.
    expected = [r.name for r in sorted(records, key=lambda r: r.datetime)]
    frame = records_to_dataframe(records)
    assert frame["name"].tolist() == expected
    assert frame["datetime"].is_monotonic_increasing
    assert frame.index.tolist() == list(range(20))


@pytest.mark.parametrize("short_first", [False, True])
@pytest.mark.parametrize("date_only", [False, True])
def test_csv_ties_do_not_turn_winning_pairs_into_losers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, short_first: bool, date_only: bool
) -> None:
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_FILE_ROOTS", str(tmp_path))
    legs = (
        [("sell", 100), ("buy", 95), ("sell", 90), ("buy", 80)]
        if short_first
        else [("buy", 100), ("sell", 105), ("buy", 110), ("sell", 120)]
    )
    timestamp = "2026-01-01" if date_only else "2026-01-01 10:00:00"
    rows = [f"{timestamp},AAPL,{side},1,{price},1" for side, price in legs * 5]
    path = tmp_path / "journal.csv"
    path.write_text(
        ("date" if date_only else "datetime")
        + ",symbol,side,quantity,price,fee\n"
        + "\n".join(rows)
        + "\n",
        encoding="utf-8",
    )

    result = json.loads(analyze_trade_journal(str(path), "profile"))
    assert result["status"] == "ok"
    profile = result["profile"]
    # Each source pair earns (5 - 2)=3 or (10 - 2)=8, repeated five times.
    assert profile["total_roundtrips"] == 10
    assert profile["total_pnl"] == 55
    assert profile["win_rate"] == 1.0
    assert profile["profit_loss_ratio"] is None  # No losses; strict JSON.
    assert [rt["pnl"] for rt in profile["roundtrips_sample"]] == [3, 8, 3, 8, 3]
    assert {rt["side"] for rt in profile["roundtrips_sample"]} == {
        "short" if short_first else "long"
    }
