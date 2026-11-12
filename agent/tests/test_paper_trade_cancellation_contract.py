"""Version closure and coverage for the additive paper cancellation contract."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.tools.paper_trade import schema, wire
from tests.test_paper_trade_cancellation import _cancel, _payload, _run

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGED = _ROOT / "agent/src/tools/paper_trade/paper_trade_step-v1.4.json"
_MIRROR = _ROOT / "schema/tool_contracts/paper_trade_step-v1.4.json"


def _contract():
    assert _PACKAGED.is_file(), "the selected v1.4 version must ship its contract"
    return schema.load_contract_schema(version="pt-v1.4")


def test_new_contract_has_a_byte_identical_published_mirror():
    assert _PACKAGED.is_file() and _MIRROR.is_file()
    assert _PACKAGED.read_bytes() == _MIRROR.read_bytes()
    assert "pt-v1.4" in schema.SCHEMA_VERSIONS
    assert _contract()["properties"]["schema_version"]["const"] == "pt-v1.4"


def test_actual_cancel_document_closes_against_the_new_schema():
    document, _ = _run(_payload(cancel_schedule=[_cancel()]))
    assert schema.validate_payload(document, _contract()) == []
    for key in ("cancel_results", "order_states", "engine_fingerprint"):
        missing = copy.deepcopy(document)
        del missing[key]
        errors = schema.validate_payload(missing, _contract())
        assert any(
            f"'{key}'" in error and "missing" in error for error in errors
        ), errors


@pytest.mark.parametrize("key", ["fills", "rejected_orders", "canceled_orders"])
def test_new_version_requires_ids_on_each_result_row(key):
    document, _ = _run(_payload(cancel_schedule=[_cancel()]))
    if key == "rejected_orders":
        payload = _payload(account_state={"cash": 0, "positions": []})
        document, _ = _run(payload)
    assert document[key], key
    assert schema.validate_payload(document, _contract()) == []
    del document[key][0]["order_id"]
    errors = schema.validate_payload(document, _contract())
    assert any("order_id" in error and "missing" in error for error in errors), errors


def test_success_and_error_paths_use_the_same_schedule_coverage():
    payload = _payload(cancel_schedule=[_cancel()])
    document, _ = _run(payload)
    assert (
        wire.received_state_hash_from_payload(payload)
        == document["received_state_hash"]
    )
    bad_orders = copy.deepcopy(payload)
    bad_orders["orders"].append(dict(bad_orders["orders"][0]))
    error, loader = _run(bad_orders)
    assert error["code"] == "INVALID_REQUEST"
    assert loader.calls == []
    assert error["received_state_hash"] == document["received_state_hash"]
    assert "schema_version" not in error
    assert (
        schema.validate_payload(
            error, schema.load_contract_schema("error_envelope", version="pt-v1.4")
        )
        == []
    )


def test_invalid_schedule_cannot_claim_a_computable_error_hash():
    document, _ = _run(
        _payload(cancel_schedule=[{"order_id": "alpha", "at": "not a time"}])
    )
    assert document["code"] == "INVALID_REQUEST"
    assert "received_state_hash" not in document


def test_explicit_empty_schedule_is_distinct_from_the_legacy_model():
    payload = _payload()
    del payload["orders"][0]["order_id"]
    legacy, _ = _run(payload)
    selected, _ = _run({**payload, "cancel_schedule": []})
    assert selected["schema_version"] == "pt-v1.4"
    assert selected["cancel_results"] == []
    assert selected["received_state_hash"] != legacy["received_state_hash"]
    assert selected["engine_fingerprint"] != legacy["engine_fingerprint"]
    assert schema.validate_payload(selected, _contract()) == []


def test_all_or_none_and_cash_only_calls_still_expose_v14_lifecycle_rows():
    payload = _payload(fill_model="all_or_none", cancel_schedule=[_cancel("09:35")])
    del payload["order_volume_ratio"]
    document, _ = _run(payload)
    assert document["schema_version"] == "pt-v1.4"
    assert document["order_states"][0]["status"] == "canceled"
    assert schema.validate_payload(document, _contract()) == []
    empty, _ = _run({**payload, "orders": [], "cancel_schedule": []})
    assert empty["cancel_results"] == empty["order_states"] == []
    assert schema.validate_payload(empty, _contract()) == []


def test_identical_new_requests_are_byte_deterministic():
    payload = _payload(cancel_schedule=[_cancel(), _cancel("09:45")])
    first, _ = _run(payload)
    second, _ = _run(copy.deepcopy(payload))
    assert wire.dumps_payload(first) == wire.dumps_payload(second)
