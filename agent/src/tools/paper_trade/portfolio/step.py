"""Internal single-day pt-v2.0 portfolio step and atomic result envelope.

:func:`run_portfolio_step` is intentionally the only composition seam for the
internal portfolio path. It parses one caller-shaped payload, resolves the
caller-declared sessions, loads each bucket's raw lookback/target bars through
the injected preflight loaders, derives prior planning marks from that data,
and runs the fixed task-11 orchestration over the pure planner, caller
conversions, all-bucket preflight journal, the Decimal execution adapter and
Decimal valuation.

The returned :class:`PortfolioStepResult` keeps the exact Decimal ledgers and
the full :class:`~.order_plan.OrderPlan` next to the atomic
:class:`~.models.PortfolioResult` envelope. Every planned order receives exactly
one terminal fill/reject/cancel row tied to its ``bucket_id`` and
``plan_order_id``; rejects/cancels are valid rows with ``complete=False``. Any
validation, data, execution-adapter or internal mismatch raises before a
document exists, so no caller can observe an end ledger or fill list from a
failed step.

Nothing here registers an Agent/MCP/REST surface, resolves a loader on its own,
reads a wall clock or imports broker/live code. A caller must inject a loader
for every canonical market, which also prevents the legacy auto-fallback from
reaching a network provider.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, NoReturn

from ..rules import RULES_VERSION
from .data import (
    PreparedPortfolioData,
    PriorMarkValuation,
    TargetBarValuation,
    preflight_portfolio_data,
)
from .execution import DecimalExecutionAdapter
from .fx import plan_conversions
from .hash import PortfolioHashInput, compute_portfolio_hashes
from .ledger import PortfolioLedger
from .models import (
    BucketResult,
    JsonObject,
    JsonValue,
    Market,
    PortfolioBucket,
    PortfolioFill,
    PortfolioHashes,
    PortfolioIssue,
    PortfolioPosition,
    PortfolioRequest,
    PortfolioResult,
    PortfolioState,
)
from .numeric import (
    MONEY_SPEC,
    PRICE_SPEC,
    EffectiveFeeModel,
    canonical_decimal,
    parse_effective_fee_model,
)
from .orchestrator import (
    CallerDeclaredConversions,
    ExecutionCancellation,
    ExecutionFill,
    ExecutionRejection,
    MarksValuation,
    OpeningLedgerValidation,
    OrchestrationAdapters,
    OrchestrationError,
    OrchestrationResult,
    PurePlanBuilder,
    StageName,
    StageObserver,
    ValuationStageResult,
    run_portfolio_orchestration,
)
from .order_plan import OrderPlan
from .planner import PLANNER_VERSION, PlanningMark
from .schema import PortfolioRequestError, parse_portfolio_request
from .sessions import PortfolioSessions, resolve_portfolio_sessions

__all__ = ["PortfolioStepResult", "run_portfolio_step"]


@dataclass(frozen=True, slots=True)
class PortfolioStepResult:
    """The atomic document plus the exact artifacts that produced it."""

    document: PortfolioResult
    order_plan: OrderPlan
    prepared_data: PreparedPortfolioData
    opening_ledger: PortfolioLedger
    post_conversion_ledger: PortfolioLedger
    end_ledger: PortfolioLedger
    valuation: ValuationStageResult
    stage_trace: tuple[StageName, ...]

    @property
    def complete(self) -> bool:
        """Return the document's order-completeness verdict."""
        return self.document.complete

    def model_dump(self, *args: Any, **kwargs: Any) -> JsonObject:
        """Serialize the atomic result envelope exactly like the typed model."""
        return self.document.model_dump(*args, **kwargs)


@dataclass(frozen=True, slots=True)
class _PreparedPreflight:
    """Serve the already-loaded preflight bundle inside the fixed stage order."""

    prepared: PreparedPortfolioData

    def preflight(
        self,
        request: PortfolioRequest,
        ledger: PortfolioLedger,
        plan: OrderPlan,
    ) -> PreparedPortfolioData:
        return self.prepared


def _reject(reason: str, path: str, bucket_id: str | None = None) -> NoReturn:
    raise PortfolioRequestError(reason=reason, path=path, bucket_id=bucket_id)


