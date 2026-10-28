"""T3 gate — cn_a per-bar 5m reference, all-or-none fills and day settlement.

Every continuous 5m bar (09:30 opening-auction print excluded) is a matching
opportunity.  A market order fills at the first bar whose fill gates pass; a
limit order rests until a bar satisfies its price and is canceled at session
end if none does.  ``bar_median`` / ``bar_close`` drive the reference, limit
marketability, the cash gate, the fill price, the notional and the fee.
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


def _dispersed_5m(day: str = _DAY) -> pd.DataFrame:
    labels = _session_labels(day)
    frame = _intraday(day, {label: 10.20 for label in labels}, auction=10.05)
    first = pd.Timestamp(f"{day} {labels[0]}")
    frame.loc[first, ["open", "high", "low", "close"]] = [10.00, 10.20, 10.00, 10.20]
    return frame


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


def test_market_buy_fills_at_the_first_continuous_bar() -> None:
    outcome = _outcome(orders=[_buy()])

    assert outcome.error is None
    assert [(f.side, f.qty, f.price, f.fee) for f in outcome.fills] == [("buy", 100.0, 10.00, 5.01)]
    assert outcome.rejected_orders == ()
    assert outcome.canceled_orders == ()
    assert outcome.end_state.cash == 98994.99
    assert outcome.end_state.positions[0].avg_cost == 10.00
    assert outcome.events == ()
    assert outcome.nav_series[0].nav == 100014.99


def test_market_sell_fills_at_the_first_continuous_bar() -> None:
    outcome = _outcome(orders=[_sell()], positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}])

    assert outcome.error is None
    assert [(f.side, f.qty, f.price, f.fee) for f in outcome.fills] == [("sell", 100.0, 10.00, 5.51)]
    assert outcome.end_state.cash == 100994.49
    assert outcome.end_state.positions == ()
    assert outcome.canceled_orders == ()


@pytest.mark.parametrize(("limit", "expected"), [(10.50, 10.00), (10.10, 10.00), (10.00, 10.00), (9.90, None)])
def test_buy_limit_fills_at_the_first_marketable_bar(limit: float, expected: float | None) -> None:
    outcome = _outcome(orders=[_buy(limit=limit)])

    if expected is not None:
        assert [(f.side, f.price) for f in outcome.fills] == [("buy", expected)]
        assert outcome.rejected_orders == ()
        assert outcome.canceled_orders == ()
        return
    assert outcome.fills == ()
    assert outcome.rejected_orders == ()
    assert [(c.reason_code, c.detail) for c in outcome.canceled_orders] == [
        (CANCELED_REASON_CODE, "unfilled day order canceled at session end")
    ]


@pytest.mark.parametrize(("limit", "expected"), [(10.00, 10.00), (10.10, 10.20), (10.20, 10.20), (10.30, None)])
def test_sell_limit_fills_at_the_first_marketable_bar(limit: float, expected: float | None) -> None:
    outcome = _outcome(orders=[_sell(limit=limit)], positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}])

    if expected is not None:
        assert [(f.side, f.price) for f in outcome.fills] == [("sell", expected)]
        assert outcome.rejected_orders == ()
        assert outcome.canceled_orders == ()
        return
    assert outcome.fills == ()
    assert outcome.rejected_orders == ()
    assert [(c.reason_code, c.detail) for c in outcome.canceled_orders] == [
        (CANCELED_REASON_CODE, "unfilled day order canceled at session end")
    ]


def test_path_model_changes_the_reference_and_the_verdict() -> None:
    market_data, _ = _cn_a_data(five={_SYM: _dispersed_5m()})
    median = _outcome(orders=[_buy(limit=10.15)], market_data=market_data)
    close = _outcome(orders=[_buy(limit=10.15)], market_data=market_data, path_model="bar_close")

    assert [f.price for f in median.fills] == [10.10]
    assert median.rejected_orders == ()
    assert close.fills == ()
    assert close.rejected_orders == ()
    assert [(c.reason_code, c.detail) for c in close.canceled_orders] == [
        (CANCELED_REASON_CODE, "unfilled day order canceled at session end")
    ]
    assert median.engine_fingerprint != close.engine_fingerprint


@pytest.mark.parametrize("path_model", ["bar_median", "bar_close"])
def test_fill_price_equals_the_first_bar_reference_under_both_path_models(path_model: str) -> None:
    market_data, _ = _cn_a_data(five={_SYM: _dispersed_5m()})
    expected = 10.20 if path_model == "bar_close" else 10.10

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
    assert "1005.01" in outcome.rejected_orders[0].detail
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
        _buy(),
        _buy(limit=9.90),
        _buy(qty=150),
        _buy(symbol="999999.SZ"),
        _sell(qty=200),
    ]
    outcome = _outcome(orders=orders, positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}])

    assert len(outcome.fills) == 1
    assert len(outcome.rejected_orders) == 3
    assert all(r.reason_code in REASON_CODES for r in outcome.rejected_orders)
    assert len(outcome.canceled_orders) == 4
    assert {c.reason_code for c in outcome.canceled_orders} == {CANCELED_REASON_CODE}
    day_end = [c for c in outcome.canceled_orders
               if c.detail == "unfilled day order canceled at session end"]
    assert [(c.symbol, c.side, c.qty) for c in day_end] == [(_SYM, "buy", 100.0)]


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
