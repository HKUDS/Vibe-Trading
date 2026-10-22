"""T2 gate — pt-v1.2 additive contract (schema + hash + wire + tool surface).

Pins the binding decisions of the P0 5m plan: the four optional request fields
and their defaults (D8), the closed vocabularies and market-combination gates
(D5), the D3 engine fingerprint, the D4 byte-compatible state hash, and the
D8 rule that a v1.1 call emits NO v1.2 key while a v1.2 call emits exactly
three.  Offline: no network, no clock, no data fetch (the 5m/hk gate returns
before the data layer is reached).
"""

from __future__ import annotations

import json
import re
import types
from dataclasses import replace
from pathlib import Path

import pytest

from src.tools.paper_trade import rules, state_hash, wire
from src.tools.paper_trade.engine import MatchOutcome
from src.tools.paper_trade.schema import (
    CANCELED_REASON_CODE,
    DEFAULT_FILL_MODEL,
    DEFAULT_INTERVAL,
    DEFAULT_PATH_MODEL,
    DEFAULT_SESSION,
    FILL_MODELS,
    INTERVALS,
    PATH_MODELS,
    SCHEMA_VERSION,
    SCHEMA_VERSION_V1_2,
    SESSION_EVENT_TYPES,
    SESSIONS,
    AccountState,
    CanceledOrder,
    DataProvenance,
    DateRange,
    Fill,
    NavPoint,
    PaperTradeSchemaError,
    PaperTradeStepResult,
    RejectedOrder,
    SessionEvent,
    SkippedDay,
    load_contract_schema,
    parse_request,
    validate_payload,
)
from src.tools.paper_trade.tool import PaperTradeStepTool, run_paper_trade_step

_CONTRACT_DIR = Path(__file__).resolve().parents[2] / "schema" / "tool_contracts"
_V12_KEYS = {"engine_fingerprint", "canceled_orders", "events"}
_V11_KEYS = {
    "schema_version", "tool", "account_id", "market", "range", "received_state_hash",
    "effective_fee_model", "fills", "rejected_orders", "end_state", "nav_series",
    "skipped_days", "warnings", "data_provenance",
}
_DAY = "2026-10-20"
_HEX_A = "a" * 64


def _payload(**overrides) -> dict:
    payload = {
        "account_id": "pa_v12_01",
        "market": "cn_a",
        "account_state": {"cash": 100000.0, "positions": []},
        "orders": [{"symbol": "600519.SH", "side": "buy", "qty": 100}],
        "from_date": _DAY,
        "to_date": _DAY,
    }
    payload.update(overrides)
    return payload


def _outcome() -> MatchOutcome:
    return MatchOutcome(
        end_state=AccountState(cash=100000.0),
        effective_fee_model=state_hash.effective_fee_model("cn_a"),
    )


def _v11_result(**overrides) -> PaperTradeStepResult:
    fields: dict = dict(
        account_id="pa_v12_01",
        market="cn_a",
        range=DateRange(from_=_DAY, to=_DAY),
        received_state_hash="0" * 64,
        effective_fee_model=state_hash.effective_fee_model("cn_a"),
        fills=(Fill(trade_date=_DAY, symbol="600519.SH", side="buy", qty=100.0,
                    price=1421.0, fee=36.95, reason=""),),
        rejected_orders=(RejectedOrder(trade_date=_DAY, symbol="000001.SZ", side="sell",
                                       qty=200.0, reason_code="insufficient_position"),),
        end_state=AccountState(cash=100000.0),
        nav_series=(NavPoint(date=_DAY, nav=100000.0, cash=100000.0, position_value=0.0),),
        skipped_days=(SkippedDay(date="2026-10-18", reason="non_trading_day"),),
        warnings=("valuation: 000001.SZ has no usable close",),
        data_provenance=DataProvenance(source="clickhouse+tencent(merged)"),
    )
    fields.update(overrides)
    return PaperTradeStepResult(**fields)


