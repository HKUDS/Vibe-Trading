"""T2-gate hk golden sample: state+orders → fills/nav/end_state (Step 3 / T3).

Market data = the VD-14 recorded tencent fixture (hk_00700_tencent.json,
raw caliber, last bar 2026-10-16 close 417.8).  Fees hand-computed to the
cent (VD-9): commission 0.03% min HK$3 + stamp duty 0.1% per order per side
quantized to WHOLE HKD ROUND_HALF_UP (the registered VD-9 choice; HKEX
itself ceils) + regulatory levy 0.003%.  Offline: fixture-backed fake
loader only (``--disable-socket`` hard gate).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.tools.paper_trade import engine
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.rules import MarketRules
from src.tools.paper_trade.schema import parse_request

_FIXTURE = Path(__file__).parent / "fixtures" / "paper_trade" / "market" / "hk_00700_tencent.json"
_DAY = "2026-10-16"  # fixture's last bar; close 417.8
_CLOSE = 417.8

# §4 hk default fee matrix (state_hash._DEFAULT_FEE_MODELS terminal values).
_FEE_MODEL = {
    "commission_rate": 0.0003,  # 0.03%
    "commission_min": 3.0,  # HK$3 minimum
    "stamp_tax_rate": 0.001,  # 0.1% per order per side, whole HKD
    "regulatory_levy_rate": 0.00003,  # ≈0.003% combined levies
}


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "tencent") -> None:
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


def _fetch(symbols: list[str], frames: dict[str, pd.DataFrame] | None = None):
    frames = frames if frames is not None else {"00700.HK": _fixture_frame()}
    return fetch_market_data("hk", symbols, _DAY, _DAY, loader=FakeLoader(frames))


def _request(cash: float, positions: list[dict], orders: list[dict]):
    return parse_request({
        "account_id": "pa_golden_hk", "market": "hk",
        "account_state": {"cash": cash, "positions": positions},
        "orders": orders, "from_date": _DAY, "to_date": _DAY,
        "fee_model": dict(_FEE_MODEL),
    })


def test_hk_buy_golden_fee_hand_computed_to_the_cent() -> None:
    # Hand computation (VD-9, Decimal ROUND_HALF_UP), close = 417.8:
    #   notional   = 100 × 417.80             = 41780.00
    #   commission = max(41780 × 0.0003, 3)   = max(12.534, 3) = 12.534
    #   stamp      = 41780 × 0.001 = 41.78    → whole HKD HALF_UP = 42
    #   levy       = 41780 × 0.00003          = 1.2534
    #   fee        = 12.534 + 42 + 1.2534 = 55.7874 → 2dp HALF_UP = 55.79
    #   cash_end   = 100000.00 − 41780.00 − 55.79 = 58164.21
    #   nav        = 58164.21 + 100 × 417.80 = 99944.21
    outcome = engine.match_orders(
        _request(100000.0, [], [{"symbol": "00700.HK", "side": "buy", "qty": 100}]),
        market_data=_fetch(["00700.HK"]),
    )

    assert outcome.error is None
    fill = outcome.fills[0]
    assert (fill.trade_date, fill.symbol, fill.side, fill.qty) == (_DAY, "00700.HK", "buy", 100)
    assert fill.price == _CLOSE  # fill price = close (§4)
    assert fill.fee == 55.79
    assert fill.reason == ""  # VD-15: orders mode
    assert outcome.end_state.cash == 58164.21
    assert outcome.end_state.positions[0].qty == 100
    assert outcome.end_state.positions[0].avg_cost == _CLOSE
    nav = outcome.nav_series[0]
    assert (nav.date, nav.nav, nav.cash, nav.position_value) == (_DAY, 99944.21, 58164.21, 41780.0)
    # DD-4 fallback chain: no lot table entry → default 100 + diagnostic warning.
    assert any("lot assumption" in w and "0700.HK" in w for w in outcome.warnings)


def test_hk_stamp_tax_quantizes_half_up_to_whole_hkd_not_banker() -> None:
    # VD-9 pin: notional 40500 → stamp 40.5 → HALF_UP → 41
    # (Python's builtin banker's rounding would give 40).
    #   commission = max(40500 × 0.0003 = 12.15, 3) = 12.15
    #   levy       = 40500 × 0.00003 = 1.215
    #   fee        = 12.15 + 41 + 1.215 = 54.365 → 2dp HALF_UP = 54.37
    rules = MarketRules("hk", _FEE_MODEL)
    assert rules.fee("buy", 100, 405.0) == Decimal("54.37")
    assert round(40.5) == 40  # the banker's-rounding trap this matrix avoids


def test_hk_same_day_round_trip_is_allowed_t0() -> None:
    # §4 settlement row: hk is T+0 — buy→sell on the same day both fill.
    #   buy fee  = 55.79 (as above); sell fee identical at the same close
    #   cash_end = 100000 − 41780.00 − 55.79 + 41780.00 − 55.79 = 99888.42
    outcome = engine.match_orders(
        _request(100000.0, [], [
            {"symbol": "00700.HK", "side": "buy", "qty": 100},
            {"symbol": "00700.HK", "side": "sell", "qty": 100},
        ]),
        market_data=_fetch(["00700.HK"]),
    )
    assert outcome.error is None
    assert [(f.side, f.fee) for f in outcome.fills] == [("buy", 55.79), ("sell", 55.79)]
    assert outcome.rejected_orders == ()
    assert outcome.end_state.cash == 99888.42
    assert outcome.end_state.positions == ()
    assert outcome.nav_series[0].nav == 99888.42


def test_hk_order_violating_the_board_lot_is_rejected() -> None:
    # §4 lot row: qty 150 is not a multiple of the (default) 100-share board
    # lot → lot_size rejection, structured, no crash, cash untouched.
    outcome = engine.match_orders(
        _request(100000.0, [], [{"symbol": "00700.HK", "side": "buy", "qty": 150}]),
        market_data=_fetch(["00700.HK"]),
    )
    assert outcome.fills == ()
    rejected = outcome.rejected_orders[0]
    assert rejected.reason_code == "lot_size"
    assert "100-share" in rejected.detail
    assert outcome.end_state.cash == 100000.0
    assert len(outcome.nav_series) == 1  # the day still commits its nav row


def test_hk_lot_table_injection_overrides_the_default() -> None:
    # DD-4: an injected per-symbol lot table (live tencent quote idx-60 is a
    # T9b wiring concern) flows into the reused _hk_board_lot mechanism.
    rules = MarketRules("hk", _FEE_MODEL, hk_lot_sizes={"00700.HK": 400})
    assert rules.lot_size("00700.HK") == 400
    assert rules.lot_violation("00700.HK", 100) is True
    assert rules.lot_violation("00700.HK", 400) is False
    assert rules.lot_assumptions == {}  # table hit → no fallback diagnostic


def test_hk_golden_is_deterministic() -> None:
    market_data = _fetch(["00700.HK"])
    request = _request(100000.0, [], [{"symbol": "00700.HK", "side": "buy", "qty": 100}])
    first = engine.match_orders(request, market_data=market_data)
    second = engine.match_orders(request, market_data=market_data)
    assert first.fills == second.fills
    assert first.nav_series == second.nav_series
    assert first.end_state == second.end_state
    assert first.warnings == second.warnings
