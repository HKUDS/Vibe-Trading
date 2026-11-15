"""Fixed pt-v2.0 portfolio step ordering over narrow typed stage adapters.

The orchestrator is the only place that decides what runs next. It validates
the opening ledger, settles caller-declared conversions against opening cash,
builds a pure plan from the post-conversion ledger, preflights every execution
bucket, matches, replays Decimal ledger events, then values and reconciles.
Any stage fault raises :class:`OrchestrationError` and discards the whole
in-memory document, so no caller can observe a partial end ledger or fill list.
Per-order reject/cancel rows are data, not faults, and force ``complete=False``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Final, Literal, NoReturn, Protocol, TypeAlias, TypeVar

from .data import (
    PreparedPortfolioData,
    PriorMarkValuation,
    TargetBarValuation,
)
from .fx import (
    FxConversionEvent,
    FxRateBook,
    plan_conversions,
)
from .ledger import (
    CashMovement,
    ConversionReplay,
    LedgerEvent,
    LedgerNavBridge,
    PortfolioLedger,
    PositionMovement,
    apply_conversions,
    value_ledger,
)
from .models import Currency, PortfolioRequest
from .numeric import EffectiveFeeModel, parse_effective_fee_model
from .order_plan import (
    OrderPlan,
    build_explicit_order_plan,
    build_target_weight_order_plan,
)
from .planner import PlanningMark, plan_target_weights
from .schema import PortfolioRequestError
from .sessions import PortfolioSessionError

__all__ = [
    "STAGE_SEQUENCE",
    "AnalyticsRow",
    "CallerDeclaredConversions",
    "ConversionAdapter",
    "ExecutionCancellation",
    "ExecutionFill",
    "ExecutionOutcome",
    "ExecutionRejection",
    "MarksValuation",
    "MatchAdapter",
    "OpeningLedgerAdapter",
    "OpeningLedgerValidation",
    "OrchestrationAdapters",
    "OrchestrationError",
    "OrchestrationResult",
    "PlanAdapter",
    "PlanStageResult",
    "PreflightAdapter",
    "PurePlanBuilder",
    "ReconciliationCheck",
    "StageName",
    "StageObserver",
    "ValuationAdapter",
    "ValuationStageResult",
    "run_portfolio_orchestration",
]

StageName: TypeAlias = Literal[
    "validate_opening_ledger",
    "apply_caller_conversions",
    "build_plan",
    "preflight_execution_inputs",
    "match_orders",
    "replay_ledger",
    "valuate_reconcile",
]
StageObserver: TypeAlias = Callable[[StageName], None]
Side: TypeAlias = Literal["buy", "sell"]
OrchestrationCode: TypeAlias = Literal[
    "INVALID_REQUEST",
    "PAPER_DATA_NOT_READY",
    "INTERNAL",
]

STAGE_SEQUENCE: Final[tuple[StageName, ...]] = (
    "validate_opening_ledger",
    "apply_caller_conversions",
    "build_plan",
    "preflight_execution_inputs",
    "match_orders",
    "replay_ledger",
    "valuate_reconcile",
)

StageValue = TypeVar("StageValue")


@dataclass(frozen=True, slots=True)
class OrchestrationError(Exception):
    """One stable stage failure; it never carries a partial ledger or fills."""

    stage: StageName
    reason: str
    code: OrchestrationCode = "INTERNAL"
    path: str = "$"
    bucket_id: str | None = None
    detail: str = ""
    completed_stages: tuple[StageName, ...] = ()

    def __str__(self) -> str:
        return f"{self.code}:{self.stage}:{self.reason}:{self.path}"


@dataclass(frozen=True, slots=True)
class ExecutionFill:
    """One whole-qty Decimal fill tied to a planned order."""

    plan_order_id: str
    bucket_id: str
    symbol: str
    currency: Currency
    side: Side
    qty: int
    price: Decimal
    fee: Decimal
    trade_date: date


@dataclass(frozen=True, slots=True)
class ExecutionRejection:
    """One explicit rejected order row; it makes the document incomplete."""

    plan_order_id: str
    bucket_id: str
    symbol: str
    currency: Currency
    side: Side
    qty: int
    trade_date: date
    reason_code: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionCancellation:
    """One explicit canceled order row; it makes the document incomplete."""

    plan_order_id: str
    bucket_id: str
    symbol: str
    currency: Currency
    side: Side
    qty: int
    trade_date: date
    reason_code: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Matcher output: ordered fills/rejects/cancels plus exact ledger events."""

    fills: tuple[ExecutionFill, ...] = ()
    rejected_orders: tuple[ExecutionRejection, ...] = ()
    canceled_orders: tuple[ExecutionCancellation, ...] = ()
    ledger_events: tuple[LedgerEvent, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.rejected_orders and not self.canceled_orders


@dataclass(frozen=True, slots=True)
class PlanStageResult:
    """A pure order plan plus any forbidden planner conversion requests."""

    plan: OrderPlan
    conversion_requests: tuple[FxConversionEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalyticsRow:
    """One caller-visible analytics value computed after valuation."""

    name: str
    value: Decimal


@dataclass(frozen=True, slots=True)
class ReconciliationCheck:
    """One explicit post-valuation check; a failed check aborts the document."""

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ValuationStageResult:
    """The retained NAV bridge plus analytics and reconciliation evidence."""

    nav_bridge: LedgerNavBridge
    analytics: tuple[AnalyticsRow, ...] = ()
    reconciliation: tuple[ReconciliationCheck, ...] = ()
    warnings: tuple[str, ...] = ()
class OpeningLedgerAdapter(Protocol):
    def validate(self, request: PortfolioRequest) -> PortfolioLedger: ...


class ConversionAdapter(Protocol):
    def apply(
        self,
        request: PortfolioRequest,
        opening: PortfolioLedger,
    ) -> ConversionReplay: ...


class PlanAdapter(Protocol):
    def build(
        self,
        request: PortfolioRequest,
        ledger: PortfolioLedger,
    ) -> PlanStageResult: ...


class PreflightAdapter(Protocol):
    def preflight(
        self,
        request: PortfolioRequest,
        ledger: PortfolioLedger,
        plan: OrderPlan,
    ) -> PreparedPortfolioData: ...


class MatchAdapter(Protocol):
    def match(
        self,
        request: PortfolioRequest,
        ledger: PortfolioLedger,
        plan: OrderPlan,
        prepared: PreparedPortfolioData,
    ) -> ExecutionOutcome: ...


class ValuationAdapter(Protocol):
    def value(
        self,
        request: PortfolioRequest,
        ledger: PortfolioLedger,
        execution: ExecutionOutcome,
        prepared: PreparedPortfolioData,
    ) -> ValuationStageResult: ...


@dataclass(frozen=True, slots=True)
class OrchestrationAdapters:
    """The six narrow seams task 12/13 compose without touching stage order."""

    opening_ledger: OpeningLedgerAdapter
    conversions: ConversionAdapter
    plan: PlanAdapter
    preflight: PreflightAdapter
    execution: MatchAdapter
    valuation: ValuationAdapter


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """One complete in-memory document produced only after every stage passes."""

    request: PortfolioRequest
    opening_ledger: PortfolioLedger
    conversion_replay: ConversionReplay
    plan: OrderPlan
    prepared_data: PreparedPortfolioData
    execution: ExecutionOutcome
    end_ledger: PortfolioLedger
    valuation: ValuationStageResult
    stage_trace: tuple[StageName, ...]

    @property
    def complete(self) -> bool:
        return self.execution.complete


@dataclass(frozen=True, slots=True)
class OpeningLedgerValidation:
    """Default opening validation against the parsed request ledger."""

    def validate(self, request: PortfolioRequest) -> PortfolioLedger:
        return PortfolioLedger.from_request(request)


@dataclass(frozen=True, slots=True)
class CallerDeclaredConversions:
    """Default pre-fill conversion replay; post-fill staging is impossible."""

    def apply(
        self,
        request: PortfolioRequest,
        opening: PortfolioLedger,
    ) -> ConversionReplay:
        plan = plan_conversions(request, stage="pre_fill")
        return apply_conversions(opening, plan, stage="pre_fill")


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