def _v12_result(**overrides) -> PaperTradeStepResult:
    fields: dict = dict(
        schema_version=SCHEMA_VERSION_V1_2,
        engine_fingerprint="d" * 64,
        canceled_orders=(
            CanceledOrder(trade_date=_DAY, symbol="600519.SH", side="buy", qty=100.0,
                          detail="limit 1000.0 not marketable"),
        ),
        events=(
            SessionEvent(trade_date=_DAY, symbol="600519.SH", event_type="auction_window",
                         detail="09:30 opening auction excluded"),
        ),
    )
    fields.update(overrides)
    return replace(_v11_result(), **fields)


# ── Defaults: absent/null new fields ARE the pt-v1.1 semantics (D8) ──


def test_absent_new_fields_take_the_v11_defaults() -> None:
    request = parse_request(_payload())
    assert (request.interval, request.session, request.path_model, request.fill_model) == (
        DEFAULT_INTERVAL, DEFAULT_SESSION, DEFAULT_PATH_MODEL, DEFAULT_FILL_MODEL,
    )
    assert (request.interval, request.session, request.path_model, request.fill_model) == (
        "1d", "auto", "bar_median", "all_or_none",
    )
    assert request.uses_v1_2 is False
    assert request.schema_version == SCHEMA_VERSION == "pt-v1.1"


@pytest.mark.parametrize("field", ["interval", "session", "path_model", "fill_model"])
def test_explicit_null_is_the_same_as_absent(field: str) -> None:
    request = parse_request(_payload(**{field: None}))
    assert request.uses_v1_2 is False


def test_any_non_default_field_selects_v12() -> None:
    for field, value in (
        ("interval", "5m"), ("session", "cn_a"), ("path_model", "bar_close"),
        ("fill_model", "all_or_none"),
    ):
        request = parse_request(_payload(**{field: value}))
        assert request.uses_v1_2 is (field != "fill_model"), field


# ── Closed vocabularies: every member accepted, everything else rejected ──


@pytest.mark.parametrize("value", INTERVALS)
def test_every_interval_is_accepted(value: str) -> None:
    assert parse_request(_payload(interval=value)).interval == value


@pytest.mark.parametrize("value", SESSIONS)
def test_every_session_is_accepted(value: str) -> None:
    assert parse_request(_payload(session=value)).session == value


@pytest.mark.parametrize("value", PATH_MODELS)
def test_every_path_model_is_accepted(value: str) -> None:
    assert parse_request(_payload(path_model=value)).path_model == value


@pytest.mark.parametrize("value", FILL_MODELS)
def test_every_fill_model_is_accepted(value: str) -> None:
    assert parse_request(_payload(fill_model=value)).fill_model == value


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interval", "15m"),
        ("interval", "5M"),
        ("session", "hk"),
        ("path_model", "vwap"),
        ("fill_model", "partial"),
        ("interval", 5),
        ("session", True),
        ("path_model", ["bar_close"]),
    ],
)
def test_out_of_vocabulary_or_non_string_values_are_rejected(field: str, value) -> None:
    with pytest.raises(PaperTradeSchemaError, match=field):
        parse_request(_payload(**{field: value}))


# ── D5 market-combination gates: in-band INVALID_REQUEST, never a traceback ──


@pytest.mark.parametrize("market", ["hk", "us"])
def test_5m_outside_cn_a_is_in_band_invalid_request(market: str) -> None:
    doc = json.loads(run_paper_trade_step(_payload(market=market, interval="5m")))
    assert doc["status"] == "error"
    assert doc["code"] == "INVALID_REQUEST"
    assert "interval 5m is cn_a-only in pt-v1.2" in doc["message"]
    assert "received_state_hash" in doc


@pytest.mark.parametrize("market", ["hk", "us"])
def test_cn_a_session_outside_cn_a_is_in_band_invalid_request(market: str) -> None:
    doc = json.loads(run_paper_trade_step(_payload(market=market, session="cn_a")))
    assert doc["code"] == "INVALID_REQUEST"
    assert "session cn_a requires market cn_a" in doc["message"]


