"""Attribution tampering tests: every mutation surfaces as a declared issue.

A changed fill, conversion, valuation mark, planned weight or published
realized weight must produce field-level reconciliation issues (or a wire
refusal); the residual is never fitted to hide the error. Shared fixtures live
in ``paper_trade_portfolio_attribution_helpers``.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from src.tools.paper_trade.portfolio.analytics import reconcile_attribution
from src.tools.paper_trade.portfolio.data import TargetBarValuation
from src.tools.paper_trade.portfolio.wire import (
    PortfolioWireError,
    build_success_payload,
)
from tests.paper_trade_portfolio_attribution_helpers import (
    _attribution,
    _base_payload,
    _decimal,
    _rebuild,
    _run,
)


def test_tampered_fill_produces_a_reconciliation_issue() -> None:
    # Given one valid step and a fill whose price is mutated after execution.
    step = _run()
    fills = step.execution.fills
    mutated = (
        replace(fills[0], price=fills[0].price + Decimal("1")),
        *fills[1:],
    )

    # When attribution is rebuilt from the tampered execution row.
    analytics = _rebuild(step, _base_payload(), fills=mutated)
    attribution = analytics.attribution
    assert attribution is not None

    # Then the mismatch is a declared issue; the residual is not fitted.
    assert attribution.reconciliation.reconciled is False
    assert attribution.reconciliation.issues
    assert any(
        issue.reason.startswith("attribution_fill")
        for issue in attribution.reconciliation.issues
    )
    assert _decimal(attribution.rounding_residual) != _decimal(
        attribution.expected_rounding_residual
    )


def test_tampered_conversion_produces_a_reconciliation_issue() -> None:
    # Given one valid conversion whose credited amount is mutated.
    step = _run()
    event = step.conversion_replay.events[0]
    mutated = (replace(event, converted_amount=event.converted_amount + Decimal("1")),)

    analytics = _rebuild(step, _base_payload(), conversion_events=mutated)
    attribution = analytics.attribution
    assert attribution is not None

    # Then conversion replay and the identity both reject the mutation.
    assert attribution.reconciliation.reconciled is False
    assert attribution.reconciliation.issues
    assert any(
        issue.reason.startswith("attribution_conversion")
        for issue in attribution.reconciliation.issues
    )
    assert _decimal(attribution.rounding_residual) != _decimal(
        attribution.expected_rounding_residual
    )


def test_tampered_mark_produces_a_reconciliation_issue() -> None:
    # Given a valuation mark that no longer agrees with the execution snapshot.
    step = _run()
    buckets = []
    for bucket in step.prepared_data.buckets:
        if bucket.bucket_id != "hk" or not isinstance(
            bucket.valuation, TargetBarValuation
        ):
            buckets.append(bucket)
            continue
        snapshot = bucket.valuation.snapshot
        bars = tuple(
            replace(bar, close=str(Decimal(bar.close) + Decimal("1")))
            if bar.symbol == "00700.HK"
            else bar
            for bar in snapshot.bars
        )
        buckets.append(
            replace(
                bucket,
                valuation=TargetBarValuation(snapshot=replace(snapshot, bars=bars)),
            )
        )
    prepared = replace(step.prepared_data, buckets=tuple(buckets))

    analytics = _rebuild(step, _base_payload(), prepared=prepared)
    attribution = analytics.attribution
    assert attribution is not None

    # Then the mark disagreement and resulting replay mismatch are explicit.
    assert attribution.reconciliation.reconciled is False
    assert attribution.reconciliation.issues
    assert any(
        issue.reason in {
            "attribution_valuation_execution_mark_mismatch",
            "attribution_fill_replay_mismatch",
        }
        for issue in attribution.reconciliation.issues
    )


def test_tampered_planned_weight_produces_a_reconciliation_issue() -> None:
    # Given a plan row whose planned weight no longer matches its quantity.
    step = _run()
    rows = list(step.order_plan.weights)
    index = next(
        index for index, row in enumerate(rows) if row.symbol == "00700.HK"
    )
    rows[index] = replace(
        rows[index],
        planned_weight=rows[index].planned_weight + Decimal("0.010000000000"),
    )
    plan = replace(step.order_plan, weights=tuple(rows))

    analytics = _rebuild(step, _base_payload(), plan=plan)
    attribution = analytics.attribution
    assert attribution is not None

    # Then the published weight view refuses to reconcile.
    assert attribution.reconciliation.reconciled is False
    assert any(
        issue.reason == "attribution_planned_weight_mismatch"
        for issue in attribution.reconciliation.issues
    )
    assert attribution.weights.reconciled is False


def test_mutated_realized_weight_has_a_reconciliation_issue() -> None:
    # Given a published attribution whose realized weight is changed in place.
    attribution = _attribution(_run())
    row = next(
        row for row in attribution.weights.rows if row.symbol == "00700.HK"
    )
    mutated_rows = tuple(
        item.model_copy(update={"realized_weight": "0.500000000000"})
        if item.symbol == row.symbol and item.bucket_id == row.bucket_id
        else item
        for item in attribution.weights.rows
    )
    mutated = attribution.model_copy(
        update={
            "weights": attribution.weights.model_copy(
                update={"rows": mutated_rows}
            )
        }
    )

    # Then the independent verifier reports the row, not a fitted residual.
    issues = reconcile_attribution(mutated)
    assert any(
        issue.reason == "attribution_realized_weight_mismatch"
        for issue in issues
    )


def test_tampered_realized_weight_is_rejected_by_the_public_wire() -> None:
    # Given a valid public document with one realized weight altered.
    public = build_success_payload(_run())
    rows = public["analytics"]["attribution"]["weights"]["rows"]
    row = next(row for row in rows if row["symbol"] == "00700.HK")
    row["realized_weight"] = "0.500000000000"

    # Then the public wire recomputes the weight and refuses the document.
    with pytest.raises(PortfolioWireError) as raised:
        build_success_payload(public)
    assert raised.value.reason.startswith("attribution_")
    assert "realized_weight" in raised.value.path or "weight" in raised.value.reason


def test_cross_bucket_conversion_identity_error_is_a_declared_issue() -> None:
    # Given a conversion redirected to a bucket with another currency.
    step = _run()
    event = step.conversion_replay.events[0]
    mutated = (
        replace(event, to_bucket_id="hk", to_currency="HKD"),
    )

    analytics = _rebuild(step, _base_payload(), conversion_events=mutated)
    attribution = analytics.attribution
    assert attribution is not None

    # Then the bucket/currency identity is rejected, never folded into NAV.
    assert attribution.reconciliation.reconciled is False
    assert any(
        issue.reason.startswith("attribution_conversion")
        for issue in attribution.reconciliation.issues
    )
