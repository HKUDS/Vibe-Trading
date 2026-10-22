"""T4 gate — cn_a session shape, 5m bar assembly and session events.

The normal-day fixture is a real 5m shape: 49 raw rows (the 09:30 opening
call-auction print plus 48 continuous bars).  The session bar must be built
from the 48 continuous bars only, a normal day must emit NO events, a halted
symbol-day must emit only ``halted``, an auction-window label must be
excluded and reported, and a whole-universe zero-bar day must fail closed as
``PAPER_DATA_NOT_READY`` instead of inventing a halt (D6).
Offline: committed fixtures and in-test frames, never the network.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from src.tools.paper_trade import calendar, engine
from src.tools.paper_trade.data import NOT_READY_CODE, fetch_market_data
from src.tools.paper_trade.schema import parse_request

_DAY = "2026-10-20"
_PREV = "2026-10-19"
_SYM = "600519.SH"
_OTHER = "000001.SZ"
_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "paper_trade" / "5m" / _SYM


def _fixture_5m(day: str = _DAY) -> pd.DataFrame:
    frame = pd.read_csv(_FIXTURE_DIR / f"{day}.csv", parse_dates=["bar_time"])
    return frame.set_index("bar_time")


def _labels(day: str = _DAY) -> list[str]:
    stamps: list[str] = []
    for hour, minute in ((9, 30), (13, 0)):
        start = dt.datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00")
        stamps.extend((start + dt.timedelta(minutes=5 * step)).strftime("%H:%M")
                      for step in range(1, 25))
    return stamps


def _intraday(day: str, prices: dict[str, float], auction: float | None = None) -> pd.DataFrame:
    records = []
    if auction is not None:
        records.append({"bar_time": f"{day} 09:30", "open": auction, "high": auction,
                        "low": auction, "close": auction, "volume": 48000.0})
    for label, price in prices.items():
        records.append({"bar_time": f"{day} {label}", "open": price, "high": price,
                        "low": price, "close": price, "volume": 120000.0})
    frame = pd.DataFrame(records)
    frame["bar_time"] = pd.to_datetime(frame["bar_time"])
    return frame.set_index("bar_time")


def _daily(rows: list[tuple[str, float]]) -> pd.DataFrame:
    records = [
        {"trade_date": day, "open": close, "high": close, "low": close,
         "close": close, "volume": 1000.0}
        for day, close in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


class FakeChClient:
    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()


class FakeLoader:
    def __init__(self, daily: dict[str, pd.DataFrame], five: dict[str, pd.DataFrame] | None = None) -> None:
        self.name = "tencent"
        self._daily = daily
        self._five = five or {}
        self.calls: list[tuple[tuple[str, ...], str, str, str]] = []

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        self.calls.append((tuple(codes), start_date, end_date, interval))
        source = self._five if interval == "5m" else self._daily
        return {code: source[code] for code in codes if code in source}


class FakeCalendarClient:
    def __init__(self, open_days: frozenset[str]) -> None:
        self._open = open_days

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {"exchange": "SSE", "cal_date": day.strftime("%Y-%m-%d"),
             "is_open": int(day.strftime("%Y-%m-%d") in self._open), "pretrade_date": ""}
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _fetch(daily, five, *, symbols=(_SYM,), interval="5m", from_date=_DAY, to_date=_DAY):
    loader = FakeLoader(daily, five)
    return fetch_market_data(
        "cn_a", list(symbols), from_date, to_date,
        loader=loader, ch_client=FakeChClient(), interval=interval), loader


def _daily_tape(*symbols: str, day_close: float = 1422.0) -> dict[str, pd.DataFrame]:
    return {symbol: _daily([(_PREV, 1421.0), (_DAY, day_close)]) for symbol in symbols}


def _run(market_data, orders=(), *, cash=1000000.0, positions=(),
         open_days=frozenset({_DAY}), path_model="bar_median"):
    request = parse_request({
        "account_id": "pa_5m_session", "market": "cn_a",
        "account_state": {"cash": cash, "positions": list(positions)},
        "orders": list(orders), "from_date": _DAY, "to_date": _DAY,
        "interval": "5m", "path_model": path_model,
    })
    return engine.match_orders(
        request, market_data=market_data, calendar_client=FakeCalendarClient(open_days))


def test_normal_day_has_48_continuous_bars_and_no_events() -> None:
    market_data, _ = _fetch(_daily_tape(_SYM), {_SYM: _fixture_5m()})
    symbol_data = market_data.data[_SYM]

    continuous = symbol_data.bars_5m[_DAY]
    assert len(continuous) == calendar.CONTINUOUS_BARS_PER_DAY == 48
    assert continuous.index.strftime("%H:%M").tolist() == _labels()
    assert symbol_data.session_bar is not None
    bar = symbol_data.session_bar
    assert (bar.open, bar.high, bar.low, bar.close, bar.bar_count) == (
        1421.0, 1422.0, 1421.0, 1422.0, 48)
    assert bar.volume == 47 * 120000.0 + 120000.0

    outcome = _run(market_data)
    assert outcome.events == ()
    assert outcome.canceled_orders == ()
    assert outcome.fills == outcome.rejected_orders == ()
    assert outcome.warnings == ()


def test_auction_print_is_excluded_from_the_session_bar() -> None:
    market_data, _ = _fetch(_daily_tape(_SYM), {_SYM: _fixture_5m()})
    labels = market_data.data[_SYM].bars_5m[_DAY].index.strftime("%H:%M").tolist()

    assert "09:30" not in labels
    # Including the 09:30 print (1423.00) would raise the session open to
    # 1423.00 and the close/median would move; the assembled bar proves the
    # exclusion changed a real number.
    assert market_data.data[_SYM].session_bar.open == 1421.0
    assert market_data.data[_SYM].auction_labels == {}


def test_closing_auction_window_label_is_excluded_and_reported() -> None:
    prices = {label: 1421.0 for label in _labels()}
    prices["14:58"] = 99.0
    frame = _intraday(_DAY, prices, auction=1423.0)
    market_data, _ = _fetch(_daily_tape(_SYM), {_SYM: frame})

    symbol_data = market_data.data[_SYM]
    assert "14:58" not in symbol_data.bars_5m[_DAY].index.strftime("%H:%M")
    assert symbol_data.session_bar.high == 1421.0  # 99.0 never pollutes the bar
    assert symbol_data.auction_labels[_DAY] == ("14:58",)
    assert any("auction-window label(s) 14:58" in warning for warning in market_data.warnings)

    outcome = _run(market_data)
    assert [(e.trade_date, e.symbol, e.event_type) for e in outcome.events] == [
        (_DAY, _SYM, "auction_window")]
    assert "14:58" in outcome.events[0].detail


def test_partial_gap_warns_with_the_bar_count_and_still_matches() -> None:
    partial = {label: 10.0 for label in _labels()[:30]}
    market_data, _ = _fetch(
        {_SYM: _daily([(_PREV, 10.0), (_DAY, 10.0)])}, {_SYM: _intraday(_DAY, partial)})

    symbol_data = market_data.data[_SYM]
    assert len(symbol_data.bars_5m[_DAY]) == 30
    assert symbol_data.session_bar.bar_count == 30
    assert any("30/48 continuous bars" in warning for warning in market_data.warnings)

    outcome = _run(market_data, orders=[{"symbol": _SYM, "side": "buy", "qty": 100}])
    assert [(f.side, f.price) for f in outcome.fills] == [("buy", 10.0)]
    assert outcome.rejected_orders == ()


def test_halted_symbol_emits_only_halted_and_leaves_the_ledger_alone() -> None:
    # The halted symbol has NO daily bar for the day either (Tushare omits a
    # suspended day from both endpoints); the other symbol traded, so the day
    # is ready and the halt is a per-symbol fact.
    daily = {_SYM: _daily([(_PREV, 10.0), (_DAY, 10.2)]), _OTHER: _daily([(_PREV, 20.0)])}
    market_data, _ = _fetch(daily, {_SYM: _intraday(_DAY, {label: 10.0 for label in _labels()})},
                            symbols=(_SYM, _OTHER))
    outcome = _run(
        market_data, orders=[{"symbol": _OTHER, "side": "buy", "qty": 100}],
        positions=[{"symbol": _OTHER, "qty": 100, "avg_cost": 20.0}])

    assert [(e.symbol, e.event_type) for e in outcome.events] == [(_OTHER, "halted")]
    assert [(r.symbol, r.reason_code) for r in outcome.rejected_orders] == [(_OTHER, "suspended")]
    assert outcome.fills == ()
    assert [(p.symbol, p.qty, p.avg_cost) for p in outcome.end_state.positions] == [(_OTHER, 100.0, 20.0)]
    assert outcome.nav_series[0].position_value == 2000.0


def test_whole_universe_zero_bars_is_data_not_ready() -> None:
    daily = {_SYM: _daily([(_PREV, 10.0)]), _OTHER: _daily([(_PREV, 20.0)])}
    market_data, _ = _fetch(daily, {}, symbols=(_SYM, _OTHER))

    outcome = _run(market_data, orders=[{"symbol": _SYM, "side": "buy", "qty": 100}])

    assert outcome.error is not None
    assert outcome.error.code == NOT_READY_CODE
    assert outcome.fills == outcome.canceled_orders == outcome.events == ()
    assert market_data.five_minute_contradiction == {}


def test_daily_bar_without_a_5m_bar_is_a_provider_fault_not_a_halt() -> None:
    # The daily bar proves the symbol traded; a provider error that returns
    # no 5m bars must fail closed as data-not-ready, never as "halted" (D6).
    daily = {_SYM: _daily([(_PREV, 10.0), (_DAY, 10.2)]),
             _OTHER: _daily([(_PREV, 20.0), (_DAY, 20.0)])}
    five = {_OTHER: _intraday(_DAY, {label: 20.0 for label in _labels()})}
    market_data, _ = _fetch(daily, five, symbols=(_SYM, _OTHER))

    assert market_data.five_minute_contradiction == {_DAY: (_SYM,)}
    outcome = _run(market_data, orders=[{"symbol": _SYM, "side": "buy", "qty": 100}])

    assert outcome.error is not None
    assert outcome.error.code == NOT_READY_CODE
    assert "provider omitted the 5m leg" in outcome.error.message
    assert _SYM in outcome.error.message
    assert "halted" not in outcome.error.message
    assert outcome.events == () and outcome.fills == ()


def test_calendar_closed_day_emits_non_trading_day_and_never_fills() -> None:
    market_data, _ = _fetch(_daily_tape(_SYM), {_SYM: _fixture_5m()})
    outcome = _run(market_data, orders=[{"symbol": _SYM, "side": "buy", "qty": 100}],
                   open_days=frozenset())

    assert [(e.trade_date, e.symbol, e.event_type) for e in outcome.events] == [
        (_DAY, "", "non_trading_day")]
    assert [(s.date, s.reason) for s in outcome.skipped_days] == [(_DAY, "non_trading_day")]
    assert [r.reason_code for r in outcome.rejected_orders] == ["non_trading_day"]
    assert [c.reason_code for c in outcome.canceled_orders] == ["canceled_after_failed_match"]
    assert outcome.fills == ()


def test_one_ranged_5m_call_with_an_exclusive_end_bound() -> None:
    market_data, loader = _fetch(_daily_tape(_SYM), {_SYM: _fixture_5m()})
    five_calls = [call for call in loader.calls if call[3] == "5m"]

    assert len(five_calls) == 1
    codes, start, end, _ = five_calls[0]
    assert codes == (_SYM,)
    assert start == _DAY
    assert end == "2026-10-21"  # provider end bound is exclusive at midnight
    assert market_data.interval == "5m"


def test_1d_fetch_never_issues_a_5m_request() -> None:
    daily = _daily_tape(_SYM)
    market_data, loader = _fetch(daily, {_SYM: _fixture_5m()}, interval="1d")

    assert [call[3] for call in loader.calls] == ["1D"]
    assert market_data.interval == "1d"
    assert len(market_data.bar_fingerprint) == 64
    assert market_data.data[_SYM].bars_5m == {}
    assert market_data.data[_SYM].session_bar is None


def test_bar_fingerprint_is_symbol_order_independent_and_deterministic() -> None:
    daily = _daily_tape(_SYM, _OTHER)
    five = {_SYM: _fixture_5m(), _OTHER: _intraday(_DAY, {label: 20.0 for label in _labels()})}
    first, _ = _fetch(daily, five, symbols=(_SYM, _OTHER))
    second, _ = _fetch(daily, five, symbols=(_OTHER, _SYM))

    assert len(first.bar_fingerprint) == 64
    assert first.bar_fingerprint == second.bar_fingerprint

    changed = dict(five)
    changed[_OTHER] = _intraday(_DAY, {label: 20.5 for label in _labels()})
    third, _ = _fetch(daily, changed, symbols=(_SYM, _OTHER))
    assert third.bar_fingerprint != first.bar_fingerprint


def test_duplicate_label_keeps_the_last_row() -> None:
    first = _intraday(_DAY, {label: 10.0 for label in _labels()})
    duplicate = _intraday(_DAY, {"10:00": 10.9})
    frame = pd.concat([first, duplicate]).sort_index(kind="stable")
    market_data, _ = _fetch({_SYM: _daily([(_PREV, 10.0), (_DAY, 10.0)])}, {_SYM: frame})

    labels = market_data.data[_SYM].bars_5m[_DAY].index.strftime("%H:%M").tolist()
    assert labels.count("10:00") == 1
    assert market_data.data[_SYM].bars_5m[_DAY].loc[pd.Timestamp(f"{_DAY} 10:00"), "close"] == 10.9


def test_5m_is_refused_outside_cn_a_and_unknown_intervals_are_refused() -> None:
    with pytest.raises(ValueError, match="cn_a-only"):
        fetch_market_data("us", ["AAPL.US"], _DAY, _DAY, loader=FakeLoader({}), interval="5m")
    with pytest.raises(ValueError, match="unknown interval"):
        fetch_market_data("cn_a", [_SYM], _DAY, _DAY, loader=FakeLoader({}), interval="1m")


@pytest.mark.parametrize(("label", "kind"), [
    ("09:30", calendar.SESSION_OPENING_AUCTION_PRINT),
    ("09:15", calendar.SESSION_AUCTION_WINDOW),
    ("09:25", calendar.SESSION_AUCTION_WINDOW),
    ("09:35", calendar.SESSION_CONTINUOUS),
    ("11:30", calendar.SESSION_CONTINUOUS),
    ("11:35", calendar.SESSION_OUTSIDE),
    ("13:00", calendar.SESSION_OUTSIDE),
    ("13:05", calendar.SESSION_CONTINUOUS),
    ("14:57", calendar.SESSION_AUCTION_WINDOW),
    ("14:59", calendar.SESSION_AUCTION_WINDOW),
    ("15:00", calendar.SESSION_CONTINUOUS),
    ("15:05", calendar.SESSION_OUTSIDE),
])
def test_session_label_classification_matrix(label: str, kind: str) -> None:
    assert calendar.classify_cn_a_session_label(label) == kind


def test_session_constants_are_the_frozen_cn_a_windows() -> None:
    assert calendar.CN_A_SESSION_TIMEZONE == "Asia/Shanghai"
    assert calendar.CONTINUOUS_MORNING == ("09:30", "11:30")
    assert calendar.CONTINUOUS_AFTERNOON == ("13:00", "15:00")
    assert calendar.OPENING_AUCTION == ("09:15", "09:25")
    assert calendar.CLOSING_AUCTION == ("14:57", "15:00")
