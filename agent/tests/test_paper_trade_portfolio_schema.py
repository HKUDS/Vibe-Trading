"""Internal pt-v2.0 portfolio request and packaged-contract tests.

Only the parser and contract-loader seams are exercised here. Execution and
public mode registration are deliberately outside this task's scope.
"""

# noqa: SIZE_OK

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, TypeAlias, assert_never

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from src.tools.paper_trade.portfolio.models import (
    BucketResult,
    JsonValue,
    PortfolioErrorResult,
    PortfolioHashes,
    PortfolioIssue,
    PortfolioResult,
)
from src.tools.paper_trade.portfolio.schema import (
    CONTRACT_PATH,
    PortfolioRequestError,
    load_portfolio_contract_schema,
    parse_portfolio_request,
)
from tests.paper_trade_portfolio_fixture import valid_portfolio_payload as _valid_payload

MIRROR_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "schema"
    / "tool_contracts"
    / "paper_trade_step-v2.0.json"
)
BoundaryDefect: TypeAlias = Literal[
    "benchmark_start_eur",
    "unused_eur_gbp_fx",
    "epoch_planning_at",
    "epoch_valuation_at",
    "epoch_session_as_of",
    "epoch_fx_as_of",
    "epoch_benchmark_observed_at",
    "empty_buckets",
]


def _mutate_boundary_defect(payload: dict, case: BoundaryDefect) -> None:
    match case:
        case "benchmark_start_eur":
            payload["benchmark"]["start"]["currency"] = "EUR"
        case "unused_eur_gbp_fx":
            payload["fx_snapshots"].append(
                {
                    "rate_id": "unused-eur-gbp",
                    "from": "EUR",
                    "to": "GBP",
                    "rate": "1.17",
                    "as_of": "2026-11-13T11:00:00+00:00",
                    "source": "unused-fix",
                }
            )
        case "epoch_planning_at":
            payload["planning_at"] = 0
        case "epoch_valuation_at":
            payload["valuation_at"] = 0
        case "epoch_session_as_of":
            payload["sessions"][0]["as_of"] = 0
        case "epoch_fx_as_of":
            payload["fx_snapshots"][0]["as_of"] = 0
        case "epoch_benchmark_observed_at":
            payload["benchmark"]["start"]["observed_at"] = 0
        case "empty_buckets":
            payload["portfolio_state"]["buckets"] = []
            payload["orders"] = []
            payload["fx_conversions"] = []
        case unreachable:
            assert_never(unreachable)


def test_parse_three_market_portfolio_request() -> None:
    # Given a caller-owned CNY/HKD/USD portfolio with direct-pair FX.
    payload = _valid_payload()

    # When the public payload crosses the portfolio parser boundary.
    request = parse_portfolio_request(payload)

    # Then it becomes an immutable, discriminated orders-mode request.
    assert request.account_id == "portfolio-cross-market-01"
    assert request.base_currency == "USD"
    assert [bucket.market for bucket in request.portfolio_state.buckets] == ["cn_a", "hk", "us"]
    assert request.plan.kind == "orders"
    assert [order.order_id for order in request.plan.orders] == ["cn-buy-1", "us-buy-1"]
    assert request.rebalance_band == "0"
    assert request.fx_conversions[0].rate_id == "cny-usd-fix"
    assert request.model_config["frozen"] is True


def _assert_invalid(
    payload: dict,
    *,
    reason: str,
    path: str,
    bucket_id: str | None = None,
) -> None:
    # When the malformed payload crosses the parser boundary.
    with pytest.raises(PortfolioRequestError) as caught:
        parse_portfolio_request(payload)

    # Then the typed error exposes stable machine-readable details.
    error = caught.value
    assert error.code == "INVALID_REQUEST"
    assert (error.reason, error.path, error.bucket_id) == (reason, path, bucket_id)
    assert str(error) == f"INVALID_REQUEST:{reason}:{path}"


