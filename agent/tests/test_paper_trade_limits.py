"""T13-gate limit-order semantics matrix (AM-7 frozen, Step 3 / T3).

buy fills only when close ≤ limit / sell only when close ≥ limit, fill price
= close (marketable orders improve to the close); violation →
``limit_not_marketable``; cn_a band checks (limit_up/limit_down) take
precedence over the limit check (AM-14 order).  Offline: fake clients only.
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


def _run_cn_a(orders: list[dict], close: float, prev_close: float = 10.0,
              positions: list[dict] | None = None):
    frames = {_SYM: _frame([(_PREV, prev_close), (_DAY, close)])}
    market_data = fetch_market_data("cn_a", [_SYM], _DAY, _DAY,
                                    loader=FakeLoader(frames), ch_client=FakeChClient())
    request = parse_request({
        "account_id": "pa_limits", "market": "cn_a",
        "account_state": {"cash": 1000000.0, "positions": positions or []},
        "orders": orders, "from_date": _DAY, "to_date": _DAY, "fee_model": {},
    })
    return engine.match_orders(request, market_data=market_data,
                               calendar_client=FakeCalendarClient())


def _run_hk(orders: list[dict], close: float):
    frames = {"00700.HK": _frame([(_PREV, close * 0.99), (_DAY, close)])}
    market_data = fetch_market_data("hk", ["00700.HK"], _DAY, _DAY, loader=FakeLoader(frames))
    request = parse_request({
        "account_id": "pa_limits", "market": "hk",
        "account_state": {"cash": 1000000.0, "positions": []},
        "orders": orders, "from_date": _DAY, "to_date": _DAY, "fee_model": {},
    })
    return engine.match_orders(request, market_data=market_data)


# ── AM-7 matrix: buy side ──


def test_buy_limit_above_close_fills_at_the_close() -> None:
    outcome = _run_cn_a([{"symbol": _SYM, "side": "buy", "qty": 100, "limit": 11.0}], close=10.5)
    assert outcome.fills[0].price == 10.5  # price improves to the close
    assert outcome.rejected_orders == ()


def test_buy_limit_equal_to_close_fills_boundary_inclusive() -> None:
    # AM-7: buy fills when close ≤ limit — equality is marketable.
    outcome = _run_cn_a([{"symbol": _SYM, "side": "buy", "qty": 100, "limit": 10.5}], close=10.5)
    assert len(outcome.fills) == 1 and outcome.fills[0].price == 10.5


def test_buy_limit_below_close_is_rejected_limit_not_marketable() -> None:
    outcome = _run_cn_a([{"symbol": _SYM, "side": "buy", "qty": 100, "limit": 10.0}], close=10.5)
    assert outcome.fills == ()
    rejected = outcome.rejected_orders[0]
    assert rejected.reason_code == "limit_not_marketable"
    assert rejected.detail == "close 10.50 > limit 10.00"


# ── AM-7 matrix: sell side (symmetric) ──


def test_sell_limit_below_close_fills_at_the_close() -> None:
    held = [{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}]
    outcome = _run_cn_a([{"symbol": _SYM, "side": "sell", "qty": 100, "limit": 10.0}],
                        close=10.5, positions=held)
    assert outcome.fills[0].price == 10.5
    assert outcome.rejected_orders == ()


def test_sell_limit_equal_to_close_fills_boundary_inclusive() -> None:
    held = [{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}]
    outcome = _run_cn_a([{"symbol": _SYM, "side": "sell", "qty": 100, "limit": 10.5}],
                        close=10.5, positions=held)
    assert len(outcome.fills) == 1


def test_sell_limit_above_close_is_rejected_limit_not_marketable() -> None:
    held = [{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}]
    outcome = _run_cn_a([{"symbol": _SYM, "side": "sell", "qty": 100, "limit": 11.0}],
                        close=10.5, positions=held)
    assert outcome.fills == ()
    rejected = outcome.rejected_orders[0]
    assert rejected.reason_code == "limit_not_marketable"
    assert rejected.detail == "close 10.50 < limit 11.00"


def test_market_order_without_limit_fills_regardless_of_direction() -> None:
    outcome = _run_cn_a([{"symbol": _SYM, "side": "buy", "qty": 100}], close=10.5)
    assert len(outcome.fills) == 1 and outcome.fills[0].price == 10.5


# ── Band precedence (AM-14: limit_up/limit_down BEFORE limit_not_marketable) ──


def test_limit_up_wins_over_limit_not_marketable() -> None:
    # prev 10.0 → up band 11.00; close 11.0 is at the band AND above the
    # 10.00 limit — the frozen order reports limit_up (slot 6 before 7).
    outcome = _run_cn_a([{"symbol": _SYM, "side": "buy", "qty": 100, "limit": 10.0}], close=11.0)
    assert outcome.rejected_orders[0].reason_code == "limit_up"


def test_limit_down_wins_over_limit_not_marketable() -> None:
    # prev 10.0 → down band 9.00; close 9.0 at band AND below a 9.50 sell
    # limit — limit_down wins.
    held = [{"symbol": _SYM, "qty": 100, "avg_cost": 10.0}]
    outcome = _run_cn_a([{"symbol": _SYM, "side": "sell", "qty": 100, "limit": 9.5}],
                        close=9.0, positions=held)
    assert outcome.rejected_orders[0].reason_code == "limit_down"


def test_marketable_limit_inside_the_band_still_fills() -> None:
    # close 10.5, band 9.00..11.00, buy limit 10.5 → fills at the close.
    outcome = _run_cn_a([{"symbol": _SYM, "side": "buy", "qty": 100, "limit": 10.5}], close=10.5)
    assert len(outcome.fills) == 1


# ── hk: AM-7 applies, bands do NOT (§4: hk has no price limits) ──


def test_hk_limit_semantics_apply_without_band_codes() -> None:
    filled = _run_hk([{"symbol": "00700.HK", "side": "buy", "qty": 100, "limit": 10.5}], close=10.5)
    assert len(filled.fills) == 1 and filled.fills[0].price == 10.5
    rejected = _run_hk([{"symbol": "00700.HK", "side": "buy", "qty": 100, "limit": 10.0}], close=10.5)
    assert rejected.rejected_orders[0].reason_code == "limit_not_marketable"
    # A 10%+ up move never yields limit_up in hk — the code is cn_a-only.
    big_move = _run_hk([{"symbol": "00700.HK", "side": "buy", "qty": 100}], close=11.0)
    assert len(big_move.fills) == 1
    assert all(r.reason_code not in {"limit_up", "limit_down"} for r in big_move.rejected_orders)
