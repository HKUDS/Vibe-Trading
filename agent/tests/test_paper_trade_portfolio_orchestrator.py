"""Fixed pt-v2.0 stage ordering and atomic-document orchestrator tests."""

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
def test_explicit_orders_follow_the_fixed_stage_sequence() -> None:
    request = _explicit_request()
    stages: list[str] = []
    log: list[str] = []
    plan_adapter = SpyPlan(log, PurePlanBuilder(planning_marks=MARKS))
    preflight_adapter = SpyPreflight(log, _prepared(request))
    match_adapter = AutoFillMatch(
        log, prices=EXECUTION_PRICES, fees=EXECUTION_FEES
    )
    adapters = _adapters(
        request,
        log,
        plan=plan_adapter,
        preflight=preflight_adapter,
        match=match_adapter,
    )

    result = run_portfolio_orchestration(
        request,
        adapters=adapters,
        observer=stages.append,
    )

    assert tuple(stages) == STAGE_SEQUENCE
    assert result.stage_trace == STAGE_SEQUENCE
    assert log == [
        "validate_opening_ledger",
        "apply_caller_conversions",
        "build_plan",
        "preflight_execution_inputs",
        "match_orders",
        "valuate_reconcile",
    ]
    assert plan_adapter.ledger_cash["cn"] == Decimal("99000.00")
    assert plan_adapter.ledger_cash["us"] == Decimal("25140.00")
    assert match_adapter.ledger_cash["cn"] == Decimal("99000.00")
    assert match_adapter.ledger_cash["us"] == Decimal("25140.00")
    assert preflight_adapter.bucket_ids == ("cn", "hk", "us")
    assert result.conversion_replay.events[0].converted_amount == Decimal("140.00")
    assert [
        (order.plan_order_id, order.bucket_id, order.side, order.qty)
        for order in result.plan.orders
    ] == [
        ("cn-sell-1", "cn", "sell", 100),
        ("us-buy-1", "us", "buy", 2),
    ]
    assert {
        bucket.bucket_id: bucket.opening_cash for bucket in result.plan.buckets
    } == {
        "cn": Decimal("99000.00"),
        "hk": Decimal("50000.00"),
        "us": Decimal("25140.00"),
    }
    assert result.complete is True
    assert result.execution.rejected_orders == ()
    assert result.execution.canceled_orders == ()
    assert len(result.execution.fills) == 2
    assert result.end_ledger.cash_map()["cn"] == Decimal("238958.00")
    assert result.end_ledger.cash_map()["us"] == Decimal("24712.60")
    assert result.end_ledger.bucket("cn").positions == ()
    assert result.end_ledger.bucket("us").positions[0].qty == 2
    assert result.valuation.nav_bridge.balanced is True
    assert len(result.valuation.nav_bridge.rows) == 3


def test_target_weights_follow_the_fixed_stage_sequence() -> None:
    request = _target_request()
    stages: list[str] = []
    log: list[str] = []
    plan_adapter = SpyPlan(log, PurePlanBuilder(planning_marks=MARKS))
    preflight_adapter = SpyPreflight(log, _prepared(request))
    match_adapter = AutoFillMatch(
        log, prices=EXECUTION_PRICES, fees=EXECUTION_FEES
    )
    adapters = _adapters(
        request,
        log,
        plan=plan_adapter,
        preflight=preflight_adapter,
        match=match_adapter,
    )

    result = run_portfolio_orchestration(
        request,
        adapters=adapters,
        observer=stages.append,
    )

    assert tuple(stages) == STAGE_SEQUENCE
    assert result.stage_trace == STAGE_SEQUENCE
    assert result.plan.mode == "target_weights"
    assert plan_adapter.ledger_cash["cn"] == Decimal("50000.00")
    assert plan_adapter.ledger_cash["us"] == Decimal("32000.00")
    assert match_adapter.ledger_cash["cn"] == Decimal("50000.00")
    assert match_adapter.ledger_cash["us"] == Decimal("32000.00")
    assert preflight_adapter.bucket_ids == ("cn", "hk", "us")
    assert result.conversion_replay.events[0].converted_amount == Decimal("7000.00")
    assert [
        (order.bucket_id, order.side, order.qty) for order in result.plan.orders
    ] == [
        ("cn", "sell", 100),
        ("hk", "sell", 100),
        ("us", "buy", 137),
    ]
    assert result.complete is True
    assert len(result.execution.fills) == 3
    assert result.end_ledger.bucket("cn").positions == ()
    assert result.end_ledger.bucket("hk").positions == ()
    assert result.end_ledger.bucket("us").positions[0].qty == 137
    assert result.end_ledger.cash_map()["cn"] == Decimal("189958.00")
    assert result.end_ledger.cash_map()["hk"] == Decimal("79991.00")
    assert result.end_ledger.cash_map()["us"] == Decimal("4572.60")
    assert result.valuation.nav_bridge.balanced is True


