"""The fixed seven-stage pt-v2.0 portfolio orchestration run."""

from __future__ import annotations

from collections.abc import Callable

from .data import PreparedPortfolioData
from .fx import plan_conversions
from .ledger import (
    ConversionReplay,
    LedgerNavBridge,
    PortfolioLedger,
    apply_conversions,
)
from .models import PortfolioRequest
from .orchestrator_outcome_validation import _validate_outcome
from .orchestrator_plan_validation import (
    _abort,
    _reject_planner_conversions,
    _run_stage,
    _validate_plan_cash,
)
from .orchestrator_preflight_validation import _validate_preflight
from .orchestrator_types import (
    ExecutionOutcome,
    OrchestrationAdapters,
    OrchestrationError,
    OrchestrationResult,
    PlanStageResult,
    ReconciliationCheck,
    StageName,
    StageObserver,
    StageValue,
    ValuationStageResult,
)
from .order_plan import OrderPlan


def run_portfolio_orchestration(
    request: PortfolioRequest,
    *,
    adapters: OrchestrationAdapters,
    observer: StageObserver | None = None,
) -> OrchestrationResult:
    """Run the seven fixed stages or raise without exposing a partial document."""
    if not isinstance(request, PortfolioRequest):
        raise OrchestrationError(
            stage="validate_opening_ledger",
            reason="invalid_portfolio_request",
            code="INVALID_REQUEST",
            path="$",
            detail="expected the parsed pt-v2.0 PortfolioRequest",
        )

    entered: list[StageName] = []
    completed: list[StageName] = []

    def stage(
        name: StageName,
        action: Callable[[], StageValue],
    ) -> StageValue:
        return _run_stage(
            name,
            action,
            observer=observer,
            entered=entered,
            completed=completed,
        )

    def validate_opening() -> PortfolioLedger:
        ledger = adapters.opening_ledger.validate(request)
        if not isinstance(ledger, PortfolioLedger):
            _abort(
                "validate_opening_ledger",
                "invalid_opening_ledger",
                path="portfolio_ledger",
                completed=completed,
            )
        expected = PortfolioLedger.from_request(request)
        if ledger != expected:
            _abort(
                "validate_opening_ledger",
                "opening_ledger_mismatch",
                path="portfolio_ledger",
                detail="the opening ledger must equal the parsed request ledger",
                completed=completed,
            )
        return ledger

    opening_ledger = stage("validate_opening_ledger", validate_opening)

    def apply_declared_conversions() -> ConversionReplay:
        replay = adapters.conversions.apply(request, opening_ledger)
        if not isinstance(replay, ConversionReplay):
            _abort(
                "apply_caller_conversions",
                "invalid_conversion_replay",
                path="fx_conversions",
                completed=completed,
            )
        if replay.opening != opening_ledger:
            _abort(
                "apply_caller_conversions",
                "conversion_opening_ledger_mismatch",
                path="fx_conversions",
                detail="conversions must settle against the validated opening ledger",
                completed=completed,
            )
        expected = apply_conversions(
            opening_ledger,
            plan_conversions(request, stage="pre_fill"),
            stage="pre_fill",
        )
        if replay.events != expected.events:
            _abort(
                "apply_caller_conversions",
                "conversion_declaration_mismatch",
                path="fx_conversions",
                detail="only caller-declared conversions may settle before planning",
                completed=completed,
            )
        if replay.post_conversion != expected.post_conversion:
            _abort(
                "apply_caller_conversions",
                "conversion_replay_mismatch",
                path="fx_conversions",
                detail="post-conversion cash must equal the declared replay",
                completed=completed,
            )
        if replay.total_residual != expected.total_residual:
            _abort(
                "apply_caller_conversions",
                "conversion_residual_mismatch",
                path="fx_conversions.residual",
                completed=completed,
            )
        return replay

    conversion_replay = stage(
        "apply_caller_conversions",
        apply_declared_conversions,
    )

    def build_pure_plan() -> PlanStageResult:
        built = adapters.plan.build(request, conversion_replay.post_conversion)
        if not isinstance(built, PlanStageResult):
            _abort(
                "build_plan",
                "invalid_plan_stage_result",
                path="order_plan",
                completed=completed,
            )
        if built.conversion_requests:
            _abort(
                "build_plan",
                "planner_generated_conversion",
                path="order_plan.conversion_requests",
                detail="conversions are caller-declared and never planner-generated",
                completed=completed,
            )
        plan = built.plan
        if not isinstance(plan, OrderPlan):
            _abort(
                "build_plan",
                "invalid_order_plan",
                path="order_plan",
                completed=completed,
            )
        _reject_planner_conversions(plan, completed)
        expected_mode = (
            "explicit_orders" if request.orders is not None else "target_weights"
        )
        if plan.mode != expected_mode:
            _abort(
                "build_plan",
                "plan_mode_mismatch",
                path="order_plan.mode",
                detail=f"expected {expected_mode!r}",
                completed=completed,
            )
        if (
            plan.trade_date != request.trade_date
            or plan.planning_at != request.planning_at
            or plan.base_currency != request.base_currency
        ):
            _abort(
                "build_plan",
                "plan_identity_mismatch",
                path="order_plan",
                detail="plan identity must equal the request identity",
                completed=completed,
            )
        _validate_plan_cash(plan, conversion_replay.post_conversion, completed)
        return built

    plan_stage = stage("build_plan", build_pure_plan)

    def preflight_execution() -> PreparedPortfolioData:
        prepared = adapters.preflight.preflight(
            request,
            conversion_replay.post_conversion,
            plan_stage.plan,
        )
        if not isinstance(prepared, PreparedPortfolioData):
            _abort(
                "preflight_execution_inputs",
                "invalid_preflight_result",
                path="prepared_data",
                completed=completed,
            )
        _validate_preflight(
            request,
            plan_stage.plan,
            prepared,
            completed,
        )
        return prepared

    prepared_data = stage("preflight_execution_inputs", preflight_execution)

    def match_orders() -> ExecutionOutcome:
        outcome = adapters.execution.match(
            request,
            conversion_replay.post_conversion,
            plan_stage.plan,
            prepared_data,
        )
        if not isinstance(outcome, ExecutionOutcome):
            _abort(
                "match_orders",
                "invalid_execution_outcome",
                path="execution",
                completed=completed,
            )
        _validate_outcome(
            outcome,
            plan_stage.plan,
            request,
            completed,
        )
        return outcome

    execution = stage("match_orders", match_orders)

    def replay_decimal_ledger() -> PortfolioLedger:
        end_ledger = conversion_replay.post_conversion.apply(
            execution.ledger_events
        )
        if not isinstance(end_ledger, PortfolioLedger):
            _abort(
                "replay_ledger",
                "invalid_end_ledger",
                path="end_ledger",
                completed=completed,
            )
        before_ids = tuple(
            bucket.bucket_id for bucket in conversion_replay.post_conversion.buckets
        )
        after_ids = tuple(bucket.bucket_id for bucket in end_ledger.buckets)
        if before_ids != after_ids:
            _abort(
                "replay_ledger",
                "end_ledger_bucket_mismatch",
                path="end_ledger.buckets",
                completed=completed,
            )
        for bucket in end_ledger.buckets:
            if bucket.cash < 0:
                _abort(
                    "replay_ledger",
                    "negative_end_cash",
                    path=f"end_ledger.{bucket.bucket_id}.cash",
                    bucket_id=bucket.bucket_id,
                    detail="execution may not leave a bucket short of cash",
                    completed=completed,
                )
        return end_ledger

    end_ledger = stage("replay_ledger", replay_decimal_ledger)

    def valuate_and_reconcile() -> ValuationStageResult:
        valued = adapters.valuation.value(
            request,
            end_ledger,
            execution,
            prepared_data,
        )
        if not isinstance(valued, ValuationStageResult):
            _abort(
                "valuate_reconcile",
                "invalid_valuation_result",
                path="valuation",
                completed=completed,
            )
        bridge = valued.nav_bridge
        if not isinstance(bridge, LedgerNavBridge):
            _abort(
                "valuate_reconcile",
                "invalid_nav_bridge",
                path="valuation.nav_bridge",
                completed=completed,
            )
        if not bridge.balanced:
            _abort(
                "valuate_reconcile",
                "nav_bridge_unbalanced",
                path="valuation.nav_bridge",
                detail="exact base NAV must equal reported base plus residual",
                completed=completed,
            )
        end_by_id = {bucket.bucket_id: bucket for bucket in end_ledger.buckets}
        row_ids = tuple(row.bucket_id for row in bridge.rows)
        if len(row_ids) != len(set(row_ids)) or set(row_ids) != set(end_by_id):
            _abort(
                "valuate_reconcile",
                "valuation_bucket_mismatch",
                path="valuation.nav_bridge.rows",
                completed=completed,
            )
        for row in bridge.rows:
            bucket = end_by_id[row.bucket_id]
            if row.market != bucket.market or row.currency != bucket.currency:
                _abort(
                    "valuate_reconcile",
                    "valuation_identity_mismatch",
                    path=f"valuation.nav_bridge.rows.{row.bucket_id}",
                    bucket_id=row.bucket_id,
                    completed=completed,
                )
            if row.cash != bucket.cash:
                _abort(
                    "valuate_reconcile",
                    "valuation_cash_mismatch",
                    path=f"valuation.nav_bridge.rows.{row.bucket_id}.cash",
                    bucket_id=row.bucket_id,
                    completed=completed,
                )
            if row.local_nav != row.cash + row.position_value:
                _abort(
                    "valuate_reconcile",
                    "valuation_nav_mismatch",
                    path=f"valuation.nav_bridge.rows.{row.bucket_id}.local_nav",
                    bucket_id=row.bucket_id,
                    completed=completed,
                )
        for check in valued.reconciliation:
            if not isinstance(check, ReconciliationCheck):
                _abort(
                    "valuate_reconcile",
                    "invalid_reconciliation_check",
                    path="valuation.reconciliation",
                    completed=completed,
                )
            if not check.passed:
                _abort(
                    "valuate_reconcile",
                    "reconciliation_failed",
                    path=f"valuation.reconciliation.{check.name}",
                    detail=check.detail,
                    completed=completed,
                )
        return valued

    valuation = stage("valuate_reconcile", valuate_and_reconcile)

    return OrchestrationResult(
        request=request,
        opening_ledger=opening_ledger,
        conversion_replay=conversion_replay,
        plan=plan_stage.plan,
        prepared_data=prepared_data,
        execution=execution,
        end_ledger=end_ledger,
        valuation=valuation,
        stage_trace=tuple(completed),
    )
