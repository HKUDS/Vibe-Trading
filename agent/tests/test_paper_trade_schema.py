"""T6 gate — pt-v1.1 wire-contract schema validation (Step 5 / T5).

Validates the ACTUAL wire documents the Step 5 builders produce (success and
AM-5 error envelope) through the existing dependency-free validator against
the finalized ``schema/tool_contracts/paper_trade_step-v1.1.json``, and pins
the frozen surfaces: ``schema_version``/``account_id`` verbatim echoes, the
closed 11+2+2 vocabularies (every member accepted, a non-member rejected),
the three-market ``effective_fee_model`` key sets (APPROVAL note 5), the
``fills[].reason`` dual mode (VD-15/B2), and the AM-4-4 rule that the error
envelope carries ``received_state_hash`` only when the state is parseable.

Offline: no network, no clock, no writes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tools.paper_trade import wire
from src.tools.paper_trade.schema import (
    ERROR_CODES,
    MARKETS,
    REASON_CODES,
    SCHEMA_VERSION,
    SIDES,
    SKIPPED_DAY_REASONS,
    TOOL_NAME,
    AccountState,
    DataProvenance,
    DateRange,
    ErrorEnvelope,
    Fill,
    NavPoint,
    PaperTradeSchemaError,
    PaperTradeStepResult,
    Position,
    RejectedOrder,
    SkippedDay,
    load_contract_schema,
    parse_account_state,
    parse_request,
    validate_payload,
)
from src.tools.paper_trade.state_hash import effective_fee_model, state_hash

_GOLDEN_DIR = Path(__file__).parent / "fixtures" / "paper_trade" / "golden"

# §4 terminal default key sets, frozen per APPROVAL note 5 (delivery note #7).
_FROZEN_FEE_KEYS = {
    "cn_a": {
        "commission_rate": 0.00025,
        "commission_min": 5.0,
        "stamp_tax_sell": 0.0005,
        "transfer_fee": 0.00001,
    },
    "hk": {
        "commission_rate": 0.0003,
        "commission_min": 3.0,
        "stamp_tax_rate": 0.001,
        "regulatory_levy_rate": 0.00003,
    },
    "us": {
        "commission_per_share": 0.0049,
        "commission_min": 0.99,
        "sec_fee_rate": 0.0,
    },
}


def _rich_result(**overrides) -> PaperTradeStepResult:
    """A semantically coherent cn_a strategy_path-shaped document exercising
    every success-schema field (multi-day range with a weekend skip)."""
    fields: dict = dict(
        account_id="pa_schema-echo_01",
        market="cn_a",
        range=DateRange(from_="2026-10-17", to="2026-10-20"),
        received_state_hash="0" * 64,
        effective_fee_model=dict(_FROZEN_FEE_KEYS["cn_a"]),
        fills=(
            Fill(trade_date="2026-10-20", symbol="600519.SH", side="buy",
                 qty=100.0, price=1421.0, fee=36.95, reason=""),
        ),
        rejected_orders=(
            RejectedOrder(trade_date="2026-10-20", symbol="000001.SZ", side="sell",
                          qty=200.0, reason_code="insufficient_position",
                          detail="sell qty 200.0 exceeds position 0.0"),
        ),
        end_state=AccountState(
            cash=57863.05,
            positions=(Position(symbol="600519.SH", qty=100.0, avg_cost=1421.0),),
        ),
        nav_series=(
            NavPoint(date="2026-10-20", nav=199963.05, cash=57863.05,
                     position_value=142100.0),
        ),
        skipped_days=(
            SkippedDay(date="2026-10-17", reason="non_trading_day"),
            SkippedDay(date="2026-10-18", reason="non_trading_day"),
        ),
        warnings=("valuation: 000001.SZ has no usable close; position valued at avg_cost",),
        data_provenance=DataProvenance(
            source="clickhouse+tencent(merged)",
            bars_as_of="2026-10-20",
            ch_as_of="2026-10-19",
            network_as_of="2026-10-20",
            limit_provenance=("600519.SH@2026-10-20:limits:heuristic",),
        ),
    )
    fields.update(overrides)
    return PaperTradeStepResult(**fields)


def _rich_payload(**overrides) -> dict:
    return wire.build_success_payload(_rich_result(**overrides))


def _envelope(**overrides) -> ErrorEnvelope:
    fields: dict = dict(
        code="PAPER_DATA_NOT_READY",
        account_id="pa_schema-echo_01",
        market="cn_a",
        range=DateRange(from_="2026-10-20", to="2026-10-20"),
        message="target bar 2026-10-20 not available from served sources",
        received_state_hash="0" * 64,
    )
    fields.update(overrides)
    return ErrorEnvelope(**fields)


# ── Success document validates through the finalized contract schema ──


def test_rich_success_payload_validates() -> None:
    assert validate_payload(_rich_payload(), load_contract_schema("result")) == []


def test_corporate_actions_provenance_entry_validates() -> None:
    payload = _rich_payload(
        market="hk",
        effective_fee_model=dict(_FROZEN_FEE_KEYS["hk"]),
        data_provenance=DataProvenance(
            source="tencent",
            bars_as_of="2026-10-16",
            network_as_of="2026-10-16",
            corporate_actions=(
                {"symbol": "00700.HK", "date": "2026-10-16", "ratio": "4:1",
                 "detected": True},
                {"symbol": "9988.HK", "date": "2026-10-16", "ratio": "0.2531",
                 "detected": False},
            ),
        ),
    )
    assert validate_payload(payload, load_contract_schema("result")) == []


@pytest.mark.parametrize("golden", sorted(p.name for p in _GOLDEN_DIR.glob("*_orders_*.json")))
def test_frozen_goldens_validate_against_the_result_schema(golden: str) -> None:
    document = json.loads((_GOLDEN_DIR / golden).read_bytes())
    assert validate_payload(document, load_contract_schema("result")) == []


# ── Verbatim echoes + wire key spelling ──


def test_schema_version_and_tool_are_the_frozen_literals() -> None:
    payload = _rich_payload()
    assert payload["schema_version"] == SCHEMA_VERSION == "pt-v1.1"
    assert payload["tool"] == TOOL_NAME == "paper_trade_step"


def test_account_id_is_echoed_verbatim() -> None:
    payload = _rich_payload(account_id="pa_verbatim-echo_42")
    assert payload["account_id"] == "pa_verbatim-echo_42"
    envelope_payload = wire.build_error_payload(
        _envelope(account_id="pa_verbatim-echo_42"))
    assert envelope_payload["account_id"] == "pa_verbatim-echo_42"


def test_range_uses_the_wire_key_from_not_the_dataclass_spelling() -> None:
    payload = _rich_payload()
    assert payload["range"] == {"from": "2026-10-17", "to": "2026-10-20"}
    assert "from_" not in json.dumps(payload)


# ── Closed vocabularies: 11 + 2 + 2, both directions ──


def test_vocabulary_sizes_are_frozen_at_11_2_2() -> None:
    assert (len(REASON_CODES), len(SKIPPED_DAY_REASONS), len(ERROR_CODES)) == (11, 2, 2)
    assert MARKETS == ("cn_a", "hk", "us")
    assert SIDES == ("buy", "sell")


@pytest.mark.parametrize("code", REASON_CODES)
def test_every_frozen_reason_code_is_accepted(code: str) -> None:
    rejected = RejectedOrder(trade_date="2026-10-20", symbol="600519.SH", side="buy",
                             qty=100.0, reason_code=code, detail="")
    payload = _rich_payload(rejected_orders=(rejected,))
    assert validate_payload(payload, load_contract_schema("result")) == []


@pytest.mark.parametrize("reason", SKIPPED_DAY_REASONS)
def test_every_frozen_skipped_reason_is_accepted(reason: str) -> None:
    payload = _rich_payload(skipped_days=(SkippedDay(date="2026-10-17", reason=reason),))
    assert validate_payload(payload, load_contract_schema("result")) == []


@pytest.mark.parametrize("code", ERROR_CODES)
def test_every_frozen_error_code_is_accepted(code: str) -> None:
    payload = wire.build_error_payload(_envelope(code=code))
    assert validate_payload(payload, load_contract_schema("error_envelope")) == []


def test_out_of_vocabulary_values_are_rejected() -> None:
    result_schema = load_contract_schema("result")
    bad_reason = _rich_payload(rejected_orders=(
        RejectedOrder(trade_date="2026-10-20", symbol="600519.SH", side="buy",
                      qty=100.0, reason_code="not_in_vocabulary", detail=""),))
    assert any("not_in_vocabulary" in e for e in validate_payload(bad_reason, result_schema))
    bad_skipped = _rich_payload(skipped_days=(SkippedDay(date="2026-10-17", reason="holiday"),))
    assert any("holiday" in e for e in validate_payload(bad_skipped, result_schema))
    bad_market = _rich_payload(market="crypto")
    assert any("crypto" in e for e in validate_payload(bad_market, result_schema))
    bad_side = _rich_payload(fills=(
        Fill(trade_date="2026-10-20", symbol="600519.SH", side="hold",
             qty=100.0, price=1421.0, fee=36.95, reason=""),))
    assert any("hold" in e for e in validate_payload(bad_side, result_schema))


def test_schema_rejects_wrong_version_missing_field_and_extra_field() -> None:
    result_schema = load_contract_schema("result")
    wrong_version = _rich_payload()
    wrong_version["schema_version"] = "pt-v1.0"
    assert any("const" in e for e in validate_payload(wrong_version, result_schema))
    missing = _rich_payload()
    del missing["received_state_hash"]
    assert any("received_state_hash" in e for e in validate_payload(missing, result_schema))
    extra = _rich_payload()
    extra["unexpected"] = 1
    assert any("unexpected" in e for e in validate_payload(extra, result_schema))
    extra_prov = _rich_payload()
    extra_prov["data_provenance"]["merge_state"] = "x"
    assert any("merge_state" in e for e in validate_payload(extra_prov, result_schema))


# ── effective_fee_model: three-market key echo (APPROVAL note 5) ──


@pytest.mark.parametrize("market", sorted(_FROZEN_FEE_KEYS))
def test_effective_fee_model_echoes_the_frozen_market_key_set(market: str) -> None:
    assert effective_fee_model(market) == _FROZEN_FEE_KEYS[market]
    payload = _rich_payload(
        market=market, effective_fee_model=dict(effective_fee_model(market)))
    assert payload["effective_fee_model"] == _FROZEN_FEE_KEYS[market]
    assert validate_payload(payload, load_contract_schema("result")) == []


def test_injected_fee_overrides_echo_in_full() -> None:
    merged = effective_fee_model("cn_a", {"commission_rate": 0.0003, "custom_key": 1.5})
    payload = _rich_payload(effective_fee_model=merged)
    assert payload["effective_fee_model"]["commission_rate"] == 0.0003
    assert payload["effective_fee_model"]["commission_min"] == 5.0
    assert payload["effective_fee_model"]["custom_key"] == 1.5


# ── fills[].reason dual mode (VD-15/B2) ──


def test_orders_mode_reason_is_the_empty_string() -> None:
    assert wire.ORDERS_FILL_REASON == ""
    payload = _rich_payload()
    assert payload["fills"][0]["reason"] == ""


def test_strategy_reason_at_the_boundary_is_kept_whole() -> None:
    exact = "a" * wire.FILL_REASON_MAX_CHARS
    assert wire.strategy_fill_reason(exact) == exact
    assert len(wire.strategy_fill_reason(exact + "b")) == wire.FILL_REASON_MAX_CHARS
    assert wire.strategy_fill_reason(exact + "b") == exact


def test_strategy_reason_truncation_never_splits_multibyte_characters() -> None:
    cjk = "贵" * (wire.FILL_REASON_MAX_CHARS + 5)
    truncated = wire.strategy_fill_reason(cjk)
    assert len(truncated) == wire.FILL_REASON_MAX_CHARS
    assert truncated == "贵" * wire.FILL_REASON_MAX_CHARS
    assert truncated.encode("utf-8").decode("utf-8") == truncated
    emoji = "👍" * (wire.FILL_REASON_MAX_CHARS + 1)
    assert wire.strategy_fill_reason(emoji) == "👍" * wire.FILL_REASON_MAX_CHARS
    mixed = "a" * (wire.FILL_REASON_MAX_CHARS - 1) + "€" + "tail"
    assert wire.strategy_fill_reason(mixed) == "a" * (wire.FILL_REASON_MAX_CHARS - 1) + "€"


def test_strategy_reason_none_maps_to_empty_and_non_str_fails_closed() -> None:
    assert wire.strategy_fill_reason(None) == ""
    with pytest.raises(TypeError):
        wire.strategy_fill_reason(123)  # type: ignore[arg-type]


# ── AM-5 error envelope ──


def test_error_envelope_validates_with_and_without_the_state_hash() -> None:
    schema = load_contract_schema("error_envelope")
    with_hash = wire.build_error_payload(_envelope())
    assert validate_payload(with_hash, schema) == []
    assert with_hash["received_state_hash"] == "0" * 64
    without = wire.build_error_payload(_envelope(received_state_hash=None))
    assert validate_payload(without, schema) == []
    assert "received_state_hash" not in without  # AM-4-4: omitted, never null
    assert without["status"] == "error"
    assert without["range"] == {"from": "2026-10-20", "to": "2026-10-20"}


def test_error_envelope_field_set_is_exactly_the_frozen_am5_set() -> None:
    assert set(wire.build_error_payload(_envelope())) == {
        "status", "code", "account_id", "market", "range", "message",
        "received_state_hash",
    }
    assert set(wire.build_error_payload(_envelope(received_state_hash=None))) == {
        "status", "code", "account_id", "market", "range", "message",
    }


def test_unknown_error_code_and_status_fail_closed_before_serialization() -> None:
    with pytest.raises(ValueError, match="frozen AM-5 vocabulary"):
        wire.build_error_payload(_envelope(code="SOMETHING_ELSE"))
    with pytest.raises(ValueError, match="status"):
        wire.build_error_payload(_envelope(status="ok"))
    bad = wire.build_error_payload(_envelope())
    bad["code"] = "SOMETHING_ELSE"
    assert validate_payload(bad, load_contract_schema("error_envelope")) != []
    bad_status = wire.build_error_payload(_envelope())
    bad_status["status"] = "ok"
    assert any("const" in e
               for e in validate_payload(bad_status, load_contract_schema("error_envelope")))


# ── AM-4-4: received_state_hash_from_payload presence rules ──


def _parseable_payload() -> dict:
    return {
        "account_id": "pa_hash_01",
        "market": "cn_a",
        "account_state": {"cash": 98213.44,
                          "positions": [{"symbol": "600519.SH", "qty": 100, "avg_cost": 1418.0}]},
        "orders": [{"symbol": "600519.SH", "side": "buy", "qty": 100}],
        "from_date": "2026-10-20",
        "to_date": "2026-10-20",
        "fee_model": dict(_FROZEN_FEE_KEYS["cn_a"]),
    }


def test_hash_is_present_and_manual_when_the_state_is_parseable() -> None:
    payload = _parseable_payload()
    computed = wire.received_state_hash_from_payload(payload)
    manual = state_hash({
        "account_id": payload["account_id"],
        "market": payload["market"],
        "account_state": payload["account_state"],
        "fee_model": effective_fee_model("cn_a", payload["fee_model"]),
        "from_date": payload["from_date"],
        "to_date": payload["to_date"],
    })
    assert computed == manual
    assert computed is not None and len(computed) == 64


def test_hash_covers_the_raw_state_so_extra_keys_change_it() -> None:
    payload = _parseable_payload()
    baseline = wire.received_state_hash_from_payload(payload)
    corrupted = _parseable_payload()
    corrupted["account_state"]["positions"][0]["qty"] = 101
    assert wire.received_state_hash_from_payload(corrupted) != baseline
    enriched = _parseable_payload()
    enriched["account_state"]["note"] = "llm-added key"
    assert wire.received_state_hash_from_payload(enriched) != baseline
    # int/float spelling is JCS-equivalent: 100 vs 100.0 must NOT change it.
    respelled = _parseable_payload()
    respelled["account_state"]["cash"] = 98213.44
    respelled["account_state"]["positions"][0]["qty"] = 100.0
    assert wire.received_state_hash_from_payload(respelled) == baseline


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(account_state={"cash": "abc", "positions": []}),
    lambda p: p.pop("account_state"),
    lambda p: p.update(market="crypto"),
    lambda p: p.pop("market"),
    lambda p: p.update(account_id=42),
    lambda p: p.pop("from_date"),
    lambda p: p.update(fee_model=["not", "a", "dict"]),
    lambda p: p.update(fee_model={"commission_rate": "0.00025"}),
])
def test_hash_is_absent_when_the_coverage_object_is_not_computable(mutate) -> None:
    payload = _parseable_payload()
    mutate(payload)
    assert wire.received_state_hash_from_payload(payload) is None


def test_hash_is_absent_for_non_dict_payloads() -> None:
    assert wire.received_state_hash_from_payload(None) is None
    assert wire.received_state_hash_from_payload("account_state") is None
    assert wire.received_state_hash_from_payload([]) is None


# ── AM-4-4 malformed-input boundary: falsy/non-finite never hash, never raise ──


@pytest.mark.parametrize("falsy", [[], "", False, 0, 0.0])
def test_falsy_non_dict_fee_model_is_malformed_not_absent(falsy) -> None:
    # A PRESENT falsy fee_model is a corrupted injection, not an omission:
    # `or {}` laundering it into the defaults would hash a coverage object
    # RM never injected (the exact divergence AM-4 exists to catch).
    payload = _parseable_payload()
    payload["fee_model"] = falsy
    assert wire.received_state_hash_from_payload(payload) is None


def test_missing_none_or_empty_fee_model_hashes_with_market_defaults() -> None:
    baseline = wire.received_state_hash_from_payload(_parseable_payload())
    missing = _parseable_payload()
    del missing["fee_model"]
    nulled = _parseable_payload()
    nulled["fee_model"] = None
    emptied = _parseable_payload()
    emptied["fee_model"] = {}
    hashes = {
        wire.received_state_hash_from_payload(variant)
        for variant in (missing, nulled, emptied)
    }
    assert hashes == {baseline}
    assert baseline is not None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10**400])
def test_non_representable_fee_values_are_not_computable(value) -> None:
    payload = _parseable_payload()
    payload["fee_model"] = {"commission_rate": value}
    assert wire.received_state_hash_from_payload(payload) is None


@pytest.mark.parametrize("cash", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_account_state_is_not_computable(cash: float) -> None:
    payload = _parseable_payload()
    payload["account_state"] = {"cash": cash, "positions": []}
    assert wire.received_state_hash_from_payload(payload) is None


def test_non_finite_position_number_is_not_computable() -> None:
    payload = _parseable_payload()
    payload["account_state"] = {
        "cash": 1000.0,
        "positions": [{"symbol": "600519.SH", "qty": float("nan"), "avg_cost": 1418.0}],
    }
    assert wire.received_state_hash_from_payload(payload) is None


def test_raw_state_that_shape_parses_but_cannot_canonicalize_is_not_computable() -> None:
    # The shape parser reads cash/positions only; a non-str key elsewhere in
    # the raw state (TypeError in JCS) or a non-finite extra value
    # (ValueError in JCS) must land as None, never raise out of the error path.
    keyed = _parseable_payload()
    keyed["account_state"] = {"cash": 1000.0, "positions": [], 1: "non-string key"}
    assert wire.received_state_hash_from_payload(keyed) is None
    valued = _parseable_payload()
    valued["account_state"] = {"cash": 1000.0, "positions": [], "note": float("nan")}
    assert wire.received_state_hash_from_payload(valued) is None


@pytest.mark.parametrize("falsy", [[], "", False, 0])
def test_parse_request_rejects_falsy_non_dict_fee_model(falsy) -> None:
    payload = _parseable_payload()
    payload["fee_model"] = falsy
    with pytest.raises(PaperTradeSchemaError, match="fee_model must be an object"):
        parse_request(payload)


@pytest.mark.parametrize("absent", ["missing", "none", "empty"])
def test_parse_request_accepts_absent_fee_model_as_empty(absent: str) -> None:
    payload = _parseable_payload()
    if absent == "missing":
        del payload["fee_model"]
    elif absent == "none":
        payload["fee_model"] = None
    else:
        payload["fee_model"] = {}
    assert parse_request(payload).fee_model == {}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), 10**400])
def test_parse_request_rejects_non_finite_numbers_everywhere(value) -> None:
    in_state = _parseable_payload()
    in_state["account_state"] = {"cash": value, "positions": []}
    with pytest.raises(PaperTradeSchemaError, match="finite"):
        parse_request(in_state)
    in_order = _parseable_payload()
    in_order["orders"] = [{"symbol": "600519.SH", "side": "buy", "qty": value}]
    with pytest.raises(PaperTradeSchemaError, match="finite"):
        parse_request(in_order)
    in_limit = _parseable_payload()
    in_limit["orders"] = [{"symbol": "600519.SH", "side": "buy", "qty": 100, "limit": value}]
    with pytest.raises(PaperTradeSchemaError, match="finite"):
        parse_request(in_limit)
    in_fee = _parseable_payload()
    in_fee["fee_model"] = {"commission_rate": value}
    with pytest.raises(PaperTradeSchemaError, match="finite"):
        parse_request(in_fee)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_parse_account_state_rejects_non_finite(value: float) -> None:
    with pytest.raises(PaperTradeSchemaError, match="finite"):
        parse_account_state({"cash": value, "positions": []})
    with pytest.raises(PaperTradeSchemaError, match="finite"):
        parse_account_state(
            {"cash": 1.0, "positions": [{"symbol": "600519.SH", "qty": 100, "avg_cost": value}]}
        )


# ── assemble_result fail-closed on errored outcomes ──


def test_assemble_result_refuses_an_errored_outcome() -> None:
    from src.tools.paper_trade.engine import EngineError, MatchOutcome
    from src.tools.paper_trade.schema import PaperTradeStepRequest

    request = PaperTradeStepRequest(
        account_id="pa_01", market="cn_a", account_state=AccountState(cash=0.0),
        from_date="2026-10-20", to_date="2026-10-20",
    )
    errored = MatchOutcome(
        end_state=AccountState(cash=0.0),
        error=EngineError("PAPER_DATA_NOT_READY", "target bar not available"),
    )
    with pytest.raises(ValueError, match="errored outcome"):
        wire.assemble_result(request, errored, raw_account_state={"cash": 0.0, "positions": []})


# ── VD-4 serialization spelling ──


def test_dumps_payload_is_sorted_compact_and_deterministic() -> None:
    payload = {"b": 1, "a": [2, {"d": 4, "c": 3}]}
    assert wire.dumps_payload(payload) == '{"a":[2,{"c":3,"d":4}],"b":1}'
    assert wire.dumps_payload(payload) == wire.dumps_payload(payload)
    assert wire.dumps_payload({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_dumps_payload_keeps_utf8_raw_and_refuses_non_finite() -> None:
    assert "贵州茅台" in wire.dumps_payload({"name": "贵州茅台"})
    with pytest.raises(ValueError):
        wire.dumps_payload({"nav": float("nan")})
    with pytest.raises(ValueError):
        wire.dumps_payload({"nav": float("inf")})


def test_packaged_schema_matches_the_published_wire_contract():
    from pathlib import Path
    import src.tools.paper_trade.schema as schema
    public = Path(__file__).resolve().parents[2] / "schema" / "tool_contracts" / "paper_trade_step-v1.1.json"
    packaged = Path(schema.__file__).with_name("paper_trade_step-v1.1.json")
    assert packaged.read_bytes() == public.read_bytes()
