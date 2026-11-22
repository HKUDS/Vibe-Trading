"""The public Decimal reconstruct-and-check execution adapter.

:class:`DecimalExecutionAdapter` validates the bundle, derives one
``MarketRules`` per bucket, matches every planned order exactly once and
returns an :class:`~.orchestrator.ExecutionOutcome` only after the full
ledger replay passes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .data import PreparedPortfolioData
from .execution_common import _abort, _effective_models, _market_rules
from .execution_outcome import _bucket_outcome, _validate_replayed_ledger
from .execution_validation import _preflight_for_bucket, _validate_plan
from .ledger import LedgerEvent, PortfolioLedger
from .models import Market, PortfolioRequest
from .numeric import EffectiveFeeModel
from .orchestrator import (
    ExecutionCancellation,
    ExecutionFill,
    ExecutionOutcome,
    ExecutionRejection,
)
from .order_plan import OrderPlan, PlannedOrder


@dataclass(frozen=True, slots=True)
class DecimalExecutionAdapter:
    """``MatchAdapter`` replaying only cash/position ledger events."""

    fee_models: tuple[EffectiveFeeModel, ...] = ()
    hk_lot_sizes: Mapping[str, int] | None = None
    limits_clients: Mapping[Market, Any] | None = None

    def match(
        self,
        request: PortfolioRequest,
        ledger: PortfolioLedger,
        plan: OrderPlan,
        prepared: PreparedPortfolioData,
    ) -> ExecutionOutcome:
        """Match every planned order once, or raise without a partial outcome."""
        _validate_plan(request, ledger, plan, prepared)
        models = _effective_models(request, self.fee_models)
        rules = {
            bucket_id: _market_rules(model, self.hk_lot_sizes)
            for bucket_id, model in models.items()
        }
        orders_by_bucket: dict[str, list[PlannedOrder]] = {}
        for order in plan.orders:
            orders_by_bucket.setdefault(order.bucket_id, []).append(order)

        fills: list[ExecutionFill] = []
        rejected: list[ExecutionRejection] = []
        canceled: list[ExecutionCancellation] = []
        events: list[LedgerEvent] = []
        for bucket_plan in plan.buckets:
            bucket_orders = tuple(orders_by_bucket.get(bucket_plan.bucket_id, ()))
            if not bucket_orders:
                continue
            bucket = next(
                row for row in ledger.buckets if row.bucket_id == bucket_plan.bucket_id
            )
            entry = _preflight_for_bucket(bucket, request, prepared)
            bucket_fills, bucket_rejected, bucket_canceled, bucket_events = _bucket_outcome(
                bucket=bucket,
                request=request,
                orders=bucket_orders,
                entry=entry,
                rules=rules[bucket.bucket_id],
                hk_lot_sizes=self.hk_lot_sizes,
                limits_clients=self.limits_clients,
            )
            fills.extend(bucket_fills)
            rejected.extend(bucket_rejected)
            canceled.extend(bucket_canceled)
            events.extend(bucket_events)

        seen: set[str] = set()
        for row in (*fills, *rejected, *canceled):
            if row.plan_order_id in seen:
                _abort(
                    "duplicate_order_outcome",
                    f"execution.{row.plan_order_id}",
                    bucket_id=row.bucket_id,
                )
            seen.add(row.plan_order_id)
        missing = {order.plan_order_id for order in plan.orders} - seen
        if missing:
            _abort(
                "missing_order_outcome",
                "execution",
                detail=f"no terminal outcome for {', '.join(sorted(missing))}",
            )
        _validate_replayed_ledger(ledger, events)
        return ExecutionOutcome(
            fills=tuple(fills),
            rejected_orders=tuple(rejected),
            canceled_orders=tuple(canceled),
            ledger_events=tuple(events),
        )
