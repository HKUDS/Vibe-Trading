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
- ``fill_model="volume_share"`` (pt-v1.3) caps every order by its OWN share of
  volume — never a shared bar budget.  A market order is capped once by
  ``floor(full continuous-session volume x order_volume_ratio / lot) x lot``
  and takes that cap at the first live bar; any residual is canceled
  immediately with ``canceled_after_volume_cap``.  A limit order is capped per
  bar by its share of that bar's volume, fills at its 委托价, and keeps its
  residual resting until a later bar or the session-end day-order cancel.
  ``all_or_none`` keeps the frozen full-fill path;
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

from . import volume_policy
from .order_lifecycle import (
    _ACTIVE_STATUSES, OrderBook, OrderRequest, OrderState, assign_ids)
from .rules import money, quantize_money
from .schema import CANCELED_REASON_CODE, CanceledOrder, Order

if TYPE_CHECKING:
    from .engine import DayPlan, _MatchSession

__all__ = ["VOLUME_CAP_REASON", "match_orders_5m"]

#: pt-v1.3 residual-cancel token for a market order clipped by its volume cap.
#: Deliberately NOT a member of the frozen ``REASON_CODES`` vocabulary.
VOLUME_CAP_REASON = "canceled_after_volume_cap"


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


def _residual(state: OrderState) -> Decimal:
    return state.request.qty - state.filled_qty


def _cancel_volume_residual(
    session: "_MatchSession", day: "DayPlan", book: OrderBook, order_id: str, order: Order
) -> None:
    state = book.cancel_order(order_id, VOLUME_CAP_REASON)
    residual = _residual(state)
    session.canceled.append(CanceledOrder(
        trade_date=day.date,
        symbol=order.symbol,
        side=order.side,
        qty=float(residual),
        reason_code=VOLUME_CAP_REASON,
        detail=f"volume cap reached; residual {residual} canceled",
    ))


def _cancel_unfilled(
    session: "_MatchSession", day: "DayPlan", book: OrderBook, by_id: dict[str, Order]
) -> None:
    for state in book.settle_day():
        order = by_id[state.order_id]
        session.canceled.append(CanceledOrder(
            trade_date=day.date,
            symbol=order.symbol,
            side=order.side,
            qty=float(_residual(state)),
            reason_code=CANCELED_REASON_CODE,
            detail="unfilled day order canceled at session end",
        ))


def match_orders_5m(
    session: "_MatchSession", day: "DayPlan", orders: Sequence[Order]
) -> tuple[OrderState, ...]:
    if not orders:
        return ()
    requests = [_request(order) for order in orders]
    states = assign_ids(requests)
    by_id = dict(zip(states, orders, strict=True))
    book = OrderBook(states)

    volume_share = session.fill_model == "volume_share"
    ratio = session.order_volume_ratio

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
        # A market order's cap is computed ONCE from the full continuous-session
        # volume (``SessionBar.volume``), not cumulatively per bar.  The 09:30
        # opening-auction print is not part of that volume — the session
        # assembly drops it — and a short/partial session caps against the
        # volume the provider actually served, so it underfills rather than
        # inventing a full day.  Caps are per order; two orders never share one.
        market_caps: dict[str, int] = {}
        if volume_share:
            lot = session.rules.lot_size(symbol)
            session_volume = sym_data.session_bars[day.date].volume
            for order_id in order_ids:
                order = by_id[order_id]
                if order.limit is not None:
                    continue
                cap = volume_policy.market_cap(session_volume, ratio, lot)
                market_caps[order_id] = cap
                if cap <= 0:
                    # A zero-cap market order never fills: cancel the whole
                    # residual now (settle_day would label it a failed match).
                    _cancel_volume_residual(session, day, book, order_id, order)
        live_bar = 0
        for _, bar in bars.sort_index().iterrows():
            if float(bar["volume"]) <= 0:
                # A zero-volume bar is not a matching opportunity, so it can
                # neither fill nor consume the first-bar marketable branch.
                continue
            ref = session._reference_price_from_bar(bar)
            first_bar = live_bar == 0
            live_bar += 1
            bar_cap = (
                volume_policy.limit_bar_cap(float(bar["volume"]), ratio, lot)
                if volume_share else 0)
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
                if volume_share:
                    cap = market_caps[order_id] if order.limit is None else bar_cap
                    if cap <= 0:
                        # Too thin for one whole lot: wait for a thicker bar.
                        # (book.fill fails closed on a non-positive cap.)
                        continue
                    executable = volume_policy.executable_qty(_residual(state), cap)
                    if executable <= 0:
                        continue
                    gate = session._fill_gate(day, order, price, executable)
                else:
                    executable = 0
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
                    session._reject(
                        day, order, code, detail,
                        cancel_qty=float(_residual(state)) if state.filled_qty > 0 else None)
                    continue
                if volume_share:
                    fill = book.fill(
                        order_id, money(executable), price, volume_cap=money(cap))
                else:
                    fill = book.fill(order_id, money(order.qty), price)
                session._fill(day.date, order, float(price), fill.qty)
                if volume_share and order.limit is None and _residual(state) > 0:
                    # The session-volume basis is fixed for the day, so a
                    # market order's residual can never be matched later.
                    _cancel_volume_residual(session, day, book, order_id, order)

    for order_id, gate in deferred.items():
        state = book.get(order_id)
        if state is None or state.status not in _ACTIVE_STATUSES:
            continue
        if state.filled_qty > 0:
            # A partially filled order is never rejected for the whole order;
            # settle_day cancels its residual with no rejected row.
            continue
        book.reject(order_id, gate[0])
        session._reject(day, by_id[order_id], *gate)
    _cancel_unfilled(session, day, book, by_id)
    return tuple(book.orders.values())