def _require_loaders(
    request: PortfolioRequest,
    loaders: Mapping[Market, Any],
) -> None:
    """Require an injected offline loader for every canonical market."""
    if not isinstance(loaders, Mapping):
        _reject("invalid_loaders", "loaders")
    for bucket in request.portfolio_state.buckets:
        if bucket.market not in loaders:
            _reject("missing_loader", f"loaders.{bucket.market}", bucket.bucket_id)


def _symbols_by_bucket(request: PortfolioRequest) -> dict[str, tuple[str, ...]]:
    symbols: dict[str, set[str]] = {}
    if request.orders is not None:
        for order in request.orders:
            symbols.setdefault(order.bucket_id, set()).add(order.symbol)
    else:
        for target in request.target_weights or ():
            symbols.setdefault(target.bucket_id, set()).add(target.symbol)
    return {bucket_id: tuple(sorted(values)) for bucket_id, values in symbols.items()}


def _planning_marks(prepared: PreparedPortfolioData) -> tuple[PlanningMark, ...]:
    """Derive strictly-prior planning marks from each bucket's raw snapshot."""
    marks = [
        PlanningMark(
            symbol=bar.symbol,
            price_date=bucket.planning.price_date,
            close=Decimal(bar.close),
            source=bucket.planning.source,
            as_of=bucket.planning.as_of,
        )
        for bucket in prepared.buckets
        for bar in bucket.planning.bars
    ]
    return tuple(sorted(marks, key=lambda mark: mark.symbol))


def _valuation_marks(prepared: PreparedPortfolioData) -> dict[str, Decimal]:
    """Choose target closes for open buckets and dated prior marks for closed ones."""
    marks: dict[str, Decimal] = {}
    for bucket in prepared.buckets:
        if isinstance(bucket.valuation, TargetBarValuation):
            for bar in bucket.valuation.snapshot.bars:
                marks[bar.symbol] = Decimal(bar.close)
        else:
            assert isinstance(bucket.valuation, PriorMarkValuation)
            for mark in bucket.valuation.marks:
                marks[mark.symbol] = Decimal(mark.close)
    return marks


def _portfolio_state(
    ledger: PortfolioLedger,
    request: PortfolioRequest,
) -> PortfolioState:
    """Render one Decimal ledger as the wire-shaped immutable portfolio state."""
    fee_models = {
        bucket.bucket_id: bucket.fee_model for bucket in request.portfolio_state.buckets
    }
    return PortfolioState(
        buckets=tuple(
            PortfolioBucket(
                bucket_id=bucket.bucket_id,
                market=bucket.market,
                currency=bucket.currency,
                cash=canonical_decimal(bucket.cash, MONEY_SPEC, f"ledger.{bucket.bucket_id}.cash"),
                positions=tuple(
                    PortfolioPosition(
                        symbol=position.symbol,
                        qty=position.qty,
                        avg_cost=canonical_decimal(
                            position.avg_cost,
                            MONEY_SPEC,
                            f"ledger.{bucket.bucket_id}.{position.symbol}.avg_cost",
                        ),
                        currency=position.currency,
                    )
                    for position in bucket.positions
                ),
                fee_model=fee_models.get(bucket.bucket_id),
            )
            for bucket in ledger.buckets
        )
    )


def _bucket_results(
    orchestration: OrchestrationResult,
) -> tuple[BucketResult, ...]:
    by_id = {bucket.bucket_id: bucket for bucket in orchestration.prepared_data.buckets}
    return tuple(
        BucketResult(
            bucket_id=row.bucket_id,
            market=row.market,
            currency=row.currency,
            session=by_id[row.bucket_id].session.session,
            cash=canonical_decimal(row.cash, MONEY_SPEC, f"valuation.{row.bucket_id}.cash"),
            position_value=canonical_decimal(
                row.position_value,
                MONEY_SPEC,
                f"valuation.{row.bucket_id}.position_value",
            ),
            nav_base=canonical_decimal(
                row.reported_base,
                MONEY_SPEC,
                f"valuation.{row.bucket_id}.nav_base",
            ),
            fx_rate_id=row.rate_id,
        )
        for row in orchestration.valuation.nav_bridge.rows
    )