def test_per_order_reject_is_explicit_data_and_forces_incomplete() -> None:
    request = _explicit_request()
    log: list[str] = []
    match_adapter = AutoFillMatch(
        log,
        prices=EXECUTION_PRICES,
        fees=EXECUTION_FEES,
        reject=("us-buy-1",),
    )
    result = run_portfolio_orchestration(
        request,
        adapters=_adapters(request, log, match=match_adapter),
    )

    assert result.complete is False
    assert result.execution.complete is False
    assert len(result.execution.fills) == 1
    assert len(result.execution.rejected_orders) == 1
    rejection = result.execution.rejected_orders[0]
    assert rejection.plan_order_id == "us-buy-1"
    assert rejection.reason_code == "test_reject"
    assert result.end_ledger.cash_map()["us"] == Decimal("25140.00")
    assert result.end_ledger.cash_map()["cn"] == Decimal("238958.00")


def test_per_order_cancel_is_explicit_data_and_forces_incomplete() -> None:
    request = _explicit_request()
    log: list[str] = []
    match_adapter = AutoFillMatch(
        log,
        prices=EXECUTION_PRICES,
        fees=EXECUTION_FEES,
        cancel=("us-buy-1",),
    )
    result = run_portfolio_orchestration(
        request,
        adapters=_adapters(request, log, match=match_adapter),
    )

    assert result.complete is False
    assert result.execution.complete is False
    assert len(result.execution.fills) == 1
    assert len(result.execution.canceled_orders) == 1
    cancellation = result.execution.canceled_orders[0]
    assert cancellation.plan_order_id == "us-buy-1"
    assert cancellation.reason_code == "test_cancel"
    assert result.end_ledger.cash_map()["us"] == Decimal("25140.00")


def test_planner_generated_conversion_discards_the_document() -> None:
    request = _explicit_request()
    log: list[str] = []
    stages: list[str] = []
    adapters = _adapters(
        request,
        log,
        plan=PlannerConversionPlan(log, PurePlanBuilder(planning_marks=MARKS)),
    )

    with pytest.raises(OrchestrationError) as caught:
        run_portfolio_orchestration(
            request,
            adapters=adapters,
            observer=stages.append,
        )

    error = caught.value
    assert error.stage == "build_plan"
    assert error.reason == "planner_generated_conversion"
    assert error.code == "INTERNAL"
    assert error.completed_stages == STAGE_SEQUENCE[:2]
    assert "preflight_execution_inputs" not in log
    assert "match_orders" not in log
    _assert_no_partial_document(error)


def test_post_fill_conversion_discards_the_document() -> None:
    request = _explicit_request()
    log: list[str] = []
    stages: list[str] = []
    adapters = _adapters(
        request,
        log,
        match=PostFillConversionMatch(
            log,
            prices=EXECUTION_PRICES,
            fees=EXECUTION_FEES,
            conversion=_conversion_event(),
        ),
    )

    with pytest.raises(OrchestrationError) as caught:
        run_portfolio_orchestration(
            request,
            adapters=adapters,
            observer=stages.append,
        )

    error = caught.value
    assert error.stage == "match_orders"
    assert error.reason == "post_fill_fx_conversion"
    assert error.completed_stages == STAGE_SEQUENCE[:4]
    assert "replay_ledger" not in stages
    assert "valuate_reconcile" not in log
    _assert_no_partial_document(error)


