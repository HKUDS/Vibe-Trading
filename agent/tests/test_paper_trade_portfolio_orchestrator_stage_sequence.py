"""Fixed pt-v2.0 stage ordering and atomic-document orchestrator tests."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from src.tools.paper_trade.portfolio.ledger import PortfolioLedger
from src.tools.paper_trade.portfolio.orchestrator import (
    STAGE_SEQUENCE,
    OrchestrationAdapters,
    OrchestrationError,
    PurePlanBuilder,
    run_portfolio_orchestration,
)
from tests.paper_trade_portfolio_orchestrator_helpers import (
    EXECUTION_FEES,
    EXECUTION_PRICES,
    MARKS,
    VALUATION_MARKS,
    AutoFillMatch,
    BridgeValuation,
    ExplodingValuation,
    FailingPreflight,
    PlannerConversionPlan,
    PostFillConversionMatch,
    SpyConversions,
    SpyPlan,
    SpyPreflight,
    StaleLedger,
    _adapters,
    _assert_no_partial_document,
    _conversion_event,
    _explicit_request,
    _prepared,
    _same_day_proceeds_request,
    _target_request,
)


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