def _fills(fills: tuple[ExecutionFill, ...]) -> tuple[PortfolioFill, ...]:
    return tuple(
        PortfolioFill(
            plan_order_id=fill.plan_order_id,
            bucket_id=fill.bucket_id,
            symbol=fill.symbol,
            currency=fill.currency,
            side=fill.side,
            qty=fill.qty,
            trade_date=fill.trade_date,
            price=canonical_decimal(
                fill.price,
                PRICE_SPEC,
                f"fills.{fill.plan_order_id}.price",
            ),
            fee=canonical_decimal(
                fill.fee,
                MONEY_SPEC,
                f"fills.{fill.plan_order_id}.fee",
            ),
        )
        for fill in fills
    )


def _outcome_issue(
    kind: str,
    row: ExecutionRejection | ExecutionCancellation,
) -> PortfolioIssue:
    return PortfolioIssue(
        reason=row.reason_code,
        path=f"execution.{kind}.{row.bucket_id}.{row.plan_order_id}",
        detail=row.detail,
        bucket_id=row.bucket_id,
    )


def _warnings(
    orchestration: OrchestrationResult,
) -> tuple[str, ...]:
    messages: list[str] = list(orchestration.plan.warnings)
    for bucket in orchestration.prepared_data.buckets:
        if not bucket.session.matchable:
            messages.append(
                f"{bucket.bucket_id}: market closed; valued at prior marks (no matcher run)"
            )
    messages.extend(orchestration.valuation.warnings)
    seen: set[str] = set()
    unique: list[str] = []
    for message in messages:
        if message not in seen:
            seen.add(message)
            unique.append(message)
    return tuple(unique)


def _hash_material(
    request: PortfolioRequest,
    sessions: PortfolioSessions,
    prepared: PreparedPortfolioData,
    fee_models: tuple[EffectiveFeeModel, ...],
) -> PortfolioHashInput:
    return PortfolioHashInput(
        request=request,
        effective_fee_models=fee_models,
        sessions=sessions,
        data=prepared,
        planner_version=PLANNER_VERSION,
        rules_versions={
            bucket.bucket_id: RULES_VERSION
            for bucket in request.portfolio_state.buckets
        },
    )


def _document_body(
    request: PortfolioRequest,
    orchestration: OrchestrationResult,
) -> JsonObject:
    execution = orchestration.execution
    return {
        "status": "success",
        "tool": "paper_trade_step",
        "schema_version": "pt-v2.0",
        "mode": "portfolio",
        "account_id": request.account_id,
        "base_currency": request.base_currency,
        "trade_date": request.trade_date,
        "planning_at": request.planning_at,
        "valuation_at": request.valuation_at,
        "opening_portfolio": _portfolio_state(orchestration.opening_ledger, request),
        "post_conversion_portfolio": _portfolio_state(
            orchestration.conversion_replay.post_conversion,
            request,
        ),
        "end_portfolio": _portfolio_state(orchestration.end_ledger, request),
        "sessions": request.sessions,
        "conversions": request.fx_conversions,
        "plan": request.plan,
        "bucket_results": _bucket_results(orchestration),
        "fills": _fills(execution.fills),
        "rejected_orders": tuple(
            {
                "plan_order_id": row.plan_order_id,
                "bucket_id": row.bucket_id,
                "symbol": row.symbol,
                "currency": row.currency,
                "side": row.side,
                "qty": row.qty,
                "trade_date": row.trade_date,
                "reason_code": row.reason_code,
                "detail": row.detail,
            }
            for row in execution.rejected_orders
        ),
        "canceled_orders": tuple(
            {
                "plan_order_id": row.plan_order_id,
                "bucket_id": row.bucket_id,
                "symbol": row.symbol,
                "currency": row.currency,
                "side": row.side,
                "qty": row.qty,
                "trade_date": row.trade_date,
                "reason_code": row.reason_code,
                "detail": row.detail,
            }
            for row in execution.canceled_orders
        ),
        "warnings": _warnings(orchestration),
        "errors": tuple(
            _outcome_issue("rejected_orders", row)
            for row in execution.rejected_orders
        )
        + tuple(
            _outcome_issue("canceled_orders", row)
            for row in execution.canceled_orders
        ),
        "complete": orchestration.complete,
    }