@pytest.mark.parametrize(
    ("case", "reason", "path", "schema_path"),
    [
        (
            "benchmark_start_eur",
            "invalid_field",
            "benchmark.start.currency",
            ("benchmark", "start", "currency"),
        ),
        (
            "unused_eur_gbp_fx",
            "invalid_field",
            "fx_snapshots[2].from",
            ("fx_snapshots", 2, "from"),
        ),
        ("epoch_planning_at", "invalid_timestamp", "planning_at", ("planning_at",)),
        ("epoch_valuation_at", "invalid_timestamp", "valuation_at", ("valuation_at",)),
        (
            "epoch_session_as_of",
            "invalid_timestamp",
            "sessions[0].as_of",
            ("sessions", 0, "as_of"),
        ),
        (
            "epoch_fx_as_of",
            "invalid_timestamp",
            "fx_snapshots[0].as_of",
            ("fx_snapshots", 0, "as_of"),
        ),
        (
            "epoch_benchmark_observed_at",
            "invalid_timestamp",
            "benchmark.start.observed_at",
            ("benchmark", "start", "observed_at"),
        ),
        (
            "empty_buckets",
            "invalid_field",
            "portfolio_state.buckets",
            ("portfolio_state", "buckets"),
        ),
    ],
)
def test_parser_and_contracts_reject_the_same_boundary_defects(
    case: BoundaryDefect,
    reason: str,
    path: str,
    schema_path: tuple[str | int, ...],
) -> None:
    # Given one verifier-confirmed mutation of an otherwise valid request.
    payload = _valid_payload()
    _mutate_boundary_defect(payload, case)

    # When / Then the parser rejects it with stable machine-readable details.
    _assert_invalid(payload, reason=reason, path=path)

    # And both independently reachable Draft 2020-12 contracts reject the same field.
    for contract_path in (CONTRACT_PATH, MIRROR_CONTRACT_PATH):
        document = json.loads(contract_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(
            document["schemas"]["request"],
            format_checker=FormatChecker(),
        )
        errors = list(validator.iter_errors(payload))
        assert any(tuple(error.absolute_path) == schema_path for error in errors), (
            contract_path,
            errors,
        )


@pytest.mark.parametrize("field", ["mode", "schema_version"])
def test_missing_mode_or_version_has_a_stable_reason(field: str) -> None:
    # Given an otherwise valid request without its discriminator.
    payload = _valid_payload()
    del payload[field]

    # When / Then parsing fails at the missing discriminator.
    _assert_invalid(payload, reason=f"missing_{field}", path=field)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("market", "cn_a"),
        ("account_state", {"cash": 1}),
        ("from_date", "2026-11-13"),
        ("to_date", "2026-11-13"),
        ("strategy_path", "strategy.py"),
        ("volume_share", "0.25"),
    ],
)
def test_legacy_only_fields_are_rejected(field: str, value: JsonValue) -> None:
    # Given a portfolio request polluted by a dummy legacy-only field.
    payload = _valid_payload()
    payload[field] = value

    # When / Then the parser rejects the legacy field before execution.
    _assert_invalid(payload, reason="legacy_field_forbidden", path=field)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("interval", "5m", "unsupported_interval"),
        ("fill_model", "volume_share", "unsupported_fill_model"),
    ],
)
def test_legacy_execution_policies_are_rejected(field: str, value: str, reason: str) -> None:
    # Given a request selecting an execution policy outside pt-v2.0.
    payload = _valid_payload()
    payload[field] = value

    # When / Then the parser returns the policy-specific stable reason.
    _assert_invalid(payload, reason=reason, path=field)


def test_orders_and_target_weights_are_mutually_exclusive() -> None:
    # Given a request containing both discriminated plan branches.
    payload = _valid_payload()
    payload["target_weights"] = [
        {"bucket_id": "us", "symbol": "AAPL.US", "currency": "USD", "weight": "0.25"}
    ]

    # When / Then the ambiguous plan is rejected.
    _assert_invalid(payload, reason="conflicting_order_plan", path="orders")


