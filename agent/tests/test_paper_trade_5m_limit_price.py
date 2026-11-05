"""T4 gate — JoinQuant limit-fill trigger and price for the cn_a 5m step.

The official contract (JoinQuantAPI.pdf, 订单处理; restated by the phase-3
planbook):

* a resting **limit buy** fills at its 委托价 once a bar's ``low`` is strictly
  below that limit (``bar.low < limit``);
* a resting **limit sell** fills at its 委托价 once a bar's ``high`` is
  strictly above that limit (``bar.high > limit``);
* equality never fills — both comparisons are strict;
* a limit already marketable at the **first continuous bar** fills at that
  bar's reference price (``ref``) only when the reference is strictly better
  than the limit (buy ``ref < limit``, sell ``ref > limit``); at equality it
  rests.  ``path_model`` therefore chooses the first-bar marketable *price*,
  while a bar-low/high cross decides the *verdict* and fills at the limit.

Every case runs a **two-bar** continuous day so the order is already resting
on bar 1 and the case under test is a deferred order on bar 2.  The days are
synthetic ``_intraday`` frames in the style of
``test_paper_trade_5m_engine.py`` (opening-auction print omitted, so the two
continuous bars are the whole session); no committed market fixture is added.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
import pytest

from src.tools.paper_trade import engine
from src.tools.paper_trade.data import fetch_market_data
from src.tools.paper_trade.schema import CANCELED_REASON_CODE, parse_request

_DAY = "2026-10-20"
_PREV = "2026-10-19"
_SYM = "600519.SH"
_FEE_MODEL = {
    "commission_rate": 0.00025,
    "commission_min": 5.0,
    "stamp_tax_sell": 0.0005,
    "transfer_fee": 0.00001,
}
_LABELS = ("09:35", "09:40")

# (open, high, low, close)
Bar = tuple[float, float, float, float]


# ── synthetic two-bar days (no committed fixture) ────────────────────────────


def _intraday(day: str, bars: tuple[Bar, Bar]) -> pd.DataFrame:
    """Two on-grid continuous 5m bars; labels are bar ENDS."""
    records = [
        {
            "bar_time": f"{day} {label}",
            "open": bar[0],
            "high": bar[1],
            "low": bar[2],
            "close": bar[3],
            "volume": 120000.0,
        }
        for label, bar in zip(_LABELS, bars, strict=True)
    ]
    frame = pd.DataFrame(records)
    frame["bar_time"] = pd.to_datetime(frame["bar_time"])
    return frame.set_index("bar_time")


def _reference(bar: Bar, path_model: str = "bar_median") -> Decimal:
    """Recompute a bar reference independently of the engine.

    ``money()`` is ``Decimal(str(x))`` and the frozen tick is 2dp HALF_UP;
    both are restated here rather than imported so an engine change cannot
    make this assertion agree with a wrong price.
    """
    open_, high, low, close = (Decimal(str(value)) for value in bar)
    if path_model == "bar_close":
        raw = close
    else:
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
    cash: float = 100000.0,
    positions: tuple[dict, ...] = (),
    path_model: str = "bar_median",
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
            "account_id": "pa_5m_limit",
            "market": "cn_a",
            "account_state": {"cash": cash, "positions": list(positions)},
            "orders": orders,
            "from_date": _DAY,
            "to_date": _DAY,
            "fee_model": dict(_FEE_MODEL),
            "interval": "5m",
            "path_model": path_model,
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


_HELD = ({"symbol": _SYM, "qty": 100, "avg_cost": 10.0},)


def _fills(outcome) -> list[tuple[str, float, float]]:
    return [(fill.side, fill.qty, fill.price) for fill in outcome.fills]


def _cancels(outcome) -> list[tuple[str, str, float, str, str]]:
    return [
        (cancel.symbol, cancel.side, cancel.qty, cancel.reason_code, cancel.detail)
        for cancel in outcome.canceled_orders
    ]


def _observed(outcome) -> str:
    return (
        f"fills={_fills(outcome)!r}, "
        f"rejected={[(r.reason_code, r.detail) for r in outcome.rejected_orders]!r}, "
        f"canceled={_cancels(outcome)!r}"
    )


def _assert_day_end_cancel(outcome, *, side: str, qty: float, case: str) -> None:
    """Exactly one day-end cancel of the whole (all-or-none) order."""
    cancels = _cancels(outcome)
    assert len(cancels) == 1, f"{case}: expected one day-end cancel; {_observed(outcome)}"
    symbol, cancel_side, cancel_qty, reason, detail = cancels[0]
    assert (symbol, cancel_side, cancel_qty) == (_SYM, side, qty), (
        f"{case}: cancel must carry the order's symbol/side/qty; got {cancels!r}"
    )
    assert reason == CANCELED_REASON_CODE, f"{case}: unexpected cancel reason; got {cancels!r}"
    assert detail.startswith("unfilled day order canceled at session end"), (
        f"{case}: expected the day-end cancel, not a rejection cancel; got {cancels!r}"
    )


# ── case 1 ───────────────────────────────────────────────────────────────────


def test_case1_resting_buy_fills_at_the_limit_when_the_bar_low_crosses() -> None:
    """Bar 1 ref 10.30 rests; bar 2 low 9.80 < 10.00 fills at 委托价 10.00."""
    bars = (
        (10.30, 10.30, 10.30, 10.30),
        (10.00, 10.40, 9.80, 10.40),
    )
    outcome = _outcome(orders=[_buy(limit=10.00)], five={_SYM: _intraday(_DAY, bars)})

    assert _reference(bars[0]) == Decimal("10.30")
    assert _reference(bars[1]) == Decimal("10.20")
    assert _fills(outcome) == [("buy", 100.0, 10.00)], (
        "case 1 (buy limit 10.00): a resting limit must fill at 委托价 10.00 once "
        "bar 2's low (9.80) is strictly below the limit. The current tree defers the "
        "order because bar 2's reference (10.20) is worse than the limit instead of "
        f"triggering on the bar low; {_observed(outcome)}"
    )
    assert outcome.rejected_orders == (), f"case 1: {_observed(outcome)}"
    assert outcome.canceled_orders == (), f"case 1: {_observed(outcome)}"


# ── case 2 ───────────────────────────────────────────────────────────────────


def test_case2_resting_buy_does_not_fill_when_the_bar_low_equals_the_limit() -> None:
    """Bar 1 ref 10.30 rests; bar 2 low == ref == 10.00 -> strict rule: no fill."""
    bars = (
        (10.30, 10.30, 10.30, 10.30),
        (10.00, 10.00, 10.00, 10.00),
    )
    outcome = _outcome(orders=[_buy(limit=10.00)], five={_SYM: _intraday(_DAY, bars)})

    assert _reference(bars[1]) == Decimal("10.00")
    assert _fills(outcome) == [], (
        "case 2 (buy limit 10.00): bar 2's low equals the limit (10.00 == 10.00), "
        "so the strict `bar.low < limit` rule must leave the order unfilled. The "
        "current tree fills at 10.00 because the reference merely equals the limit "
        f"and equality is treated as marketable; {_observed(outcome)}"
    )
    assert outcome.rejected_orders == (), f"case 2: {_observed(outcome)}"
    _assert_day_end_cancel(outcome, side="buy", qty=100.0, case="case 2")


# ── case 3 ───────────────────────────────────────────────────────────────────


def test_case3_resting_sell_fills_at_the_limit_when_the_bar_high_crosses() -> None:
    """Bar 1 ref 9.70 rests; bar 2 high 10.20 > 10.00 fills at 委托价 10.00."""
    bars = (
        (9.70, 9.70, 9.70, 9.70),
        (10.00, 10.20, 9.70, 9.80),
    )
    outcome = _outcome(
        orders=[_sell(limit=10.00)],
        five={_SYM: _intraday(_DAY, bars)},
        positions=_HELD,
    )

    assert _reference(bars[0]) == Decimal("9.70")
    assert _reference(bars[1]) == Decimal("9.90")
    assert _fills(outcome) == [("sell", 100.0, 10.00)], (
        "case 3 (sell limit 10.00): a resting limit must fill at 委托价 10.00 once "
        "bar 2's high (10.20) is strictly above the limit. The current tree defers "
        "the order because bar 2's reference (9.90) is worse than the limit instead "
        f"of triggering on the bar high; {_observed(outcome)}"
    )
    assert outcome.rejected_orders == (), f"case 3: {_observed(outcome)}"
    assert outcome.canceled_orders == (), f"case 3: {_observed(outcome)}"


# ── case 4 ───────────────────────────────────────────────────────────────────


def test_case4_resting_sell_does_not_fill_when_the_bar_high_equals_the_limit() -> None:
    """Bar 1 ref 9.70 rests; bar 2 high == ref == 10.00 -> strict rule: no fill."""
    bars = (
        (9.70, 9.70, 9.70, 9.70),
        (10.00, 10.00, 10.00, 10.00),
    )
    outcome = _outcome(
        orders=[_sell(limit=10.00)],
        five={_SYM: _intraday(_DAY, bars)},
        positions=_HELD,
    )

    assert _reference(bars[1]) == Decimal("10.00")
    assert _fills(outcome) == [], (
        "case 4 (sell limit 10.00): bar 2's high equals the limit (10.00 == 10.00), "
        "so the strict `bar.high > limit` rule must leave the order unfilled. The "
        "current tree fills at 10.00 because the reference merely equals the limit "
        f"and equality is treated as marketable; {_observed(outcome)}"
    )
    assert outcome.rejected_orders == (), f"case 4: {_observed(outcome)}"
    _assert_day_end_cancel(outcome, side="sell", qty=100.0, case="case 4")


# ── case 5: first live bar marketability ─────────────────────────────────────


def test_case5_buy_first_bar_is_marketable_only_below_the_limit() -> None:
    """A buy limit on a flat 10.40 first bar: fills at 10.40 under 10.50, rests at 10.40."""
    bars = (
        (10.40, 10.40, 10.40, 10.40),
        (10.40, 10.40, 10.40, 10.40),
    )
    frame = _intraday(_DAY, bars)
    assert _reference(bars[0]) == Decimal("10.40")

    marketable = _outcome(orders=[_buy(limit=10.50)], five={_SYM: frame})
    assert _fills(marketable) == [("buy", 100.0, 10.40)], (
        "case 5 (buy, ref 10.40 < limit 10.50): the first bar is marketable and must "
        f"fill at its reference, never worse than the limit; {_observed(marketable)}"
    )
    assert marketable.fills[0].price <= 10.50
    assert marketable.rejected_orders == ()
    assert marketable.canceled_orders == ()

    resting = _outcome(orders=[_buy(limit=10.40)], five={_SYM: frame})
    assert _fills(resting) == [], (
        "case 5 (buy, ref 10.40 == limit 10.40): at equality the first bar is NOT "
        "marketable and the order must rest; the current tree fills at the reference "
        f"because equality is treated as marketable; {_observed(resting)}"
    )
    assert resting.rejected_orders == (), f"case 5 (buy equality): {_observed(resting)}"
    _assert_day_end_cancel(resting, side="buy", qty=100.0, case="case 5 (buy equality)")


def test_case5_sell_first_bar_is_marketable_only_above_the_limit() -> None:
    """A sell limit on a flat 10.60 first bar: fills at 10.60 over 10.50, rests at 10.60."""
    bars = (
        (10.60, 10.60, 10.60, 10.60),
        (10.60, 10.60, 10.60, 10.60),
    )
    frame = _intraday(_DAY, bars)
    assert _reference(bars[0]) == Decimal("10.60")

    marketable = _outcome(orders=[_sell(limit=10.50)], five={_SYM: frame}, positions=_HELD)
    assert _fills(marketable) == [("sell", 100.0, 10.60)], (
        "case 5 (sell, ref 10.60 > limit 10.50): the first bar is marketable and must "
        f"fill at its reference, never worse than the limit; {_observed(marketable)}"
    )
    assert marketable.fills[0].price >= 10.50
    assert marketable.rejected_orders == ()
    assert marketable.canceled_orders == ()

    resting = _outcome(orders=[_sell(limit=10.60)], five={_SYM: frame}, positions=_HELD)
    assert _fills(resting) == [], (
        "case 5 (sell, ref 10.60 == limit 10.60): at equality the first bar is NOT "
        "marketable and the order must rest; the current tree fills at the reference "
        f"because equality is treated as marketable; {_observed(resting)}"
    )
    assert resting.rejected_orders == (), f"case 5 (sell equality): {_observed(resting)}"
    _assert_day_end_cancel(resting, side="sell", qty=100.0, case="case 5 (sell equality)")


# ── case 6: path_model="bar_close" ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("side", "bars", "expected_fill"),
    [
        ("buy", ((10.30, 10.30, 10.30, 10.30), (10.00, 10.40, 9.80, 10.40)), 10.00),
        ("buy", ((10.30, 10.30, 10.30, 10.30), (10.00, 10.00, 10.00, 10.00)), None),
        ("sell", ((9.70, 9.70, 9.70, 9.70), (10.00, 10.20, 9.70, 9.80)), 10.00),
        ("sell", ((9.70, 9.70, 9.70, 9.70), (10.00, 10.00, 10.00, 10.00)), None),
    ],
    ids=["buy-cross", "buy-equality", "sell-cross", "sell-equality"],
)
def test_case6_bar_close_keeps_the_bar_low_high_verdict(
    side: str, bars: tuple[Bar, Bar], expected_fill: float | None
) -> None:
    """bar_close moves the reference; a low/high cross still decides the verdict."""
    frame = _intraday(_DAY, bars)
    order = _buy(limit=10.00) if side == "buy" else _sell(limit=10.00)
    outcome = _outcome(
        orders=[order],
        five={_SYM: frame},
        positions=() if side == "buy" else _HELD,
        path_model="bar_close",
    )
    close_ref = _reference(bars[-1], "bar_close")
    median_ref = _reference(bars[-1])
    if len(set(bars[-1])) > 1:
        # The bar is dispersed, so the two path models really disagree here...
        assert close_ref != median_ref

    if expected_fill is not None:
        assert _fills(outcome) == [(side, 100.0, expected_fill)], (
            f"case 6 ({side}-cross, bar_close ref {close_ref} vs bar_median ref "
            f"{median_ref}): a bar-low/high cross must decide the verdict and fill at "
            f"the 委托价 {expected_fill:.2f} regardless of the reference; "
            f"{_observed(outcome)}"
        )
        assert outcome.fills[0].price == expected_fill
        assert outcome.rejected_orders == (), f"case 6 ({side}-cross): {_observed(outcome)}"
        assert outcome.canceled_orders == (), f"case 6 ({side}-cross): {_observed(outcome)}"
        return

    assert _fills(outcome) == [], (
        f"case 6 ({side}-equality, bar_close ref {close_ref}): equality must not fill "
        f"under the strict bar low/high rule; {_observed(outcome)}"
    )
    assert outcome.rejected_orders == (), f"case 6 ({side}-equality): {_observed(outcome)}"
    _assert_day_end_cancel(outcome, side=side, qty=100.0, case=f"case 6 ({side}-equality)")


def test_case6_bar_close_changes_the_first_bar_marketable_price() -> None:
    """Only the first-bar marketable *price* follows the reference, never the limit rule."""
    buy_bar: Bar = (10.00, 10.30, 9.90, 10.30)
    buy_frame = _intraday(_DAY, (buy_bar, (10.30, 10.30, 10.30, 10.30)))
    assert _reference(buy_bar) == Decimal("10.15")
    assert _reference(buy_bar, "bar_close") == Decimal("10.30")

    buy_median = _outcome(orders=[_buy(limit=10.35)], five={_SYM: buy_frame})
    buy_close = _outcome(
        orders=[_buy(limit=10.35)], five={_SYM: buy_frame}, path_model="bar_close"
    )
    assert _fills(buy_median) == [("buy", 100.0, 10.15)], (
        "case 6 (buy first bar): bar_median reference 10.15 is strictly below the "
        f"limit 10.35, so the fill is the reference; {_observed(buy_median)}"
    )
    assert _fills(buy_close) == [("buy", 100.0, 10.30)], (
        "case 6 (buy first bar): bar_close reference 10.30 is strictly below the "
        f"limit 10.35, so the fill is the reference; {_observed(buy_close)}"
    )
    assert buy_median.fills[0].price <= 10.35 and buy_close.fills[0].price <= 10.35
    assert buy_median.canceled_orders == () and buy_close.canceled_orders == ()

    sell_bar: Bar = (10.80, 10.80, 10.50, 10.50)
    sell_frame = _intraday(_DAY, (sell_bar, (10.50, 10.50, 10.50, 10.50)))
    assert _reference(sell_bar) == Decimal("10.65")
    assert _reference(sell_bar, "bar_close") == Decimal("10.50")

    sell_median = _outcome(orders=[_sell(limit=10.40)], five={_SYM: sell_frame}, positions=_HELD)
    sell_close = _outcome(
        orders=[_sell(limit=10.40)],
        five={_SYM: sell_frame},
        positions=_HELD,
        path_model="bar_close",
    )
    assert _fills(sell_median) == [("sell", 100.0, 10.65)], (
        "case 6 (sell first bar): bar_median reference 10.65 is strictly above the "
        f"limit 10.40, so the fill is the reference; {_observed(sell_median)}"
    )
    assert _fills(sell_close) == [("sell", 100.0, 10.50)], (
        "case 6 (sell first bar): bar_close reference 10.50 is strictly above the "
        f"limit 10.40, so the fill is the reference; {_observed(sell_close)}"
    )
    assert sell_median.fills[0].price >= 10.40 and sell_close.fills[0].price >= 10.40
    assert sell_median.canceled_orders == () and sell_close.canceled_orders == ()
