"""Shared request builders and Spy adapter doubles for the pt-v2.0 orchestrator tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from src.tools.paper_trade.portfolio.data import (
    DataSnapshot,
    PreparedBucketData,
    PreparedPortfolioData,
    TargetBarValuation,
)
from src.tools.paper_trade.portfolio.fx import FxConversionEvent, FxRateBook
from src.tools.paper_trade.portfolio.ledger import (
    CashMovement,
    PortfolioLedger,
    PositionMovement,
    value_ledger,
)
from src.tools.paper_trade.portfolio.models import PortfolioRequest
from src.tools.paper_trade.portfolio.orchestrator import (
    STAGE_SEQUENCE,
    CallerDeclaredConversions,
    ExecutionCancellation,
    ExecutionFill,
    ExecutionOutcome,
    ExecutionRejection,
    OrchestrationAdapters,
    OrchestrationError,
    PlanStageResult,
    PurePlanBuilder,
    ValuationStageResult,
    run_portfolio_orchestration,
)
from src.tools.paper_trade.portfolio.planner import PlanningMark
from src.tools.paper_trade.portfolio.schema import parse_portfolio_request
from src.tools.paper_trade.portfolio.sessions import BucketSession
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload

AS_OF = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
PLANNING_AT = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
VALUATION_AT = datetime(2026, 11, 13, 21, tzinfo=timezone.utc)
TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)

MARKS = (
    PlanningMark(
        symbol="600519.SH",
        price_date=PRIOR_DATE,
        close=Decimal("1400.00"),
        source="test:cn",
        as_of=AS_OF,
    ),
    PlanningMark(
        symbol="00700.HK",
        price_date=PRIOR_DATE,
        close=Decimal("300.00"),
        source="test:hk",
        as_of=AS_OF,
    ),
    PlanningMark(
        symbol="AAPL.US",
        price_date=PRIOR_DATE,
        close=Decimal("200.00"),
        source="test:us",
        as_of=AS_OF,
    ),
)
EXECUTION_PRICES = {
    "600519.SH": Decimal("1400.00"),
    "00700.HK": Decimal("300.00"),
    "AAPL.US": Decimal("200.00"),
}
EXECUTION_FEES = {
    "600519.SH": Decimal("42.00"),
    "00700.HK": Decimal("9.00"),
    "AAPL.US": Decimal("27.40"),
}
VALUATION_MARKS = {
    "600519.SH": Decimal("1400.00"),
    "00700.HK": Decimal("300.00"),
    "AAPL.US": Decimal("200.00"),
}


def _payload() -> dict[str, Any]:
    return json.loads(json.dumps(valid_portfolio_payload()))


def _explicit_request() -> PortfolioRequest:
    payload = _payload()
    payload["fx_conversions"] = [
        {
            "rate_id": "cny-usd-fix",
            "from_bucket_id": "cn",
            "to_bucket_id": "us",
            "amount": "1000.00",
        }
    ]
    payload["orders"] = [
        {
            "order_id": "cn-sell-1",
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "side": "sell",
            "qty": 100,
        },
        {
            "order_id": "us-buy-1",
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "side": "buy",
            "qty": 2,
        },
    ]
    return parse_portfolio_request(payload)


def _target_request() -> PortfolioRequest:
    payload = _payload()
    payload["fx_conversions"] = [
        {
            "rate_id": "cny-usd-fix",
            "from_bucket_id": "cn",
            "to_bucket_id": "us",
            "amount": "50000.00",
        }
    ]
    payload.pop("orders")
    payload["target_weights"] = [
        {
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "weight": "0.00",
        },
        {
            "bucket_id": "hk",
            "symbol": "00700.HK",
            "currency": "HKD",
            "weight": "0.00",
        },
        {
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "weight": "0.40",
        },
    ]
    payload["rebalance_band"] = "0"
    return parse_portfolio_request(payload)


def _same_day_proceeds_request() -> PortfolioRequest:
    payload = _payload()
    payload["portfolio_state"]["buckets"][2]["cash"] = "0.00"
    payload["fx_snapshots"].append(
        {
            "rate_id": "usd-hkd-fix",
            "from": "USD",
            "to": "HKD",
            "rate": "7.80",
            "as_of": "2026-11-13T11:00:00+00:00",
            "source": "caller-fix",
        }
    )
    payload["fx_conversions"] = [
        {
            "rate_id": "cny-usd-fix",
            "from_bucket_id": "cn",
            "to_bucket_id": "us",
            "amount": "1000.00",
        },
        {
            "rate_id": "usd-hkd-fix",
            "from_bucket_id": "us",
            "to_bucket_id": "hk",
            "amount": "140.00",
        },
    ]
    payload["orders"] = []
    return parse_portfolio_request(payload)


def _conversion_event() -> FxConversionEvent:
    return FxConversionEvent(
        rate_id="cny-usd-fix",
        from_bucket_id="cn",
        to_bucket_id="us",
        from_currency="CNY",
        to_currency="USD",
        source_amount=Decimal("1.00"),
        rate=Decimal("0.14"),
        exact_converted=Decimal("0.14"),
        converted_amount=Decimal("0.14"),
        residual=Decimal("0.00"),
    )


def _prepared(request: PortfolioRequest) -> PreparedPortfolioData:
    sessions = {session.market: session for session in request.sessions}
    buckets: list[PreparedBucketData] = []
    for bucket in request.portfolio_state.buckets:
        session = BucketSession(
            bucket_id=bucket.bucket_id,
            market=bucket.market,
            price_date=request.trade_date,
            required=True,
            position_symbols=tuple(position.symbol for position in bucket.positions),
            session=sessions[bucket.market],
        )
        planning = DataSnapshot(
            price_date=PRIOR_DATE,
            source="test:planning",
            as_of=PLANNING_AT,
        )
        execution = DataSnapshot(
            price_date=request.trade_date,
            source="test:execution",
            as_of=PLANNING_AT,
        )
        valuation = DataSnapshot(
            price_date=request.trade_date,
            source="test:valuation",
            as_of=VALUATION_AT,
        )
        buckets.append(
            PreparedBucketData(
                session=session,
                planning=planning,
                execution=execution,
                valuation=TargetBarValuation(snapshot=valuation),
            )
        )
    return PreparedPortfolioData(buckets=tuple(buckets))
class SpyLedger:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def validate(self, request: PortfolioRequest) -> PortfolioLedger:
        self.log.append("validate_opening_ledger")
        return PortfolioLedger.from_request(request)


class StaleLedger:
    def __init__(self, log: list[str], ledger: PortfolioLedger) -> None:
        self.log = log
        self.ledger = ledger

    def validate(self, request: PortfolioRequest) -> PortfolioLedger:
        self.log.append("validate_opening_ledger")
        return self.ledger


class SpyConversions:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def apply(self, request: PortfolioRequest, opening: PortfolioLedger):
        self.log.append("apply_caller_conversions")
        return CallerDeclaredConversions().apply(request, opening)


class SpyPlan:
    def __init__(self, log: list[str], delegate: PurePlanBuilder) -> None:
        self.log = log
        self.delegate = delegate
        self.ledger_cash: dict[str, Decimal] = {}

    def build(self, request: PortfolioRequest, ledger: PortfolioLedger) -> PlanStageResult:
        self.log.append("build_plan")
        self.ledger_cash = dict(ledger.cash_map())
        return self.delegate.build(request, ledger)


class PlannerConversionPlan(SpyPlan):
    def build(self, request: PortfolioRequest, ledger: PortfolioLedger) -> PlanStageResult:
        built = super().build(request, ledger)
        return PlanStageResult(
            plan=built.plan,
            conversion_requests=(_conversion_event(),),
        )


class SpyPreflight:
    def __init__(self, log: list[str], prepared: PreparedPortfolioData) -> None:
        self.log = log
        self.prepared = prepared
        self.bucket_ids: tuple[str, ...] = ()

    def preflight(self, request, ledger, plan) -> PreparedPortfolioData:
        self.log.append("preflight_execution_inputs")
        self.bucket_ids = tuple(bucket.bucket_id for bucket in self.prepared.buckets)
        return self.prepared


class FailingPreflight:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def preflight(self, request, ledger, plan):
        self.log.append("preflight_execution_inputs")
        raise RuntimeError("later bucket preflight failed")


class AutoFillMatch:
    def __init__(
        self,
        log: list[str],
        *,
        prices: dict[str, Decimal],
        fees: dict[str, Decimal],
        reject: tuple[str, ...] = (),
        cancel: tuple[str, ...] = (),
    ) -> None:
        self.log = log
        self.prices = prices
        self.fees = fees
        self.reject = frozenset(reject)
        self.cancel = frozenset(cancel)
        self.ledger_cash: dict[str, Decimal] = {}

    def match(self, request, ledger, plan, prepared) -> ExecutionOutcome:
        self.log.append("match_orders")
        self.ledger_cash = dict(ledger.cash_map())
        fills: list[ExecutionFill] = []
        rejected: list[ExecutionRejection] = []
        canceled: list[ExecutionCancellation] = []
        events: list[CashMovement | PositionMovement] = []
        for order in plan.orders:
            if order.plan_order_id in self.reject:
                rejected.append(
                    ExecutionRejection(
                        plan_order_id=order.plan_order_id,
                        bucket_id=order.bucket_id,
                        symbol=order.symbol,
                        currency=order.currency,
                        side=order.side,
                        qty=order.qty,
                        trade_date=request.trade_date,
                        reason_code="test_reject",
                        detail="caller order rejected by the execution stage",
                    )
                )
                continue
            if order.plan_order_id in self.cancel:
                canceled.append(
                    ExecutionCancellation(
                        plan_order_id=order.plan_order_id,
                        bucket_id=order.bucket_id,
                        symbol=order.symbol,
                        currency=order.currency,
                        side=order.side,
                        qty=order.qty,
                        trade_date=request.trade_date,
                        reason_code="test_cancel",
                        detail="caller order canceled by the execution stage",
                    )
                )
                continue
            price = self.prices.get(order.symbol, order.price)
            fee = self.fees.get(order.symbol, Decimal("0.00"))
            fills.append(
                ExecutionFill(
                    plan_order_id=order.plan_order_id,
                    bucket_id=order.bucket_id,
                    symbol=order.symbol,
                    currency=order.currency,
                    side=order.side,
                    qty=order.qty,
                    price=price,
                    fee=fee,
                    trade_date=request.trade_date,
                )
            )
            notional = Decimal(order.qty) * price
            if order.side == "buy":
                events.append(
                    CashMovement(bucket_id=order.bucket_id, amount=-(notional + fee))
                )
                events.append(
                    PositionMovement(
                        bucket_id=order.bucket_id,
                        symbol=order.symbol,
                        qty_delta=order.qty,
                        avg_cost=price,
                    )
                )
            else:
                events.append(
                    CashMovement(bucket_id=order.bucket_id, amount=notional - fee)
                )
                events.append(
                    PositionMovement(
                        bucket_id=order.bucket_id,
                        symbol=order.symbol,
                        qty_delta=-order.qty,
                    )
                )
        return ExecutionOutcome(
            fills=tuple(fills),
            rejected_orders=tuple(rejected),
            canceled_orders=tuple(canceled),
            ledger_events=tuple(events),
        )


class PostFillConversionMatch(AutoFillMatch):
    def __init__(
        self,
        log: list[str],
        *,
        prices: dict[str, Decimal],
        fees: dict[str, Decimal],
        conversion: FxConversionEvent,
    ) -> None:
        super().__init__(log, prices=prices, fees=fees)
        self.conversion = conversion

    def match(self, request, ledger, plan, prepared) -> ExecutionOutcome:
        outcome = super().match(request, ledger, plan, prepared)
        return replace(
            outcome,
            ledger_events=outcome.ledger_events + (self.conversion,),
        )


class BridgeValuation:
    def __init__(self, log: list[str], marks: dict[str, Decimal]) -> None:
        self.log = log
        self.marks = marks

    def value(self, request, ledger, execution, prepared) -> ValuationStageResult:
        self.log.append("valuate_reconcile")
        book = FxRateBook.from_snapshots(request.fx_snapshots, at=request.valuation_at)
        bridge = value_ledger(
            ledger,
            self.marks,
            book,
            base_currency=request.base_currency,
        )
        return ValuationStageResult(nav_bridge=bridge)


class ExplodingValuation:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def value(self, request, ledger, execution, prepared) -> ValuationStageResult:
        self.log.append("valuate_reconcile")
        raise RuntimeError("valuation exploded after the ledger replay")


def _adapters(
    request: PortfolioRequest,
    log: list[str],
    *,
    plan: Any = None,
    preflight: Any = None,
    match: Any = None,
    valuation: Any = None,
) -> OrchestrationAdapters:
    return OrchestrationAdapters(
        opening_ledger=SpyLedger(log),
        conversions=SpyConversions(log),
        plan=plan or SpyPlan(log, PurePlanBuilder(planning_marks=MARKS)),
        preflight=preflight or SpyPreflight(log, _prepared(request)),
        execution=match
        or AutoFillMatch(log, prices=EXECUTION_PRICES, fees=EXECUTION_FEES),
        valuation=valuation or BridgeValuation(log, VALUATION_MARKS),
    )


def _assert_no_partial_document(exc: OrchestrationError) -> None:
    assert not hasattr(exc, "end_ledger")
    assert not hasattr(exc, "fills")
    assert not hasattr(exc, "result")


class MutatingMatch:
    """Delegate to a match adapter, then mutate the returned outcome."""

    def __init__(self, delegate: Any, mutate: Any) -> None:
        self.delegate = delegate
        self.mutate = mutate

    def match(self, request, ledger, plan, prepared) -> ExecutionOutcome:
        return self.mutate(self.delegate.match(request, ledger, plan, prepared))


def _assert_outcome_abort(
    request: PortfolioRequest,
    log: list[str],
    stages: list[str],
    execution: Any,
    *,
    reason: str,
) -> OrchestrationError:
    with pytest.raises(OrchestrationError) as caught:
        run_portfolio_orchestration(
            request,
            adapters=_adapters(request, log, match=execution),
            observer=stages.append,
        )
    error = caught.value
    assert error.stage == "match_orders"
    assert error.reason == reason
    assert error.completed_stages == STAGE_SEQUENCE[:4]
    assert tuple(stages) == STAGE_SEQUENCE[:5]
    assert "replay_ledger" not in log
    assert "valuate_reconcile" not in log
    _assert_no_partial_document(error)
    return error