def _document(
    request: PortfolioRequest,
    orchestration: OrchestrationResult,
    material: PortfolioHashInput,
) -> PortfolioResult:
    body = _document_body(request, orchestration)
    placeholder = PortfolioHashes(
        plan_hash="0" * 64,
        planning_data_hash="0" * 64,
        execution_data_fingerprint="0" * 64,
        document_hash="0" * 64,
    )
    # Hash the validated model body so pydantic's canonical timestamp rendering
    # (for example UTC as ``Z``) is identical in the body and final document.
    provisional = PortfolioResult(**body, hashes=placeholder)
    hashes = compute_portfolio_hashes(material, provisional)
    document = PortfolioResult(**body, hashes=hashes)
    if compute_portfolio_hashes(material, document) != hashes:
        raise OrchestrationError(
            stage="valuate_reconcile",
            reason="internal_document_hash_mismatch",
            code="INTERNAL",
            path="hashes",
            detail="the final document body changed after model validation",
        )
    return document


def run_portfolio_step(
    payload: JsonValue | PortfolioRequest,
    *,
    loaders: Mapping[Market, Any],
    calendar_client: Any = None,
    ch_clients: Mapping[Market, Any] | None = None,
    hk_lot_sizes: Mapping[str, int] | None = None,
    observer: StageObserver | None = None,
) -> PortfolioStepResult:
    """Run one internal single-day pt-v2.0 portfolio step.

    The caller injects one offline loader per canonical market. All bucket data
    (planning lookback, target-day execution bars, closed prior marks) is
    loaded and preflighted before the fixed orchestration starts; the
    orchestrator's own preflight stage then asserts that same prepared bundle,
    so no bucket can fetch or match ahead of an earlier validation failure.

    Per-order rejects/cancels are ordinary rows with ``complete=False``.
    Validation, data, execution-adapter or internal identity faults raise and
    produce no document, fills or end ledger.
    """
    request = (
        payload
        if isinstance(payload, PortfolioRequest)
        else parse_portfolio_request(payload)
    )
    _require_loaders(request, loaders)

    # Fail fast before any provider call: opening ledger, fee models, conversions.
    PortfolioLedger.from_request(request)
    fee_models: tuple[EffectiveFeeModel, ...] = tuple(
        parse_effective_fee_model(bucket)
        for bucket in request.portfolio_state.buckets
    )
    plan_conversions(request, stage="pre_fill")

    sessions = resolve_portfolio_sessions(
        request,
        price_dates={
            bucket.market: request.trade_date
            for bucket in request.portfolio_state.buckets
        },
    )
    prepared = preflight_portfolio_data(
        sessions,
        symbols_by_bucket=_symbols_by_bucket(request),
        loaders=loaders,
        ch_clients=ch_clients
        if ch_clients is not None
        else {bucket.market: None for bucket in request.portfolio_state.buckets},
        calendar_client=calendar_client,
    )
    planning_marks = _planning_marks(prepared)

    orchestration = run_portfolio_orchestration(
        request,
        adapters=OrchestrationAdapters(
            opening_ledger=OpeningLedgerValidation(),
            conversions=CallerDeclaredConversions(),
            plan=PurePlanBuilder(
                planning_marks=planning_marks,
                fee_models=fee_models,
                hk_lot_sizes=hk_lot_sizes,
            ),
            preflight=_PreparedPreflight(prepared),
            execution=DecimalExecutionAdapter(
                fee_models=fee_models,
                hk_lot_sizes=hk_lot_sizes,
            ),
            valuation=MarksValuation(marks=_valuation_marks(prepared)),
        ),
        observer=observer,
    )
    material = _hash_material(request, sessions, prepared, fee_models)
    document = _document(request, orchestration, material)
    return PortfolioStepResult(
        document=document,
        order_plan=orchestration.plan,
        prepared_data=orchestration.prepared_data,
        opening_ledger=orchestration.opening_ledger,
        post_conversion_ledger=orchestration.conversion_replay.post_conversion,
        end_ledger=orchestration.end_ledger,
        valuation=orchestration.valuation,
        stage_trace=orchestration.stage_trace,
    )