def test_later_stage_exception_discards_the_document() -> None:
    request = _explicit_request()
    log: list[str] = []
    stages: list[str] = []
    adapters = _adapters(
        request,
        log,
        valuation=ExplodingValuation(log),
    )

    with pytest.raises(OrchestrationError) as caught:
        run_portfolio_orchestration(
            request,
            adapters=adapters,
            observer=stages.append,
        )

    error = caught.value
    assert error.stage == "valuate_reconcile"
    assert error.reason == "internal_stage_failure"
    assert "RuntimeError" in error.detail
    assert error.completed_stages == STAGE_SEQUENCE[:-1]
    assert tuple(stages) == STAGE_SEQUENCE
    assert isinstance(error.__cause__, RuntimeError)
    _assert_no_partial_document(error)


def test_preflight_failure_never_reaches_match() -> None:
    request = _explicit_request()
    log: list[str] = []
    adapters = _adapters(
        request,
        log,
        preflight=FailingPreflight(log),
    )

    with pytest.raises(OrchestrationError) as caught:
        run_portfolio_orchestration(request, adapters=adapters)

    error = caught.value
    assert error.stage == "preflight_execution_inputs"
    assert error.reason == "internal_stage_failure"
    assert error.completed_stages == STAGE_SEQUENCE[:3]
    assert "match_orders" not in log
    _assert_no_partial_document(error)


def test_stale_opening_ledger_is_rejected_before_conversions() -> None:
    request = _explicit_request()
    log: list[str] = []
    opening = PortfolioLedger.from_request(request)
    buckets = list(opening.buckets)
    buckets[0] = replace(buckets[0], cash=buckets[0].cash + Decimal("1.00"))
    stale = PortfolioLedger(buckets=tuple(buckets))
    adapters = OrchestrationAdapters(
        opening_ledger=StaleLedger(log, stale),
        conversions=SpyConversions(log),
        plan=SpyPlan(log, PurePlanBuilder(planning_marks=MARKS)),
        preflight=SpyPreflight(log, _prepared(request)),
        execution=AutoFillMatch(
            log, prices=EXECUTION_PRICES, fees=EXECUTION_FEES
        ),
        valuation=BridgeValuation(log, VALUATION_MARKS),
    )

    with pytest.raises(OrchestrationError) as caught:
        run_portfolio_orchestration(request, adapters=adapters)

    error = caught.value
    assert error.stage == "validate_opening_ledger"
    assert error.reason == "opening_ledger_mismatch"
    assert error.completed_stages == ()
    assert log == ["validate_opening_ledger"]
    _assert_no_partial_document(error)


def test_malformed_request_is_rejected_before_any_stage() -> None:
    request = _explicit_request()
    log: list[str] = []
    malformed: Any = {"mode": "portfolio"}

    with pytest.raises(OrchestrationError) as caught:
        run_portfolio_orchestration(
            malformed,
            adapters=_adapters(request, log),
        )

    error = caught.value
    assert error.stage == "validate_opening_ledger"
    assert error.reason == "invalid_portfolio_request"
    assert error.code == "INVALID_REQUEST"
    assert error.completed_stages == ()
    assert log == []
    _assert_no_partial_document(error)


def test_same_day_conversion_proceeds_cannot_fund_another_conversion() -> None:
    request = _same_day_proceeds_request()
    log: list[str] = []
    adapters = _adapters(request, log)

    with pytest.raises(OrchestrationError) as caught:
        run_portfolio_orchestration(request, adapters=adapters)

    error = caught.value
    assert error.stage == "apply_caller_conversions"
    assert error.reason == "insufficient_fx_cash"
    assert error.completed_stages == STAGE_SEQUENCE[:1]
    assert "build_plan" not in log
    assert "match_orders" not in log
    _assert_no_partial_document(error)


def test_explicit_and_target_runs_share_the_same_stage_sequence() -> None:
    explicit_stages: list[str] = []
    explicit_log: list[str] = []
    explicit_request = _explicit_request()
    run_portfolio_orchestration(
        explicit_request,
        adapters=_adapters(explicit_request, explicit_log),
        observer=explicit_stages.append,
    )
    target_stages: list[str] = []
    target_log: list[str] = []
    target_request = _target_request()
    run_portfolio_orchestration(
        target_request,
        adapters=_adapters(target_request, target_log),
        observer=target_stages.append,
    )

    assert tuple(explicit_stages) == tuple(target_stages) == STAGE_SEQUENCE
    assert explicit_log[:5] == target_log[:5]


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


