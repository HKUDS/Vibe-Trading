"""Preflight validation for pt-v2.0 orchestration (preflight_execution_inputs stage)."""

from __future__ import annotations

from .data import (
    PreparedPortfolioData,
    PriorMarkValuation,
    TargetBarValuation,
)
from .models import PortfolioRequest
from .orchestrator_plan_validation import _abort, _required_bucket_ids
from .orchestrator_types import StageName
from .order_plan import OrderPlan


def _validate_preflight(
    request: PortfolioRequest,
    plan: OrderPlan,
    prepared: PreparedPortfolioData,
    completed: list[StageName],
) -> None:
    expected_ids = tuple(
        bucket.bucket_id for bucket in request.portfolio_state.buckets
    )
    prepared_ids = tuple(bucket.bucket_id for bucket in prepared.buckets)
    if prepared_ids != expected_ids:
        _abort(
            "preflight_execution_inputs",
            "preflight_bucket_mismatch",
            path="prepared_data.buckets",
            detail="every request bucket must be preflighted in declaration order",
            completed=completed,
        )
    if prepared.preflight:
        journal_ids = tuple(entry.bucket_id for entry in prepared.preflight)
        if journal_ids != expected_ids:
            _abort(
                "preflight_execution_inputs",
                "incomplete_bucket_preflight",
                path="prepared_data.preflight",
                detail="the preflight journal must cover every bucket before matching",
                completed=completed,
            )
    sessions = {session.market: session for session in request.sessions}
    by_id = {bucket.bucket_id: bucket for bucket in prepared.buckets}
    for bucket in request.portfolio_state.buckets:
        prepared_bucket = by_id[bucket.bucket_id]
        session = prepared_bucket.session
        if (
            session.bucket_id != bucket.bucket_id
            or session.market != bucket.market
            or session.price_date != request.trade_date
            or session.session != sessions[bucket.market]
        ):
            _abort(
                "preflight_execution_inputs",
                "preflight_session_mismatch",
                path=f"prepared_data.buckets.{bucket.bucket_id}.session",
                bucket_id=bucket.bucket_id,
                completed=completed,
            )
        if session.matchable:
            if prepared_bucket.execution is None:
                _abort(
                    "preflight_execution_inputs",
                    "missing_execution_inputs",
                    path=f"prepared_data.buckets.{bucket.bucket_id}.execution",
                    bucket_id=bucket.bucket_id,
                    completed=completed,
                )
            if prepared_bucket.execution.price_date != request.trade_date:
                _abort(
                    "preflight_execution_inputs",
                    "preflight_execution_date_mismatch",
                    path=f"prepared_data.buckets.{bucket.bucket_id}.execution",
                    bucket_id=bucket.bucket_id,
                    completed=completed,
                )
            if not isinstance(prepared_bucket.valuation, TargetBarValuation):
                _abort(
                    "preflight_execution_inputs",
                    "missing_target_valuation",
                    path=f"prepared_data.buckets.{bucket.bucket_id}.valuation",
                    bucket_id=bucket.bucket_id,
                    completed=completed,
                )
            if prepared_bucket.valuation.snapshot.price_date != request.trade_date:
                _abort(
                    "preflight_execution_inputs",
                    "preflight_valuation_date_mismatch",
                    path=f"prepared_data.buckets.{bucket.bucket_id}.valuation",
                    bucket_id=bucket.bucket_id,
                    completed=completed,
                )
        else:
            if prepared_bucket.execution is not None:
                _abort(
                    "preflight_execution_inputs",
                    "closed_bucket_execution_inputs",
                    path=f"prepared_data.buckets.{bucket.bucket_id}.execution",
                    bucket_id=bucket.bucket_id,
                    completed=completed,
                )
            if not isinstance(prepared_bucket.valuation, PriorMarkValuation):
                _abort(
                    "preflight_execution_inputs",
                    "missing_prior_mark_valuation",
                    path=f"prepared_data.buckets.{bucket.bucket_id}.valuation",
                    bucket_id=bucket.bucket_id,
                    completed=completed,
                )
    required = _required_bucket_ids(request)
    for bucket_id in required:
        if not by_id[bucket_id].session.matchable:
            _abort(
                "preflight_execution_inputs",
                "required_bucket_not_open",
                path=f"prepared_data.buckets.{bucket_id}.session.status",
                bucket_id=bucket_id,
                completed=completed,
            )
    for order in plan.orders:
        prepared_bucket = by_id.get(order.bucket_id)
        if prepared_bucket is None or not prepared_bucket.session.matchable:
            _abort(
                "preflight_execution_inputs",
                "order_on_closed_bucket",
                path=f"order_plan.orders.{order.plan_order_id}.bucket_id",
                bucket_id=order.bucket_id,
                completed=completed,
            )
