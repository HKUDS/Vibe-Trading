"""T3-gate negative-path matrix for the paper_trade matching engine.

Covers every frozen reason_code (≥1 case each, 11 total), the AM-14
first-match order (multi-reason orders report only the first hit), the
t_plus_1/insufficient_position discrimination (available = total −
bought_today), same-symbol dual orders (buy→sell rejects the sell t_plus_1;
sell→buy both fill), the AM-6 skipped-day semantics (cn_a non_trading_day /
hk-us market_closed_inferred + warning), the R-V3 sanity-gate mapping
(suspended), the T4 corporate-action seam, and the no-crash / no-half-day
invariants.  Offline: fake loader / CH / calendar clients only.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools.paper_trade import engine
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.rules import REJECTION_ORDER
from src.tools.paper_trade.schema import REASON_CODES, AccountState, Order, parse_request

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
    def __init__(self, open_days: frozenset[str]) -> None:
        self._open = open_days

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {"exchange": "SSE", "cal_date": day.strftime("%Y-%m-%d"),
             "is_open": int(day.strftime("%Y-%m-%d") in self._open), "pretrade_date": ""}
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()  # served as an empty window → unknown_symbol facts
    records = [
        {"trade_date": day, "open": close, "high": close, "low": close, "close": close, "volume": 1000.0}
        for day, close in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


# Default cn_a tape: prev close 10.0 → heuristic band 9.00..11.00; target 10.5.
_TAPE = {_SYM: _frame([(_PREV, 10.0), (_DAY, 10.5)])}


def _fetch_cn_a(frames: dict[str, pd.DataFrame] | None = None, symbols: list[str] | None = None,
                from_date: str = _DAY, to_date: str = _DAY):
    frames = _TAPE if frames is None else frames
    symbols = symbols if symbols is not None else list(frames)
    return fetch_market_data("cn_a", symbols, from_date, to_date,
                             loader=FakeLoader(frames), ch_client=FakeChClient())


def _cn_a(cash=100000.0, positions=(), orders=(), frames=None, symbols=None,
          open_days=frozenset({_DAY}), from_date=_DAY, to_date=_DAY, **kwargs):
    market_data = _fetch_cn_a(frames, symbols, from_date, to_date)
    request = parse_request({
        "account_id": "pa_rej", "market": "cn_a",
        "account_state": {"cash": cash, "positions": list(positions)},
        "orders": list(orders), "from_date": from_date, "to_date": to_date, "fee_model": {},
    })
    return engine.match_orders(request, market_data=market_data,
                               calendar_client=FakeCalendarClient(open_days), **kwargs)


def _buy(symbol=_SYM, qty=100, limit=None):
    order = {"symbol": symbol, "side": "buy", "qty": qty}
    if limit is not None:
        order["limit"] = limit
    return order


def _sell(symbol=_SYM, qty=100, limit=None):
    order = {"symbol": symbol, "side": "sell", "qty": qty}
    if limit is not None:
        order["limit"] = limit
    return order


def _codes(outcome) -> list[str]:
    return [rejected.reason_code for rejected in outcome.rejected_orders]


# ── The frozen ladder itself ──


def test_rejection_order_constant_is_the_am14_frozen_sequence() -> None:
    assert REJECTION_ORDER == (
        "unknown_symbol", "non_trading_day", "suspended", "corporate_action_unresolved",
        "lot_size", "limit_up", "limit_down", "limit_not_marketable",
        "t_plus_1", "insufficient_position", "insufficient_cash",
    )
    assert len(REJECTION_ORDER) == 11
    assert set(REJECTION_ORDER) <= set(REASON_CODES)  # closed vocabulary


# ── One case per frozen reason_code ──


def test_unknown_symbol_when_the_window_served_no_bar_at_all() -> None:
    outcome = _cn_a(orders=[_buy("999999.SH")], symbols=[_SYM, "999999.SH"],
                    frames={**_TAPE, "999999.SH": _frame([])})
    assert _codes(outcome) == ["unknown_symbol"]
    assert "999999.SH" in outcome.rejected_orders[0].detail
    assert outcome.fills == ()


def test_non_trading_day_skips_the_day_and_rejects_its_orders() -> None:
    outcome = _cn_a(orders=[_buy()], open_days=frozenset())  # calendar closed
    assert _codes(outcome) == ["non_trading_day"]
    assert [(s.date, s.reason) for s in outcome.skipped_days] == [(_DAY, "non_trading_day")]
    assert outcome.nav_series == ()  # R3: skipped days produce NO nav row
    assert outcome.fills == ()
    assert outcome.end_state.cash == 100000.0  # state untouched — no half-day


def test_suspended_when_the_symbol_has_no_bar_today() -> None:
    # Halted symbol: bar yesterday, none today; a healthy symbol still fills.
    frames = {
        _SYM: _TAPE[_SYM],
        "000001.SZ": _frame([(_PREV, 10.0)]),  # no target-day bar
    }
    outcome = _cn_a(
        positions=[{"symbol": "000001.SZ", "qty": 100, "avg_cost": 9.5}],
        orders=[_buy("000001.SZ"), _buy(_SYM)],
        frames=frames, symbols=[_SYM, "000001.SZ"],
    )
    assert _codes(outcome) == ["suspended"]
    assert outcome.rejected_orders[0].symbol == "000001.SZ"
    assert [f.symbol for f in outcome.fills] == [_SYM]
    # Carry-forward valuation: the halted position values at its last close
    # (10.0), not avg_cost — nav = cash + 100×10.5 (filled) + 100×10.0.
    cash = 100000.0 - 1050.0 - 5.01
    assert outcome.nav_series[0].position_value == 100 * 10.5 + 100 * 10.0
    assert outcome.nav_series[0].nav == pytest.approx(cash + 2050.0)


def test_corporate_action_unresolved_through_the_injectable_t4_seam() -> None:
    # The detector is T4; the slot + rejection channel are reserved and
    # injectable per day (default empty ⇒ never fires).
    outcome = _cn_a(orders=[_buy()], corporate_action_unresolved_by_day={_DAY: [_SYM]})
    assert _codes(outcome) == ["corporate_action_unresolved"]
    assert "fail-closed" in outcome.rejected_orders[0].detail
    default = _cn_a(orders=[_buy()])
    assert _codes(default) == [] and len(default.fills) == 1


def test_lot_size_rejections_for_illegal_quantities() -> None:
    for qty in (150, 99, 0, -100, 100.5):
        outcome = _cn_a(orders=[_buy(qty=qty)])
        assert _codes(outcome) == ["lot_size"], qty
        assert "100-share" in outcome.rejected_orders[0].detail
    assert _codes(_cn_a(orders=[_sell(qty=150)],
                        positions=[{"symbol": _SYM, "qty": 200, "avg_cost": 10.0}])) == ["lot_size"]


def test_limit_up_rejects_a_buy_at_the_upper_band() -> None:
    # prev 10.0 → heuristic up limit 11.00; close 11.0 = band → buy rejected.
    frames = {_SYM: _frame([(_PREV, 10.0), (_DAY, 11.0)])}
    outcome = _cn_a(orders=[_buy()], frames=frames)
    assert _codes(outcome) == ["limit_up"]
    assert "up limit 11.00" in outcome.rejected_orders[0].detail


def test_limit_down_rejects_a_sell_at_the_lower_band() -> None:
    # prev 10.0 → down limit 9.00; close 9.0 = band → sell rejected.
    frames = {_SYM: _frame([(_PREV, 10.0), (_DAY, 9.0)])}
    outcome = _cn_a(positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}],
                    orders=[_sell()], frames=frames)
    assert _codes(outcome) == ["limit_down"]
    assert "down limit 9.00" in outcome.rejected_orders[0].detail


def test_limit_not_marketable_rejects_a_buy_above_the_limit() -> None:
    outcome = _cn_a(orders=[_buy(limit=10.0)])  # close 10.5 > limit 10.0
    assert _codes(outcome) == ["limit_not_marketable"]
    assert outcome.rejected_orders[0].detail == "close 10.50 > limit 10.00"


def test_t_plus_1_rejects_selling_shares_bought_the_same_day() -> None:
    outcome = _cn_a(orders=[_buy(), _sell()])  # buy fills first (VD-10 order)
    assert [f.side for f in outcome.fills] == ["buy"]
    assert _codes(outcome) == ["t_plus_1"]
    assert "T+1" in outcome.rejected_orders[0].detail


def test_insufficient_position_when_qty_exceeds_the_total_holding() -> None:
    outcome = _cn_a(positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}],
                    orders=[_sell(qty=200)])
    assert _codes(outcome) == ["insufficient_position"]
    outcome_empty = _cn_a(orders=[_sell(qty=100)])  # no position at all
    assert _codes(outcome_empty) == ["insufficient_position"]


def test_insufficient_cash_when_cost_exceeds_cash() -> None:
    # cost = 100 × 10.50 + 5.01 = 1055.01 > 100.00
    outcome = _cn_a(cash=100.0, orders=[_buy()])
    assert _codes(outcome) == ["insufficient_cash"]
    assert "exceeds cash" in outcome.rejected_orders[0].detail
    assert outcome.end_state.cash == 100.0


# ── t_plus_1 vs insufficient_position discrimination (AM-14 note) ──


def test_discrimination_total_vs_available_position() -> None:
    held = [{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}]
    # buy 100 today → total 200, available 100.  sell 200: total ≥ qty >
    # available → t_plus_1 (NOT insufficient_position).
    t1 = _cn_a(positions=held, orders=[_buy(), _sell(qty=200)])
    assert [f.side for f in t1.fills] == ["buy"]
    assert _codes(t1) == ["t_plus_1"]
    # sell 300: qty > total → insufficient_position.
    ip = _cn_a(positions=held, orders=[_buy(), _sell(qty=300)])
    assert _codes(ip) == ["insufficient_position"]
    # sell 100: qty ≤ available → fills.
    ok = _cn_a(positions=held, orders=[_buy(), _sell(qty=100)])
    assert _codes(ok) == [] and [f.side for f in ok.fills] == ["buy", "sell"]


def test_same_symbol_sell_then_buy_both_fill_on_the_same_day() -> None:
    outcome = _cn_a(positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}],
                    orders=[_sell(), _buy()])
    assert _codes(outcome) == []
    assert [f.side for f in outcome.fills] == ["sell", "buy"]
    assert outcome.end_state.positions[0].qty == 100


# ── AM-14 first-match: multi-reason orders report ONLY the first hit ──


def test_first_match_unknown_symbol_beats_non_trading_day() -> None:
    outcome = _cn_a(orders=[_buy("999999.SH")], symbols=[_SYM, "999999.SH"],
                    frames={**_TAPE, "999999.SH": _frame([])}, open_days=frozenset())
    assert _codes(outcome) == ["unknown_symbol"]  # slot 1, not slot 2


def test_first_match_suspended_beats_lot_size() -> None:
    # The healthy _SYM bar keeps the target day ready (AM-6①); the halted
    # symbol's order hits slot 3 (suspended) before slot 5 (lot_size).
    frames = {**_TAPE, "000001.SZ": _frame([(_PREV, 10.0)])}
    outcome = _cn_a(orders=[_buy("000001.SZ", qty=150)], frames=frames,
                    symbols=[_SYM, "000001.SZ"])
    assert _codes(outcome) == ["suspended"]  # slot 3, not slot 5


def test_first_match_corporate_action_beats_lot_size_and_suspended() -> None:
    seam = {_DAY: [_SYM, "000001.SZ"]}
    ca_lot = _cn_a(orders=[_buy(qty=150)], corporate_action_unresolved_by_day=seam)
    assert _codes(ca_lot) == ["corporate_action_unresolved"]  # slot 4, not slot 5
    frames = {**_TAPE, "000001.SZ": _frame([(_PREV, 10.0)])}
    ca_susp = _cn_a(orders=[_buy("000001.SZ")], frames=frames, symbols=[_SYM, "000001.SZ"],
                    corporate_action_unresolved_by_day=seam)
    assert _codes(ca_susp) == ["suspended"]  # slot 3, not slot 4


def test_first_match_lot_size_beats_insufficient_cash() -> None:
    outcome = _cn_a(cash=1.0, orders=[_buy(qty=150)])
    assert _codes(outcome) == ["lot_size"]  # slot 5, not slot 10


def test_first_match_limit_up_beats_limit_not_marketable() -> None:
    # close 11.0 = up band AND above the 10.00 limit → limit_up wins (slot 6).
    frames = {_SYM: _frame([(_PREV, 10.0), (_DAY, 11.0)])}
    outcome = _cn_a(orders=[_buy(limit=10.0)], frames=frames)
    assert _codes(outcome) == ["limit_up"]


# ── R-V3 price sanity gate → suspended (documented mapping) ──


def test_untradable_bar_rejects_suspended_and_values_carry_forward() -> None:
    frames = {_SYM: _frame([(_PREV, 10.0), (_DAY, -3.5)])}  # additive-qfq gone negative
    outcome = _cn_a(positions=[{"symbol": _SYM, "qty": 100, "avg_cost": 9.0}],
                    orders=[_buy()], frames=frames)
    assert _codes(outcome) == ["suspended"]
    assert "price sanity gate" in outcome.rejected_orders[0].detail
    # Valuation skips the non-positive bar: 100 × last positive close 10.0.
    assert outcome.nav_series[0].position_value == 1000.0
    assert any("price sanity" in w for w in outcome.warnings)  # data-layer warning kept


# ── Day-level semantics: skipped days, multi-day loop, no half-day ──


def test_mixed_day_commits_exactly_one_nav_row_and_a_consistent_ledger() -> None:
    outcome = _cn_a(cash=2000.0, orders=[_buy(), _buy(qty=200)])  # second: no cash
    assert len(outcome.fills) == 1 and _codes(outcome) == ["insufficient_cash"]
    assert len(outcome.nav_series) == 1  # per-day atomicity: one nav row
    nav = outcome.nav_series[0]
    # cash = 2000 − 1050.00 − 5.01 = 944.99; position 100 × 10.5 = 1050.00
    assert nav.cash == 944.99 and nav.position_value == 1050.0
    assert nav.nav == 1994.99
    assert outcome.end_state.cash == nav.cash  # ledger ↔ nav consistent


def test_cn_a_multiday_loop_skips_closed_days_and_resets_t_plus_1() -> None:
    # Mon 10-19 open, Tue 10-20 closed, Wed 10-21 open.  Buy Monday, an
    # order on the closed Tuesday rejects non_trading_day, sell Wednesday
    # (T+1 availability resets each day; day-1 state carries into day-3).
    frames = {_SYM: _frame([("2026-10-16", 9.9), ("2026-10-19", 10.0), ("2026-10-21", 10.2)])}
    market_data = _fetch_cn_a(frames, [_SYM], "2026-10-19", "2026-10-21")
    outcome = engine.run_day_loop(
        market="cn_a",
        account_state=AccountState(cash=100000.0),
        from_date="2026-10-19", to_date="2026-10-21",
        orders_by_day={
            "2026-10-19": (Order(_SYM, "buy", 100),),
            "2026-10-20": (Order(_SYM, "buy", 100),),
            "2026-10-21": (Order(_SYM, "sell", 100),),
        },
        market_data=market_data,
        calendar_client=FakeCalendarClient(frozenset({"2026-10-19", "2026-10-21"})),
    )
    assert outcome.error is None
    assert [(s.date, s.reason) for s in outcome.skipped_days] == [("2026-10-20", "non_trading_day")]
    assert _codes(outcome) == ["non_trading_day"]
    assert [f.trade_date for f in outcome.fills] == ["2026-10-19", "2026-10-21"]
    assert [n.date for n in outcome.nav_series] == ["2026-10-19", "2026-10-21"]  # ascending, no skip row
    # Monday: fee 5.01 → cash 98994.99, nav 99994.99.  Wednesday: sell
    # notional 1020.00, fee = 5 + 0.0102 + 0.51 = 5.5202 → 5.52;
    # cash = 98994.99 + 1020.00 − 5.52 = 100009.47.
    assert outcome.nav_series[0].nav == 99994.99
    assert outcome.fills[1].fee == 5.52
    assert outcome.end_state.cash == 100009.47
    assert outcome.end_state.positions == ()


def test_hk_mid_range_zero_bar_is_market_closed_inferred_with_warning() -> None:
    # AM-6②: Mon/Wed served, Tue all-market zero bar → skipped
    # market_closed_inferred + mandatory warning; NEVER non_trading_day.
    frames = {"00700.HK": _frame([("2026-10-19", 100.0), ("2026-10-21", 102.0)])}
    market_data = fetch_market_data("hk", ["00700.HK"], "2026-10-19", "2026-10-21",
                                    loader=FakeLoader(frames))
    outcome = engine.run_day_loop(
        market="hk",
        account_state=AccountState(cash=100000.0),
        from_date="2026-10-19", to_date="2026-10-21",
        orders_by_day={
            "2026-10-19": (Order("00700.HK", "buy", 100),),
            "2026-10-20": (Order("00700.HK", "buy", 100),),  # defensive: rejected suspended
            "2026-10-21": (Order("00700.HK", "sell", 100),),
        },
        market_data=market_data,
    )
    assert outcome.error is None
    assert [(s.date, s.reason) for s in outcome.skipped_days] == [
        ("2026-10-20", "market_closed_inferred")]
    assert any("2026-10-20" in w and "inferred closed" in w for w in outcome.warnings)
    assert "non_trading_day" not in {s.reason for s in outcome.skipped_days}
    assert _codes(outcome) == ["suspended"]  # the closed day's defensive order
    # Mon buy: notional 10000, comm max(3.0, 3) = 3.00, stamp 10 → 10,
    # levy 0.3 → fee 13.30; cash 89986.70, nav 99986.70.
    # Wed sell: notional 10200, comm 3.06, stamp 10.2 → 10, levy 0.306 →
    # fee 13.366 → 13.37; cash 89986.70 + 10200.00 − 13.37 = 100173.33.
    assert outcome.fills[0].fee == 13.3 and outcome.fills[1].fee == 13.37
    assert [n.date for n in outcome.nav_series] == ["2026-10-19", "2026-10-21"]
    assert outcome.nav_series[0].nav == 99986.7
    assert outcome.end_state.cash == 100173.33


def test_hk_empty_universe_short_circuits_the_classifier_to_cash_only_navs() -> None:
    # T2 handoff contradiction: assess_readiness treats an empty universe as
    # vacuously ready while classify_zero_calendar_day reads it literally as
    # all-market zero bar.  A cash-only account must still get its nav rows —
    # the engine short-circuits the classifier (success proves it: a
    # classified target day would have failed the run).
    market_data = fetch_market_data("hk", [], "2026-10-19", "2026-10-20",
                                    loader=FakeLoader({}))
    outcome = engine.run_day_loop(
        market="hk", account_state=AccountState(cash=5000.0),
        from_date="2026-10-19", to_date="2026-10-20", orders_by_day={},
        market_data=market_data,
    )
    assert outcome.error is None
    assert outcome.skipped_days == ()
    assert [(n.date, n.nav, n.position_value) for n in outcome.nav_series] == [
        ("2026-10-19", 5000.0, 0.0), ("2026-10-20", 5000.0, 0.0)]


def test_target_day_all_market_zero_bar_returns_not_ready_material() -> None:
    # AM-6①/AM-9: the in-band PAPER_DATA_NOT_READY material, never matching
    # on stale data, never an exception.
    frames = {_SYM: _frame([(_PREV, 10.0)])}  # target day missing everywhere
    outcome = _cn_a(orders=[_buy()], frames=frames)
    assert outcome.error is not None
    assert outcome.error.code == "PAPER_DATA_NOT_READY"
    assert f"target bar {_DAY}" in outcome.error.message
    assert outcome.fills == () and outcome.nav_series == () and outcome.rejected_orders == ()
