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

import hashlib
import json
import math
import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade import engine
from src.tools.paper_trade.portfolio import run_portfolio_step
from src.tools.paper_trade.portfolio.orchestrator import OrchestrationError
from src.tools.paper_trade.portfolio.schema import (
    PortfolioRequestError,
    load_portfolio_contract_schema,
)
from src.tools.paper_trade.portfolio.sessions import PortfolioSessionError
from src.tools.paper_trade.portfolio.wire import (
    INPUT_HASH_MARKER,
    PortfolioWireError,
    build_error_from_exception,
    build_error_payload,
    build_success_payload,
    compute_raw_input_hash,
    dumps_payload,
    error_code_for_exception,
    serialize_error,
    serialize_success,
)
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload

TRADE_DATE = date(2026, 11, 13)
PRIOR_DATE = date(2026, 11, 12)
DAY = TRADE_DATE.isoformat()
PRIOR = PRIOR_DATE.isoformat()

_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_DECIMAL_KEYS = {
    "amount",
    "avg_cost",
    "cash",
    "fee",
    "limit",
    "nav_base",
    "position_value",
    "price",
    "rebalance_band",
    "value",
    "weight",
}


class FakeLoader:
    """Offline loader double; the wire tests must never touch a provider."""

    def __init__(self, frames: dict[str, pd.DataFrame], name: str) -> None:
        self.name = name
        self.frames = frames

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
        return {code: self.frames[code] for code in codes if code in self.frames}


class OpenCalendar:
    def get_trade_calendar(self, start_date: str, end_date: str) -> pd.DataFrame:
        rows = [
            {
                "exchange": "SSE",
                "cal_date": day.strftime("%Y-%m-%d"),
                "is_open": 1,
                "pretrade_date": "",
            }
            for day in pd.date_range(start_date, end_date)
        ]
        return pd.DataFrame(
            rows,
            columns=["exchange", "cal_date", "is_open", "pretrade_date"],
        )


def _frame(prior: float, target: float | None) -> pd.DataFrame:
    records = [
        {
            "trade_date": PRIOR,
            "open": prior,
            "high": prior,
            "low": prior,
            "close": prior,
            "volume": 1000.0,
        }
    ]
    if target is not None:
        records.append(
            {
                "trade_date": DAY,
                "open": target,
                "high": target,
                "low": target,
                "close": target,
                "volume": 1000.0,
            }
        )
    frame = pd.DataFrame(records)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame.set_index("trade_date")[["open", "high", "low", "close", "volume"]]


def _loaders() -> dict[str, Any]:
    return {
        "cn_a": FakeLoader({"600519.SH": _frame(1418.0, 1421.0)}, "cn-fixture"),
        "hk": FakeLoader({"00700.HK": _frame(410.0, 417.8)}, "hk-fixture"),
        "us": FakeLoader({"AAPL.US": _frame(340.0, 343.46)}, "us-fixture"),
    }


def _payload() -> dict[str, Any]:
    return json.loads(json.dumps(valid_portfolio_payload()))


def _explicit_payload() -> dict[str, Any]:
    payload = _payload()
    payload["fx_conversions"] = []
    payload["portfolio_state"]["buckets"][0]["cash"] = "200000.00"
    payload["portfolio_state"]["buckets"][1]["fee_model"] = {
        "currency": "HKD",
        "parameters": {"commission_rate": "0.0003", "commission_min": "20.00"},
    }
    payload["orders"] = [
        {
            "order_id": "cn-buy-1",
            "bucket_id": "cn",
            "symbol": "600519.SH",
            "currency": "CNY",
            "side": "buy",
            "qty": 100,
        },
        {
            "order_id": "hk-buy-1",
            "bucket_id": "hk",
            "symbol": "00700.HK",
            "currency": "HKD",
            "side": "buy",
            "qty": 100,
        },
        {
            "order_id": "us-buy-1",
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "side": "buy",
            "qty": 10,
        },
    ]
    return payload


