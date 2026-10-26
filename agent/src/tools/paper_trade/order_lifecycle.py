"""A bar-agnostic order lifecycle for the deterministic paper-trading engine.

Implements phase 1 of the #1938 roadmap: the JoinQuant-shaped order object as
a standalone state machine — no engine wiring, no calendar, no market data.
Wiring into the 5m session engine (phase 2) and the partial-fill volume-cap
policy (phase 3) are separate decisions.

Scope, frozen from the thread:

- order id stable across replay (a replayed order list reproduces identical
  ids, so a retry is distinguishable from a new order);
- status set ``new / open / filled / canceled / rejected / held
  (partially filled) / pending_cancel``;
- cancel by order id; cancel of a terminal order is refused, cancel of an
  already-cancel-requested order is idempotent;
- day-order semantics: every unfinished order is canceled at end of day
  (``settle_day``);
- partial fills under a caller-supplied volume cap;
- market and limit order styles; no replace primitive (modify = cancel + a
  new order with a new id), no TIF.

Determinism: no wall-clock reads, Decimal money arithmetic, frozen status
constants. The machine is a pure function of (order set, events) — the same
inputs always produce the same ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

STATUS_NEW = "new"
STATUS_OPEN = "open"
STATUS_FILLED = "filled"
STATUS_CANCELED = "canceled"
STATUS_REJECTED = "rejected"
STATUS_HELD = "held"
STATUS_PENDING_CANCEL = "pending_cancel"

_TERMINAL_STATUSES = frozenset(
    {STATUS_FILLED, STATUS_CANCELED, STATUS_REJECTED}
)
_UNFINISHED_STATUSES = frozenset({STATUS_NEW, STATUS_OPEN, STATUS_HELD, STATUS_PENDING_CANCEL})
_ACTIVE_STATUSES = frozenset({STATUS_NEW, STATUS_OPEN, STATUS_HELD})

_ORDER_ID_PREFIX = "pt"


class OrderLifecycleError(ValueError):
    """A lifecycle operation the frozen contract refuses (fail-closed)."""


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """A caller-submitted order, before any lifecycle state.

    ``order_id`` may be omitted; :func:`assign_ids` then derives a stable id
    from the request's position in the list, so a replayed list reproduces
    identical ids and a retry is distinguishable from a new order.
    """

    symbol: str
    side: str
    qty: Decimal
    order_type: str = "market"
    limit_price: Decimal | None = None
    order_id: str | None = None

    def __post_init__(self) -> None:
        if self.side not in ("buy", "sell"):
            raise OrderLifecycleError(f"order side must be 'buy' or 'sell', got {self.side!r}")
        if self.order_type not in ("market", "limit"):
            raise OrderLifecycleError(f"order type must be 'market' or 'limit', got {self.order_type!r}")
        if self.qty <= 0:
            raise OrderLifecycleError(f"order qty must be positive, got {self.qty}")
        if self.order_type == "limit" and self.limit_price is None:
            raise OrderLifecycleError("a limit order must carry limit_price")
        if self.order_type == "market" and self.limit_price is not None:
            raise OrderLifecycleError("a market order must not carry limit_price")


@dataclass(frozen=True, slots=True)
class Fill:
    """One execution against an order; one order can have several fills."""

    order_id: str
    qty: Decimal
    price: Decimal


@dataclass(slots=True)
class OrderState:
    """The mutable lifecycle record of one order (ids are stable, status flows)."""

    request: OrderRequest
    order_id: str
    status: str = STATUS_NEW
    filled_qty: Decimal = Decimal(0)
    avg_fill_price: Decimal | None = None
    fills: list[Fill] = field(default_factory=list)
    rejected_reason: str | None = None


def assign_ids(requests: Iterable[OrderRequest]) -> dict[str, OrderState]:
    """Assign stable ids to a batch of requests.

    Explicit ids are honoured and must be unique; requests without an id get
    ``pt-<index>`` in list order, so replaying the same list reproduces the
    same ids byte for byte.
    """
    states: dict[str, OrderState] = {}
    for index, request in enumerate(requests):
        order_id = request.order_id or f"{_ORDER_ID_PREFIX}-{index}"
        if order_id in states:
            raise OrderLifecycleError(f"duplicate order id {order_id!r}")
        states[order_id] = OrderState(request=request, order_id=order_id)
    return states


class OrderBook:
    """The bar-agnostic lifecycle: orders in, statuses and fills out.

    The book never reads the clock and never touches money floats; fill
    quantities and prices are ``Decimal``. It is deliberately unwired to any
    engine: the 5m session engine (phase 2) will drive it bar by bar.
    """

    def __init__(self, states: dict[str, OrderState] | None = None) -> None:
        self._states: dict[str, OrderState] = dict(states) if states else {}

    # ------------------------------------------------------------------ reads
    @property
    def orders(self) -> dict[str, OrderState]:
        return self._states

    def get(self, order_id: str) -> OrderState | None:
        return self._states.get(order_id)

    def open_orders(self) -> list[OrderState]:
        """Today's unfinished orders (JoinQuant's ``get_open_orders``)."""
        return [s for s in self._states.values() if s.status in _ACTIVE_STATUSES]

    # ----------------------------------------------------------------- writes
    def submit(self, request: OrderRequest) -> OrderState:
        """Accept a new order; the id must not collide with a live or dead one."""
        order_id = request.order_id
        if order_id is None:
            raise OrderLifecycleError("submit requires an explicit order_id")
        if order_id in self._states:
            raise OrderLifecycleError(f"duplicate order id {order_id!r}")
        state = OrderState(request=request, order_id=order_id)
        self._states[order_id] = state
        return state

    def reject(self, order_id: str, reason: str) -> OrderState:
        """Move an unfinished order to ``rejected``; terminal orders are frozen."""
        state = self._require(order_id)
        self._require_unfinished(state, "reject")
        state.status = STATUS_REJECTED
        state.rejected_reason = reason
        return state

    def activate(self, order_id: str) -> OrderState:
        """Move a ``new`` order to ``open`` (accepted for matching)."""
        state = self._require(order_id)
        if state.status != STATUS_NEW:
            raise OrderLifecycleError(
                f"order {order_id!r} cannot activate from status {state.status!r}"
            )
        state.status = STATUS_OPEN
        return state

    def request_cancel(self, order_id: str) -> OrderState:
        """Ask to cancel by order id.

        A terminal order (filled/canceled/rejected) cannot be canceled — the
        refusal is an error, not a silent no-op. Asking twice is idempotent:
        the second call returns the ``pending_cancel`` state unchanged.
        """
        state = self._require(order_id)
        if state.status in _TERMINAL_STATUSES:
            raise OrderLifecycleError(
                f"order {order_id!r} is already {state.status}; it cannot be canceled"
            )
        if state.status != STATUS_PENDING_CANCEL:
            state.status = STATUS_PENDING_CANCEL
        return state

    def fill(self, order_id: str, qty: Decimal, price: Decimal, *, volume_cap: Decimal | None = None) -> Fill:
        """Execute part or all of an unfinished order at ``price``.

        Args:
            order_id: The order to fill.
            qty: Requested execution quantity; clipped to the remaining
                quantity, never negative.
            price: Execution price for this fill.
            volume_cap: Optional per-fill cap (the phase-3 volume-share
                policy); the executed quantity is ``min(qty, cap, remaining)``.

        Returns:
            The executed :class:`Fill`.

        Raises:
            OrderLifecycleError: The order is terminal or already
                cancel-requested (a pending_cancel order stops matching), or
                the qty/cap is not positive.
        """
        state = self._require(order_id)
        if state.status in _TERMINAL_STATUSES:
            raise OrderLifecycleError(
                f"order {order_id!r} is already {state.status}; it cannot fill"
            )
        if state.status == STATUS_PENDING_CANCEL:
            raise OrderLifecycleError(
                f"order {order_id!r} has a pending cancel; it no longer matches"
            )
        if qty <= 0:
            raise OrderLifecycleError(f"fill qty must be positive, got {qty}")
        if volume_cap is not None and volume_cap <= 0:
            raise OrderLifecycleError(f"volume_cap must be positive, got {volume_cap}")
        remaining = state.request.qty - state.filled_qty
        executable = qty if volume_cap is None else min(qty, volume_cap)
        executable = min(executable, remaining)
        if executable <= 0:
            raise OrderLifecycleError(
                f"order {order_id!r} has no remaining quantity to fill"
            )
        fill = Fill(order_id=order_id, qty=executable, price=price)
        state.fills.append(fill)
        state.filled_qty += executable
        total_cost = sum((f.qty * f.price for f in state.fills), Decimal(0))
        state.avg_fill_price = total_cost / state.filled_qty
        state.status = (
            STATUS_FILLED if state.filled_qty == state.request.qty else STATUS_HELD
        )
        return fill

    def settle_day(self) -> list[OrderState]:
        """Day-order semantics: cancel every unfinished order at session end.

        Returns the canceled states. A ``pending_cancel`` order settles the
        same way — the cancel it asked for has arrived.
        """
        settled: list[OrderState] = []
        for state in self._states.values():
            if state.status in _UNFINISHED_STATUSES:
                state.status = STATUS_CANCELED
                settled.append(state)
        return settled

    # --------------------------------------------------------------- helpers
    def _require(self, order_id: str) -> OrderState:
        state = self._states.get(order_id)
        if state is None:
            raise OrderLifecycleError(f"unknown order id {order_id!r}")
        return state

    @staticmethod
    def _require_unfinished(state: OrderState, action: str) -> None:
        if state.status in _TERMINAL_STATUSES:
            raise OrderLifecycleError(
                f"order {state.order_id!r} is already {state.status}; cannot {action} it"
            )


def replay_snapshot(book: OrderBook) -> dict[str, dict[str, object]]:
    """Render the book as a JSON-ready, replay-comparable snapshot.

    Keys are sorted so two runs over identical inputs produce identical
    snapshots; Decimal values are rendered as strings (JCS-safe, like the
    engine's wire format).
    """
    snapshot: dict[str, dict[str, object]] = {}
    for order_id in sorted(book.orders):
        state = book.orders[order_id]
        snapshot[order_id] = {
            "status": state.status,
            "filled_qty": str(state.filled_qty),
            "avg_fill_price": (
                None if state.avg_fill_price is None else str(state.avg_fill_price)
            ),
            "fills": [
                {"qty": str(f.qty), "price": str(f.price)} for f in state.fills
            ],
        }
    return snapshot
