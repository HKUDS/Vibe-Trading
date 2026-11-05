"""Failing-first tests for JoinQuant order-status semantics (#1938).

JoinQuant's ``OrderStatus`` names the two degrees of completion the other way
round from the phase-1 lifecycle that shipped:

- ``filled`` -> partially filled, still active: it may receive further fills
  and it can still be canceled;
- ``held``   -> fully filled, terminal: it can neither fill nor be canceled.

These tests pin that contract through the public ``OrderBook`` API. They are
expected to fail on the pre-fix tree, where ``STATUS_FILLED`` marks a complete
fill and ``STATUS_HELD`` a partial one.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.tools.paper_trade.order_lifecycle import (
    STATUS_CANCELED,
    STATUS_FILLED,
    STATUS_HELD,
    STATUS_PENDING_CANCEL,
    OrderBook,
    OrderLifecycleError,
    OrderRequest,
    assign_ids,
    replay_snapshot,
)

D = Decimal


def _request(**overrides):
    kwargs = dict(symbol="600519.SH", side="buy", qty=D("100"))
    kwargs.update(overrides)
    return OrderRequest(**kwargs)


def _partially_filled_book(book_qty: str = "100", fill_qty: str = "40") -> OrderBook:
    """One activated order filled for less than it requested."""
    book = OrderBook(assign_ids([_request(qty=D(book_qty))]))
    book.activate("pt-0")
    book.fill("pt-0", D(fill_qty), D("1700.00"))
    return book


def test_full_fill_ends_held_and_terminal():
    """A complete fill is ``held`` and accepts no further lifecycle event."""
    book = OrderBook(assign_ids([_request(qty=D("100"))]))
    book.activate("pt-0")
    book.fill("pt-0", D("100"), D("1700.00"))

    state = book.get("pt-0")
    assert state is not None
    assert state.filled_qty == D("100")
    assert state.status == STATUS_HELD
    # Terminal: not among today's open orders.
    assert "pt-0" not in [open_state.order_id for open_state in book.open_orders()]
    with pytest.raises(OrderLifecycleError, match="cannot fill"):
        book.fill("pt-0", D("1"), D("1700.00"))
    with pytest.raises(OrderLifecycleError, match="cannot be canceled"):
        book.request_cancel("pt-0")


def test_partial_fill_ends_filled_stays_open_and_settles_to_canceled():
    """A partial fill is ``filled``, remains open, and its residual settles."""
    book = OrderBook(assign_ids([_request(qty=D("100"))]))
    book.activate("pt-0")
    book.fill("pt-0", D("40"), D("1700.00"))

    state = book.get("pt-0")
    assert state is not None
    assert state.filled_qty == D("40")
    assert state.status == STATUS_FILLED
    assert [open_state.order_id for open_state in book.open_orders()] == ["pt-0"]

    settled = book.settle_day()
    assert [settled_state.order_id for settled_state in settled] == ["pt-0"]
    assert state.status == STATUS_CANCELED
    assert state.filled_qty == D("40")
    assert state.request.qty - state.filled_qty == D("60")


def test_request_cancel_accepts_filled_and_refuses_held():
    """Cancel is accepted on a partial fill and refused on a complete one."""
    partial = _partially_filled_book()
    assert partial.get("pt-0").status == STATUS_FILLED
    canceled = partial.request_cancel("pt-0")
    assert canceled.status == STATUS_PENDING_CANCEL

    full = OrderBook(assign_ids([_request(qty=D("100"))]))
    full.activate("pt-0")
    full.fill("pt-0", D("100"), D("1700.00"))
    assert full.get("pt-0").status == STATUS_HELD
    with pytest.raises(OrderLifecycleError, match="cannot be canceled"):
        full.request_cancel("pt-0")


def test_replay_snapshot_reports_filled_for_partial_and_held_for_full():
    """The replay snapshot carries the JoinQuant names, not the inverted ones."""
    book = OrderBook(
        assign_ids([_request(qty=D("100")), _request(side="sell", qty=D("100"))])
    )
    book.activate("pt-0")
    book.activate("pt-1")
    book.fill("pt-0", D("40"), D("1700.00"))
    book.fill("pt-1", D("100"), D("1710.00"))

    snapshot = replay_snapshot(book)
    assert snapshot["pt-0"]["status"] == STATUS_FILLED
    assert snapshot["pt-0"]["filled_qty"] == "40"
    assert snapshot["pt-1"]["status"] == STATUS_HELD
    assert snapshot["pt-1"]["filled_qty"] == "100"


def test_canceled_partial_keeps_its_filled_qty():
    """Canceling a partial fill does not erase the quantity already executed."""
    book = _partially_filled_book()
    book.request_cancel("pt-0")
    settled = book.settle_day()

    state = book.get("pt-0")
    assert [settled_state.order_id for settled_state in settled] == ["pt-0"]
    assert state is not None
    assert state.status == STATUS_CANCELED
    assert state.filled_qty == D("40")
    assert [fill.qty for fill in state.fills] == [D("40")]
    assert replay_snapshot(book)["pt-0"]["filled_qty"] == "40"