def test_a_plan_branch_is_required() -> None:
    # Given a request with neither explicit orders nor target weights.
    payload = _valid_payload()
    del payload["orders"]

    # When / Then the absent plan discriminator is rejected.
    _assert_invalid(payload, reason="missing_order_plan", path="$")


def test_noncanonical_bucket_currency_is_rejected_with_bucket_details() -> None:
    # Given a US bucket denominated in a noncanonical currency.
    payload = _valid_payload()
    payload["portfolio_state"]["buckets"][2]["currency"] = "CAD"

    # When / Then the error identifies both the field and its bucket.
    _assert_invalid(
        payload,
        reason="invalid_bucket_currency",
        path="portfolio_state.buckets[2].currency",
        bucket_id="us",
    )


@pytest.mark.parametrize("row_kind", ["positions", "orders", "target_weights", "fee_model"])
def test_non_hkd_hk_counters_are_rejected(row_kind: str) -> None:
    # Given an HK counter explicitly denominated in USD.
    payload = _valid_payload()
    if row_kind == "positions":
        payload["portfolio_state"]["buckets"][1]["positions"][0]["currency"] = "USD"
        path = "portfolio_state.buckets[1].positions[0].currency"
    elif row_kind == "fee_model":
        payload["portfolio_state"]["buckets"][1]["fee_model"]["currency"] = "USD"
        path = "portfolio_state.buckets[1].fee_model.currency"
    else:
        payload.pop("orders")
        payload[row_kind] = [
            {
                **(
                    {"order_id": "hk-usd-order", "side": "buy", "qty": 1}
                    if row_kind == "orders"
                    else {"weight": "0.10"}
                ),
                "bucket_id": "hk",
                "symbol": "00700.HK",
                "currency": "USD",
            }
        ]
        path = f"{row_kind}[0].currency"

    # When / Then the incompatible counter fails closed with bucket identity.
    _assert_invalid(payload, reason="non_hkd_hk_counter", path=path, bucket_id="hk")


def test_target_weights_select_the_other_discriminated_plan() -> None:
    # Given a target-weight request with an explicit nonzero rebalance band.
    payload = _valid_payload()
    del payload["orders"]
    payload["target_weights"] = [
        {"bucket_id": "us", "symbol": "AAPL.US", "currency": "USD", "weight": "0.25"}
    ]
    payload["rebalance_band"] = "0.01"

    # When the request is parsed.
    request = parse_portfolio_request(payload)

    # Then only the target-weight branch and band are present.
    assert request.plan.kind == "target_weights"
    assert request.plan.target_weights[0].weight == "0.25"
    assert request.plan.rebalance_band == "0.01"
    assert request.rebalance_band == "0.01"
    assert request.orders is None


@pytest.mark.parametrize("case", ["missing", "duplicate", "invalid_status"])
def test_market_sessions_are_explicit_complete_and_valid(case: str) -> None:
    # Given a request whose caller-declared sessions are malformed.
    payload = _valid_payload()
    if case == "missing":
        del payload["sessions"][2]
        expected = ("missing_session", "sessions", "us")
    elif case == "duplicate":
        payload["sessions"].append(payload["sessions"][0])
        expected = ("duplicate_session", "sessions[3].market", None)
    else:
        payload["sessions"][1]["status"] = "inferred"
        expected = ("invalid_session", "sessions[1].status", None)

    # When / Then the session fault is identified deterministically.
    reason, path, bucket_id = expected
    _assert_invalid(payload, reason=reason, path=path, bucket_id=bucket_id)


