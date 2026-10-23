"""T12-gate orders-mode validation half (AM-3, Step 3 / T3).

orders mode is single-day only: ``from_date != to_date`` → stable in-band
``INVALID_REQUEST`` material (T6 maps it to the envelope) — no matching, no
half-day.  The strategy_path timeout half of T12 lands with T7 (B1 frozen
message formats ``strategy_execution_timeout:{date}`` /
``strategy_execution_error:{date}:{class}``); nothing here pre-empts it.
Offline: fake clients only.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools.paper_trade import engine
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import ERROR_CODES, AccountState, Order, parse_request

_DAY = "2026-10-20"
_PREV = "2026-10-19"
_SYM = "600519.SH"


class FakeChClient:
    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "tencent") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


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
        {"trade_date": day, "open": close, "high": close, "low": close, "close": close, "volume": 1000.0}
        for day, close in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


def _cn_a_data(from_date: str = _DAY, to_date: str = _DAY):
    frames = {_SYM: _frame([(_PREV, 10.0), (_DAY, 10.5)])}
    return fetch_market_data("cn_a", [_SYM], from_date, to_date,
                             loader=FakeLoader(frames), ch_client=FakeChClient())


def _request(from_date: str, to_date: str, orders: list[dict] | None, market: str = "cn_a"):
    payload = {
        "account_id": "pa_validation", "market": market,
        "account_state": {"cash": 100000.0, "positions": []},
        "from_date": from_date, "to_date": to_date, "fee_model": {},
    }
    if orders is not None:
        payload["orders"] = orders
    return parse_request(payload)


_BUY = [{"symbol": _SYM, "side": "buy", "qty": 100}]


def test_orders_mode_multi_day_range_is_invalid_request_material() -> None:
    outcome = engine.match_orders(
        _request(_PREV, _DAY, _BUY), market_data=_cn_a_data(_PREV, _DAY),
        calendar_client=FakeCalendarClient(),
    )
    assert outcome.error is not None
    assert outcome.error.code == "INVALID_REQUEST"
    assert outcome.error.code in ERROR_CODES  # frozen vocabulary member
    assert "from_date == to_date" in outcome.error.message
    assert f"from_date={_PREV}" in outcome.error.message and f"to_date={_DAY}" in outcome.error.message
    # No matching, no half-day: every output array is empty, state untouched.
    assert outcome.fills == () and outcome.rejected_orders == ()
    assert outcome.nav_series == () and outcome.skipped_days == ()
    assert outcome.end_state.cash == 100000.0


def test_orders_mode_reversed_range_is_also_invalid_request() -> None:
    outcome = engine.match_orders(
        _request(_DAY, _PREV, _BUY), market_data=_cn_a_data(_PREV, _DAY),
        calendar_client=FakeCalendarClient(),
    )
    assert outcome.error is not None and outcome.error.code == "INVALID_REQUEST"
    assert outcome.nav_series == ()


def test_missing_orders_array_is_invalid_request_and_names_the_t7_seam() -> None:
    # strategy_path mode (orders=None) is not this entry's contract; the
    # timeout/error half of T12 (B1 frozen messages) lands with T7.
    outcome = engine.match_orders(
        _request(_DAY, _DAY, None), market_data=_cn_a_data(),
        calendar_client=FakeCalendarClient(),
    )
    assert outcome.error is not None and outcome.error.code == "INVALID_REQUEST"
    assert "Step 7" in outcome.error.message
    assert outcome.fills == () and outcome.nav_series == ()


def test_cn_a_without_an_injected_calendar_client_fails_loud() -> None:
    # AM-6: the CH calendar is the cn_a truth — a missing client is an engine
    # wiring fault (transport class), never a silent weekday fallback.
    with pytest.raises(ValueError, match="TradeCalendarClient"):
        engine.match_orders(_request(_DAY, _DAY, _BUY), market_data=_cn_a_data())


def test_market_mismatch_between_data_and_request_fails_loud() -> None:
    with pytest.raises(ValueError, match="market_data was fetched for"):
        engine.match_orders(_request(_DAY, _DAY, _BUY, market="hk"), market_data=_cn_a_data())


def test_zero_order_pure_valuation_path_produces_a_cash_plus_position_nav() -> None:
    # Empty orders array (NOT None) is the zero-order pure-valuation path:
    # one nav row, no fills, position valued at the day's close.
    request = parse_request({
        "account_id": "pa_validation", "market": "cn_a",
        "account_state": {"cash": 1000.0,
                          "positions": [{"symbol": _SYM, "qty": 100, "avg_cost": 9.0}]},
        "orders": [], "from_date": _DAY, "to_date": _DAY, "fee_model": {},
    })
    outcome = engine.match_orders(request, market_data=_cn_a_data(),
                                  calendar_client=FakeCalendarClient())
    assert outcome.error is None
    assert outcome.fills == () and outcome.rejected_orders == ()
    assert outcome.nav_series[0].nav == 1000.0 + 100 * 10.5
    assert outcome.end_state.positions[0].avg_cost == 9.0  # untouched


def test_hk_needs_no_calendar_client_zero_calendar_by_design() -> None:
    frames = {"00700.HK": _frame([(_PREV, 400.0), (_DAY, 417.8)])}
    market_data = fetch_market_data("hk", ["00700.HK"], _DAY, _DAY, loader=FakeLoader(frames))
    outcome = engine.match_orders(
        _request(_DAY, _DAY, [{"symbol": "00700.HK", "side": "buy", "qty": 100}], market="hk"),
        market_data=market_data,
    )
    assert outcome.error is None
    assert len(outcome.fills) == 1 and outcome.fills[0].price == 417.8


def test_run_day_loop_rejects_a_reversed_range_deterministically() -> None:
    frames = {"00700.HK": _frame([(_DAY, 417.8)])}
    market_data = fetch_market_data("hk", ["00700.HK"], _DAY, _DAY, loader=FakeLoader(frames))
    with pytest.raises(ValueError, match="> to_date"):
        engine.run_day_loop(
            market="hk", account_state=AccountState(cash=1.0),
            from_date=_DAY, to_date=_PREV,
            orders_by_day={_DAY: (Order("00700.HK", "buy", 100),)},
            market_data=market_data,
        )


@pytest.mark.parametrize(("market", "symbol"), [("hk", "00700.HK"), ("us", "AAPL.US")])
def test_zero_bar_target_day_returns_in_band_not_ready_never_a_raise(market: str, symbol: str) -> None:
    # AM-9/AM-6① regression (orchestrator-found): the target day has only a
    # prior-day bar, so the merged frame is all-market zero on the target —
    # the readiness gate must return the in-band PAPER_DATA_NOT_READY
    # material, never the transport-class RuntimeError the day-plan builder
    # used to raise before the gate ran.
    frames = {symbol: _frame([(_PREV, 100.0)])}
    market_data = fetch_market_data(market, [symbol], _DAY, _DAY, loader=FakeLoader(frames))
    outcome = engine.run_day_loop(
        market=market, account_state=AccountState(cash=1000.0),
        from_date=_DAY, to_date=_DAY, orders_by_day={}, market_data=market_data,
    )
    assert outcome.error is not None
    assert outcome.error.code == "PAPER_DATA_NOT_READY"
    assert outcome.error.code in ERROR_CODES
    assert f"target bar {_DAY}" in outcome.error.message
    assert outcome.fills == () and outcome.rejected_orders == ()
    assert outcome.nav_series == () and outcome.skipped_days == ()
    assert outcome.end_state.cash == 1000.0  # state untouched — no half-day
