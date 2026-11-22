"""Stage-fault helpers and plan-stage validation for pt-v2.0 orchestration."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import NoReturn

from .ledger import PortfolioLedger
from .models import PortfolioRequest
from .orchestrator_types import (
    OrchestrationCode,
    OrchestrationError,
    StageName,
    StageObserver,
    StageValue,
)
from .order_plan import OrderPlan
from .schema import PortfolioRequestError
from .sessions import PortfolioSessionError


def _abort(
    stage: StageName,
    reason: str,
    *,
    path: str = "$",
    bucket_id: str | None = None,
    code: OrchestrationCode = "INTERNAL",
    detail: str = "",
    completed: list[StageName],
) -> NoReturn:
    raise OrchestrationError(
        stage=stage,
        reason=reason,
        code=code,
        path=path,
        bucket_id=bucket_id,
        detail=detail,
        completed_stages=tuple(completed),
    )


def _run_stage(
    stage: StageName,
    action: Callable[[], StageValue],
    *,
    observer: StageObserver | None,
    entered: list[StageName],
    completed: list[StageName],
) -> StageValue:
    entered.append(stage)
    if observer is not None:
        observer(stage)
    try:
        value = action()
    except OrchestrationError:
        raise
    except PortfolioSessionError as exc:
        raise OrchestrationError(
            stage=stage,
            reason=exc.reason,
            code=exc.code,
            path=exc.path,
            bucket_id=exc.bucket_id,
            detail=exc.detail,
            completed_stages=tuple(completed),
        ) from None
    except PortfolioRequestError as exc:
        raise OrchestrationError(
            stage=stage,
            reason=exc.reason,
            code="INVALID_REQUEST",
            path=exc.path,
            bucket_id=exc.bucket_id,
            detail=exc.detail,
            completed_stages=tuple(completed),
        ) from None
    except Exception as exc:
        raise OrchestrationError(
            stage=stage,
            reason="internal_stage_failure",
            path="$",
            detail=f"{type(exc).__name__}: {exc}"[:200],
            completed_stages=tuple(completed),
        ) from exc
    completed.append(stage)
    return value


def _required_bucket_ids(request: PortfolioRequest) -> frozenset[str]:
    if request.orders is not None:
        return frozenset(order.bucket_id for order in request.orders)
    targets = request.target_weights or ()
    return frozenset(
        target.bucket_id for target in targets if Decimal(target.weight) != 0
    )


def _require_positive(value: object, path: str, completed: list[StageName]) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        _abort(
            "match_orders",
            "invalid_execution_decimal",
            path=path,
            detail="expected a finite positive Decimal",
            completed=completed,
        )


def _require_nonnegative(value: object, path: str, completed: list[StageName]) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        _abort(
            "match_orders",
            "invalid_execution_decimal",
            path=path,
            detail="expected a finite nonnegative Decimal",
            completed=completed,
        )


def _validate_plan_cash(
    plan: OrderPlan,
    ledger: PortfolioLedger,
    completed: list[StageName],
) -> None:
    ledger_by_id = {bucket.bucket_id: bucket for bucket in ledger.buckets}
    plan_ids = [bucket.bucket_id for bucket in plan.buckets]
    if len(plan_ids) != len(set(plan_ids)) or set(plan_ids) != set(ledger_by_id):
        _abort(
            "build_plan",
            "plan_bucket_mismatch",
            path="order_plan.buckets",
            detail="the plan must name each ledger bucket exactly once",
            completed=completed,
        )
    for bucket in plan.buckets:
        ledger_bucket = ledger_by_id[bucket.bucket_id]
        if (
            bucket.market != ledger_bucket.market
            or bucket.currency != ledger_bucket.currency
        ):
            _abort(
                "build_plan",
                "plan_bucket_mismatch",
                path=f"order_plan.buckets.{bucket.bucket_id}",
                bucket_id=bucket.bucket_id,
                detail="plan and ledger bucket identity must agree",
                completed=completed,
            )
        if bucket.opening_cash != ledger_bucket.cash:
            _abort(
                "build_plan",
                "plan_cash_mismatch",
                path=f"order_plan.buckets.{bucket.bucket_id}.opening_cash",
                bucket_id=bucket.bucket_id,
                detail="the plan must use post-conversion cash, not opening cash",
                completed=completed,
            )
    seen_ids: set[str] = set()
    for order in plan.orders:
        if order.plan_order_id in seen_ids:
            _abort(
                "build_plan",
                "duplicate_plan_order_id",
                path=f"order_plan.orders.{order.plan_order_id}",
                bucket_id=order.bucket_id,
                completed=completed,
            )
        seen_ids.add(order.plan_order_id)
        if order.bucket_id not in ledger_by_id:
            _abort(
                "build_plan",
                "plan_bucket_mismatch",
                path=f"order_plan.orders.{order.plan_order_id}.bucket_id",
                bucket_id=order.bucket_id,
                completed=completed,
            )


def _reject_planner_conversions(
    plan: OrderPlan,
    completed: list[StageName],
) -> None:
    for attribute in ("conversions", "fx_conversions"):
        if getattr(plan, attribute, ()):
            _abort(
                "build_plan",
                "planner_generated_conversion",
                path=f"order_plan.{attribute}",
                detail="conversions are caller-declared and never planner-generated",
                completed=completed,
            )
