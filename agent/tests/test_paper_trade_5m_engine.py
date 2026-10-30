"""T3 gate — cn_a 5m reference price, all-or-none fills and emergency cancel.

Every order matches ONE assembled session bar (D1: the 48 continuous 5m bars
of the day, 09:30 opening-auction print excluded).  The reference price is
``bar_median`` (median of open/high/low/close) or ``bar_close``; it drives
limit marketability, the cash gate, the fill price, the notional and the fee.
A failed order keeps its specific pt-v1.1 reason in ``rejected_orders`` AND
gets one ``canceled_after_failed_match`` row in ``canceled_orders`` (D2).
Offline: synthetic frames through a fake loader, never the network.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from src.tools.paper_trade import engine, state_hash
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import CANCELED_REASON_CODE, REASON_CODES, parse_request

_DAY = "2026-10-20"
_PREV = "2026-10-19"
_SYM = "600519.SH"
_OTHER = "000001.SZ"
_FEE_MODEL = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.00001,
}


def _session_labels(day: str = _DAY) -> list[str]:
    stamps: list[str] = []
    for hour, minute in ((9, 30), (13, 0)):
        start = dt.datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00")
        stamps.extend((start + dt.timedelta(minutes=5 * step)).strftime("%H:%M") for step in range(1, 25))
    return stamps


def _intraday(day: str, prices: dict[str, float], auction: float | None = None) -> pd.DataFrame:
    records = []
    if auction is not None:
        records.append(
            {
                "bar_time": f"{day} 09:30",
                "open": auction,
                "high": auction,
                "low": auction,
                "close": auction,
                "volume": 48000.0,
            }
        )
    for label, price in prices.items():
        records.append(
            {
                "bar_time": f"{day} {label}",
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 120000.0,
            }
        )
    frame = pd.DataFrame(records)
    frame["bar_time"] = pd.to_datetime(frame["bar_time"])
    return frame.set_index("bar_time")


def _normal_5m(day: str = _DAY, *, close: float = 10.20) -> pd.DataFrame:
    labels = _session_labels(day)
    prices = {label: 10.00 for label in labels[:-1]}
    prices[labels[-1]] = close
    return _intraday(day, prices, auction=10.05)


def _flat_5m(day: str, price: float) -> pd.DataFrame:
    return _intraday(day, {label: price for label in _session_labels(day)}, auction=price)


def _daily(rows: list[tuple[str, float]]) -> pd.DataFrame:
    records = [
        {"trade_date": day, "open": close, "high": close, "low": close, "close": close, "volume": 1000.0}
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
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": int(day.strftime("%Y-%m-%d") in self._open),
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _market_data(daily: dict[str, pd.DataFrame], five: dict[str, pd.DataFrame], *, symbols: tuple[str, ...] = (_SYM,)):
    return fetch_market_data(
        "cn_a",
        list(symbols),
        _DAY,
        _DAY,
        loader=FakeLoader(daily, five),
        ch_client=FakeChClient(),
        interval="5m",
    )


def _cn_a_data(**overrides) -> tuple[object, FakeLoader]:
    five_overrides = overrides.pop("five", None)
    daily_overrides = overrides.pop("daily", None)
    symbols = tuple(overrides.pop("symbols", (_SYM,)))
    daily = {_SYM: _daily([(_PREV, 10.00), (_DAY, 10.20)])}
    if daily_overrides:
        daily.update(daily_overrides)
    five = {_SYM: _normal_5m()}
    if five_overrides is not None:
        five = five_overrides
    return _market_data(daily, five, symbols=symbols), FakeLoader(daily, five)


def _outcome(
    *,
    orders,
    cash=100000.0,
    positions=(),
    path_model="bar_median",
    market_data=None,
    open_days=frozenset({_DAY}),
    **frames,
):
    if market_data is None:
        market_data, _ = _cn_a_data(**frames)
    request = parse_request(
        {
            "account_id": "pa_5m",
            "market": "cn_a",
            "account_state": {"cash": cash, "positions": list(positions)},
            "orders": list(orders),
            "from_date": _DAY,
            "to_date": _DAY,
            "fee_model": dict(_FEE_MODEL),
            "interval": "5m",
            "path_model": path_model,
        }
    )
    return engine.match_orders(request, market_data=market_data, calendar_client=FakeCalendarClient(open_days))


def _buy(limit=None, qty=100, symbol=_SYM):
    order = {"symbol": symbol, "side": "buy", "qty": qty}
    if limit is not None:
        order["limit"] = limit
    return order


def _sell(limit=None, qty=100, symbol=_SYM):
    order = {"symbol": symbol, "side": "sell", "qty": qty}
    if limit is not None:
        order["limit"] = limit
    return order


def test_market_buy_fills_at_the_session_median() -> None:
    # Session bar o/h/l/c = 10.00/10.20/10.00/10.20 → median 10.10.  The 09:30
    # auction print (10.05) is excluded; including it would move the median.
    outcome = _outcome(orders=[_buy()])

    assert outcome.error is None
    assert [(f.side, f.qty, f.price, f.fee) for f in outcome.fills] == [("buy", 100.0, 10.10, 5.01)]
    assert outcome.rejected_orders == ()
    assert outcome.canceled_orders == ()
    assert outcome.end_state.cash == 98984.99
    assert outcome.end_state.positions[0].avg_cost == 10.10
    assert outcome.events == ()
    assert outcome.nav_series[0].nav == 100004.99


def test_market_sell_fills_at_the_session_median() -> None:
    outcome = _outcome(orders=[_sell()], positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}])

    assert outcome.error is None
    assert [(f.side, f.qty, f.price, f.fee) for f in outcome.fills] == [("sell", 100.0, 10.10, 5.52)]
    assert outcome.end_state.cash == 101004.48
    assert outcome.end_state.positions == ()
    assert outcome.canceled_orders == ()


@pytest.mark.parametrize(("limit", "fills"), [(10.50, True), (10.10, True), (10.00, False)])
def test_buy_limit_marketability_at_the_reference(limit: float, fills: bool) -> None:
    outcome = _outcome(orders=[_buy(limit=limit)])

    if fills:
        assert [(f.side, f.price) for f in outcome.fills] == [("buy", 10.10)]
        assert outcome.rejected_orders == ()
        return
    assert outcome.fills == ()
    assert [r.reason_code for r in outcome.rejected_orders] == ["limit_not_marketable"]
    assert outcome.rejected_orders[0].detail == "ref 10.10 > limit 10.00"
    assert [c.reason_code for c in outcome.canceled_orders] == [CANCELED_REASON_CODE]


@pytest.mark.parametrize(("limit", "fills"), [(10.00, True), (10.10, True), (10.20, False)])
def test_sell_limit_marketability_at_the_reference(limit: float, fills: bool) -> None:
    outcome = _outcome(orders=[_sell(limit=limit)], positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}])

    if fills:
        assert [(f.side, f.price) for f in outcome.fills] == [("sell", 10.10)]
        assert outcome.rejected_orders == ()
        return
    assert outcome.fills == ()
    assert [r.reason_code for r in outcome.rejected_orders] == ["limit_not_marketable"]
    assert outcome.rejected_orders[0].detail == "ref 10.10 < limit 10.20"
    assert [c.reason_code for c in outcome.canceled_orders] == [CANCELED_REASON_CODE]


def test_path_model_changes_the_reference_and_the_verdict() -> None:
    market_data, _ = _cn_a_data()
    median = _outcome(orders=[_buy(limit=10.15)], market_data=market_data)
    close = _outcome(orders=[_buy(limit=10.15)], market_data=market_data, path_model="bar_close")

    assert [(f.price) for f in median.fills] == [10.10]
    assert median.rejected_orders == ()
    assert close.fills == ()
    assert [r.reason_code for r in close.rejected_orders] == ["limit_not_marketable"]
    assert close.rejected_orders[0].detail == "ref 10.20 > limit 10.15"
    assert median.engine_fingerprint != close.engine_fingerprint


@pytest.mark.parametrize("path_model", ["bar_median", "bar_close"])
def test_fill_price_equals_the_reference_under_both_path_models(path_model: str) -> None:
    market_data, _ = _cn_a_data()
    bar = market_data.data[_SYM].session_bar
    expected = 10.20 if path_model == "bar_close" else 10.10
    assert (bar.open, bar.high, bar.low, bar.close) == (10.00, 10.20, 10.00, 10.20)

    outcome = _outcome(orders=[_buy(), _buy(qty=200)], market_data=market_data, path_model=path_model, cash=1000000.0)

    assert [f.price for f in outcome.fills] == [expected, expected]
    assert outcome.canceled_orders == ()
    assert outcome.engine_fingerprint == state_hash.engine_fingerprint(
        interval="5m", path_model=path_model, fill_model="all_or_none", bar_fingerprint=market_data.bar_fingerprint
    )


def test_insufficient_cash_rejects_and_cancels() -> None:
    outcome = _outcome(orders=[_buy()], cash=500.0)

    assert outcome.fills == ()
    assert [r.reason_code for r in outcome.rejected_orders] == ["insufficient_cash"]
    assert "1015.01" in outcome.rejected_orders[0].detail
    assert len(outcome.canceled_orders) == 1
    assert outcome.canceled_orders[0].detail == "rejected: insufficient_cash"
    assert outcome.end_state.cash == 500.0


def test_insufficient_position_rejects_and_cancels() -> None:
    outcome = _outcome(orders=[_sell(qty=200)], positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}])

    assert outcome.fills == ()
    assert [r.reason_code for r in outcome.rejected_orders] == ["insufficient_position"]
    assert [c.reason_code for c in outcome.canceled_orders] == [CANCELED_REASON_CODE]
    assert outcome.end_state.positions[0].qty == 100


def test_lot_size_rejects_and_cancels() -> None:
    outcome = _outcome(orders=[_buy(qty=150)])

    assert outcome.fills == ()
    assert [r.reason_code for r in outcome.rejected_orders] == ["lot_size"]
    assert len(outcome.canceled_orders) == 1


def test_limit_up_buy_rejects_with_a_price_limit_event() -> None:
    daily = {_SYM: _daily([(_PREV, 10.00), (_DAY, 11.00)])}
    five = {_SYM: _flat_5m(_DAY, 11.00)}
    outcome = _outcome(orders=[_buy()], daily=daily, five=five)

    assert outcome.fills == ()
    assert [r.reason_code for r in outcome.rejected_orders] == ["limit_up"]
    assert [(e.symbol, e.event_type) for e in outcome.events] == [(_SYM, "price_limit")]
    assert "up limit 11.00" in outcome.events[0].detail
    assert len(outcome.canceled_orders) == 1


def test_limit_down_sell_rejects_with_a_price_limit_event() -> None:
    daily = {_SYM: _daily([(_PREV, 10.00), (_DAY, 9.00)])}
    five = {_SYM: _flat_5m(_DAY, 9.00)}
    outcome = _outcome(
        orders=[_sell()], daily=daily, five=five, positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}]
    )

    assert outcome.fills == ()
    assert [r.reason_code for r in outcome.rejected_orders] == ["limit_down"]
    assert [(e.symbol, e.event_type) for e in outcome.events] == [(_SYM, "price_limit")]
    assert len(outcome.canceled_orders) == 1


def test_halted_symbol_rejects_suspended_and_its_position_is_untouched() -> None:
    daily = {
        _SYM: _daily([(_PREV, 10.00), (_DAY, 10.20)]),
        _OTHER: _daily([(_PREV, 20.00)]),
    }
    five = {_SYM: _normal_5m()}
    market_data, _ = _cn_a_data(daily=daily, five=five, symbols=(_SYM, _OTHER))
    outcome = _outcome(
        orders=[_buy(symbol=_OTHER)],
        market_data=market_data,
        positions=[{"symbol": _OTHER, "qty": 100, "avg_cost": 20.0}],
    )

    assert outcome.fills == ()
    assert [(r.symbol, r.reason_code) for r in outcome.rejected_orders] == [(_OTHER, "suspended")]
    assert [(e.symbol, e.event_type) for e in outcome.events] == [(_OTHER, "halted")]
    assert [(p.symbol, p.qty, p.avg_cost) for p in outcome.end_state.positions] == [(_OTHER, 100.0, 20.0)]
    assert outcome.end_state.cash == 100000.0
    assert outcome.nav_series[0].position_value == 2000.0
    assert len(outcome.canceled_orders) == 1


def test_every_order_is_terminal_and_every_failure_has_a_reason() -> None:
    orders = [
        _buy(),  # fills
        _buy(limit=10.00),  # limit_not_marketable
        _buy(qty=150),  # lot_size
        _buy(symbol="999999.SZ"),  # unknown_symbol
        _sell(qty=200),  # insufficient_position
    ]
    outcome = _outcome(orders=orders, positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}])

    assert len(outcome.fills) + len(outcome.rejected_orders) == len(orders)
    assert all(r.reason_code in REASON_CODES for r in outcome.rejected_orders)
    assert len(outcome.canceled_orders) == len(outcome.rejected_orders)
    assert {c.reason_code for c in outcome.canceled_orders} == {CANCELED_REASON_CODE}
    assert [(c.symbol, c.side, c.qty) for c in outcome.canceled_orders] == [
        (r.symbol, r.side, r.qty) for r in outcome.rejected_orders
    ]


def test_1d_mode_is_unchanged_and_never_cancels_or_events() -> None:
    daily = {_SYM: _daily([(_PREV, 10.00), (_DAY, 10.20)])}
    market_data = fetch_market_data("cn_a", [_SYM], _DAY, _DAY, loader=FakeLoader(daily), ch_client=FakeChClient())
    request = parse_request(
        {
            "account_id": "pa_5m_1d",
            "market": "cn_a",
            "account_state": {"cash": 100000.0, "positions": []},
            "orders": [_buy(limit=10.00)],
            "from_date": _DAY,
            "to_date": _DAY,
            "fee_model": dict(_FEE_MODEL),
        }
    )
    outcome = engine.match_orders(
        request, market_data=market_data, calendar_client=FakeCalendarClient(frozenset({_DAY}))
    )

    assert outcome.fills == ()
    assert outcome.rejected_orders[0].detail == "close 10.20 > limit 10.00"
    assert outcome.canceled_orders == ()
    assert outcome.events == ()
    assert market_data.interval == "1d"
    assert len(market_data.bar_fingerprint) == 64


def test_5m_request_refuses_a_daily_frame() -> None:
    daily = {_SYM: _daily([(_PREV, 10.00), (_DAY, 10.20)])}
    market_data = fetch_market_data("cn_a", [_SYM], _DAY, _DAY, loader=FakeLoader(daily), ch_client=FakeChClient())
    request = parse_request(
        {
            "account_id": "pa_5m_gate",
            "market": "cn_a",
            "account_state": {"cash": 100000.0, "positions": []},
            "orders": [_buy()],
            "from_date": _DAY,
            "to_date": _DAY,
            "fee_model": dict(_FEE_MODEL),
            "interval": "5m",
        }
    )
    outcome = engine.match_orders(
        request, market_data=market_data, calendar_client=FakeCalendarClient(frozenset({_DAY}))
    )

    assert outcome.error is not None
    assert outcome.error.code == "INVALID_REQUEST"
    assert "interval" in outcome.error.message
    assert outcome.fills == () and outcome.canceled_orders == ()
