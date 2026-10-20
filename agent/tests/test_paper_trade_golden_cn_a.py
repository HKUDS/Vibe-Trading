"""T2-gate cn_a golden sample: state+orders → fills/nav/end_state (Step 3 / T3).

Fees are hand-computed to the cent (VD-9 Decimal + ROUND_HALF_UP); the
arithmetic is written out in the comments of each test.  Offline by
construction: fake CH bar client + fake network loader + fake calendar
client, never the network (``--disable-socket`` is a hard gate).
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from src.tools.paper_trade import engine
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.rules import MarketRules
from src.tools.paper_trade.schema import parse_request

# §4 cn_a default fee matrix (state_hash._DEFAULT_FEE_MODELS terminal values).
_FEE_MODEL = {
    "commission_rate": 0.00025,  # 万2.5 bilateral
    "commission_min": 5.0,  # ¥5 minimum
    "stamp_tax_sell": 0.0005,  # 万5 sell-only
    "transfer_fee": 0.00001,  # 万0.1 bilateral
}

_DAY = "2026-10-20"  # Tuesday
_PREV = "2026-10-19"


class FakeChClient:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._frames.get(ts_code, pd.DataFrame())


class FakeLoader:
    def __init__(self, frames: dict[str, pd.DataFrame], name: str = "tencent") -> None:
        self.name = name
        self._frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {c: self._frames[c] for c in codes if c in self._frames}


class FakeCalendarClient:
    """CH trade_calendar rows; the golden week is fully open on the target."""

    def __init__(self, open_days: tuple[str, ...] = (_DAY,)) -> None:
        self._open = set(open_days)

    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = []
        for day in pd.date_range(start_date, end_date):
            iso = day.strftime("%Y-%m-%d")
            rows.append({"exchange": "SSE", "cal_date": iso, "is_open": int(iso in self._open),
                         "pretrade_date": ""})
        return pd.DataFrame(rows, columns=["exchange", "cal_date", "is_open", "pretrade_date"])


def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    records = [
        {"trade_date": day, "open": close, "high": close, "low": close, "close": close, "volume": 1000.0}
        for day, close in rows
    ]
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


def _fetch(frames: dict[str, pd.DataFrame], symbols: list[str], day: str = _DAY):
    return fetch_market_data(
        "cn_a", symbols, day, day, loader=FakeLoader(frames), ch_client=FakeChClient({})
    )


def _request(cash: float, positions: list[dict], orders: list[dict], day: str = _DAY):
    return parse_request({
        "account_id": "pa_golden_cn_a", "market": "cn_a",
        "account_state": {"cash": cash, "positions": positions},
        "orders": orders, "from_date": day, "to_date": day,
        "fee_model": dict(_FEE_MODEL),
    })


def _match(request, market_data, **kwargs) -> engine.MatchOutcome:
    return engine.match_orders(
        request, market_data=market_data,
        calendar_client=kwargs.pop("calendar_client", None) or FakeCalendarClient(),
        **kwargs,
    )


# 600519.SH: prev close 1418.0 (heuristic band 1276.20..1559.80), target 1421.0.
_FRAMES = {"600519.SH": _frame([(_PREV, 1418.0), (_DAY, 1421.0)])}


def test_cn_a_buy_golden_fee_hand_computed_to_the_cent() -> None:
    # Hand computation (VD-9, Decimal ROUND_HALF_UP):
    #   notional   = 100 × 1421.00            = 142100.00
    #   commission = max(142100.00 × 0.00025, 5.00) = max(35.525, 5) = 35.525
    #   transfer   = 142100.00 × 0.00001      = 1.421
    #   stamp(buy) = 0
    #   fee        = 35.525 + 1.421 = 36.946  → quantize 2dp HALF_UP = 36.95
    #   cash_end   = 200000.00 − 142100.00 − 36.95 = 57863.05
    #   nav        = 57863.05 + 100 × 1421.00 = 199963.05
    outcome = _match(_request(200000.0, [], [{"symbol": "600519.SH", "side": "buy", "qty": 100}]),
                     _fetch(_FRAMES, ["600519.SH"]))

    assert outcome.error is None
    assert len(outcome.fills) == 1
    fill = outcome.fills[0]
    assert (fill.trade_date, fill.symbol, fill.side, fill.qty) == (_DAY, "600519.SH", "buy", 100)
    assert fill.price == 1421.0  # fill price = close (§4)
    assert fill.fee == 36.95
    assert fill.reason == ""  # VD-15: orders mode
    assert outcome.rejected_orders == ()
    assert outcome.end_state.cash == 57863.05
    assert outcome.end_state.positions[0].symbol == "600519.SH"
    assert outcome.end_state.positions[0].qty == 100
    assert outcome.end_state.positions[0].avg_cost == 1421.0
    nav = outcome.nav_series[0]
    assert (nav.date, nav.nav, nav.cash, nav.position_value) == (_DAY, 199963.05, 57863.05, 142100.0)
    # VD-11: no limits client injected → heuristic band path, provenance recorded.
    assert any("limits:heuristic" in token for token in outcome.limit_provenance)


def test_cn_a_sell_golden_fee_hand_computed_to_the_cent() -> None:
    # Hand computation:
    #   notional   = 100 × 1425.50            = 142550.00
    #   commission = max(142550.00 × 0.00025, 5) = 35.6375
    #   transfer   = 142550.00 × 0.00001      = 1.4255
    #   stamp(sell)= 142550.00 × 0.0005      = 71.275
    #   fee        = 35.6375 + 1.4255 + 71.275 = 108.338 → 2dp HALF_UP = 108.34
    #   cash_end   = 1000.00 + 142550.00 − 108.34 = 143441.66
    frames = {"600519.SH": _frame([(_PREV, 1421.0), (_DAY, 1425.5)])}
    outcome = _match(
        _request(1000.0, [{"symbol": "600519.SH", "qty": 100, "avg_cost": 1418.0}],
                 [{"symbol": "600519.SH", "side": "sell", "qty": 100}]),
        _fetch(frames, ["600519.SH"]),
    )

    assert outcome.error is None
    assert outcome.fills[0].fee == 108.34
    assert outcome.end_state.cash == 143441.66
    assert outcome.end_state.positions == ()  # fully closed, zero-qty dropped
    assert outcome.nav_series[0].nav == 143441.66
    assert outcome.nav_series[0].position_value == 0.0


def test_cn_a_commission_minimum_dominates_small_orders() -> None:
    # Hand computation: notional = 100 × 10.00 = 1000.00
    #   commission = max(1000 × 0.00025 = 0.25, 5.00) = 5.00
    #   transfer   = 1000 × 0.00001 = 0.01
    #   fee        = 5.01
    frames = {"600519.SH": _frame([(_PREV, 10.0), (_DAY, 10.0)])}
    outcome = _match(_request(100000.0, [], [{"symbol": "600519.SH", "side": "buy", "qty": 100}]),
                     _fetch(frames, ["600519.SH"]))
    assert outcome.fills[0].fee == 5.01
    assert outcome.end_state.cash == 100000.0 - 1000.0 - 5.01


def test_cn_a_avg_cost_is_the_fee_exclusive_weighted_average() -> None:
    # Existing 100 @ 10.00 + buy 100 @ close 11.00:
    #   avg_cost = (100×10.00 + 100×11.00) / 200 = 10.50 (fee-exclusive, 4dp)
    #   fee: notional 1100 → comm max(0.275, 5) = 5, transfer 0.011 → 5.011 → 5.01
    #   cash = 5000 − 1100.00 − 5.01 = 3894.99; nav = 3894.99 + 200×11.00 = 6094.99
    frames = {"600519.SH": _frame([(_PREV, 10.5), (_DAY, 11.0)])}
    outcome = _match(
        _request(5000.0, [{"symbol": "600519.SH", "qty": 100, "avg_cost": 10.0}],
                 [{"symbol": "600519.SH", "side": "buy", "qty": 100}]),
        _fetch(frames, ["600519.SH"]),
    )
    position = outcome.end_state.positions[0]
    assert (position.qty, position.avg_cost) == (200, 10.5)
    assert outcome.fills[0].fee == 5.01
    assert outcome.end_state.cash == 3894.99
    assert outcome.nav_series[0].nav == 6094.99


def test_decimal_fee_matches_the_reused_engine_primitive_values() -> None:
    # E2/VD-2 numeric-agreement pin: the Decimal matrix equals the reused
    # ChinaAEngine.calc_commission float primitive (pre-quantization), and the
    # quantized terminal value is the hand-computed cent.
    from backtest.engines.china_a import ChinaAEngine

    primitive = ChinaAEngine({})
    rules = MarketRules("cn_a", _FEE_MODEL)
    buy_float = primitive.calc_commission(100, 1421.0, 1, True)
    sell_float = primitive.calc_commission(100, 1425.5, -1, False)
    assert buy_float == pytest.approx(36.946, abs=1e-9)
    assert sell_float == pytest.approx(108.338, abs=1e-9)
    assert abs(float(rules.fee("buy", 100, 1421.0)) - buy_float) <= 0.005
    assert abs(float(rules.fee("sell", 100, 1425.5)) - sell_float) <= 0.005
    assert rules.fee("buy", 100, 1421.0) == Decimal("36.95")
    assert rules.fee("sell", 100, 1425.5) == Decimal("108.34")


def test_serial_matching_input_order_decides_who_gets_the_cash() -> None:
    # VD-10: orders array order = matching order (frozen tie-breaker).
    # cash 142200.00; 600519.SH buy cost = 142100.00 + 36.95 = 142136.95;
    # 000001.SZ buy cost = 1000.00 + 5.01 = 1005.01.  Both do NOT fit.
    frames = {
        "600519.SH": _frame([(_PREV, 1418.0), (_DAY, 1421.0)]),
        "000001.SZ": _frame([(_PREV, 9.9), (_DAY, 10.0)]),
    }
    market_data = _fetch(frames, ["000001.SZ", "600519.SH"])
    big = {"symbol": "600519.SH", "side": "buy", "qty": 100}
    small = {"symbol": "000001.SZ", "side": "buy", "qty": 100}

    forward = _match(_request(142200.0, [], [big, small]), market_data)
    assert [f.symbol for f in forward.fills] == ["600519.SH"]
    assert forward.rejected_orders[0].symbol == "000001.SZ"
    assert forward.rejected_orders[0].reason_code == "insufficient_cash"
    # nav = 63.05 + 100×1421.00 = 142163.05
    assert forward.nav_series[0].nav == 142163.05

    reversed_ = _match(_request(142200.0, [], [small, big]), market_data)
    assert [f.symbol for f in reversed_.fills] == ["000001.SZ"]
    assert reversed_.rejected_orders[0].symbol == "600519.SH"
    assert reversed_.rejected_orders[0].reason_code == "insufficient_cash"


def test_fee_model_override_flows_through_to_the_effective_values() -> None:
    # R7-3 pass-through (T5 finalizes the wire echo): an injected override
    # wins over the default.  notional 1000 → comm 1000×0.01 = 10.00,
    # transfer 0.01 → fee 10.01.
    frames = {"600519.SH": _frame([(_PREV, 10.0), (_DAY, 10.0)])}
    request = parse_request({
        "account_id": "pa_golden_cn_a", "market": "cn_a",
        "account_state": {"cash": 100000.0, "positions": []},
        "orders": [{"symbol": "600519.SH", "side": "buy", "qty": 100}],
        "from_date": _DAY, "to_date": _DAY,
        "fee_model": {**_FEE_MODEL, "commission_rate": 0.01},
    })
    outcome = _match(request, _fetch(frames, ["600519.SH"]))
    assert outcome.fills[0].fee == 10.01
    assert outcome.effective_fee_model["commission_rate"] == 0.01
    assert outcome.effective_fee_model["commission_min"] == 5.0


def test_same_inputs_produce_identical_outcomes() -> None:
    # Determinism (R1-1) at the outcome level; byte-level sha goldens are T5.
    market_data = _fetch(_FRAMES, ["600519.SH"])
    request = _request(200000.0, [], [{"symbol": "600519.SH", "side": "buy", "qty": 100}])
    first = _match(request, market_data)
    second = _match(request, market_data)
    assert first.fills == second.fills
    assert first.rejected_orders == second.rejected_orders
    assert first.nav_series == second.nav_series
    assert first.end_state == second.end_state
    assert first.warnings == second.warnings
    assert first.effective_fee_model == second.effective_fee_model
