"""T11 — JCS frozen-vector tests for paper_trade state hashing (AM-4-2 / VD-4).

The vector file ``agent/tests/fixtures/paper_trade/jcs_vectors.json`` is the
SOLE cross-repo interpretation authority: the RM side asserts its own JCS
implementation against the same vectors.  Per the VD-14 re-baseline protocol
the vectors are immutable once RM adopts them — regeneration requires human
sign-off named in the commit message.

Also smoke-tests the finalized pt-v1.1 contract schema (VD-13 file +
dependency-free subset validator); the full T6 gate lives in
test_paper_trade_schema.py (Step 5).

Offline: no network, no clock, no writes.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.tools.paper_trade.schema import (
    ERROR_CODES,
    REASON_CODES,
    SKIPPED_DAY_REASONS,
    load_contract_schema,
    validate_payload,
)
from src.tools.paper_trade.state_hash import (
    canonicalize,
    compute_received_state_hash,
    effective_fee_model,
    state_hash,
)

_VECTORS_PATH = Path(__file__).parent / "fixtures" / "paper_trade" / "jcs_vectors.json"


def _load_vectors() -> list[dict]:
    document = json.loads(_VECTORS_PATH.read_text(encoding="utf-8"))
    vectors = document["vectors"]
    assert vectors, "frozen vector file must not be empty"
    return vectors


_VECTORS = _load_vectors()
_BY_NAME = {vector["name"]: vector for vector in _VECTORS}
_VECTOR_IDS = [vector["name"] for vector in _VECTORS]


# ── Frozen vectors: canonical form AND hash, per vector ──


@pytest.mark.parametrize("vector", _VECTORS, ids=_VECTOR_IDS)
def test_canonical_form_matches_frozen_vector(vector: dict) -> None:
    assert canonicalize(vector["input"]) == vector["canonical"]


@pytest.mark.parametrize("vector", _VECTORS, ids=_VECTOR_IDS)
def test_state_hash_matches_frozen_vector(vector: dict) -> None:
    assert state_hash(vector["input"]) == vector["sha256"]


def test_vector_file_pins_sha256_of_canonical_string() -> None:
    """The stored digest must be sha256 of the stored canonical bytes.

    Guards the artifact itself: a vector whose sha was not derived from its
    canonical string would silently desynchronize VT and RM.
    """
    import hashlib

    for vector in _VECTORS:
        expected = hashlib.sha256(vector["canonical"].encode("utf-8")).hexdigest()
        assert vector["sha256"] == expected, vector["name"]


# ── T11 semantic assertions (the vector-independent half of the gate) ──


def test_key_order_shuffle_is_invariant() -> None:
    a = {"market": "cn_a", "account_id": "pa_01", "cash": 1000.5}
    b = {"cash": 1000.5, "account_id": "pa_01", "market": "cn_a"}
    c = {"account_id": "pa_01", "market": "cn_a", "cash": 1000.5}
    assert canonicalize(a) == canonicalize(b) == canonicalize(c)
    assert state_hash(a) == state_hash(b) == _BY_NAME["key_order_shuffle_a"]["sha256"]


def test_integral_float_and_int_are_equivalent() -> None:
    # 100000.0 ≡ 100000 — the headline JCS number rule (AM-4-1).
    assert canonicalize({"qty": 100000.0}) == canonicalize({"qty": 100000}) == '{"qty":100000}'
    assert _BY_NAME["float_int_equiv_float"]["sha256"] == _BY_NAME["float_int_equiv_int"]["sha256"]


def test_large_and_exponent_forms_follow_ecmascript() -> None:
    assert canonicalize(1e16) == "10000000000000000"  # n=17 ≤ 21: plain form
    assert canonicalize(1.2345678901234567e20) == "123456789012345670000"  # n=21 boundary
    assert canonicalize(1e21) == "1e+21"  # n=22: exponential
    assert canonicalize(-1e21) == "-1e+21"
    assert canonicalize(1e-6) == "0.000001"  # n=-5 > -6: plain form
    assert canonicalize(1.5e-7) == "1.5e-7"  # n=-6: exponential


def test_negative_zero_canonicalizes_to_positive_zero() -> None:
    assert canonicalize(-0.0) == "0"
    assert canonicalize({"x": -0.0}) == canonicalize({"x": 0.0}) == canonicalize({"x": 0})


def test_shortest_round_trip_repr_is_used() -> None:
    # The classic float artifact: shortest digits that round-trip.
    assert canonicalize(0.1 + 0.2) == "0.30000000000000004"
    assert canonicalize(0.3) == "0.3"


def test_unicode_symbols_stay_raw_utf8() -> None:
    text = canonicalize({"symbol": "600519.SH", "name": "贵州茅台", "note": "naïve café — ✓"})
    assert "贵州茅台" in text  # ensure_ascii=False: no \uXXXX escaping for BMP text
    assert "\\u" not in text


def test_empty_positions_canonical_form() -> None:
    assert canonicalize({"cash": 100000.0, "positions": []}) == '{"cash":100000,"positions":[]}'


def test_array_order_is_semantic() -> None:
    ab = _BY_NAME["array_order_ab"]["input"]
    ba = _BY_NAME["array_order_ba"]["input"]
    assert canonicalize(ab) != canonicalize(ba)
    assert state_hash(ab) != state_hash(ba)
    # Same element set — only the order differs, and order is part of the hash.
    assert sorted(ab["positions"], key=lambda p: p["symbol"]) == sorted(
        ba["positions"], key=lambda p: p["symbol"]
    )


def test_json_base_tokens() -> None:
    assert canonicalize(True) == "true"
    assert canonicalize(False) == "false"
    assert canonicalize(None) == "null"
    assert canonicalize({"flag": True}) == '{"flag":true}'  # bool is NOT int 1


def test_non_json_types_fail_closed() -> None:
    with pytest.raises(TypeError):
        canonicalize(Decimal("1.5"))  # Decimal must be converted by the caller (VD-9)
    with pytest.raises(TypeError):
        canonicalize({1: "int key"})  # JSON object keys must be str
    with pytest.raises(TypeError):
        canonicalize(object())


def test_non_finite_floats_fail_closed() -> None:
    with pytest.raises(ValueError):
        canonicalize(float("nan"))
    with pytest.raises(ValueError):
        canonicalize(float("inf"))


def test_canonicalization_is_deterministic_across_calls() -> None:
    payload = _BY_NAME["am4_hash_coverage_object"]["input"]
    assert canonicalize(payload) == canonicalize(payload)
    assert state_hash(payload) == state_hash(payload)


# ── AM-4 coverage object + effective_fee_model echo ──


def test_received_state_hash_covers_the_frozen_am4_object() -> None:
    account_state = {"cash": 98213.44, "positions": [{"symbol": "600519.SH", "qty": 100, "avg_cost": 1418.0}]}
    fee_model = {
        "commission_rate": 0.00025,
        "commission_min": 5.0,
        "stamp_tax_sell": 0.0005,
        "transfer_fee": 0.00001,
    }
    computed = compute_received_state_hash(
        account_id="pa_deadbeefdeadbeefdeadbeef",
        market="cn_a",
        account_state=account_state,
        fee_model=fee_model,
        from_date="2026-10-20",
        to_date="2026-10-20",
    )
    # Identical to hashing the frozen coverage object by hand (AM-4-1).
    manual = state_hash(
        {
            "account_id": "pa_deadbeefdeadbeefdeadbeef",
            "market": "cn_a",
            "account_state": account_state,
            "fee_model": fee_model,
            "from_date": "2026-10-20",
            "to_date": "2026-10-20",
        }
    )
    assert computed == manual == _BY_NAME["am4_hash_coverage_object"]["sha256"]


def test_effective_fee_model_echoes_cn_a_defaults() -> None:
    # FROZEN terminal values (G1 approved 2026-10-19): REQUIREMENTS §4 matrix,
    # cn_a key names verbatim per AMENDMENT §2.2 / APPROVAL note 5.  Any
    # change = major schema bump with RM written confirmation.
    assert effective_fee_model("cn_a") == {
        "commission_rate": 0.00025,
        "commission_min": 5.0,
        "stamp_tax_sell": 0.0005,
        "transfer_fee": 0.00001,
    }


def test_effective_fee_model_echoes_hk_defaults() -> None:
    # FROZEN terminal values (APPROVAL note 5): hk key names mapped
    # item-by-item to the §4 matrix — commission 0.03% min HK$3, stamp duty
    # 0.1% per side (whole HKD ROUND_HALF_UP, VD-9 registered), regulatory
    # levy ≈0.003% combined.
    assert effective_fee_model("hk") == {
        "commission_rate": 0.0003,
        "commission_min": 3.0,
        "stamp_tax_rate": 0.001,
        "regulatory_levy_rate": 0.00003,
    }


def test_effective_fee_model_echoes_us_defaults() -> None:
    # FROZEN terminal values (APPROVAL note 5): us key names mapped to the
    # §4 matrix — $0.0049/share min $0.99, SEC fee simplified to 0 (VD-9
    # registered).
    assert effective_fee_model("us") == {
        "commission_per_share": 0.0049,
        "commission_min": 0.99,
        "sec_fee_rate": 0.0,
    }


def test_effective_fee_model_merges_overrides_per_key() -> None:
    merged = effective_fee_model("cn_a", {"commission_rate": 0.0003, "custom_key": 1.5})
    assert merged["commission_rate"] == 0.0003  # overridden
    assert merged["commission_min"] == 5.0  # default kept
    assert merged["custom_key"] == 1.5  # caller keys pass through


def test_effective_fee_model_unknown_market_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown market"):
        effective_fee_model("crypto")


# ── Contract-schema skeleton smoke (full T6 lands in Step 5) ──


_MINIMAL_RESULT = {
    "schema_version": "pt-v1.1",
    "tool": "paper_trade_step",
    "account_id": "pa_01",
    "market": "cn_a",
    "range": {"from": "2026-10-20", "to": "2026-10-20"},
    "received_state_hash": "0" * 64,
    "effective_fee_model": {"commission_rate": 0.00025},
    "fills": [],
    "rejected_orders": [],
    "end_state": {"cash": 100000.0, "positions": []},
    "nav_series": [
        {"date": "2026-10-20", "nav": 100000.0, "cash": 100000.0, "position_value": 0.0}
    ],
    "skipped_days": [],
    "warnings": [],
    "data_provenance": {"source": "clickhouse+tencent(merged)"},
}


class TestContractSchemaSkeleton:
    def test_named_schemas_load(self) -> None:
        result_schema = load_contract_schema("result")
        envelope_schema = load_contract_schema("error_envelope")
        assert result_schema["type"] == "object"
        assert "received_state_hash" in result_schema["properties"]
        assert "effective_fee_model" in result_schema["properties"]
        assert envelope_schema["properties"]["status"]["const"] == "error"

    def test_unknown_schema_name_fails_closed(self) -> None:
        with pytest.raises(KeyError):
            load_contract_schema("request")

    def test_minimal_result_payload_validates(self) -> None:
        assert validate_payload(_MINIMAL_RESULT, load_contract_schema("result")) == []

    def test_validator_reports_missing_wrong_and_extra(self) -> None:
        payload = dict(_MINIMAL_RESULT)
        del payload["tool"]
        payload["market"] = "crypto"
        payload["unexpected"] = 1
        payload["rejected_orders"] = [
            {
                "trade_date": "2026-10-20",
                "symbol": "600519.SH",
                "side": "buy",
                "qty": 100,
                "reason_code": "not_in_vocabulary",
                "detail": "",
            }
        ]
        errors = validate_payload(payload, load_contract_schema("result"))
        joined = "\n".join(errors)
        assert "missing required property 'tool'" in joined
        assert "not in enum" in joined  # market
        assert "additional property 'unexpected'" in joined
        assert "not_in_vocabulary" in joined  # reason_code enum

    def test_error_envelope_validates(self) -> None:
        envelope = {
            "status": "error",
            "code": "PAPER_DATA_NOT_READY",
            "account_id": "pa_01",
            "market": "cn_a",
            "range": {"from": "2026-10-20", "to": "2026-10-20"},
            "received_state_hash": "0" * 64,
            "message": "target bar 2026-10-20 not available from served sources",
        }
        assert validate_payload(envelope, load_contract_schema("error_envelope")) == []
        bad = dict(envelope, code="SOMETHING_ELSE")
        assert validate_payload(bad, load_contract_schema("error_envelope")) != []

    def test_vocabularies_are_closed_and_consistent_with_schema_file(self) -> None:
        # AM-14: 11 reason_code + 2 skipped reason + 2 error code — the
        # schema.py tuples and the jsonschema enums must agree exactly.
        assert (len(REASON_CODES), len(SKIPPED_DAY_REASONS), len(ERROR_CODES)) == (11, 2, 2)
        result_schema = load_contract_schema("result")
        reason_enum = result_schema["properties"]["rejected_orders"]["items"]["properties"][
            "reason_code"
        ]["enum"]
        skipped_enum = result_schema["properties"]["skipped_days"]["items"]["properties"]["reason"][
            "enum"
        ]
        code_enum = load_contract_schema("error_envelope")["properties"]["code"]["enum"]
        assert tuple(reason_enum) == REASON_CODES
        assert tuple(skipped_enum) == SKIPPED_DAY_REASONS
        assert tuple(code_enum) == ERROR_CODES