def test_session_is_inert_for_interval_1d_and_cn_a() -> None:
    request = parse_request(_payload(market="cn_a", session="cn_a", interval="1d"))
    assert request.uses_v1_2 is True
    assert request.schema_version == SCHEMA_VERSION_V1_2


# ── D3 engine fingerprint ──


def test_engine_fingerprint_matches_the_frozen_formula() -> None:
    actual = state_hash.engine_fingerprint(
        interval="5m", path_model="bar_close", fill_model="all_or_none",
        bar_fingerprint=_HEX_A,
    )
    manual = state_hash.state_hash({
        "interval": "5m",
        "path_model": "bar_close",
        "fill_model": "all_or_none",
        "rules_version": rules.RULES_VERSION,
        "bar_fingerprint": _HEX_A,
    })
    assert rules.RULES_VERSION == "pt-rules-v1"
    assert actual == manual
    assert re.fullmatch(r"[0-9a-f]{64}", actual)


def test_engine_fingerprint_is_deterministic_and_input_sensitive() -> None:
    base_kwargs = dict(interval="5m", path_model="bar_median", fill_model="all_or_none",
                       bar_fingerprint=_HEX_A)
    base = state_hash.engine_fingerprint(**base_kwargs)
    assert state_hash.engine_fingerprint(**base_kwargs) == base
    assert state_hash.engine_fingerprint(**{**base_kwargs, "interval": "1d"}) != base
    assert state_hash.engine_fingerprint(**{**base_kwargs, "path_model": "bar_close"}) != base
    assert state_hash.engine_fingerprint(**{**base_kwargs, "fill_model": "x"}) != base
    assert state_hash.engine_fingerprint(**{**base_kwargs, "bar_fingerprint": "b" * 64}) != base
    assert state_hash.engine_fingerprint(
        **{**base_kwargs, "rules_version": "pt-rules-v0"}) != base


def test_engine_fingerprint_defaults_are_the_pt_v11_parameters() -> None:
    assert state_hash.engine_fingerprint() == state_hash.engine_fingerprint(
        interval="1d", path_model="bar_median", fill_model="all_or_none",
        bar_fingerprint="", rules_version=rules.RULES_VERSION,
    )


# ── D4 received_state_hash: v1.1 byte-compatible, v1.2 covered ──


def test_v11_hash_is_the_frozen_coverage_object() -> None:
    request = parse_request(_payload())
    result = wire.assemble_result(request, _outcome(), raw_account_state=_payload()["account_state"])
    manual = state_hash.state_hash({
        "account_id": "pa_v12_01",
        "market": "cn_a",
        "account_state": _payload()["account_state"],
        "fee_model": state_hash.effective_fee_model("cn_a"),
        "from_date": _DAY,
        "to_date": _DAY,
    })
    assert result.received_state_hash == manual


def test_explicit_defaults_do_not_change_the_hash() -> None:
    base = wire.received_state_hash_from_payload(_payload())
    respelled = wire.received_state_hash_from_payload(_payload(
        interval="1d", session="auto", path_model="bar_median", fill_model="all_or_none",
    ))
    assert base is not None and base == respelled


def test_non_default_fields_join_the_hash() -> None:
    baseline = wire.received_state_hash_from_payload(_payload())
    v12 = wire.received_state_hash_from_payload(_payload(interval="5m", path_model="bar_close"))
    assert v12 is not None and v12 != baseline
    manual = state_hash.state_hash({
        "account_id": "pa_v12_01",
        "market": "cn_a",
        "account_state": _payload()["account_state"],
        "fee_model": state_hash.effective_fee_model("cn_a"),
        "from_date": _DAY,
        "to_date": _DAY,
        "interval": "5m",
        "path_model": "bar_close",
    })
    assert v12 == manual


@pytest.mark.parametrize(
    ("field", "value"),
    [("interval", "15m"), ("session", 5), ("path_model", "vwap"), ("fill_model", [])],
)
def test_error_path_hash_is_omitted_for_malformed_v12_fields(field: str, value) -> None:
    assert wire.received_state_hash_from_payload(_payload(**{field: value})) is None


