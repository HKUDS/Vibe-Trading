"""Outcome-validation abort tests for the pt-v2.0 orchestrator match_orders stage."""

from __future__ import annotations

from dataclasses import replace

from src.tools.paper_trade.portfolio.orchestrator import ExecutionRejection
from tests.paper_trade_portfolio_orchestrator_helpers import (
    EXECUTION_FEES,
    EXECUTION_PRICES,
    AutoFillMatch,
    MutatingMatch,
    _assert_outcome_abort,
    _explicit_request,
)


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
