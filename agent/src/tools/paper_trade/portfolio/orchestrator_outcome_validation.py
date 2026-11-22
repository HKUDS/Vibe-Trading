"""Execution-outcome validation for pt-v2.0 orchestration (match_orders stage)."""

from __future__ import annotations

from .fx import FxConversionEvent
from .ledger import CashMovement, PositionMovement
from .models import PortfolioRequest
from .orchestrator_plan_validation import (
    _abort,
    _require_nonnegative,
    _require_positive,
)
from .orchestrator_types import ExecutionOutcome, StageName
from .order_plan import OrderPlan


def _validate_outcome(
    outcome: ExecutionOutcome,
    plan: OrderPlan,
    request: PortfolioRequest,
    completed: list[StageName],
) -> None:
    for attribute in ("conversions", "fx_conversions", "conversion_requests"):
        if getattr(outcome, attribute, ()):
            _abort(
                "match_orders",
                "post_fill_fx_conversion",
                path=f"execution.{attribute}",
                detail="conversions settle before matching and never after fills",
                completed=completed,
            )
    for event in outcome.ledger_events:
        if isinstance(event, FxConversionEvent):
            _abort(
                "match_orders",
                "post_fill_fx_conversion",
                path="execution.ledger_events",
                detail="a post-fill conversion event cannot enter Decimal replay",
                completed=completed,
            )
        if not isinstance(event, (CashMovement, PositionMovement)):
            _abort(
                "match_orders",
                "invalid_ledger_event",
                path="execution.ledger_events",
                detail="only cash and position movements may be replayed",
                completed=completed,
            )
    plan_by_id = {}
    for order in plan.orders:
        if order.plan_order_id in plan_by_id:
            _abort(
                "match_orders",
                "duplicate_plan_order_id",
                path=f"order_plan.orders.{order.plan_order_id}",
                bucket_id=order.bucket_id,
                completed=completed,
            )
        plan_by_id[order.plan_order_id] = order
    seen: set[str] = set()
    outcome_rows = (
        ("fills", outcome.fills),
        ("rejected_orders", outcome.rejected_orders),
        ("canceled_orders", outcome.canceled_orders),
    )
    for field, rows in outcome_rows:
        for row in rows:
            order = plan_by_id.get(row.plan_order_id)
            if order is None:
                _abort(
                    "match_orders",
                    "unknown_plan_order_id",
                    path=f"execution.{field}.{row.plan_order_id}",
                    bucket_id=row.bucket_id,
                    completed=completed,
                )
            if row.plan_order_id in seen:
                _abort(
                    "match_orders",
                    "duplicate_order_outcome",
                    path=f"execution.{field}.{row.plan_order_id}",
                    bucket_id=row.bucket_id,
                    detail="every planned order has exactly one terminal outcome",
                    completed=completed,
                )
            seen.add(row.plan_order_id)
            mismatch = (
                row.bucket_id != order.bucket_id
                or row.symbol != order.symbol
                or row.currency != order.currency
                or row.side != order.side
                or row.trade_date != request.trade_date
            )
            if mismatch:
                _abort(
                    "match_orders",
                    "execution_plan_mismatch",
                    path=f"execution.{field}.{row.plan_order_id}",
                    bucket_id=order.bucket_id,
                    detail="the outcome row must describe its planned order",
                    completed=completed,
                )
            if type(row.qty) is not int or row.qty <= 0:
                _abort(
                    "match_orders",
                    "invalid_execution_quantity",
                    path=f"execution.{field}.{row.plan_order_id}.qty",
                    bucket_id=order.bucket_id,
                    completed=completed,
                )
            if field != "fills" and row.qty != order.qty:
                _abort(
                    "match_orders",
                    "outcome_quantity_mismatch",
                    path=f"execution.{field}.{row.plan_order_id}.qty",
                    bucket_id=order.bucket_id,
                    detail="every terminal outcome must match its planned order quantity",
                    completed=completed,
                )
    missing = set(plan_by_id) - seen
    if missing:
        _abort(
            "match_orders",
            "missing_order_outcome",
            path="execution",
            detail=f"no terminal outcome for {', '.join(sorted(missing))}",
            completed=completed,
        )
    for fill in outcome.fills:
        order = plan_by_id[fill.plan_order_id]
        if fill.qty != order.qty:
            _abort(
                "match_orders",
                "fill_quantity_mismatch",
                path=f"execution.fills.{fill.plan_order_id}.qty",
                bucket_id=fill.bucket_id,
                detail="all_or_none fills must fill the planned quantity exactly",
                completed=completed,
            )
        _require_positive(
            fill.price,
            f"execution.fills.{fill.plan_order_id}.price",
            completed,
        )
        _require_nonnegative(
            fill.fee,
            f"execution.fills.{fill.plan_order_id}.fee",
            completed,
        )
    for field, rows in (
        ("rejected_orders", outcome.rejected_orders),
        ("canceled_orders", outcome.canceled_orders),
    ):
        for row in rows:
            if not isinstance(row.reason_code, str) or not row.reason_code:
                _abort(
                    "match_orders",
                    "missing_outcome_reason",
                    path=f"execution.{field}.{row.plan_order_id}.reason_code",
                    bucket_id=row.bucket_id,
                    completed=completed,
                )