@pytest.mark.parametrize("case", ["unknown_rate", "pair_mismatch", "duplicate_rate"])
def test_fx_conversions_require_unique_matching_direct_pairs(case: str) -> None:
    # Given a conversion whose direct-pair declaration is malformed.
    payload = _valid_payload()
    if case == "unknown_rate":
        payload["fx_conversions"][0]["rate_id"] = "missing-rate"
        expected = ("unknown_fx_rate", "fx_conversions[0].rate_id")
    elif case == "pair_mismatch":
        payload["fx_snapshots"][0]["from"] = "USD"
        payload["fx_snapshots"][0]["to"] = "CNY"
        expected = ("fx_pair_mismatch", "fx_conversions[0].rate_id")
    else:
        payload["fx_snapshots"].append(payload["fx_snapshots"][0])
        expected = ("duplicate_fx_rate", "fx_snapshots[2].rate_id")

    # When / Then the direct-pair fault is rejected before any arithmetic.
    reason, path = expected
    _assert_invalid(payload, reason=reason, path=path, bucket_id="cn")


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        ("planning_at", "2026-11-13T12:00:00", "invalid_timestamp"),
        ("valuation_at", "2026-11-12T21:00:00+00:00", "invalid_timestamp_order"),
    ],
)
def test_planning_and_valuation_timestamps_are_aware_and_ordered(
    path: str, value: str, reason: str
) -> None:
    # Given a naive or incorrectly ordered envelope timestamp.
    payload = _valid_payload()
    payload[path] = value

    # When / Then the timestamp fault is reported at its own field.
    _assert_invalid(payload, reason=reason, path=path)


def test_fx_snapshot_timestamp_requires_an_offset() -> None:
    # Given an FX snapshot without a timezone offset.
    payload = _valid_payload()
    payload["fx_snapshots"][0]["as_of"] = "2026-11-13T11:00:00"

    # When / Then the FX timestamp fails closed.
    _assert_invalid(payload, reason="invalid_timestamp", path="fx_snapshots[0].as_of")


def test_noncanonical_base_currency_is_rejected() -> None:
    # Given a valuation currency outside the canonical pt-v2.0 set.
    payload = _valid_payload()
    payload["base_currency"] = "EUR"

    # When / Then no mixed or unsupported valuation currency is accepted.
    _assert_invalid(payload, reason="invalid_base_currency", path="base_currency")


def test_explicit_orders_cannot_set_a_nonzero_rebalance_band() -> None:
    # Given an explicit-orders request with a planner-only nonzero band.
    payload = _valid_payload()
    payload["rebalance_band"] = "0.01"

    # When / Then the incompatible planner input is rejected.
    _assert_invalid(payload, reason="unexpected_rebalance_band", path="rebalance_band")


def test_packaged_contract_validates_the_three_market_request() -> None:
    # Given the independently authored three-market fixture and both contract copies.
    payload = _valid_payload()

    for contract_path in (CONTRACT_PATH, MIRROR_CONTRACT_PATH):
        document = json.loads(contract_path.read_text(encoding="utf-8"))
        request_schema = document["schemas"]["request"]
        Draft202012Validator.check_schema(request_schema)

        # When a real Draft 2020-12 validator checks formats and values.
        validator = Draft202012Validator(request_schema, format_checker=FormatChecker())
        errors = list(validator.iter_errors(payload))

        # Then no schema or format violation remains in either copy.
        assert errors == [], (contract_path, errors)


def test_packaged_contract_and_published_mirror_are_byte_identical() -> None:
    # Given the packaged loader path and independent repository mirror.
    packaged = CONTRACT_PATH.read_bytes()
    mirror = (
        Path(__file__).resolve().parents[2]
        / "schema"
        / "tool_contracts"
        / "paper_trade_step-v2.0.json"
    ).read_bytes()

    # When the loader resolves the request schema and hashes are computed.
    schema = load_portfolio_contract_schema("request")
    packaged_sha = hashlib.sha256(packaged).hexdigest()
    mirror_sha = hashlib.sha256(mirror).hexdigest()

    # Then packaging cannot drift from the published contract.
    assert schema["$id"].endswith("paper_trade_step-v2.0/request.json")
    assert packaged == mirror
    assert packaged_sha == mirror_sha