def _target_payload() -> dict[str, Any]:
    payload = _payload()
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
            "weight": "0.16",
        },
        {
            "bucket_id": "us",
            "symbol": "AAPL.US",
            "currency": "USD",
            "weight": "0.20",
        },
    ]
    payload["rebalance_band"] = "0"
    return payload


def _run(payload: dict[str, Any]):
    return run_portfolio_step(
        payload,
        loaders=_loaders(),
        calendar_client=OpenCalendar(),
    )


def _validate(payload: dict[str, Any], schema_name: str) -> None:
    schema = load_portfolio_contract_schema(schema_name)
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(payload)
    )
    assert errors == []


def _scan_numeric_types(value: Any, path: str = "$") -> None:
    """Fail on any public float/Decimal and every non-finite numeric."""
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        pytest.fail(f"float leaked at {path}: {value!r}")
    if isinstance(value, Decimal):
        pytest.fail(f"Decimal leaked at {path}: {value!r}")
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str)
            _scan_numeric_types(item, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _scan_numeric_types(item, f"{path}[{index}]")
        return
    pytest.fail(f"non-JSON value leaked at {path}: {type(value).__name__}")


def _assert_decimal_strings(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key in _DECIMAL_KEYS:
                assert isinstance(item, str), f"{item_path} must be a decimal string"
                assert _DECIMAL_PATTERN.fullmatch(item), f"{item_path} is not canonical"
            elif key == "parameters":
                assert isinstance(item, dict)
                for name, parameter in item.items():
                    assert isinstance(parameter, str)
                    assert _DECIMAL_PATTERN.fullmatch(parameter), (
                        f"{item_path}.{name} is not canonical"
                    )
            else:
                _assert_decimal_strings(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_decimal_strings(item, f"{path}[{index}]")


def _outcome_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in ("fills", "rejected_orders", "canceled_orders"):
        rows.extend(payload[field])
    return rows


def _dumped(step: Any) -> dict[str, Any]:
    return step.document.model_dump(mode="json", by_alias=True, exclude_none=True)


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


def test_lone_surrogate_error_echo_still_serializes_a_valid_envelope() -> None:
    # Given a request whose echoed account id and detail carry lone surrogates.
    raw = {"account_id": "pf-\ud800", "mode": "portfolio"}
    detail = "bad echo \udfff"
    payload = build_error_payload(
        raw,
        code="INVALID_REQUEST",
        reason="invalid_utf8",
        path="account_id",
        detail=detail,
    )
    text = serialize_error(
        raw,
        code="INVALID_REQUEST",
        reason="invalid_utf8",
        path="account_id",
        detail=detail,
    )

    # Then the envelope is schema-valid UTF-8 with the same deterministic hash.
    _validate(payload, "error_envelope")
    text.encode("utf-8")
    assert "\ud800" not in payload["account_id"]
    assert json.loads(text) == payload
    assert payload["error"]["detail"].endswith(
        f"{INPUT_HASH_MARKER}={compute_raw_input_hash(raw)}"
    )
    assert compute_raw_input_hash(b"\xff\xfe") == hashlib.sha256(b"\xff\xfe").hexdigest()
    invalid_bytes = build_error_payload(
        b"\xff\xfe",
        code="INVALID_REQUEST",
        reason="invalid_utf8",
        path="$",
        detail="request bytes are not valid UTF-8",
    )
    _validate(invalid_bytes, "error_envelope")
    assert invalid_bytes["account_id"] == ""


def test_existing_input_hash_marker_is_replaced_not_accumulated() -> None:
    # Given details already carrying one or more stale hash suffixes.
    raw = {"account_id": "pf", "mode": "portfolio"}
    stale = "boom; input_sha256=" + ("0" * 64)
    doubled = stale + "; input_sha256=" + ("1" * 64)
    current = f"{INPUT_HASH_MARKER}={compute_raw_input_hash(raw)}"

    for detail in (stale, doubled, current):
        payload = build_error_payload(
            raw,
            code="INVALID_REQUEST",
            reason="boom",
            path="$",
            detail=detail,
        )

        # Then exactly one current marker remains at the end of the detail.
        final = payload["error"]["detail"]
        assert final.count(f"{INPUT_HASH_MARKER}=") == 1
        assert final.endswith(current)


def test_internal_is_never_in_band_and_no_error_carries_a_ledger_or_fills() -> None:
    # Given every public error path and one internal fault.
    raw = {"account_id": "pf", "mode": "portfolio"}
    documents = [
        build_error_payload(
            raw,
            code="INVALID_REQUEST",
            reason="invalid_mode",
            path="mode",
            detail="mode must be portfolio",
        ),
        build_error_payload(
            raw,
            code="PAPER_DATA_NOT_READY",
            reason="open_bucket_zero_target_bars",
            path="sessions.us.status",
            detail="us: no target-day bar",
            bucket_id="us",
        ),
        build_error_payload(
            {**raw, "value": math.nan},
            code="INVALID_REQUEST",
            reason="non_finite_input",
            path="value",
            detail="non-finite JSON number",
        ),
        build_error_payload(
            b"\xff\xfe",
            code="INVALID_REQUEST",
            reason="invalid_utf8",
            path="$",
            detail="request bytes are not valid UTF-8",
        ),
    ]

    # Then no envelope publishes a success ledger, fill or cancel row.
    for document in documents:
        _validate(document, "error_envelope")
        for forbidden in (
            "end_portfolio",
            "end_state",
            "fills",
            "rejected_orders",
            "canceled_orders",
        ):
            assert forbidden not in document

    # Then INTERNAL still refuses to become a public in-band code.
    with pytest.raises(PortfolioWireError) as caught:
        build_error_payload(
            raw,
            code="INTERNAL",
            reason="boom",
            path="execution.fills.us-buy-1",
        )
    assert caught.value.code == "INTERNAL"
    assert caught.value.reason == "internal_error_not_in_band"


# ── failure: stable in-band errors without a fabricated ledger ──


def test_error_document_validates_echoes_input_hash_and_has_no_ledger() -> None:
    raw = b'{"mode":"portfolio","account_id":"bad-\xff"}'
    first = build_error_payload(
        raw,
        code="PAPER_DATA_NOT_READY",
        reason="open_bucket_zero_target_bars",
        path="sessions.us.status",
        detail="us: no target-day bar",
        bucket_id="us",
    )
    second = build_error_payload(
        raw,
        code="PAPER_DATA_NOT_READY",
        reason="open_bucket_zero_target_bars",
        path="sessions.us.status",
        detail="us: no target-day bar",
        bucket_id="us",
    )

    # Then the envelope validates and is deterministic.
    _validate(first, "error_envelope")
    _scan_numeric_types(first)
    assert first == second
    assert first["status"] == "error"
    assert first["code"] == "PAPER_DATA_NOT_READY"
    assert first["error"] == {
        "reason": "open_bucket_zero_target_bars",
        "path": "sessions.us.status",
        "detail": "us: no target-day bar; "
        f"{INPUT_HASH_MARKER}={compute_raw_input_hash(raw)}",
        "bucket_id": "us",
    }

    # Then it echoes the raw byte hash but never an end ledger or fills.
    digest = hashlib.sha256(raw).hexdigest()
    assert f"{INPUT_HASH_MARKER}={digest}" in first["error"]["detail"]
    for forbidden in ("end_portfolio", "end_state", "fills", "canceled_orders"):
        assert forbidden not in first
    text = serialize_error(
        raw,
        code="PAPER_DATA_NOT_READY",
        reason="open_bucket_zero_target_bars",
        path="sessions.us.status",
        detail="us: no target-day bar",
        bucket_id="us",
    )
    assert json.loads(text) == first
    text.encode("utf-8")


def test_nonfinite_raw_input_still_yields_a_deterministic_error_document() -> None:
    raw = {"account_id": "pf", "value": math.nan}
    first = build_error_payload(
        raw,
        code="INVALID_REQUEST",
        reason="non_finite_input",
        path="value",
        detail="non-finite JSON number",
    )
    second = build_error_payload(
        raw,
        code="INVALID_REQUEST",
        reason="non_finite_input",
        path="value",
        detail="non-finite JSON number",
    )
    _validate(first, "error_envelope")
    _scan_numeric_types(first)
    assert first == second
    assert "bucket_id" not in first["error"]
    assert f"{INPUT_HASH_MARKER}={compute_raw_input_hash(raw)}" in first["error"]["detail"]
    assert "end_portfolio" not in first and "fills" not in first


def test_error_from_exception_preserves_codes_and_refuses_internal_masks() -> None:
    raw = {"account_id": "pf", "mode": "portfolio"}
    request_error = PortfolioRequestError(reason="missing_mode", path="mode")
    data_error = PortfolioSessionError(
        reason="open_bucket_zero_target_bars",
        path="sessions.us.status",
        bucket_id="us",
    )
    internal = OrchestrationError(
        stage="match_orders",
        reason="execution_plan_mismatch",
        code="INTERNAL",
        path="execution.fills.us-buy-1",
        bucket_id="us",
        completed_stages=("validate_opening_ledger", "apply_caller_conversions"),
    )

    assert error_code_for_exception(request_error) == "INVALID_REQUEST"
    assert error_code_for_exception(data_error) == "PAPER_DATA_NOT_READY"
    assert error_code_for_exception(internal) == "INTERNAL"

    request_document = build_error_from_exception(raw, request_error)
    data_document = build_error_from_exception(raw, data_error)
    _validate(request_document, "error_envelope")
    _validate(data_document, "error_envelope")
    assert (request_document["code"], request_document["error"]["reason"]) == (
        "INVALID_REQUEST",
        "missing_mode",
    )
    assert (
        data_document["code"],
        data_document["error"]["reason"],
        data_document["error"]["bucket_id"],
    ) == ("PAPER_DATA_NOT_READY", "open_bucket_zero_target_bars", "us")

    with pytest.raises(PortfolioWireError) as caught:
        build_error_from_exception(raw, internal)
    assert caught.value.reason == "internal_error_not_in_band"
    assert caught.value.path == "execution.fills.us-buy-1"

    with pytest.raises(PortfolioWireError) as caught:
        build_error_payload(raw, code="INTERNAL", reason="boom", path="$")
    assert caught.value.reason == "internal_error_not_in_band"

    with pytest.raises(PortfolioWireError) as caught:
        build_error_payload(raw, code="SOMETHING_ELSE", reason="boom", path="$")
    assert caught.value.reason == "invalid_error_code"


def test_fault_after_conversion_has_no_public_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a matcher whose float fee disagrees after conversions have settled.
    real_run = engine.run_day_loop

    def mismatched(*args, **kwargs):
        outcome = real_run(*args, **kwargs)
        if not outcome.fills:
            return outcome
        from dataclasses import replace

        fills = list(outcome.fills)
        fills[0] = replace(fills[0], fee=fills[0].fee + 1.0)
        return replace(outcome, fills=tuple(fills))

    monkeypatch.setattr(engine, "run_day_loop", mismatched)

    # When the internal step faults after the conversion stage.
    with pytest.raises(OrchestrationError) as caught:
        _run(_explicit_payload())

    # Then the fault is internal, never an in-band partial success document.
    assert caught.value.code == "INTERNAL"
    assert "apply_caller_conversions" in caught.value.completed_stages
    with pytest.raises(PortfolioWireError) as wire_error:
        build_error_from_exception(_explicit_payload(), caught.value)
    assert wire_error.value.reason == "internal_error_not_in_band"
    assert not hasattr(wire_error.value, "payload")


def test_input_hash_is_order_independent_and_byte_stable() -> None:
    assert compute_raw_input_hash({"a": 1, "b": [2, 3]}) == compute_raw_input_hash(
        {"b": [2, 3], "a": 1}
    )
    assert compute_raw_input_hash(b"raw-bytes") == hashlib.sha256(b"raw-bytes").hexdigest()
    assert compute_raw_input_hash("raw-text") == hashlib.sha256(b"raw-text").hexdigest()
    assert (
        compute_raw_input_hash({"value": math.nan})
        == compute_raw_input_hash({"value": math.nan})
    )
    assert len(compute_raw_input_hash({"a": 1})) == 64
