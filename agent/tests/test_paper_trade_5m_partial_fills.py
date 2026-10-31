"""T9 gate — cn_a 5m ``fill_model="volume_share"`` partial fills.

The phase-3 contract (JoinQuant ``set_option('order_volume_ratio')`` /
``OrderStatus``; planbook IS-1..IS-3):

* a **market** order is capped once by
  ``floor(full continuous-session volume x ratio / lot) x lot`` and fills at
  the first live bar's reference; any residual is canceled immediately with
  ``canceled_after_volume_cap``;
* a **limit** order is capped per bar by
  ``floor(bar volume x ratio / lot) x lot``, fills at its 委托价, keeps its
  residual resting across bars, and is canceled at session end with the
  existing ``canceled_after_failed_match`` reason (never rejected);
* caps are **per order**, so two orders may collectively fill more than one
  bar's volume;
* every fill pays its own fee (two 100-share fills pay two ¥5 minimums);
* the cash/position gates evaluate the quantity that will actually trade, so
  a partial sell does not reject ``insufficient_position`` on its next bar and
  cash never goes negative;
* a zero-volume bar is never a matching opportunity.

Every case runs a synthetic cn_a 5m day through the fake loader used by the
other 5m suites (``_intraday`` + ``_FakeLoader``); no committed fixture is
added and no network is touched.  The request is driven through
``fill_model="volume_share"`` / ``order_volume_ratio`` only — this file never
imports ``volume_policy`` (T8 owns it).
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
import pytest

from src.tools.paper_trade import engine
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import CANCELED_REASON_CODE, parse_request
from src.tools.paper_trade.tool import run_paper_trade_step

_DAY = "2026-10-20"
_PREV = "2026-10-19"
_SYM = "600519.SH"

#: T10's new residual-cancel token (pt-v1.3 vocabulary); stated literally so a
#: missing implementation fails on behavior, not on an import error.
_VOLUME_CAP_REASON = "canceled_after_volume_cap"

#: transfer_fee is pinned to 0 so every 100-share fill is exactly the ¥5
#: commission minimum: two fills must total 10.00, one all-or-none fill 5.00.
_FEE_MODEL = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.0,
}

_LABELS = ("09:35", "09:40", "09:45")

# (open, high, low, close, volume)
Bar = tuple[float, float, float, float, float]


# ── synthetic 5m days (no committed fixture) ─────────────────────────────────


def _intraday(day: str, bars: tuple[Bar, ...]) -> pd.DataFrame:
    """On-grid continuous 5m bars; labels are bar ENDS (09:30 is the auction)."""
    records = [
        {
            "bar_time": f"{day} {label}",
            "open": bar[0],
            "high": bar[1],
            "low": bar[2],
            "close": bar[3],
            "volume": bar[4],
        }
        for label, bar in zip(_LABELS[: len(bars)], bars, strict=True)
    ]
    frame = pd.DataFrame(records)
    frame["bar_time"] = pd.to_datetime(frame["bar_time"])
    return frame.set_index("bar_time")


def _reference(bar: Bar) -> Decimal:
    """Recompute the bar_median reference independently of the engine."""
    open_, high, low, close = (Decimal(str(value)) for value in bar[:4])
    prices = sorted((open_, high, low, close))
    raw = (prices[1] + prices[2]) / Decimal(2)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _daily() -> pd.DataFrame:
    rows = [(_PREV, 10.00), (_DAY, 10.20)]
    frame = pd.DataFrame(
        [
            {
                "trade_date": day,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000.0,
            }
            for day, close in rows
        ]
    )
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")


class _FakeChClient:
    def get_bars(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()


class _FakeLoader:
    name = "tencent"

    def __init__(self, five: dict[str, pd.DataFrame]) -> None:
        self._daily = {_SYM: _daily()}
        self._five = five
        self.calls: list[tuple[tuple[str, ...], str, str, str]] = []

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        self.calls.append((tuple(codes), start_date, end_date, interval))
        source = self._five if interval == "5m" else self._daily
        return {code: source[code] for code in codes if code in source}


class _FakeCalendarClient:
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


# ── harness ──────────────────────────────────────────────────────────────────


def _outcome(
    *,
    orders: list[dict],
    five: dict[str, pd.DataFrame],
    cash: float = 100_000.0,
    positions: tuple[dict, ...] = (),
    ratio: float = 1.0,
    fill_model: str = "volume_share",
):
    market_data = fetch_market_data(
        "cn_a",
        [_SYM],
        _DAY,
        _DAY,
        loader=_FakeLoader(five),
        ch_client=_FakeChClient(),
        interval="5m",
    )
    request = parse_request(
        {
            "account_id": "pa_5m_partial",
            "market": "cn_a",
            "account_state": {"cash": cash, "positions": list(positions)},
            "orders": orders,
            "from_date": _DAY,
            "to_date": _DAY,
            "fee_model": dict(_FEE_MODEL),
            "interval": "5m",
            "fill_model": fill_model,
            "order_volume_ratio": ratio,
        }
    )
    return engine.match_orders(
        request,
        market_data=market_data,
        calendar_client=_FakeCalendarClient(frozenset({_DAY})),
    )


def _buy(limit: float | None = None, qty: float = 100) -> dict:
    order = {"symbol": _SYM, "side": "buy", "qty": qty}
    if limit is not None:
        order["limit"] = limit
    return order


def _sell(limit: float | None = None, qty: float = 100) -> dict:
    order = {"symbol": _SYM, "side": "sell", "qty": qty}
    if limit is not None:
        order["limit"] = limit
    return order


def _fills(outcome) -> list[tuple[str, float, float, float]]:
    return [(fill.side, fill.qty, fill.price, fill.fee) for fill in outcome.fills]


def _cancels(outcome) -> list[tuple[str, float, str]]:
    return [
        (cancel.side, cancel.qty, cancel.reason_code) for cancel in outcome.canceled_orders
    ]


def _observed(outcome) -> str:
    return (
        f"fills={_fills(outcome)!r}, "
        f"rejected={[(r.reason_code, r.detail) for r in outcome.rejected_orders]!r}, "
        f"canceled={_cancels(outcome)!r}, cash={outcome.end_state.cash!r}"
    )


def _assert_positive_lot_fills(outcome, side: str, count: int, case: str) -> None:
    fills = _fills(outcome)
    assert len(fills) == count, (
        f"{case}: expected {count} {side} fill(s) of one 100-share lot each; the "
        f"current tree ignores the volume cap and fills the whole order at once; "
        f"{_observed(outcome)}"
    )
    for fill in fills:
        assert fill == (side, 100.0, 10.00, 5.00), (
            f"{case}: every 100-share fill must execute at its price and pay the ¥5 "
            f"per-fill minimum; got {fills!r}"
        )


def _assert_single_volume_cap_cancel(outcome, *, side: str, qty: float, case: str) -> None:
    cancels = _cancels(outcome)
    assert cancels == [(side, qty, _VOLUME_CAP_REASON)], (
        f"{case}: the market residual must be canceled once with qty {qty:.0f} and "
        f"reason {_VOLUME_CAP_REASON!r}; the current tree has no volume cap and "
        f"never emits that cancel; got {cancels!r}"
    )


# ── case 1: market cap = full-session volume × ratio, residual canceled ──────


def _partial_market_day() -> pd.DataFrame:
    """Session volume 1_000 shares across two bars; first bar ref 10.00."""
    return _intraday(
        _DAY,
        (
            (10.00, 10.00, 10.00, 10.00, 600.0),
            (10.20, 10.20, 10.20, 10.20, 400.0),
        ),
    )


def test_market_order_is_capped_by_session_volume_and_cancels_the_residual() -> None:
    """300 @ ratio 0.1 of a 1_000-share session -> one 100 fill, 200 canceled."""
    outcome = _outcome(orders=[_buy(qty=300)], five={_SYM: _partial_market_day()}, ratio=0.1)

    assert outcome.error is None, f"unexpected engine error: {outcome.error!r}"
    assert _fills(outcome) == [("buy", 100.0, 10.00, 5.00)], (
        "case 1 (market buy 300, session volume 1000, ratio 0.1): floor(1000 x 0.1 / "
        "100) x 100 = 100 shares execute at the first bar reference 10.00; the "
        f"current tree fills all 300; {_observed(outcome)}"
    )
    assert sum(fill.qty for fill in outcome.fills) < 300, (
        f"case 1: the full 300-share order must not fill; {_observed(outcome)}"
    )
    assert outcome.rejected_orders == (), f"case 1: {_observed(outcome)}"
    _assert_single_volume_cap_cancel(outcome, side="buy", qty=200.0, case="case 1")
    assert outcome.order_states, (
        "case 1: a 5m volume-share match must expose the final per-order "
        "lifecycle states for the pt-v1.3 contract"
    )
    assert [state.status for state in outcome.order_states] == ["canceled"], (
        "case 1: the market order's residual is canceled immediately, so its "
        f"terminal state must be 'canceled'; got "
        f"{[state.status for state in outcome.order_states]!r}"
    )
    assert outcome.end_state.cash == pytest.approx(100_000.0 - (1000.0 + 5.0), abs=1e-9)
    assert outcome.end_state.cash >= 0


# ── case 2: limit cap is per bar, one lot at a time across bars ──────────────


def _triggering_bars(count: int, volume: float = 100.0) -> tuple[Bar, ...]:
    """A bar whose low (9.90) strictly crosses the 10.00 buy limit.

    The reference is 10.10 on every bar, so the first bar is not marketable and
    the fill must use the 委托价 10.00.
    """
    bar: Bar = (10.10, 10.20, 9.90, 10.10, volume)
    return tuple(bar for _ in range(count))


def test_limit_buy_fills_one_bar_cap_at_a_time_across_three_bars() -> None:
    """300 limit buy over three 100-share bars at ratio 1.0 -> three 100 fills."""
    bars = _triggering_bars(3)
    assert all(_reference(bar) > Decimal("10.00") for bar in bars)
    outcome = _outcome(
        orders=[_buy(limit=10.00, qty=300)],
        five={_SYM: _intraday(_DAY, bars)},
        ratio=1.0,
    )

    _assert_positive_lot_fills(outcome, "buy", 3, "case 2")
    assert outcome.rejected_orders == (), f"case 2: {_observed(outcome)}"
    assert outcome.canceled_orders == (), f"case 2: {_observed(outcome)}"
    assert outcome.end_state.cash == pytest.approx(100_000.0 - 3 * (1000.0 + 5.0), abs=1e-9)
    assert outcome.end_state.cash >= 0


# ── case 3: a limit residual is a day-end cancel, never a rejection ─────────


def test_limit_residual_is_canceled_at_day_end_with_the_existing_reason() -> None:
    """Two bars cross, the third only touches the limit -> residual 100 canceled."""
    no_trigger: Bar = (10.10, 10.20, 10.00, 10.10, 100.0)
    assert _reference(no_trigger) > Decimal("10.00")
    bars = (*_triggering_bars(2), no_trigger)
    outcome = _outcome(
        orders=[_buy(limit=10.00, qty=300)],
        five={_SYM: _intraday(_DAY, bars)},
        ratio=1.0,
    )

    _assert_positive_lot_fills(outcome, "buy", 2, "case 3")
    assert outcome.rejected_orders == (), (
        f"case 3: an unfilled limit residual is a day-order cancel, never a "
        f"rejection; {_observed(outcome)}"
    )
    assert _cancels(outcome) == [("buy", 100.0, CANCELED_REASON_CODE)], (
        "case 3 (limit buy 300, two 100-share fills, third bar does not cross): "
        "the residual 100 must be canceled at session end with the existing "
        f"{CANCELED_REASON_CODE!r} reason and the residual qty, not the order qty; "
        f"got {_cancels(outcome)!r}"
    )
    assert outcome.end_state.cash == pytest.approx(100_000.0 - 2 * (1000.0 + 5.0), abs=1e-9)
    assert outcome.end_state.cash >= 0


# ── case 4: each fill pays its own minimum commission ───────────────────────


def test_each_fill_pays_its_own_minimum_commission() -> None:
    """Two 100-share fills at 10.00 pay two ¥5 minimums (10.00 total)."""
    outcome = _outcome(
        orders=[_buy(limit=10.00, qty=200)],
        five={_SYM: _intraday(_DAY, _triggering_bars(2))},
        ratio=1.0,
    )

    _assert_positive_lot_fills(outcome, "buy", 2, "case 4")
    assert [fill.fee for fill in outcome.fills] == [5.00, 5.00], (
        "case 4: a 100-share fill at 10.00 is 1_000 notional, below the ¥5 "
        f"commission minimum, so each fill pays exactly 5.00; {_observed(outcome)}"
    )
    assert sum(fill.fee for fill in outcome.fills) == pytest.approx(10.00, abs=1e-9), (
        "case 4: two fills must pay two minimum commissions (10.00 total); the "
        f"current tree charges one fee on the whole all-or-none order; {_observed(outcome)}"
    )
    assert outcome.end_state.cash == pytest.approx(100_000.0 - 2010.0, abs=1e-9)
    assert outcome.end_state.cash >= 0


# ── case 5: cash/position gates use the quantity that will trade ────────────


def _sell_bars(count: int) -> tuple[Bar, ...]:
    """A bar whose high (10.20) strictly crosses the 10.00 sell limit.

    The reference equals the limit, so the first bar is not marketable and the
    fill must use the 委托价 10.00.
    """
    bar: Bar = (10.00, 10.20, 9.90, 10.00, 100.0)
    return tuple(bar for _ in range(count))


def test_sell_position_gate_uses_the_remaining_quantity() -> None:
    """A 300-share sell fills 100 per bar from a 300-share position, no reject."""
    positions = ({"symbol": _SYM, "qty": 300, "avg_cost": 10.0},)
    outcome = _outcome(
        orders=[_sell(limit=10.00, qty=300)],
        five={_SYM: _intraday(_DAY, _sell_bars(3))},
        positions=positions,
        ratio=1.0,
    )

    assert outcome.rejected_orders == (), (
        "case 5 (sell 300 from exactly 300 held): after the first 100-share "
        "fill the sliding position gate must check the remaining 200, not the "
        f"original 300, or bar 2 self-rejects insufficient_position; {_observed(outcome)}"
    )
    fills = _fills(outcome)
    assert fills == [("sell", 100.0, 10.00, 5.50)] * 3, (
        "case 5: a 300-share sell under a 100-share per-bar cap must fill three "
        f"100-share lots at the 委托价 10.00; {_observed(outcome)}"
    )
    assert outcome.canceled_orders == (), f"case 5: {_observed(outcome)}"
    # ``AccountState`` drops zero-qty rows (the frozen end-state contract, see
    # the full-sell case in test_paper_trade_5m_engine.py), so flat is the
    # empty position tuple rather than a 0.0 row.
    assert outcome.end_state.positions == (), (
        f"case 5: the fully sold position must be flat; {_observed(outcome)}"
    )
    assert outcome.end_state.cash == pytest.approx(100_000.0 + 3 * (1000.0 - 5.50), abs=1e-9)
    assert outcome.end_state.cash >= 0


# ── case 6: cash is conserved and never negative ────────────────────────────


def _partial_sell_day() -> pd.DataFrame:
    return _intraday(_DAY, _sell_bars(3))


def _limit_three_bar_day() -> pd.DataFrame:
    return _intraday(_DAY, _triggering_bars(3))


@pytest.mark.parametrize(
    ("case", "orders", "five", "positions", "ratio"),
    [
        (
            "market-buy-partial",
            [_buy(qty=300)],
            _partial_market_day,
            (),
            0.1,
        ),
        (
            "limit-buy-partial",
            [_buy(limit=10.00, qty=300)],
            _limit_three_bar_day,
            (),
            1.0,
        ),
        (
            "limit-sell-partial",
            [_sell(limit=10.00, qty=300)],
            _partial_sell_day,
            ({"symbol": _SYM, "qty": 300, "avg_cost": 10.0},),
            1.0,
        ),
    ],
    ids=["market-buy-partial", "limit-buy-partial", "limit-sell-partial"],
)
def test_cash_stays_non_negative_and_conserved(case, orders, five, positions, ratio) -> None:
    outcome = _outcome(orders=orders, five={_SYM: five()}, positions=positions, ratio=ratio)

    assert outcome.fills, f"{case}: scenario must produce at least one fill; {_observed(outcome)}"
    assert outcome.end_state.cash >= 0, f"{case}: cash went negative; {_observed(outcome)}"
    delta = 0.0
    for fill in outcome.fills:
        notional = fill.qty * fill.price
        delta += notional - fill.fee if fill.side == "sell" else -(notional + fill.fee)
    assert outcome.end_state.cash == pytest.approx(100_000.0 + delta, abs=1e-6), (
        f"{case}: end cash must equal start cash plus every filled notional net of "
        f"its own fee; {_observed(outcome)}"
    )


# ── case 7: a zero-volume bar is not a matching opportunity ────────────────


def test_zero_volume_bar_is_skipped_not_filled() -> None:
    """The first bar has volume 0 and price 8.00; the fill must land on 10.00."""
    bars = (
        (8.00, 8.00, 8.00, 8.00, 0.0),
        (10.00, 10.00, 10.00, 10.00, 100.0),
        (10.50, 10.50, 10.50, 10.50, 100.0),
    )
    outcome = _outcome(
        orders=[_buy(qty=100)],
        five={_SYM: _intraday(_DAY, bars)},
        ratio=1.0,
    )

    assert _fills(outcome) == [("buy", 100.0, 10.00, 5.00)], (
        "case 7: a zero-volume bar can neither fill nor set the fill price; the "
        f"first live bar prices the market buy at 10.00; {_observed(outcome)}"
    )
    assert all(fill.price != 8.00 for fill in outcome.fills), f"case 7: {_observed(outcome)}"
    assert outcome.rejected_orders == (), f"case 7: {_observed(outcome)}"
    assert outcome.canceled_orders == (), f"case 7: {_observed(outcome)}"
    assert outcome.end_state.cash >= 0


# ── case 8: caps are per order, never a shared bar budget ──────────────────


def test_two_orders_get_independent_per_order_caps() -> None:
    """Two 200-share limit buys on one 100-share bar each fill their own 100."""
    bar: Bar = (10.10, 10.20, 9.90, 10.10, 100.0)
    outcome = _outcome(
        orders=[_buy(limit=10.00, qty=200), _buy(limit=10.00, qty=200)],
        five={_SYM: _intraday(_DAY, (bar,))},
        ratio=1.0,
    )

    assert _fills(outcome) == [("buy", 100.0, 10.00, 5.00)] * 2, (
        "case 8: each order independently caps at floor(100 x 1.0 / 100) x 100 = "
        "100 shares, so two orders fill 200 in total from a 100-share bar; a "
        f"shared bar budget would fill only 100 across both; {_observed(outcome)}"
    )
    assert sum(fill.qty for fill in outcome.fills) == 200.0 > 100.0, (
        f"case 8: the two per-order caps must not share one bar budget; {_observed(outcome)}"
    )
    assert outcome.rejected_orders == (), f"case 8: {_observed(outcome)}"
    assert _cancels(outcome) == [
        ("buy", 100.0, CANCELED_REASON_CODE),
        ("buy", 100.0, CANCELED_REASON_CODE),
    ], (
        "case 8: each order leaves its own 100-share residual, canceled at session "
        f"end with the existing day-end reason; got {_cancels(outcome)!r}"
    )
    assert outcome.end_state.cash >= 0


# ── manual QA: one market order larger than its cap, printed as v1.3 ────────


def test_manual_qa_market_partial() -> None:
    payload = {
        "account_id": "pa_5m_manual_qa",
        "market": "cn_a",
        "account_state": {"cash": 100_000.0, "positions": []},
        "orders": [_buy(qty=300)],
        "from_date": _DAY,
        "to_date": _DAY,
        "fee_model": dict(_FEE_MODEL),
        "interval": "5m",
        "fill_model": "volume_share",
        "order_volume_ratio": 0.1,
    }
    raw = run_paper_trade_step(
        payload,
        loader=_FakeLoader({_SYM: _partial_market_day()}),
        ch_client=_FakeChClient(),
        calendar_client=_FakeCalendarClient(frozenset({_DAY})),
        limits_client=None,
    )
    document = json.loads(raw)
    print("MANUAL_QA_V13_DOCUMENT=" + json.dumps(document, sort_keys=True, ensure_ascii=False))

    assert document["schema_version"] == "pt-v1.3"
    row = document["order_states"][0]
    assert (row["status"], row["amount"], row["filled"], row["price"]) == (
        "canceled",
        300.0,
        100.0,
        10.00,
    )
    assert row["filled"] < row["amount"]
    assert len(document["fills"]) == 1
    assert document["fills"][0]["qty"] == 100.0 < row["amount"]
    assert len(document["canceled_orders"]) == 1
    residual = document["canceled_orders"][0]
    assert (residual["qty"], residual["reason_code"]) == (200.0, _VOLUME_CAP_REASON)
    assert document["end_state"]["cash"] >= 0
