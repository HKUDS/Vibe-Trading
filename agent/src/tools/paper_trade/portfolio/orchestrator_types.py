"""Typed stage vocabulary, errors, outcomes and adapter seams for pt-v2.0 orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final, Literal, Protocol, TypeAlias, TypeVar

from .data import PreparedPortfolioData
from .fx import FxConversionEvent, plan_conversions
from .ledger import (
    ConversionReplay,
    LedgerEvent,
    LedgerNavBridge,
    PortfolioLedger,
    apply_conversions,
)
from .models import Currency, PortfolioRequest
from .order_plan import OrderPlan

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
    """The six narrow seams the orchestration composes without touching stage order."""

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
