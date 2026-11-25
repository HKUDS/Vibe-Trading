"""Public pt-v2.0 portfolio wire documents and bucket-aware errors.

The wire layer is the independent public boundary over the internal Decimal
step: success documents validate against the packaged ``result`` schema, every
outcome row keeps its ``bucket_id``/``plan_order_id`` link, and every public
numeric remains a canonical fixed-point string (quantities stay integers).
Errors validate against the packaged ``error_envelope`` schema, echo a stable
hash of the raw input, and never fabricate an end ledger, fills or a partial
success document.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from decimal import Decimal

import pytest

from src.tools.paper_trade.portfolio.wire import (
    PortfolioWireError,
    build_success_payload,
    dumps_payload,
    serialize_success,
)
from tests.paper_trade_portfolio_wire_helpers import (
    _assert_decimal_strings,
    _dumped,
    _explicit_payload,
    _outcome_rows,
    _payload,
    _run,
    _scan_numeric_types,
    _target_payload,
    _validate,
)

# ── happy: success documents validate and keep every identity link ──


def test_three_market_success_wire_document_validates_and_links_every_outcome() -> None:
    # Given a completed three-market explicit-order step.
    step = _run(_explicit_payload())

    # When the public wire serializes the step result.
    payload = build_success_payload(step)

    # Then the document validates, is strict JSON, and exposes no floats.
    _validate(payload, "result")
    _scan_numeric_types(payload)
    _assert_decimal_strings(payload)
    assert payload["status"] == "success"
    assert payload["tool"] == "paper_trade_step"
    assert payload["schema_version"] == "pt-v2.0"
    assert payload["mode"] == "portfolio"
    assert payload["complete"] is True
    assert payload["plan"]["kind"] == "orders"

    # Then every fill links to its bucket and an explicit plan line.
    plan_ids = {order["order_id"] for order in payload["plan"]["orders"]}
    assert [(row["plan_order_id"], row["bucket_id"]) for row in payload["fills"]] == [
        ("cn-buy-1", "cn"),
        ("hk-buy-1", "hk"),
        ("us-buy-1", "us"),
    ]
    assert {row["plan_order_id"] for row in payload["fills"]} == plan_ids
    assert set(payload["hashes"]) == {
        "plan_hash",
        "planning_data_hash",
        "execution_data_fingerprint",
        "document_hash",
    }

    # Then the canonical serializer is deterministic and round-trips the payload.
    text = serialize_success(step)
    assert text == dumps_payload(payload)
    assert json.loads(text) == payload
    assert serialize_success(step) == text
    text.encode("utf-8")


def test_target_weight_success_links_generated_plan_lines() -> None:
    # Given target weights whose fills come from the internal generated plan.
    step = _run(_target_payload())

    # When the public wire serializes the result.
    payload = build_success_payload(step)
    _validate(payload, "result")
    _scan_numeric_types(payload)

    # Then every outcome row links to a generated plan line and a bucket.
    planned = {order.plan_order_id: order.bucket_id for order in step.order_plan.orders}
    assert payload["plan"]["kind"] == "target_weights"
    assert [(row["plan_order_id"], row["bucket_id"]) for row in payload["fills"]] == [
        (order_id, bucket_id) for order_id, bucket_id in planned.items()
    ]
    assert len(_outcome_rows(payload)) == len(planned)
    assert payload["complete"] is True


def test_rejected_order_serializes_complete_false_with_bucket_error() -> None:
    # Given one fill and one limit order below the target close.
    payload = _payload()
    payload["fx_conversions"] = []
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
            "qty": 10,
            "limit": "300.00",
        },
    ]
    document = _run(payload)
    wire_document = build_success_payload(document)

    # Then the success document validates but is explicitly incomplete.
    _validate(wire_document, "result")
    _scan_numeric_types(wire_document)
    assert wire_document["complete"] is False
    assert [row["plan_order_id"] for row in wire_document["fills"]] == ["cn-sell-1"]
    assert [
        (row["plan_order_id"], row["bucket_id"], row["reason_code"])
        for row in wire_document["rejected_orders"]
    ] == [("us-buy-1", "us", "limit_not_marketable")]
    assert [(row["reason"], row["bucket_id"]) for row in wire_document["errors"]] == [
        ("limit_not_marketable", "us")
    ]


def test_canceled_orders_serialize_complete_false_with_bucket_and_plan_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a matcher that cancels every planned order at session end.
    from src.tools.paper_trade.portfolio import step as step_module
    from src.tools.paper_trade.portfolio.orchestrator import (
        ExecutionCancellation,
        ExecutionOutcome,
    )

    def cancel_all(self, request, ledger, plan, prepared):
        return ExecutionOutcome(
            canceled_orders=tuple(
                ExecutionCancellation(
                    plan_order_id=order.plan_order_id,
                    bucket_id=order.bucket_id,
                    symbol=order.symbol,
                    currency=order.currency,
                    side=order.side,
                    qty=order.qty,
                    trade_date=request.trade_date,
                    reason_code="day_end_cancel",
                    detail="canceled at session end",
                )
                for order in plan.orders
            )
        )

    monkeypatch.setattr(step_module.DecimalExecutionAdapter, "match", cancel_all)
    document = _run(_explicit_payload())
    wire_document = build_success_payload(document)

    # Then cancels remain bucket/plan-linked rows and the document is incomplete.
    _validate(wire_document, "result")
    _scan_numeric_types(wire_document)
    assert wire_document["complete"] is False
    assert wire_document["fills"] == []
    assert [
        (row["bucket_id"], row["plan_order_id"], row["reason_code"])
        for row in wire_document["canceled_orders"]
    ] == [
        ("cn", "cn-buy-1", "day_end_cancel"),
        ("hk", "hk-buy-1", "day_end_cancel"),
        ("us", "us-buy-1", "day_end_cancel"),
    ]
    assert {row["bucket_id"] for row in wire_document["errors"]} == {"cn", "hk", "us"}


def test_closed_bucket_and_conversion_documents_validate() -> None:
    # Given a closed HK bucket with holdings and a pre-fill CNY->USD conversion.
    payload = _explicit_payload()
    payload["fx_conversions"] = [
        {
            "rate_id": "cny-usd-fix",
            "from_bucket_id": "cn",
            "to_bucket_id": "us",
            "amount": "1000.00",
        }
    ]
    payload["orders"] = [order for order in payload["orders"] if order["bucket_id"] != "hk"]
    for session in payload["sessions"]:
        if session["market"] == "hk":
            session["status"] = "closed"
    document = _run(payload)

    # When the public wire serializes the conversion and closed valuation.
    wire_document = build_success_payload(document)
    _validate(wire_document, "result")
    _scan_numeric_types(wire_document)
    _assert_decimal_strings(wire_document)

    # Then conversions are explicit and the post-conversion ledger differs.
    assert wire_document["conversions"] == [
        {
            "rate_id": "cny-usd-fix",
            "from_bucket_id": "cn",
            "to_bucket_id": "us",
            "amount": "1000.00",
        }
    ]
    opening = {bucket["bucket_id"]: bucket["cash"] for bucket in wire_document["opening_portfolio"]["buckets"]}
    converted = {
        bucket["bucket_id"]: bucket["cash"]
        for bucket in wire_document["post_conversion_portfolio"]["buckets"]
    }
    assert opening["cn"] == "200000.00"
    assert converted["cn"] == "199000.00"
    assert converted["us"] == "25140.00"

    # Then the closed bucket kept its prior-mark valuation and never filled.
    hk = next(row for row in wire_document["bucket_results"] if row["bucket_id"] == "hk")
    assert hk["session"]["status"] == "closed"
    assert (hk["cash"], hk["position_value"], hk["nav_base"]) == (
        "50000.00",
        "41000.00",
        "11648.00",
    )
    assert [fill["bucket_id"] for fill in wire_document["fills"]] == ["cn", "us"]
    assert any("hk: market closed" in warning for warning in wire_document["warnings"])


# ── failure: malformed success documents fail closed ──


@pytest.mark.parametrize("missing", ["missing", "empty"])
def test_missing_plan_order_id_is_a_stable_wire_error(missing: str) -> None:
    # Given a valid public document with one fill's plan identity destroyed.
    payload = _run(_explicit_payload()).document.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    if missing == "missing":
        del payload["fills"][0]["plan_order_id"]
    else:
        payload["fills"][0]["plan_order_id"] = ""

    # When / Then the wire refuses to publish it.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(payload)
    assert caught.value.reason == "missing_plan_order_id"
    assert caught.value.path == "fills[0].plan_order_id"


def test_unknown_bucket_and_unknown_plan_line_are_rejected() -> None:
    base = _run(_explicit_payload()).document.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )

    bad_bucket = json.loads(json.dumps(base))
    bad_bucket["fills"][0]["bucket_id"] = "moon"
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(bad_bucket)
    assert caught.value.reason == "unknown_bucket"
    assert caught.value.path == "fills[0].bucket_id"

    bad_plan = json.loads(json.dumps(base))
    bad_plan["fills"][0]["plan_order_id"] = "not-a-plan-line"
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(bad_plan)
    assert caught.value.reason == "unknown_plan_order"
    assert caught.value.path == "fills[0].plan_order_id"


def test_target_weight_outcome_must_match_a_target_plan_line() -> None:
    base = _run(_target_payload()).document.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    base["fills"][0]["symbol"] = "UNKNOWN.US"

    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(base)
    assert caught.value.reason == "unknown_plan_line"
    assert caught.value.path == "fills[0]"


def test_missing_plan_outcome_and_inconsistent_complete_are_rejected() -> None:
    base = _run(_explicit_payload()).document.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )

    missing = json.loads(json.dumps(base))
    missing["fills"].pop()
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(missing)
    assert caught.value.reason == "missing_plan_outcome"

    inconsistent = json.loads(json.dumps(base))
    inconsistent["complete"] = False
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(inconsistent)
    assert caught.value.reason == "inconsistent_complete"


def test_float_decimal_and_nonfinite_values_are_rejected() -> None:
    base = _run(_explicit_payload()).document.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )

    leaked_float = json.loads(json.dumps(base))
    leaked_float["end_portfolio"]["buckets"][0]["cash"] = 1.5
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(leaked_float)
    assert caught.value.reason == "float_not_allowed"
    assert "end_portfolio.buckets[0].cash" in caught.value.path

    leaked_decimal = json.loads(json.dumps(base))
    leaked_decimal["fills"][0]["fee"] = Decimal("1.25")
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(leaked_decimal)
    assert caught.value.reason == "decimal_not_allowed"

    nonfinite = json.loads(json.dumps(base))
    nonfinite["fills"][0]["price"] = math.nan
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(nonfinite)
    assert caught.value.reason == "nonfinite_number"

    with pytest.raises(PortfolioWireError) as caught:
        dumps_payload({"status": "success", "value": math.inf})
    assert caught.value.reason == "nonfinite_number"


def test_extra_top_level_ledger_is_rejected_before_serialization() -> None:
    # Given a valid document carrying an undeclared second ending ledger.
    base = _dumped(_run(_explicit_payload()))
    base["extra_ledger"] = {"buckets": []}

    # When / Then the packaged result shape refuses the extra member.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(base)
    assert caught.value.reason == "unknown_field"
    assert caught.value.path == "extra_ledger"


def test_missing_fill_price_is_rejected_as_a_required_member() -> None:
    # Given a fill whose required packaged price member was dropped.
    base = _dumped(_run(_explicit_payload()))
    del base["fills"][0]["price"]

    # When / Then the nested required key is enforced, not defaulted away.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(base)
    assert caught.value.reason == "missing_field"
    assert caught.value.path == "fills[0].price"


def test_invalid_base_currency_is_rejected() -> None:
    # Given a document whose base currency is outside the packaged enum.
    base = _dumped(_run(_explicit_payload()))
    base["base_currency"] = "EUR"

    # When / Then the enum is enforced deterministically.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(base)
    assert caught.value.reason == "invalid_base_currency"
    assert caught.value.path == "base_currency"


def test_string_fill_quantity_is_rejected() -> None:
    # Given a fill quantity spelled as a JSON string.
    base = _dumped(_run(_explicit_payload()))
    base["fills"][0]["qty"] = str(base["fills"][0]["qty"])

    # When / Then quantities must remain strict JSON integers.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(base)
    assert caught.value.reason == "invalid_qty"
    assert caught.value.path == "fills[0].qty"


def test_empty_account_id_is_rejected() -> None:
    # Given a success document with an empty account identity.
    base = _dumped(_run(_explicit_payload()))
    base["account_id"] = ""

    # When / Then the minLength-1 identity remains required.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(base)
    assert caught.value.reason == "invalid_account_id"
    assert caught.value.path == "account_id"


def test_target_plan_missing_rebalance_band_is_rejected() -> None:
    # Given a target-weight plan relying on the model default.
    base = _dumped(_run(_target_payload()))
    del base["plan"]["rebalance_band"]

    # When / Then a schema-required member cannot be supplied by a default.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(base)
    assert caught.value.reason == "missing_field"
    assert caught.value.path == "plan.rebalance_band"


def test_bucket_missing_positions_is_rejected() -> None:
    # Given an ending bucket relying on the model's empty-tuple default.
    base = _dumped(_run(_explicit_payload()))
    del base["end_portfolio"]["buckets"][0]["positions"]

    # When / Then the packaged required member is enforced.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(base)
    assert caught.value.reason == "missing_field"
    assert caught.value.path == "end_portfolio.buckets[0].positions"


def test_explicit_public_plan_cannot_diverge_from_the_internal_order_plan() -> None:
    # Given a step whose public plan dropped one order but kept its outcome.
    step = _run(_explicit_payload())
    public_plan = step.document.plan
    assert public_plan.kind == "orders"
    shortened = public_plan.model_copy(update={"orders": public_plan.orders[1:]})
    document = step.document.model_copy(update={"plan": shortened})
    diverged = replace(step, document=document)

    # When / Then the public/internal divergence is refused explicitly.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(diverged)
    assert caught.value.reason == "plan_line_divergence"
    assert caught.value.path == "plan.orders"
    assert public_plan.orders[0].order_id in caught.value.detail

    # Then a bare re-validation of the same tree also refuses the orphan outcome.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(_dumped(diverged))
    assert caught.value.reason == "unknown_plan_order"


@pytest.mark.parametrize(
    ("field", "mutated"),
    [
        ("symbol", "00700.HK"),
        ("currency", "HKD"),
        ("side", "sell"),
        ("qty", 999),
    ],
)
def test_explicit_outcome_fields_must_match_the_public_plan_line(
    field: str,
    mutated: object,
) -> None:
    # Given an explicit fill that still links to its plan id and bucket.
    base = _dumped(_run(_explicit_payload()))
    base["fills"][0][field] = mutated

    # When / Then symbol/currency/side/qty cannot silently disagree with the plan.
    with pytest.raises(PortfolioWireError) as caught:
        build_success_payload(base)
    assert caught.value.reason == "plan_line_mismatch"
    assert caught.value.path == f"fills[0].{field}"
