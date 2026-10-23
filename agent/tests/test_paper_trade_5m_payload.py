"""T2 gate — malformed and zero-volume 5m payloads fail closed.

A payload that cannot be trusted must never become a tradable session.  Three
provider faults are refused as ``PAPER_DATA_NOT_READY``: a finer interval
(1m) served as 5m, an all-NaN continuous day, and a non-finite session.  A
zero-volume session is different: nothing traded, so the day is dropped and
the engine's existing halted path rejects orders ``suspended``.  A partial
5m session keeps the existing ``<48`` warning and still fills, and the
auction-only halt (no continuous bar, daily bar present) stays a halt.

Every case drives the public ``run_paper_trade_step`` surface with a fake
loader and calendar: one symbol, one cn_a day, no network.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd

from src.tools.paper_trade.tool import run_paper_trade_step

_DAY = "2026-10-20"
_PREV = "2026-10-19"
_SYM = "600519.SH"
_FEES = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.00001,
}


def _grid(start: str, step_minutes: int, count: int) -> list[str]:
    first = dt.datetime.fromisoformat(f"{_DAY}T{start}:00")
    return [(first + dt.timedelta(minutes=step_minutes * index)).strftime("%Y-%m-%d %H:%M") for index in range(count)]


def _session_labels() -> list[str]:
    """The 48 legitimate continuous labels: 09:35..11:30, 13:05..15:00."""
    return _grid("09:35", 5, 24) + _grid("13:05", 5, 24)


def _minute_labels() -> list[str]:
    """240 one-minute labels served as if they were 5m bars."""
    return _grid("09:31", 1, 120) + _grid("13:01", 1, 120)


def _intraday(
    labels: list[str], *, price: float = 10.0, volume: float = 120_000.0, all_nan: bool = False
) -> pd.DataFrame:
    records = [
        {
            "bar_time": label,
            "open": float("nan") if all_nan else price,
            "high": float("nan") if all_nan else price,
            "low": float("nan") if all_nan else price,
            "close": float("nan") if all_nan else price,
            "volume": volume,
        }
        for label in labels
    ]
    frame = pd.DataFrame(records)
    frame["bar_time"] = pd.to_datetime(frame["bar_time"])
    return frame.set_index("bar_time")


def _daily(close: float = 10.0) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {"trade_date": _PREV, "open": close, "high": close, "low": close, "close": close, "volume": 1_000.0},
            {"trade_date": _DAY, "open": close, "high": close, "low": close, "close": close, "volume": 1_000.0},
        ]
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


class _Loader:
    name = "fixture"

    def __init__(self, five_minute: pd.DataFrame, daily: pd.DataFrame | None = None) -> None:
        self._five_minute = five_minute
        self._daily = _daily() if daily is None else daily

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        five_minute = str(interval).lower() in ("5m", "5min", "5")
        frame = self._five_minute if five_minute else self._daily
        return {code: frame.copy() for code in codes if not frame.empty}


class _Calendar:
    def __init__(self, open_days: tuple[str, ...]) -> None:
        self._open = frozenset(open_days)

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": int(day.strftime("%Y-%m-%d") in self._open),
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _payload(orders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "account_id": "pa_5m_payload",
        "market": "cn_a",
        "account_state": {"cash": 1_000_000.0, "positions": []},
        "orders": [{"symbol": _SYM, "side": "buy", "qty": 100}] if orders is None else orders,
        "from_date": _DAY,
        "to_date": _DAY,
        "fee_model": dict(_FEES),
        "interval": "5m",
    }


def _run(loader: _Loader, orders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    document = run_paper_trade_step(
        _payload(orders),
        loader=loader,
        ch_client=None,
        calendar_client=_Calendar((_DAY,)),
        limits_client=None,
    )
    return json.loads(document)


def test_zero_volume_48_bar_session_is_halted_not_filled() -> None:
    loader = _Loader(_intraday(_session_labels(), volume=0.0))

    document = _run(loader)

    assert "status" not in document, document
    assert document["fills"] == []
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [(_SYM, "suspended")]
    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [(_SYM, "halted")]
    assert len(document["canceled_orders"]) == 1
    assert document["end_state"]["cash"] == 1_000_000.0
    assert any("zero-volume session; treated as halted" in warning for warning in document["warnings"])


def test_one_minute_payload_is_data_not_ready_not_a_session() -> None:
    loader = _Loader(_intraday(_minute_labels()))

    document = _run(loader)

    assert document["status"] == "error", document
    assert document["code"] == "PAPER_DATA_NOT_READY"
    assert "fills" not in document
    assert "could not be parsed" in document["message"]
    assert "halted" not in document["message"]


def test_all_nan_continuous_payload_is_data_not_ready() -> None:
    loader = _Loader(_intraday(_session_labels(), all_nan=True))

    document = _run(loader)

    assert document["status"] == "error", document
    assert document["code"] == "PAPER_DATA_NOT_READY"
    assert "fills" not in document
    assert "suspended" not in document["message"]
    assert "halted" not in document["message"]


def test_partial_5m_session_still_fills_with_coverage_warning() -> None:
    loader = _Loader(_intraday(_session_labels()[:30]))

    document = _run(loader)

    assert "status" not in document, document
    assert [(fill["symbol"], fill["side"], fill["qty"], fill["price"]) for fill in document["fills"]] == [
        (_SYM, "buy", 100.0, 10.0)
    ]
    assert document["rejected_orders"] == []
    assert document["events"] == []
    assert any("30/48 continuous bars" in warning for warning in document["warnings"])


def test_auction_only_symbol_with_a_daily_bar_is_still_halted() -> None:
    auction_only = _intraday(["2026-10-20 09:30"], price=10.0, volume=48_000.0)
    loader = _Loader(auction_only)

    document = _run(loader)

    assert "status" not in document, document
    assert document["fills"] == []
    assert [(row["symbol"], row["reason_code"]) for row in document["rejected_orders"]] == [(_SYM, "suspended")]
    assert [(row["symbol"], row["event_type"]) for row in document["events"]] == [(_SYM, "halted")]
    assert not any("zero-volume" in warning for warning in document["warnings"])
    assert not any("continuous bars;" in warning for warning in document["warnings"])