def test_contract_contains_discriminated_result_and_error_definitions() -> None:
    # Given the complete packaged contract document.
    document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    # When its three public-facing wire definitions are inspected.
    schemas = document["schemas"]
    result = schemas["result"]
    error = schemas["error_envelope"]

    # Then success/error status and the portfolio discriminator are explicit.
    assert set(schemas) == {"request", "result", "error_envelope"}
    assert result["properties"]["status"]["const"] == "success"
    assert result["properties"]["mode"]["const"] == "portfolio"
    assert error["properties"]["status"]["const"] == "error"
    assert error["properties"]["code"]["enum"] == [
        "INVALID_REQUEST",
        "PAPER_DATA_NOT_READY",
    ]
    for name in ("result", "error_envelope"):
        Draft202012Validator.check_schema(schemas[name])


def test_typed_success_result_round_trips_through_result_contract() -> None:
    # Given a parsed request and independent bucket-valued success outputs.
    request = parse_portfolio_request(_valid_payload())
    bucket_results = tuple(
        BucketResult(
            bucket_id=bucket.bucket_id,
            market=bucket.market,
            currency=bucket.currency,
            session=next(row for row in request.sessions if row.market == bucket.market),
            cash=bucket.cash,
            position_value="0",
            nav_base="0",
        )
        for bucket in request.portfolio_state.buckets
    )
    result = PortfolioResult(
        account_id=request.account_id,
        base_currency=request.base_currency,
        trade_date=request.trade_date,
        planning_at=request.planning_at,
        valuation_at=request.valuation_at,
        opening_portfolio=request.portfolio_state,
        post_conversion_portfolio=request.portfolio_state,
        end_portfolio=request.portfolio_state,
        sessions=request.sessions,
        conversions=request.fx_conversions,
        plan=request.plan,
        bucket_results=bucket_results,
        fills=(),
        rejected_orders=(),
        canceled_orders=(),
        warnings=(),
        errors=(),
        complete=True,
        hashes=PortfolioHashes(
            plan_hash="a" * 64,
            planning_data_hash="b" * 64,
            execution_data_fingerprint="c" * 64,
            document_hash="d" * 64,
        ),
    )

    # When the typed result is serialized and validated independently.
    document = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    schema = load_portfolio_contract_schema("result")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document))

    # Then the public-shaped result satisfies every result invariant.
    assert errors == []


def test_target_weights_default_rebalance_band_is_zero() -> None:
    # Given a target-weight request that omits the optional planner band.
    payload = _valid_payload()
    del payload["orders"]
    payload["target_weights"] = [
        {"bucket_id": "us", "symbol": "AAPL.US", "currency": "USD", "weight": "0.25"}
    ]

    # When the request is parsed into its discriminated plan.
    request = parse_portfolio_request(payload)

    # Then both the envelope and typed plan use the canonical zero default.
    assert request.rebalance_band == "0"
    assert request.plan.rebalance_band == "0"


@pytest.mark.parametrize("null_field", ["orders", "target_weights"])
def test_explicit_null_does_not_hide_a_supplied_plan_branch(null_field: str) -> None:
    # Given both plan keys in the wire payload, one with an explicit null value.
    payload = _valid_payload()
    payload["target_weights"] = [
        {"bucket_id": "us", "symbol": "AAPL.US", "currency": "USD", "weight": "0.25"}
    ]
    payload[null_field] = None

    # When / Then field presence cannot bypass the same XOR gate as the JSON contract.
    _assert_invalid(payload, reason="conflicting_order_plan", path="orders")


def test_typed_error_result_round_trips_through_error_contract() -> None:
    # Given a typed boundary error with stable machine-readable issue details.
    result = PortfolioErrorResult(
        account_id="portfolio-cross-market-01",
        code="INVALID_REQUEST",
        error=PortfolioIssue(
            reason="missing_mode",
            path="mode",
            detail="mode is required",
        ),
    )

    # When the typed error is serialized and validated independently.
    document = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    schema = load_portfolio_contract_schema("error_envelope")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document))

    # Then the public-shaped error satisfies every error-envelope invariant.
    assert document["status"] == "error"
    assert document["error"]["reason"] == "missing_mode"
    assert errors == []
