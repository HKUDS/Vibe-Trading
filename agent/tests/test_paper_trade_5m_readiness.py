"""B2 gate: a 5m pure-valuation step fails closed on a missing target bar.

A step with no orders issues no 5m request, so its NAV comes from the daily
leg and its readiness is the interval="1d" contract: at least one served
symbol must carry the target daily bar.  Without it the step returns the same
``PAPER_DATA_NOT_READY`` material instead of advancing NAV on a stale frame.
Offline: fake loader / calendar only, never the network.
"""

from __future__ import annotations

import pandas as pd

from src.tools.paper_trade import engine
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import parse_request

_DAY = "2026-10-20"
_PREV = "2026-10-19"
_SYM = "600519.SH"


class FakeChClient:
    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.name = "tencent"
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self._frames[code] for code in codes if code in self._frames}


class FakeCalendarClient:
    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {"exchange": "SSE", "cal_date": day.strftime("%Y-%m-%d"), "is_open": 1,
             "pretrade_date": ""}
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    records = [
        {"trade_date": day, "open": close, "high": close, "low": close,
         "close": close, "volume": 1000.0}
        for day, close in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


def _valuation(interval: str, rows: list[tuple[str, float]]):
    market_data = fetch_market_data(
        "cn_a", [_SYM], _DAY, _DAY,
        loader=FakeLoader({_SYM: _frame(rows)}), ch_client=FakeChClient(),
        interval=interval,
        five_minute_symbols=() if interval == "5m" else None,
    )
    request = parse_request({
        "account_id": "pa_5m_readiness", "market": "cn_a",
        "account_state": {
            "cash": 1000.0,
            "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}],
        },
        "orders": [], "from_date": _DAY, "to_date": _DAY,
        "fee_model": {}, "interval": interval,
    })
    return engine.match_orders(
        request, market_data=market_data, calendar_client=FakeCalendarClient())


def test_5m_valuation_without_target_daily_bar_is_not_ready() -> None:
    outcome = _valuation("5m", [(_PREV, 10.0)])

    assert outcome.error is not None
    assert outcome.error.code == "PAPER_DATA_NOT_READY"
    assert f"target bar {_DAY}" in outcome.error.message
    assert outcome.fills == () and outcome.nav_series == ()
    assert outcome.end_state.cash == 1000.0


def test_5m_valuation_with_target_daily_bar_is_ready() -> None:
    outcome = _valuation("5m", [(_PREV, 10.0), (_DAY, 10.5)])

    assert outcome.error is None
    assert outcome.fills == ()
    assert [(point.date, point.nav) for point in outcome.nav_series] == [(_DAY, 2050.0)]


def test_5m_and_1d_agree_on_a_missing_target_bar() -> None:
    five = _valuation("5m", [(_PREV, 10.0)])
    daily = _valuation("1d", [(_PREV, 10.0)])

    assert five.error is not None and daily.error is not None
    assert five.error.code == daily.error.code == "PAPER_DATA_NOT_READY"
    assert five.error.message == daily.error.message
