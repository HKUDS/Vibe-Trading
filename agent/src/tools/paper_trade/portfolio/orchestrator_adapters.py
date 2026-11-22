"""Default pure plan builder and marks valuation adapters for pt-v2.0 orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .data import PreparedPortfolioData
from .fx import FxRateBook
from .ledger import PortfolioLedger, value_ledger
from .models import PortfolioRequest
from .numeric import EffectiveFeeModel, parse_effective_fee_model
from .orchestrator_types import (
    AnalyticsRow,
    ExecutionOutcome,
    PlanStageResult,
    ReconciliationCheck,
    ValuationStageResult,
)
from .order_plan import build_explicit_order_plan, build_target_weight_order_plan
from .planner import PlanningMark, plan_target_weights
from .schema import PortfolioRequestError


@dataclass(frozen=True, slots=True)
class PurePlanBuilder:
    """Default plan builder using only post-conversion cash and prior marks."""

    planning_marks: tuple[PlanningMark, ...]
    fee_models: tuple[EffectiveFeeModel, ...] = ()
    hk_lot_sizes: Mapping[str, int] | None = None
    max_fx_age: timedelta | None = None

    def build(
        self,
        request: PortfolioRequest,
        ledger: PortfolioLedger,
    ) -> PlanStageResult:
        fee_models = self.fee_models or tuple(
            parse_effective_fee_model(bucket)
            for bucket in request.portfolio_state.buckets
        )
        if request.orders is not None:
            plan = build_explicit_order_plan(
                request.orders,
                ledger=ledger,
                trade_date=request.trade_date,
                planning_at=request.planning_at,
                base_currency=request.base_currency,
                marks=self.planning_marks,
                fx_snapshots=request.fx_snapshots,
                fee_models=fee_models,
                hk_lot_sizes=self.hk_lot_sizes,
                max_fx_age=self.max_fx_age,
            )
        else:
            if request.target_weights is None:
                raise PortfolioRequestError(
                    reason="missing_order_plan",
                    path="target_weights",
                )
            allocation = plan_target_weights(
                ledger,
                trade_date=request.trade_date,
                planning_at=request.planning_at,
                base_currency=request.base_currency,
                marks=self.planning_marks,
                fx_snapshots=request.fx_snapshots,
                target_weights=request.target_weights,
                rebalance_band=request.rebalance_band,
                max_fx_age=self.max_fx_age,
            )
            plan = build_target_weight_order_plan(
                allocation,
                fee_models=fee_models,
                hk_lot_sizes=self.hk_lot_sizes,
            )
        return PlanStageResult(plan=plan)


@dataclass(frozen=True, slots=True)
class MarksValuation:
    """Default valuation of the replayed ledger through direct FX pairs."""

    marks: Mapping[str, Decimal | str]
    max_fx_age: timedelta | None = None
    analytics: tuple[AnalyticsRow, ...] = ()
    reconciliation: tuple[ReconciliationCheck, ...] = ()
    warnings: tuple[str, ...] = ()

    def value(
        self,
        request: PortfolioRequest,
        ledger: PortfolioLedger,
        execution: ExecutionOutcome,
        prepared: PreparedPortfolioData,
    ) -> ValuationStageResult:
        book = FxRateBook.from_snapshots(
            request.fx_snapshots,
            at=request.valuation_at,
            max_age=self.max_fx_age,
        )
        return ValuationStageResult(
            nav_bridge=value_ledger(
                ledger,
                self.marks,
                book,
                base_currency=request.base_currency,
            ),
            analytics=self.analytics,
            reconciliation=self.reconciliation,
            warnings=self.warnings,
        )
