"""Deterministic layered JCS provenance for internal pt-v2.0 portfolios.

Planning marks and target-day execution bars deliberately have independent
fingerprints. The document layer hashes the final body (without its embedded
``hashes`` member) together with the three authoritative input-layer hashes,
so it covers every layer without a self-referential ``document_hash``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from typing import Final, NoReturn, TypeAlias, assert_never

from ..state_hash import canonicalize
from .data import (CalendarCoverage, DataSnapshot, PreparedBucketData, PreparedPortfolioData,
                   PriceBar, PriorMark, PriorMarkValuation, TargetBarValuation)
from .models import JsonObject, JsonValue, PortfolioDocument, PortfolioHashes, PortfolioModel, PortfolioRequest
from .numeric import (FX_RATE_SPEC, MONEY_SPEC, PRICE_SPEC, WEIGHT_SPEC, DecimalSpec,
                      EffectiveFeeModel, canonical_decimal, parse_decimal)
from .schema import PortfolioRequestError
from .sessions import BucketSession, PortfolioSessions

__all__ = [
    "PortfolioDataHashes",
    "PortfolioHashInput",
    "compute_portfolio_hashes",
    "document_canonical_bytes",
    "document_hash",
    "execution_canonical_bytes",
    "execution_data_fingerprint",
    "plan_canonical_bytes",
    "plan_hash",
    "planning_canonical_bytes",
    "planning_data_hash",
]

_DataclassValue: TypeAlias = (
    PortfolioSessions | BucketSession | DataSnapshot | PriceBar | PriorMark | CalendarCoverage
    | TargetBarValuation | PriorMarkValuation
)
_HashValue: TypeAlias = (
    None | bool | int | float | str | Decimal | date | datetime | PortfolioModel
    | EffectiveFeeModel | _DataclassValue | tuple["_HashValue", ...]
    | list["_HashValue"] | Mapping[str, "_HashValue"]
)
_FIELD_SPECS: Final[Mapping[str, DecimalSpec]] = {
    "amount": MONEY_SPEC,
    "avg_cost": PRICE_SPEC,
    "cash": MONEY_SPEC,
    "close": PRICE_SPEC,
    "limit": PRICE_SPEC,
    "rate": FX_RATE_SPEC,
    "rebalance_band": WEIGHT_SPEC,
    "weight": WEIGHT_SPEC,
}


@dataclass(frozen=True, slots=True)
class PortfolioHashInput:
    """Typed raw inputs whose layers must remain independently auditable."""

    request: PortfolioRequest
    effective_fee_models: tuple[EffectiveFeeModel, ...]
    sessions: PortfolioSessions
    data: PreparedPortfolioData
    planner_version: str
    rules_versions: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PortfolioDataHashes:
    """The three input-layer hashes required by the final document layer."""

    plan_hash: str
    planning_data_hash: str
    execution_data_fingerprint: str


def _reject(path: str, detail: str) -> NoReturn:
    raise PortfolioRequestError(reason="invalid_hash_payload", path=path, detail=detail)


def _dataclass_payload(value: _DataclassValue) -> JsonObject:
    return {field.name: getattr(value, field.name) for field in fields(value)}


def _json_value(value: _HashValue, *, canonical_numbers: bool, path: str) -> JsonValue:
    """Convert typed values to strict JSON, rejecting every float and Decimal leak."""
    match value:
        case None | bool() | str():
            return value
        case int():
            return value
        case float() | Decimal():
            _reject(path, "hash payloads require fixed-point strings, not float/Decimal values")
        case datetime():
            return value.isoformat()
        case date():
            return value.isoformat()
        case EffectiveFeeModel():
            return {
                "bucket_id": value.bucket_id,
                "market": value.market,
                "currency": value.currency,
                "parameters": dict(value.canonical_parameters()),
            }
        case PortfolioModel():
            dumped = value.model_dump(mode="json", by_alias=True)
            return _json_value(dumped, canonical_numbers=canonical_numbers, path=path)
        case PortfolioSessions() | BucketSession() | DataSnapshot() | PriceBar() | PriorMark() \
                | CalendarCoverage() | TargetBarValuation() | PriorMarkValuation():
            return _json_value(
                _dataclass_payload(value), canonical_numbers=canonical_numbers, path=path,
            )
        case Mapping():
            converted: JsonObject = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    _reject(path, "JCS object keys must be strings")
                item_path = f"{path}.{key}"
                spec = _FIELD_SPECS.get(key) if canonical_numbers else None
                if spec is not None and isinstance(item, str):
                    parsed = parse_decimal(item, spec, item_path)
                    converted[key] = canonical_decimal(parsed, spec, item_path)
                else:
                    converted[key] = _json_value(
                        item, canonical_numbers=canonical_numbers, path=item_path,
                    )
            return converted
        case tuple() | list():
            return [
                _json_value(item, canonical_numbers=canonical_numbers, path=f"{path}[{index}]")
                for index, item in enumerate(value)
            ]
        case unreachable:
            _reject(path, f"unsupported hash value type: {type(unreachable).__name__}")
            assert_never(unreachable)


def _canonical_bytes(value: _HashValue, path: str) -> bytes:
    json_value = _json_value(value, canonical_numbers=True, path=path)
    return canonicalize(json_value).encode("utf-8")


def _hash_payload(value: _HashValue, path: str) -> str:
    return hashlib.sha256(_canonical_bytes(value, path)).hexdigest()


def _planning_bucket(bucket: PreparedBucketData) -> JsonObject:
    match bucket.valuation:
        case PriorMarkValuation(marks=marks):
            prior_marks = marks
        case TargetBarValuation():
            prior_marks = ()
        case unreachable:
            assert_never(unreachable)
    return {
        "bucket_id": bucket.bucket_id,
        "planning": bucket.planning,
        "prior_marks": prior_marks,
        "valuation_kind": bucket.valuation.kind,
    }


def _execution_bucket(bucket: PreparedBucketData) -> JsonObject:
    match bucket.valuation:
        case TargetBarValuation(snapshot=snapshot):
            valuation = snapshot
        case PriorMarkValuation():
            valuation = None
        case unreachable:
            assert_never(unreachable)
    return {
        "bucket_id": bucket.bucket_id,
        "execution": bucket.execution,
        "valuation": valuation,
    }


def _planning_payload(material: PortfolioHashInput) -> JsonObject:
    request = material.request
    return {
        "sessions": material.sessions,
        "fx_snapshots": request.fx_snapshots,
        "fx_conversions": request.fx_conversions,
        "buckets": tuple(_planning_bucket(bucket) for bucket in material.data.buckets),
    }


def _plan_payload(material: PortfolioHashInput, planning_hash: str) -> JsonObject:
    request = material.request
    context = {
        "tool": request.tool,
        "schema_version": request.schema_version,
        "mode": request.mode,
        "account_id": request.account_id,
        "base_currency": request.base_currency,
        "trade_date": request.trade_date,
        "planning_at": request.planning_at,
        "valuation_at": request.valuation_at,
        "interval": request.interval,
        "fill_model": request.fill_model,
    }
    return {
        "context": context,
        "opening_portfolio": request.portfolio_state,
        "effective_fee_models": material.effective_fee_models,
        "plan": request.plan,
        "planner_version": material.planner_version,
        "planning_data_hash": planning_hash,
    }


def _execution_payload(material: PortfolioHashInput) -> JsonObject:
    return {
        "trade_date": material.request.trade_date,
        "effective_fee_models": material.effective_fee_models,
        "rules_versions": material.rules_versions,
        "buckets": tuple(_execution_bucket(bucket) for bucket in material.data.buckets),
    }


def _document_payload(
    document: PortfolioDocument | JsonObject, hashes: PortfolioDataHashes,
) -> JsonObject:
    body = _json_value(document, canonical_numbers=False, path="document")
    if not isinstance(body, dict):
        _reject("document", "final document must be a JSON object")
    return {
        "document": {key: value for key, value in body.items() if key != "hashes"},
        "plan_hash": hashes.plan_hash,
        "planning_data_hash": hashes.planning_data_hash,
        "execution_data_fingerprint": hashes.execution_data_fingerprint,
    }


def planning_canonical_bytes(material: PortfolioHashInput) -> bytes:
    """Return canonical planning/session/FX/conversion/prior-mark bytes."""
    return _canonical_bytes(_planning_payload(material), "planning_data")


def plan_canonical_bytes(material: PortfolioHashInput) -> bytes:
    """Return canonical opening-portfolio/plan/planner/planning-link bytes."""
    return _canonical_bytes(_plan_payload(material, planning_data_hash(material)), "plan")


def execution_canonical_bytes(material: PortfolioHashInput) -> bytes:
    """Return canonical target-day execution/valuation bars, fees and rules bytes."""
    return _canonical_bytes(_execution_payload(material), "execution_data")


def document_canonical_bytes(
    document: PortfolioDocument | JsonObject, hashes: PortfolioDataHashes,
) -> bytes:
    """Return canonical final-body bytes with authoritative three-layer coverage."""
    payload = _document_payload(document, hashes)
    converted = _json_value(payload, canonical_numbers=False, path="document")
    return canonicalize(converted).encode("utf-8")


def planning_data_hash(material: PortfolioHashInput) -> str:
    """Hash only planning-time data, sessions, FX snapshots and conversions."""
    return hashlib.sha256(planning_canonical_bytes(material)).hexdigest()


def plan_hash(material: PortfolioHashInput) -> str:
    """Hash the raw opening portfolio and plan against its planning-data identity."""
    return _hash_payload(_plan_payload(material, planning_data_hash(material)), "plan")


def execution_data_fingerprint(material: PortfolioHashInput) -> str:
    """Hash target-day bars, effective fees and execution rule versions."""
    return hashlib.sha256(execution_canonical_bytes(material)).hexdigest()


def document_hash(
    document: PortfolioDocument | JsonObject, hashes: PortfolioDataHashes,
) -> str:
    """Hash the final document body together with all three input-layer hashes."""
    return hashlib.sha256(document_canonical_bytes(document, hashes)).hexdigest()


def compute_portfolio_hashes(
    material: PortfolioHashInput, document: PortfolioDocument | JsonObject,
) -> PortfolioHashes:
    """Compute the complete non-circular four-layer portfolio identity."""
    planning_hash = planning_data_hash(material)
    layers = PortfolioDataHashes(
        plan_hash=_hash_payload(_plan_payload(material, planning_hash), "plan"),
        planning_data_hash=planning_hash,
        execution_data_fingerprint=execution_data_fingerprint(material),
    )
    return PortfolioHashes(
        plan_hash=layers.plan_hash,
        planning_data_hash=layers.planning_data_hash,
        execution_data_fingerprint=layers.execution_data_fingerprint,
        document_hash=document_hash(document, layers),
    )
