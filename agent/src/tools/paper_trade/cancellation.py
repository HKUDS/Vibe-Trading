"""Caller cancellation for the discrete 5m paper session, never broker orders."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Sequence

from .order_lifecycle import (
    STATUS_PENDING_CANCEL,
    OrderBook,
    OrderLifecycleError,
    OrderRequest,
    OrderState,
    assign_ids,
)

if TYPE_CHECKING:
    from .schema import Order, PaperTradeStepRequest

CALLER_CANCEL_REASON = "canceled_by_caller"
_CANCEL_WINDOWS = ((9 * 60 + 30, 11 * 60 + 30), (13 * 60, 15 * 60))
_AT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\+08:00")


@dataclass(frozen=True, slots=True)
class CancelRequest:
    order_id: str
    at: str

    @property
    def timestamp(self) -> dt.datetime:
        # Served bar labels are naive Shanghai local times; the input fixes +08:00.
        return dt.datetime.fromisoformat(self.at).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class CancelResult:
    order_id: str
    at: str
    status: str
    filled: float
    remaining: float
    reason: str


def parse_order_id(value: Any, path: str) -> str | None:
    """Keep caller ids opaque; only null selects the existing positional id."""
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ValueError(f"{path} must be a non-empty string of at most 128 characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{path} must contain valid Unicode") from exc
    return value


def parse_cancel_schedule(
    value: Any, *, day: str | None = None
) -> tuple[CancelRequest, ...] | None:
    """Parse same-day Shanghai session boundaries without reading a clock."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("cancel_schedule must be an array")
    requests = []
    for index, item in enumerate(value):
        path = f"cancel_schedule[{index}]"
        if not isinstance(item, dict) or set(item) != {"order_id", "at"}:
            raise ValueError(f"{path} must contain only order_id and at")
        order_id = parse_order_id(item["order_id"], f"{path}.order_id")
        if order_id is None:
            raise ValueError(f"{path}.order_id must be a non-empty string")
        at = item["at"]
        if not isinstance(at, str) or _AT_RE.fullmatch(at) is None:
            raise ValueError(f"{path}.at must be YYYY-MM-DDTHH:MM:00+08:00")
        try:
            timestamp = dt.datetime.fromisoformat(at)
        except ValueError as exc:
            raise ValueError(f"{path}.at must be a valid calendar time") from exc
        minute = timestamp.hour * 60 + timestamp.minute
        if timestamp.minute % 5 or not any(
            start <= minute <= end for start, end in _CANCEL_WINDOWS
        ):
            raise ValueError(f"{path}.at must be a five-minute cn_a session boundary")
        if day is not None and timestamp.date().isoformat() != day:
            raise ValueError(f"{path}.at must be on to_date {day}")
        requests.append(CancelRequest(order_id=order_id, at=at))
    return tuple(requests)


def schedule_payload(
    requests: tuple[CancelRequest, ...] | None,
) -> list[dict[str, str]] | None:
    """Preserve caller ordering in the hash coverage object."""
    if requests is None:
        return None
    return [{"order_id": request.order_id, "at": request.at} for request in requests]


def assign_order_ids(orders: Sequence[Order]) -> dict[str, OrderState]:
    """Use the existing lifecycle id owner for validation and matching alike."""
    requests = []
    for order in orders:
        limit = Decimal(str(order.limit)) if order.limit is not None else None
        requests.append(
            OrderRequest(
                symbol=order.symbol,
                side=order.side,
                qty=Decimal(str(order.qty)),
                order_type="limit" if limit is not None else "market",
                limit_price=limit,
                order_id=getattr(order, "order_id", None),
            )
        )
    return assign_ids(requests)


def validate_request(request: PaperTradeStepRequest) -> None:
    """Reject ambiguous cancellation before providers or matching can run."""
    if not request.uses_v1_4:
        return
    if (
        request.interval != "5m"
        or request.market != "cn_a"
        or request.orders is None
        or request.strategy_path is not None
        or request.from_date != request.to_date
    ):
        raise ValueError(
            "caller order_id and cancel_schedule require single-day 5m cn_a orders mode"
        )
    states = assign_order_ids(request.orders)
    for cancel in request.cancel_schedule or ():
        if cancel.order_id not in states:
            raise ValueError(
                f"cancel_schedule references unknown order_id {cancel.order_id!r}"
            )


def apply_cancel(book: OrderBook, request: CancelRequest) -> CancelResult:
    """Stop further matching now; the existing day settlement confirms cancel."""
    state = book.get(request.order_id)
    if state is None:
        raise OrderLifecycleError(f"unknown order id {request.order_id!r}")
    previous = state.status
    try:
        book.request_cancel(request.order_id, reason=CALLER_CANCEL_REASON)
    except OrderLifecycleError:
        status, reason = "rejected", f"terminal_{previous}"
    else:
        status = STATUS_PENDING_CANCEL
        if previous == STATUS_PENDING_CANCEL:
            reason = "already_pending_cancel"
        else:
            reason = "cancel_requested"
    return CancelResult(
        order_id=request.order_id,
        at=request.at,
        status=status,
        filled=float(state.filled_qty),
        remaining=float(state.request.qty - state.filled_qty),
        reason=reason,
    )
