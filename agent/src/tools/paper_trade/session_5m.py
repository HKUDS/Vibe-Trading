"""Per-bar cn_a 5-minute session wiring for the paper-trading engine (#1938 phase 2).

The bar-agnostic :class:`~.order_lifecycle.OrderBook` drives one completed 5m
session: orders are submitted once for the day, every continuous bar is a
matching opportunity, and unfilled day orders are canceled at the session
close.  Only ``interval="5m"`` reaches this module; the pt-v1.1 daily path is
untouched.

Phase-2 semantics:

- a market order fills in full at the first continuous bar whose fill gates
  pass; a limit order rests across bars and fills in full at the first bar
  whose reference price satisfies the limit;
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

from typing import TYPE_CHECKING, Sequence

from .order_lifecycle import STATUS_OPEN, OrderBook, OrderRequest, assign_ids
from .rules import money
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
        for _, bar in bars.sort_index().iterrows():
            if float(bar["volume"]) <= 0:
                continue
            ref = session._reference_price_from_bar(bar)
            for order_id in order_ids:
                state = book.get(order_id)
                if state is None or state.status != STATUS_OPEN:
                    continue
                order = by_id[order_id]
                gate = session._fill_gate(day, order, ref)
                if gate is not None:
                    code, detail = gate
                    if code in {"limit_not_marketable", "limit_up", "limit_down"}:
                        deferred[order_id] = gate
                        continue
                    book.reject(order_id, code)
                    session._reject(day, order, code, detail)
                    continue
                book.fill(order_id, money(order.qty), ref)
                session._fill(day.date, order, float(ref))

    for order_id, gate in deferred.items():
        state = book.get(order_id)
        if state is not None and state.status == STATUS_OPEN and gate[0] != "limit_not_marketable":
            book.reject(order_id, gate[0])
            session._reject(day, by_id[order_id], *gate)
    _cancel_unfilled(session, day, book, by_id)
