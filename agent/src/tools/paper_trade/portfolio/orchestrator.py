"""Fixed pt-v2.0 portfolio step ordering over narrow typed stage adapters.

The orchestrator is the only place that decides what runs next. It validates
the opening ledger, settles caller-declared conversions against opening cash,
builds a pure plan from the post-conversion ledger, preflights every execution
bucket, matches, replays Decimal ledger events, then values and reconciles.
Any stage fault raises :class:`OrchestrationError` and discards the whole
in-memory document, so no caller can observe a partial end ledger or fill list.
Per-order reject/cancel rows are data, not faults, and force ``complete=False``.

The implementation lives in focused sibling modules (``orchestrator_types``,
``orchestrator_adapters``, ``orchestrator_plan_validation``,
``orchestrator_outcome_validation``, ``orchestrator_preflight_validation``,
``orchestrator_run``); this facade keeps every historic
``orchestrator.<symbol>`` binding path importable and patchable unchanged.
"""

from __future__ import annotations

from .orchestrator_adapters import MarksValuation, PurePlanBuilder
from .orchestrator_outcome_validation import _validate_outcome as _validate_outcome
from .orchestrator_plan_validation import (
    _abort as _abort,
    _reject_planner_conversions as _reject_planner_conversions,
    _required_bucket_ids as _required_bucket_ids,
    _require_nonnegative as _require_nonnegative,
    _require_positive as _require_positive,
    _run_stage as _run_stage,
    _validate_plan_cash as _validate_plan_cash,
)
from .orchestrator_preflight_validation import (
    _validate_preflight as _validate_preflight,
)
from .orchestrator_run import run_portfolio_orchestration
from .orchestrator_types import (
    STAGE_SEQUENCE,
    AnalyticsRow,
    CallerDeclaredConversions,
    ConversionAdapter,
    ExecutionCancellation,
    ExecutionFill,
    ExecutionOutcome,
    ExecutionRejection,
    MatchAdapter,
    OpeningLedgerAdapter,
    OpeningLedgerValidation,
    OrchestrationAdapters,
    OrchestrationCode as OrchestrationCode,
    OrchestrationError,
    OrchestrationResult,
    PlanAdapter,
    PlanStageResult,
    PreflightAdapter,
    ReconciliationCheck,
    Side as Side,
    StageName,
    StageObserver,
    StageValue as StageValue,
    ValuationAdapter,
    ValuationStageResult,
)

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