# ── D8 wire shape: v1.1 untouched, v1.2 adds exactly three keys ──


def test_v11_payload_key_set_is_the_frozen_set() -> None:
    payload = wire.build_success_payload(_v11_result())
    assert set(payload) == _V11_KEYS
    assert payload["schema_version"] == "pt-v1.1"
    assert validate_payload(payload, load_contract_schema("result")) == []


def test_v12_payload_adds_exactly_the_three_documented_keys() -> None:
    payload = wire.build_success_payload(_v12_result())
    assert set(payload) - set(_v11_result_payload()) == _V12_KEYS
    assert payload["schema_version"] == "pt-v1.2"
    assert payload["engine_fingerprint"] == "d" * 64
    assert payload["canceled_orders"][0]["reason_code"] == CANCELED_REASON_CODE
    assert payload["events"][0]["event_type"] == "auction_window"
    assert validate_payload(payload, load_contract_schema("result", version="pt-v1.2")) == []


def _v11_result_payload() -> dict:
    return wire.build_success_payload(_v11_result())


def test_v11_result_stays_valid_under_the_additive_v12_document() -> None:
    payload = _v11_result_payload()
    assert set(payload).isdisjoint(_V12_KEYS)
    assert validate_payload(payload, load_contract_schema("result", version="pt-v1.2")) == []


def test_the_subset_validator_defers_the_v12_version_gate_to_the_wire_builder() -> None:
    unversioned = _v11_result_payload() | {"schema_version": "pt-v1.2"}
    assert validate_payload(
        unversioned, load_contract_schema("result", version="pt-v1.2")
    ) == []
    with pytest.raises(ValueError, match="engine_fingerprint"):
        wire.build_success_payload(_v12_result(engine_fingerprint=""))


def test_v12_result_does_not_validate_as_a_v11_document() -> None:
    payload = wire.build_success_payload(_v12_result())
    errors = validate_payload(payload, load_contract_schema("result"))
    assert any("schema_version" in error for error in errors)


def test_v12_assembly_reads_the_engine_populated_outcome_fields() -> None:
    base = _outcome()
    outcome = types.SimpleNamespace(
        error=None,
        effective_fee_model=base.effective_fee_model,
        fills=base.fills,
        rejected_orders=base.rejected_orders,
        end_state=base.end_state,
        nav_series=base.nav_series,
        skipped_days=base.skipped_days,
        warnings=base.warnings,
        data_provenance=base.data_provenance,
        limit_provenance=base.limit_provenance,
        engine_fingerprint="e" * 64,
        canceled_orders=(CanceledOrder(trade_date=_DAY, symbol="600519.SH", side="buy",
                                       qty=100.0),),
        events=(SessionEvent(trade_date=_DAY, symbol="600519.SH", event_type="halted"),),
    )
    request = parse_request(_payload(interval="5m"))
    result = wire.assemble_result(
        request, outcome, raw_account_state=_payload()["account_state"])
    assert result.engine_fingerprint == "e" * 64
    assert result.canceled_orders[0].reason_code == CANCELED_REASON_CODE
    assert result.events[0].event_type == "halted"


def test_v12_assembly_computes_a_fingerprint_before_the_engine_populates_it() -> None:
    request = parse_request(_payload(interval="5m", path_model="bar_close"))
    result = wire.assemble_result(
        request, _outcome(), raw_account_state=_payload()["account_state"])
    assert result.schema_version == SCHEMA_VERSION_V1_2
    assert result.engine_fingerprint == state_hash.engine_fingerprint(
        interval="5m", path_model="bar_close", fill_model="all_or_none")


def test_v11_assembly_never_carries_v12_fields() -> None:
    request = parse_request(_payload())
    result = wire.assemble_result(
        request, _outcome(), raw_account_state=_payload()["account_state"])
    assert result.schema_version == SCHEMA_VERSION
    assert (result.engine_fingerprint, result.canceled_orders, result.events) == ("", (), ())


# ── Fail-closed serialization on engine bugs ──


