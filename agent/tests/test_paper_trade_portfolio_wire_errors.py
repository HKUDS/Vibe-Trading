"""Public pt-v2.0 portfolio wire error envelopes and raw-input hash identity.

Every in-band error validates against the packaged ``error_envelope`` schema,
echoes a deterministic hash of the raw request, and never fabricates a ledger
or fills; INTERNAL faults stay transport-level PortfolioWireError raises.
"""

from __future__ import annotations

import hashlib
import json
import math

import pytest

from src.tools.paper_trade import engine
from src.tools.paper_trade.portfolio.orchestrator import OrchestrationError
from src.tools.paper_trade.portfolio.schema import PortfolioRequestError
from src.tools.paper_trade.portfolio.sessions import PortfolioSessionError
from src.tools.paper_trade.portfolio.wire import (
    INPUT_HASH_MARKER,
    PortfolioWireError,
    build_error_from_exception,
    build_error_payload,
    compute_raw_input_hash,
    error_code_for_exception,
    serialize_error,
)
from tests.paper_trade_portfolio_wire_helpers import (
    _explicit_payload,
    _run,
    _scan_numeric_types,
    _validate,
)


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