def test_rejection_quantity_mismatch_discards_the_document() -> None:
    request = _explicit_request()
    log: list[str] = []
    stages: list[str] = []
    base = AutoFillMatch(
        log,
        prices=EXECUTION_PRICES,
        fees=EXECUTION_FEES,
        reject=("us-buy-1",),
    )
    execution = MutatingMatch(
        base,
        lambda outcome: replace(
            outcome,
            rejected_orders=(
                replace(outcome.rejected_orders[0], qty=3),
            ),
        ),
    )

    error = _assert_outcome_abort(
        request,
        log,
        stages,
        execution,
        reason="outcome_quantity_mismatch",
    )
    assert "us-buy-1.qty" in error.path


def test_cancellation_quantity_mismatch_discards_the_document() -> None:
    request = _explicit_request()
    log: list[str] = []
    stages: list[str] = []
    base = AutoFillMatch(
        log,
        prices=EXECUTION_PRICES,
        fees=EXECUTION_FEES,
        cancel=("us-buy-1",),
    )
    execution = MutatingMatch(
        base,
        lambda outcome: replace(
            outcome,
            canceled_orders=(
                replace(outcome.canceled_orders[0], qty=3),
            ),
        ),
    )

    error = _assert_outcome_abort(
        request,
        log,
        stages,
        execution,
        reason="outcome_quantity_mismatch",
    )
    assert "us-buy-1.qty" in error.path


def test_fill_quantity_mismatch_still_discards_the_document() -> None:
    request = _explicit_request()
    log: list[str] = []
    stages: list[str] = []
    base = AutoFillMatch(log, prices=EXECUTION_PRICES, fees=EXECUTION_FEES)
    execution = MutatingMatch(
        base,
        lambda outcome: replace(
            outcome,
            fills=tuple(
                replace(fill, qty=3)
                if fill.plan_order_id == "us-buy-1"
                else fill
                for fill in outcome.fills
            ),
        ),
    )

    error = _assert_outcome_abort(
        request,
        log,
        stages,
        execution,
        reason="fill_quantity_mismatch",
    )
    assert "us-buy-1.qty" in error.path


def test_duplicate_terminal_outcome_discards_the_document() -> None:
    request = _explicit_request()
    log: list[str] = []
    stages: list[str] = []
    base = AutoFillMatch(log, prices=EXECUTION_PRICES, fees=EXECUTION_FEES)
    duplicate = ExecutionRejection(
        plan_order_id="us-buy-1",
        bucket_id="us",
        symbol="AAPL.US",
        currency="USD",
        side="buy",
        qty=2,
        trade_date=request.trade_date,
        reason_code="test_duplicate",
        detail="a second terminal outcome for the same planned order",
    )
    execution = MutatingMatch(
        base,
        lambda outcome: replace(
            outcome,
            rejected_orders=(duplicate,),
        ),
    )

    _assert_outcome_abort(
        request,
        log,
        stages,
        execution,
        reason="duplicate_order_outcome",
    )


def test_missing_terminal_outcome_discards_the_document() -> None:
    request = _explicit_request()
    log: list[str] = []
    stages: list[str] = []
    base = AutoFillMatch(log, prices=EXECUTION_PRICES, fees=EXECUTION_FEES)
    execution = MutatingMatch(
        base,
        lambda outcome: replace(
            outcome,
            fills=tuple(
                fill
                for fill in outcome.fills
                if fill.plan_order_id != "us-buy-1"
            ),
        ),
    )

    error = _assert_outcome_abort(
        request,
        log,
        stages,
        execution,
        reason="missing_order_outcome",
    )
    assert "us-buy-1" in error.detail


def test_identity_mismatched_outcome_discards_the_document() -> None:
    request = _explicit_request()
    log: list[str] = []
    stages: list[str] = []
    base = AutoFillMatch(
        log,
        prices=EXECUTION_PRICES,
        fees=EXECUTION_FEES,
        reject=("us-buy-1",),
    )
    execution = MutatingMatch(
        base,
        lambda outcome: replace(
            outcome,
            rejected_orders=(
                replace(outcome.rejected_orders[0], symbol="MSFT.US"),
            ),
        ),
    )

    _assert_outcome_abort(
        request,
        log,
        stages,
        execution,
        reason="execution_plan_mismatch",
    )