def test_v12_without_a_fingerprint_fails_closed() -> None:
    with pytest.raises(ValueError, match="engine_fingerprint"):
        wire.build_success_payload(_v12_result(engine_fingerprint=""))


def test_wrong_cancel_token_fails_closed() -> None:
    bad = CanceledOrder(trade_date=_DAY, symbol="600519.SH", side="buy", qty=100.0,
                        reason_code="insufficient_cash")
    with pytest.raises(ValueError, match="canceled reason_code"):
        wire.build_success_payload(_v12_result(canceled_orders=(bad,)))


def test_unknown_event_type_fails_closed() -> None:
    bad = SessionEvent(trade_date=_DAY, symbol="600519.SH", event_type="closing_auction")
    with pytest.raises(ValueError, match="event_type"):
        wire.build_success_payload(_v12_result(events=(bad,)))


def test_unknown_schema_version_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown schema_version"):
        wire.build_success_payload(_v11_result(schema_version="pt-v1.0"))


# ── Contract files: v1.2 additive copy, v1.1 frozen ──


def test_v12_contract_file_declares_the_additive_surface() -> None:
    document = json.loads((_CONTRACT_DIR / "paper_trade_step-v1.2.json").read_text("utf-8"))
    assert document["version"] == "pt-v1.2"
    assert "additive" in document["$comment"].lower()
    result = document["schemas"]["result"]
    assert result["properties"]["schema_version"]["enum"] == ["pt-v1.1", "pt-v1.2"]
    assert result["properties"]["engine_fingerprint"]["pattern"] == "^[0-9a-f]{64}$"
    cancel_reason = result["properties"]["canceled_orders"]["items"]["properties"]["reason_code"]
    assert cancel_reason["const"] == CANCELED_REASON_CODE
    event_types = result["properties"]["events"]["items"]["properties"]["event_type"]["enum"]
    assert tuple(event_types) == SESSION_EVENT_TYPES


def test_v12_contract_requires_the_additive_fields_only_for_a_v12_document() -> None:
    document = json.loads((_CONTRACT_DIR / "paper_trade_step-v1.2.json").read_text("utf-8"))
    result = document["schemas"]["result"]
    assert "engine_fingerprint" not in result["required"]
    conditional = next(node for node in result["allOf"] if "if" in node)
    assert conditional["if"]["properties"]["schema_version"]["const"] == "pt-v1.2"
    assert set(conditional["then"]["required"]) == _V12_KEYS
    assert "wire.build_success_payload" in conditional["$comment"]


def test_v11_contract_file_is_not_edited() -> None:
    document = json.loads((_CONTRACT_DIR / "paper_trade_step-v1.1.json").read_text("utf-8"))
    assert document["version"] == "pt-v1.1"
    result = document["schemas"]["result"]
    assert result["properties"]["schema_version"]["const"] == "pt-v1.1"
    assert not (_V12_KEYS & set(result["properties"]))


def test_loader_defaults_to_v11_and_rejects_an_unknown_version() -> None:
    assert load_contract_schema("result")["properties"]["schema_version"]["const"] == "pt-v1.1"
    with pytest.raises(KeyError, match="unknown contract version"):
        load_contract_schema("result", version="pt-v1.3")


# ── Tool registration surface ──


def test_tool_parameters_expose_the_four_optional_fields() -> None:
    parameters = PaperTradeStepTool.parameters
    properties = parameters["properties"]
    assert properties["interval"]["enum"] == ["1d", "5m"]
    assert properties["interval"]["default"] == "1d"
    assert properties["session"]["enum"] == ["auto", "cn_a"]
    assert properties["session"]["default"] == "auto"
    assert properties["path_model"]["enum"] == ["bar_median", "bar_close"]
    assert properties["path_model"]["default"] == "bar_median"
    assert properties["fill_model"]["enum"] == ["all_or_none"]
    assert properties["fill_model"]["default"] == "all_or_none"
    assert parameters["required"] == [
        "account_id", "market", "account_state", "from_date", "to_date",
    ]
    assert "deterministic paper-trading matching engine; never places real orders" in (
        PaperTradeStepTool.description)
