"""Per-bar cn_a 5-minute session wiring for the paper-trading engine (#1938 phase 2).

The bar-agnostic :class:`~.order_lifecycle.OrderBook` drives one completed 5m
session: orders are submitted once for the day, every continuous bar is a
matching opportunity, and unfilled day orders are canceled at the session
close.  Only ``interval="5m"`` reaches this module; the pt-v1.1 daily path is
untouched.

Phase-2/3 semantics:

- a market order fills in full at the first continuous bar whose fill gates
  pass, at that bar's reference price;
- a resting limit order (JoinQuant 订单处理) fills in full at its 委托价
  (``order.limit``) once a bar trades through it: a buy needs
  ``bar.low < limit``, a sell needs ``bar.high > limit`` — both strict, so a
  bar that only touches the limit never fills.  On the first continuous bar a
  strictly better reference (buy ``ref < limit``, sell ``ref > limit``) fills
  at that reference, never worse than the limit; at equality the bar rule
  alone decides.  Later bars let only the bar low/high rule decide the
  verdict, so ``path_model`` cannot change a limit fill that the bar trades
  through — it only picks the first-bar marketable *price*;
- the price-limit band and cash gates are anchored on the actual fill price
  (the reference for market/first-bar fills, the 委托价 for bar-low/high
  fills);
- an order that never fills is canceled by ``settle_day`` at session end (15:00
  on a complete session);
- no partial fills and no volume-share model (Phase 3);
- daily data supplies the prior-close bands and final NAV; the current bar
  reference controls price-limit eligibility, and T+1, board
  lots, fees and corporate-action gates use the same frozen rules as the
  daily path.

Determinism: the bar timeline comes from the served 5m frame, order ids are
positional (``pt-<index>``), and no clock or randomness is read.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Sequence

from .order_lifecycle import _ACTIVE_STATUSES, OrderBook, OrderRequest, assign_ids
from .rules import money, quantize_money
from .schema import CANCELED_REASON_CODE, CanceledOrder, Order

if TYPE_CHECKING:
    from .engine import DayPlan, _MatchSession

__all__ = ["match_orders_5m"]


def _request(order: Order) -> OrderRequest:
    limit = money(order.limit) if order.limit is not None else None
    return OrderRequest(
        symbol=order.symbol,
        side=order.side,
        qty=money(order.qty),
        order_type="limit" if limit is not None else "market",
        limit_price=limit,
    )


def _limit_fill_price(order: Order, ref: Decimal, bar: Any, *, first_bar: bool) -> Decimal | None:
    """The 委托价 execution for a resting limit, or ``None`` while it rests.

    JoinQuant's bar matching triggers on the bar's traded range: a buy needs
    ``bar.low < limit`` and a sell ``bar.high > limit`` (both strict, so a bar
    whose low/high only touches the limit never fills), and the execution is
    the 委托价.  The first continuous bar adds the first-bar marketable rule:
    a strictly better reference fills at that reference, never worse than the
    limit; at equality the bar-low/high rule alone decides.
    """
    limit = money(order.limit)
    low = quantize_money(money(float(bar["low"])))
    high = quantize_money(money(float(bar["high"])))
    if order.side == "buy":
        if first_bar and ref < limit:
            return ref
        return limit if low < limit else None
    if first_bar and ref > limit:
        return ref
    return limit if high > limit else None


def _cancel_unfilled(
    session: "_MatchSession", day: "DayPlan", book: OrderBook, by_id: dict[str, Order]
) -> None:
    for state in book.settle_day():
        order = by_id[state.order_id]
        session.canceled.append(CanceledOrder(
            trade_date=day.date,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            reason_code=CANCELED_REASON_CODE,
            detail="unfilled day order canceled at session end",
        ))


def match_orders_5m(session: "_MatchSession", day: "DayPlan", orders: Sequence[Order]) -> None:
    if not orders:
        return
    requests = [_request(order) for order in orders]
    states = assign_ids(requests)
    by_id = dict(zip(states, orders, strict=True))
    book = OrderBook(states)

    deferred: dict[str, tuple[str, str]] = {}
    active: list[str] = []
    for order_id, order in by_id.items():
        gate = session._day_gate(day, order)
        if gate is not None:
            book.reject(order_id, gate[0])
            session._reject(day, order, *gate)
            continue
        book.activate(order_id)
        active.append(order_id)

    for symbol in sorted({by_id[order_id].symbol for order_id in active}):
        sym_data = session.market_data.data[symbol]
        bars = sym_data.bars_5m.get(day.date)
        order_ids = [order_id for order_id in active if by_id[order_id].symbol == symbol]
        if bars is None or bars.empty:
            for order_id in order_ids:
                order = by_id[order_id]
                book.reject(order_id, "suspended")
                session._reject(
                    day, order, "suspended",
                    f"no 5m continuous bars for {symbol} on {day.date}")
            continue
        live_bar = 0
        for _, bar in bars.sort_index().iterrows():
            if float(bar["volume"]) <= 0:
                # A zero-volume bar is not a matching opportunity, so it can
                # neither fill nor consume the first-bar marketable branch.
                continue
            ref = session._reference_price_from_bar(bar)
            first_bar = live_bar == 0
            live_bar += 1
            for order_id in order_ids:
                state = book.get(order_id)
                if state is None or state.status not in _ACTIVE_STATUSES:
                    continue
                order = by_id[order_id]
                if order.limit is None:
                    price = ref
                else:
                    # Trigger/price split: the bar range decides whether a
                    # resting limit fills, and it fills at the 委托价; only the
                    # first continuous bar can fill at a strictly better
                    # reference.  A limit that never triggers rests untouched.
                    price = _limit_fill_price(order, ref, bar, first_bar=first_bar)
                    if price is None:
                        continue
                gate = session._fill_gate(day, order, price)
                if gate is not None:
                    code, detail = gate
                    if code in {"limit_up", "limit_down"}:
                        # The band blocks the side; the order waits for a
                        # later bar (and is rejected at day end if still
                        # blocked), exactly like a market order.
                        deferred[order_id] = gate
                        continue
                    book.reject(order_id, code)
                    session._reject(day, order, code, detail)
                    continue
                book.fill(order_id, money(order.qty), price)
                session._fill(day.date, order, float(price))

    for order_id, gate in deferred.items():
        state = book.get(order_id)
        if state is not None and state.status in _ACTIVE_STATUSES:
            book.reject(order_id, gate[0])
            session._reject(day, by_id[order_id], *gate)
    _cancel_unfilled(session, day, book, by_id)
