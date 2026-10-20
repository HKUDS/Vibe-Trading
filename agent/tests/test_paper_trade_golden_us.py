"""T2-gate us golden sample: state+orders → fills/nav/end_state (Step 3 / T3).

Market data = the VD-14 recorded sina fixture (us_AAPL_sina.json, raw
caliber, last bar 2026-10-16 close 343.46).  Fees hand-computed to the cent
(VD-9): commission $0.0049/share min $0.99, SEC fee simplified to 0 (§4 —
the registered terminal value; any micro-adjustment is a delivery-note
item).  Offline: fixture-backed fake loader only (``--disable-socket``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.tools.paper_trade import engine
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import parse_request

_FIXTURE = Path(__file__).parent / "fixtures" / "paper_trade" / "market" / "us_AAPL_sina.json"
_DAY = "2026-10-16"  # fixture's last bar; close 343.46
_CLOSE = 343.46

# §4 us default fee matrix (state_hash._DEFAULT_FEE_MODELS terminal values).
_FEE_MODEL = {
    "commission_per_share": 0.0049,  # $0.0049/share
    "commission_min": 0.99,  # $0.99 minimum
    "sec_fee_rate": 0.0,  # simplified to zero (§4)
}


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "sina") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


def _fixture_frame() -> pd.DataFrame:
    document = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    frame = pd.DataFrame(document["bars"])
    frame["trade_date"] = pd.to_datetime(frame["date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _fetch(symbols: list[str]):
    return fetch_market_data(
        "us", symbols, _DAY, _DAY, loader=FakeLoader({"AAPL.US": _fixture_frame()})
    )


def _request(cash: float, positions: list[dict], orders: list[dict]):
    return parse_request({
        "account_id": "pa_golden_us", "market": "us",
        "account_state": {"cash": cash, "positions": positions},
        "orders": orders, "from_date": _DAY, "to_date": _DAY,
        "fee_model": dict(_FEE_MODEL),
    })


def test_us_buy_golden_fee_hand_computed_to_the_cent() -> None:
    # Hand computation (VD-9, Decimal ROUND_HALF_UP), close = 343.46:
    #   notional   = 10 × 343.46              = 3434.60
    #   commission = max(10 × 0.0049 = 0.049, 0.99) = 0.99 (minimum dominates)
    #   SEC fee    = 3434.60 × 0.0 = 0        (§4 simplified)
    #   fee        = 0.99
    #   cash_end   = 50000.00 − 3434.60 − 0.99 = 46564.41
    #   nav        = 46564.41 + 10 × 343.46 = 49999.01
    outcome = engine.match_orders(
        _request(50000.0, [], [{"symbol": "AAPL.US", "side": "buy", "qty": 10}]),
        market_data=_fetch(["AAPL.US"]),
    )

    assert outcome.error is None
    fill = outcome.fills[0]
    assert (fill.trade_date, fill.symbol, fill.side, fill.qty) == (_DAY, "AAPL.US", "buy", 10)
    assert fill.price == _CLOSE  # fill price = close (§4)
    assert fill.fee == 0.99
    assert fill.reason == ""  # VD-15: orders mode
    assert outcome.end_state.cash == 46564.41
    assert outcome.end_state.positions[0].qty == 10
    assert outcome.end_state.positions[0].avg_cost == _CLOSE
    nav = outcome.nav_series[0]
    assert (nav.date, nav.nav, nav.cash, nav.position_value) == (_DAY, 49999.01, 46564.41, 3434.6)
    assert outcome.warnings == ()  # us lot = 1 share: no board-lot assumptions


def test_us_commission_scales_above_the_minimum() -> None:
    # Hand computation: 1000 shares → commission = max(1000 × 0.0049 = 4.90,
    # 0.99) = 4.90; notional = 1000 × 343.46 = 343460.00
    #   cash_end = 400000.00 − 343460.00 − 4.90 = 56535.10
    #   nav      = 56535.10 + 343460.00 = 399995.10
    outcome = engine.match_orders(
        _request(400000.0, [], [{"symbol": "AAPL.US", "side": "buy", "qty": 1000}]),
        market_data=_fetch(["AAPL.US"]),
    )
    assert outcome.fills[0].fee == 4.9
    assert outcome.end_state.cash == 56535.10
    assert outcome.nav_series[0].nav == 399995.10


def test_us_fractional_qty_violates_the_one_share_lot() -> None:
    # §4 lot row: us = 1 share — fractional qty rejects lot_size (the paper
    # engine never rounds a user-stated qty), structured and no crash.
    outcome = engine.match_orders(
        _request(50000.0, [], [{"symbol": "AAPL.US", "side": "buy", "qty": 1.5}]),
        market_data=_fetch(["AAPL.US"]),
    )
    assert outcome.fills == ()
    assert outcome.rejected_orders[0].reason_code == "lot_size"
    assert outcome.end_state.cash == 50000.0
    assert len(outcome.nav_series) == 1  # the day still commits its nav row


def test_us_same_day_sell_then_buy_both_fill_t0() -> None:
    # §4 settlement row: us is T+0.  Sell the seeded 10 shares, buy 10 back:
    #   sell proceeds = 3434.60 − 0.99 = 3433.61
    #   buy cost      = 3434.60 + 0.99 = 3435.59
    #   cash_end = 50000.00 + 3433.61 − 3435.59 = 49998.02
    #   new avg_cost = 343.46 (re-opened at the fill price)
    #   nav = 49998.02 + 10 × 343.46 = 53432.62
    outcome = engine.match_orders(
        _request(50000.0, [{"symbol": "AAPL.US", "qty": 10, "avg_cost": 340.0}], [
            {"symbol": "AAPL.US", "side": "sell", "qty": 10},
            {"symbol": "AAPL.US", "side": "buy", "qty": 10},
        ]),
        market_data=_fetch(["AAPL.US"]),
    )
    assert outcome.error is None
    assert [(f.side, f.fee) for f in outcome.fills] == [("sell", 0.99), ("buy", 0.99)]
    assert outcome.rejected_orders == ()
    assert outcome.end_state.cash == 49998.02
    assert outcome.end_state.positions[0].avg_cost == _CLOSE
    assert outcome.nav_series[0].nav == 53432.62


def test_us_golden_is_deterministic() -> None:
    market_data = _fetch(["AAPL.US"])
    request = _request(50000.0, [], [{"symbol": "AAPL.US", "side": "buy", "qty": 10}])
    first = engine.match_orders(request, market_data=market_data)
    second = engine.match_orders(request, market_data=market_data)
    assert first.fills == second.fills
    assert first.nav_series == second.nav_series
    assert first.end_state == second.end_state
    assert first.warnings == second.warnings
