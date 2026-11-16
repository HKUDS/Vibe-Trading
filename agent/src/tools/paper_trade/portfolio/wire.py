"""Public pt-v2.0 portfolio wire serialization and bucket-aware errors.

This module is the independent public boundary over the internal Decimal
step. It owns two document shapes, both matching the packaged
``paper_trade_step-v2.0.json`` contract:

* a success result containing the status/tool/schema/mode header, the
  opening, post-conversion and ending ledgers, the caller plan, per-bucket
  valuations, fills/reject/cancel rows linked to their ``bucket_id`` and
  ``plan_order_id``, conversions, sessions, warnings, the ``complete`` verdict
  and the four-layer hashes;
* a stable in-band error envelope with ``INVALID_REQUEST`` or
  ``PAPER_DATA_NOT_READY``, the reason/path/detail/bucket id, and a
  deterministic ``input_sha256=...`` echo of the raw request so an auditor can
  correlate the failure without receiving a fabricated end ledger or fills.

Every public numeric is a canonical fixed-point string; quantities remain JSON
integers. The serializer rejects floats, ``Decimal`` values, NaN/Infinity,
non-string mapping keys and invalid UTF-8 rather than coercing them. Internal
wire faults raise :class:`PortfolioWireError`; they are never serialized as one
of the two public error codes, so the ``INTERNAL`` distinction stays visible
to the caller.

The module is dependency-free beyond the standard library and the existing
portfolio models: no jsonschema runtime import, no clock, no randomness, no
network, and no legacy ``paper_trade.wire`` behaviour is touched.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, NoReturn

from pydantic import ValidationError

from ..state_hash import canonicalize
from .models import JsonObject, JsonValue, PortfolioModel, PortfolioResult
from .orchestrator import OrchestrationError, OrchestrationCode
from .schema import PortfolioRequestError
from .sessions import PortfolioSessionError

__all__ = [
    "INPUT_HASH_MARKER",
    "PUBLIC_ERROR_CODES",
    "PortfolioWireError",
    "build_error_from_exception",
    "build_error_payload",
    "build_success_payload",
    "compute_raw_input_hash",
    "dumps_payload",
    "error_code_for_exception",
    "serialize_error",
    "serialize_success",
]

WIRE_TOOL: Final = "paper_trade_step"
WIRE_SCHEMA_VERSION: Final = "pt-v2.0"
WIRE_MODE: Final = "portfolio"
INPUT_HASH_MARKER: Final = "input_sha256"
PUBLIC_ERROR_CODES: Final[tuple[str, ...]] = (
    "INVALID_REQUEST",
    "PAPER_DATA_NOT_READY",
)

_DECIMAL_PATTERN: Final = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_HASH_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_KEYS: Final = frozenset(
    {
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
)
_REQUIRED_SUCCESS_KEYS: Final = (
    "status",
    "tool",
    "schema_version",
    "mode",
    "account_id",
    "base_currency",
    "trade_date",
    "planning_at",
    "valuation_at",
    "opening_portfolio",
    "post_conversion_portfolio",
    "end_portfolio",
    "sessions",
    "conversions",
    "plan",
    "bucket_results",
    "fills",
    "rejected_orders",
    "canceled_orders",
    "warnings",
    "errors",
    "complete",
    "hashes",
)
_SUCCESS_KEYS: Final = frozenset(_REQUIRED_SUCCESS_KEYS)
_CURRENCY_VALUES: Final = frozenset({"CNY", "HKD", "USD"})
_INPUT_HASH_SUFFIX: Final = re.compile(r"(?:^|;\s*)input_sha256=[0-9a-f]{64}\s*$")
_BUCKET_REQUIRED_KEYS: Final = ("bucket_id", "market", "currency", "cash", "positions")
_PLAN_LINE_FIELDS: Final = ("symbol", "currency", "side", "qty")


@dataclass(frozen=True, slots=True)
class _PlanLine:
    bucket_id: str
    symbol: str
    currency: str
    side: str
    qty: int


@dataclass(frozen=True, slots=True)
class PortfolioWireError(ValueError):
    """One stable serialization/identity fault; never a public error envelope.

    ``code`` is always ``INTERNAL``: these failures mean the engine produced a
    document or an exception class the public pt-v2.0 contract cannot publish
    in-band. The tool layer must surface them as a transport/engine fault,
    exactly like the legacy pt-v1.x wire raises rather than shipping a document
    an auditor cannot route.
    """

    reason: str
    path: str = "$"
    bucket_id: str | None = None
    detail: str = ""

    @property
    def code(self) -> str:
        return "INTERNAL"

    def __str__(self) -> str:
        return f"{self.code}:{self.reason}:{self.path}"


def _reject(
    reason: str,
    path: str,
    *,
    bucket_id: str | None = None,
    detail: str = "",
) -> NoReturn:
    raise PortfolioWireError(reason=reason, path=path or "$", bucket_id=bucket_id, detail=detail)


# The raw-input hash deliberately hashes the wire spelling for bytes/str and
# the JCS spelling for parsed JSON values: the first is the actual request an
# auditor received, the second is order-independent so a dict-built test
# fixture and its reordered twin still identify the same payload.


def _fallback_text(value: str) -> str:
    """Replace lone surrogates with deterministic escape text for hashing."""
    return value.encode("utf-8", "backslashreplace").decode("utf-8")


def _fallback_json(value: Any) -> JsonValue:
    """Normalize a non-JSON-native value into a deterministic hashable shape.

    Used only by :func:`compute_raw_input_hash` when the raw input contains a
    non-finite float, ``Decimal`` or other value JCS refuses. The fallback is
    intentionally tagged and total so the error path can still echo an input
    hash instead of raising a second fault.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "<float:nan>"
        if math.isinf(value):
            return "<float:infinity>" if value > 0 else "<float:-infinity>"
        return repr(value)
    if isinstance(value, str):
        return _fallback_text(value)
    if isinstance(value, Decimal):
        return f"<decimal:{value}>"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<bytes:{bytes(value).hex()}>"
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            text = key if isinstance(key, str) else f"<key:{type(key).__name__}:{key!r}>"
            normalized[_fallback_text(text)] = _fallback_json(item)
        return normalized
    if isinstance(value, (set, frozenset)):
        return [_fallback_json(item) for item in sorted(value, key=repr)]
    if isinstance(value, Sequence):
        return [_fallback_json(item) for item in value]
    return f"<{type(value).__module__}.{type(value).__qualname__}>"


def compute_raw_input_hash(raw_input: JsonValue | str | bytes | Any) -> str:
    """Return a stable SHA-256 identity for the raw request.

    ``bytes``/``str`` are hashed exactly as received (the auditor's raw wire
    text); every other value is hashed through RFC 8785 JCS. Values JCS cannot
    represent (NaN/Infinity, ``Decimal``, lone surrogates) fall back to a
    deterministic tagged normalization so an invalid request still has a
    stable identity for the error envelope.
    """
    if isinstance(raw_input, (bytes, bytearray, memoryview)):
        payload = bytes(raw_input)
    elif isinstance(raw_input, str):
        payload = raw_input.encode("utf-8", "surrogatepass")
    else:
        try:
            payload = canonicalize(raw_input).encode("utf-8")
        except (TypeError, ValueError, OverflowError, RecursionError):
            normalized = json.dumps(
                _fallback_json(raw_input),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            payload = normalized.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _raw_account_id(raw_input: Any) -> str:
    """Echo ``account_id`` only when the raw request actually carries a string."""
    raw: Any = raw_input
    if isinstance(raw_input, (bytes, bytearray, memoryview, str)):
        try:
            raw = json.loads(raw_input)
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return ""
    if isinstance(raw, Mapping):
        account_id = raw.get("account_id")
        if isinstance(account_id, str):
            return account_id
    return ""


def _wire_text(value: str) -> str:
    """Replace lone surrogates so an echoed error field stays valid UTF-8."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    return value


def _strip_input_hash_suffix(detail: str) -> str:
    """Remove any trailing hash markers before appending the current one."""
    while True:
        stripped = _INPUT_HASH_SUFFIX.sub("", detail)
        if stripped == detail:
            return detail
        detail = stripped


def _with_input_hash(detail: str, raw_input: Any) -> str:
    digest = compute_raw_input_hash(raw_input)
    marker = f"{INPUT_HASH_MARKER}={digest}"
    stable = _strip_input_hash_suffix(_wire_text(detail))
    return f"{stable}; {marker}" if stable else marker


_UNION_TAGS: Final = frozenset({"ExplicitOrdersPlan", "TargetWeightsPlan"})


def _location_path(location: tuple[Any, ...]) -> str:
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        elif part not in _UNION_TAGS:
            path += ("." if path else "") + str(part)
    return path or "$"


def _first_result_error(exc: ValidationError, payload: JsonObject) -> Any:
    errors = exc.errors()
    plan = payload.get("plan")
    kind = plan.get("kind") if isinstance(plan, dict) else None
    if kind == "orders":
        matching = [error for error in errors if "TargetWeightsPlan" not in error["loc"]]
    elif kind == "target_weights":
        matching = [error for error in errors if "ExplicitOrdersPlan" not in error["loc"]]
    else:
        matching = []
    return (matching or errors)[0]


_MISSING_IDENTITY_REASONS: Final = {
    "plan_order_id": "missing_plan_order_id",
    "order_id": "missing_plan_order_id",
    "bucket_id": "missing_bucket_id",
    "symbol": "missing_symbol",
    "currency": "missing_currency",
}
_PYDANTIC_FIELD_REASONS: Final = {
    "account_id": "invalid_account_id",
    "base_currency": "invalid_base_currency",
    "currency": "invalid_currency",
    "market": "invalid_market",
    "side": "invalid_side",
    "qty": "invalid_qty",
    "kind": "invalid_plan_kind",
    "status": "invalid_status",
    "tool": "invalid_tool",
    "schema_version": "invalid_schema_version",
    "mode": "invalid_mode",
    "trade_date": "invalid_date",
    "planning_at": "invalid_timestamp",
    "valuation_at": "invalid_timestamp",
    "as_of": "invalid_timestamp",
    "observed_at": "invalid_timestamp",
}


def _pydantic_reason(error_type: str, path: str) -> str:
    if error_type == "extra_forbidden":
        return "unknown_field"
    field = path.rsplit(".", maxsplit=1)[-1].split("[", maxsplit=1)[0]
    if error_type == "missing":
        return _MISSING_IDENTITY_REASONS.get(field, "missing_field")
    mapped = _PYDANTIC_FIELD_REASONS.get(field)
    if mapped is not None:
        return mapped
    if error_type == "string_too_short":
        return _MISSING_IDENTITY_REASONS.get(field, "invalid_field")
    if error_type in {
        "bool_type",
        "date_from_datetime_parsing",
        "date_type",
        "datetime_parsing",
        "datetime_type",
        "dict_type",
        "int_from_float",
        "int_parsing",
        "int_type",
        "list_type",
        "model_attributes_type",
        "model_type",
        "string_type",
        "tuple_type",
    }:
        return "invalid_type"
    return "invalid_field"


def _normalize_json(value: Any, path: str) -> JsonValue:
    """Deep-copy a document into strict JSON, rejecting hostile numerics."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _reject("nonfinite_number", path, detail="NaN/Infinity is not a public value")
        _reject("float_not_allowed", path, detail="public numerics are fixed-point strings")
    if isinstance(value, Decimal):
        _reject("decimal_not_allowed", path, detail="public numerics are fixed-point strings")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            _reject("invalid_utf8", path, detail="public strings must be valid UTF-8")
        return value
    if isinstance(value, datetime):
        _reject("non_json_value", path, detail="timestamps must already be JSON strings")
    if isinstance(value, date):
        _reject("non_json_value", path, detail="dates must already be JSON strings")
    if isinstance(value, (bytes, bytearray, memoryview)):
        _reject("non_json_value", path, detail="bytes must already be JSON strings")
    if isinstance(value, PortfolioModel):
        return _normalize_json(
            value.model_dump(mode="json", by_alias=True, exclude_none=True),
            path,
        )
    if isinstance(value, Mapping):
        converted: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _reject("non_string_key", path, detail="JCS/JSON object keys must be strings")
            item_path = f"{path}.{key}" if key else f"{path}.[]"
            converted[key] = _normalize_json(item, item_path)
        return converted
    if isinstance(value, (list, tuple)):
        return [
            _normalize_json(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    _reject(
        "non_json_value",
        path,
        detail=f"unsupported public value type {type(value).__name__}",
    )


def _assert_decimal_strings(value: JsonValue, path: str) -> None:
    """Require known decimal fields to be canonical fixed-point strings."""
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}" if key else f"{path}.[]"
            if key in _DECIMAL_KEYS:
                if not isinstance(item, str) or _DECIMAL_PATTERN.fullmatch(item) is None:
                    _reject(
                        "invalid_decimal",
                        item_path,
                        detail="expected a canonical fixed-point string",
                    )
                if item.startswith("-") and not item.lstrip("-0.").strip("0"):
                    _reject("negative_zero", item_path)
            elif key == "parameters":
                if not isinstance(item, dict):
                    _reject("invalid_decimal", item_path, detail="fee parameters must be an object")
                for name, parameter in item.items():
                    parameter_path = f"{item_path}.{name}"
                    if (
                        not isinstance(parameter, str)
                        or _DECIMAL_PATTERN.fullmatch(parameter) is None
                    ):
                        _reject(
                            "invalid_decimal",
                            parameter_path,
                            detail="expected a canonical fixed-point string",
                        )
            else:
                _assert_decimal_strings(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_decimal_strings(item, f"{path}[{index}]")


def _dump_result(document: PortfolioResult) -> JsonObject:
    return document.model_dump(mode="json", by_alias=True, exclude_none=True)


def _coerce_success(document: Any) -> tuple[JsonObject, Any | None]:
    """Return the success payload source and an optional internal order plan."""
    if isinstance(document, PortfolioResult):
        return _dump_result(document), None
    if isinstance(document, PortfolioModel):
        _reject(
            "invalid_document",
            "$",
            detail="build_success_payload accepts a PortfolioResult, not an error model",
        )
    nested = getattr(document, "document", None)
    if isinstance(nested, PortfolioResult):
        return _dump_result(nested), getattr(document, "order_plan", None)
    if isinstance(document, Mapping):
        return dict(document), None
    _reject("invalid_document", "$", detail="expected a PortfolioResult or JSON object")


def _require_mapping(payload: JsonObject, key: str) -> JsonObject:
    value = payload.get(key)
    if not isinstance(value, dict):
        _reject("missing_field", key, detail=f"required object {key!r} is absent")
    return value


def _require_list(payload: JsonObject, key: str) -> list[JsonValue]:
    value = payload.get(key)
    if not isinstance(value, list):
        _reject("missing_field", key, detail=f"required array {key!r} is absent")
    return value


def _bucket_ids(payload: JsonObject) -> set[str]:
    ids: set[str] = set()
    for state_key in ("opening_portfolio", "post_conversion_portfolio", "end_portfolio"):
        state = _require_mapping(payload, state_key)
        for index, bucket in enumerate(_require_list(state, "buckets")):
            if not isinstance(bucket, dict):
                _reject("invalid_bucket", f"{state_key}.buckets[{index}]")
            bucket_id = bucket.get("bucket_id")
            if not isinstance(bucket_id, str) or not bucket_id:
                _reject(
                    "missing_bucket_id",
                    f"{state_key}.buckets[{index}].bucket_id",
                )
            ids.add(bucket_id)
    for index, row in enumerate(_require_list(payload, "bucket_results")):
        if not isinstance(row, dict):
            _reject("invalid_bucket", f"bucket_results[{index}]")
        bucket_id = row.get("bucket_id")
        if not isinstance(bucket_id, str) or not bucket_id:
            _reject("missing_bucket_id", f"bucket_results[{index}].bucket_id")
        ids.add(bucket_id)
    return ids


def _plan_line(row: JsonObject, path: str) -> _PlanLine:
    bucket_id = row.get("bucket_id")
    symbol = row.get("symbol")
    currency = row.get("currency")
    side = row.get("side")
    qty = row.get("qty")
    if not isinstance(bucket_id, str) or not bucket_id:
        _reject("missing_bucket_id", f"{path}.bucket_id")
    if not isinstance(symbol, str) or not symbol:
        _reject("missing_symbol", f"{path}.symbol")
    if not isinstance(currency, str) or not currency:
        _reject("missing_currency", f"{path}.currency")
    if not isinstance(side, str) or side not in {"buy", "sell"}:
        _reject("invalid_side", f"{path}.side")
    if type(qty) is not int or qty <= 0:
        _reject("invalid_qty", f"{path}.qty")
    return _PlanLine(
        bucket_id=bucket_id,
        symbol=symbol,
        currency=currency,
        side=side,
        qty=qty,
    )


def _explicit_plan_lines(payload: JsonObject) -> dict[str, _PlanLine] | None:
    plan = _require_mapping(payload, "plan")
    kind = plan.get("kind")
    if kind == "orders":
        lines: dict[str, _PlanLine] = {}
        for index, order in enumerate(_require_list(plan, "orders")):
            if not isinstance(order, dict):
                _reject("invalid_plan_line", f"plan.orders[{index}]")
            order_id = order.get("order_id")
            if not isinstance(order_id, str) or not order_id:
                _reject("missing_plan_order_id", f"plan.orders[{index}].order_id")
            if order_id in lines:
                _reject("duplicate_plan_order_id", f"plan.orders[{index}].order_id")
            lines[order_id] = _plan_line(order, f"plan.orders[{index}]")
        return lines
    if kind == "target_weights":
        for index, target in enumerate(_require_list(plan, "target_weights")):
            if not isinstance(target, dict):
                _reject("invalid_plan_line", f"plan.target_weights[{index}]")
            bucket_id = target.get("bucket_id")
            if not isinstance(bucket_id, str) or not bucket_id:
                _reject("missing_bucket_id", f"plan.target_weights[{index}].bucket_id")
        return None
    _reject("invalid_plan_kind", "plan.kind", detail="expected orders or target_weights")


def _target_plan_keys(payload: JsonObject) -> set[tuple[str, str, str]]:
    """Return the target-weight plan lines a generated outcome must describe."""
    plan = _require_mapping(payload, "plan")
    if plan.get("kind") != "target_weights":
        return set()
    keys: set[tuple[str, str, str]] = set()
    for index, target in enumerate(_require_list(plan, "target_weights")):
        bucket_id = target.get("bucket_id")
        symbol = target.get("symbol")
        currency = target.get("currency")
        path = f"plan.target_weights[{index}]"
        if not isinstance(bucket_id, str) or not bucket_id:
            _reject("missing_bucket_id", f"{path}.bucket_id")
        if not isinstance(symbol, str) or not symbol:
            _reject("missing_symbol", f"{path}.symbol")
        if not isinstance(currency, str) or not currency:
            _reject("missing_currency", f"{path}.currency")
        keys.add((bucket_id, symbol, currency))
    return keys


def _internal_plan_lines(order_plan: Any) -> dict[str, _PlanLine] | None:
    if order_plan is None:
        return None
    orders = getattr(order_plan, "orders", None)
    if orders is None:
        return None
    lines: dict[str, _PlanLine] = {}
    for index, order in enumerate(orders):
        path = f"execution.order_plan.orders[{index}]"
        order_id = getattr(order, "plan_order_id", None)
        bucket_id = getattr(order, "bucket_id", None)
        symbol = getattr(order, "symbol", None)
        currency = getattr(order, "currency", None)
        side = getattr(order, "side", None)
        qty = getattr(order, "qty", None)
        if not isinstance(order_id, str) or not order_id:
            _reject("missing_plan_order_id", f"{path}.plan_order_id")
        if not isinstance(bucket_id, str) or not bucket_id:
            _reject("missing_bucket_id", f"{path}.bucket_id")
        if not isinstance(symbol, str) or not symbol:
            _reject("missing_symbol", f"{path}.symbol")
        if not isinstance(currency, str) or not currency:
            _reject("missing_currency", f"{path}.currency")
        if not isinstance(side, str) or side not in {"buy", "sell"}:
            _reject("invalid_side", f"{path}.side")
        if type(qty) is not int or qty <= 0:
            _reject("invalid_qty", f"{path}.qty")
        if order_id in lines:
            _reject("duplicate_plan_order_id", f"{path}.plan_order_id")
        lines[order_id] = _PlanLine(
            bucket_id=bucket_id,
            symbol=symbol,
            currency=currency,
            side=side,
            qty=qty,
        )
    return lines


def _assert_plan_divergence(
    public_lines: dict[str, _PlanLine],
    internal_lines: dict[str, _PlanLine],
) -> None:
    missing = sorted(set(internal_lines) - set(public_lines))
    if missing:
        _reject(
            "plan_line_divergence",
            "plan.orders",
            detail=f"internal plan orders absent from the public plan: {', '.join(missing)}",
        )
    extra = sorted(set(public_lines) - set(internal_lines))
    if extra:
        _reject(
            "plan_line_divergence",
            "plan.orders",
            detail=f"public plan orders absent from the internal plan: {', '.join(extra)}",
        )
    for order_id in sorted(set(public_lines) & set(internal_lines)):
        public = public_lines[order_id]
        internal = internal_lines[order_id]
        for field in ("bucket_id", *_PLAN_LINE_FIELDS):
            if getattr(public, field) != getattr(internal, field):
                _reject(
                    "plan_line_divergence",
                    "plan.orders",
                    detail=f"plan order {order_id!r} disagrees on {field}",
                )


def _assert_success_header(payload: JsonObject) -> None:
    for key in _REQUIRED_SUCCESS_KEYS:
        if key not in payload:
            _reject("missing_field", key, detail=f"required field {key!r} is absent")
    extra = sorted(set(payload) - _SUCCESS_KEYS)
    if extra:
        _reject("unknown_field", extra[0], detail=f"field {extra[0]!r} is not in the result shape")
    if payload["status"] != "success":
        _reject("invalid_status", "status", detail="build_success_payload needs a success document")
    if payload["tool"] != WIRE_TOOL:
        _reject("invalid_tool", "tool")
    if payload["schema_version"] != WIRE_SCHEMA_VERSION:
        _reject("invalid_schema_version", "schema_version")
    if payload["mode"] != WIRE_MODE:
        _reject("invalid_mode", "mode")
    account_id = payload["account_id"]
    if not isinstance(account_id, str) or not account_id:
        _reject("invalid_account_id", "account_id")
    base_currency = payload["base_currency"]
    if not isinstance(base_currency, str) or base_currency not in _CURRENCY_VALUES:
        _reject("invalid_base_currency", "base_currency")
    if not isinstance(payload["complete"], bool):
        _reject("invalid_complete", "complete", detail="complete must be a boolean")
    for key in ("fills", "rejected_orders", "canceled_orders", "warnings", "errors"):
        _require_list(payload, key)
    hashes = _require_mapping(payload, "hashes")
    for key in (
        "plan_hash",
        "planning_data_hash",
        "execution_data_fingerprint",
        "document_hash",
    ):
        value = hashes.get(key)
        if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
            _reject("invalid_hash", f"hashes.{key}")


def _assert_required_nested_members(payload: JsonObject) -> None:
    """Require nested members the frozen Pydantic models would default away."""
    for state_key in ("opening_portfolio", "post_conversion_portfolio", "end_portfolio"):
        state = _require_mapping(payload, state_key)
        for index, bucket in enumerate(_require_list(state, "buckets")):
            if not isinstance(bucket, dict):
                _reject("invalid_bucket", f"{state_key}.buckets[{index}]")
            for key in _BUCKET_REQUIRED_KEYS:
                if key not in bucket:
                    _reject("missing_field", f"{state_key}.buckets[{index}].{key}")
    plan = _require_mapping(payload, "plan")
    if "kind" not in plan:
        _reject("missing_field", "plan.kind")
    if plan.get("kind") == "target_weights" and "rebalance_band" not in plan:
        _reject("missing_field", "plan.rebalance_band")
    if plan.get("kind") == "orders" and "orders" not in plan:
        _reject("missing_field", "plan.orders")


def _assert_result_model(payload: JsonObject) -> None:
    """Validate the full nested result shape with the existing Pydantic models."""
    try:
        PortfolioResult.model_validate(payload)
    except ValidationError as exc:
        first = _first_result_error(exc, payload)
        path = _location_path(tuple(first.get("loc", ())))
        _reject(
            _pydantic_reason(str(first.get("type", "")), path),
            path,
            detail=str(first.get("msg", "invalid result value")),
        )


def _assert_success_links(
    payload: JsonObject,
    *,
    order_plan: Any | None,
) -> None:
    """Require every outcome row to link to a known bucket and plan line."""
    bucket_ids = _bucket_ids(payload)
    plan = _require_mapping(payload, "plan")
    plan_kind = plan.get("kind")
    public_lines = _explicit_plan_lines(payload)
    internal_lines = _internal_plan_lines(order_plan)
    target_keys = _target_plan_keys(payload)
    internal_mode = getattr(order_plan, "mode", None) if order_plan is not None else None
    expected_mode = "explicit_orders" if plan_kind == "orders" else "target_weights"
    if internal_mode is not None and internal_mode != expected_mode:
        _reject(
            "plan_line_divergence",
            "plan.kind",
            detail="the public plan kind disagrees with the internal order plan",
        )
    if plan_kind == "orders":
        if public_lines is None:
            _reject("invalid_plan_kind", "plan.kind")
        if internal_lines is not None:
            _assert_plan_divergence(public_lines, internal_lines)
        expected = public_lines
    else:
        expected = internal_lines

    seen: set[str] = set()
    for field in ("fills", "rejected_orders", "canceled_orders"):
        for index, row in enumerate(_require_list(payload, field)):
            row_path = f"{field}[{index}]"
            if not isinstance(row, dict):
                _reject("invalid_outcome", row_path)
            plan_order_id = row.get("plan_order_id")
            bucket_id = row.get("bucket_id")
            if not isinstance(plan_order_id, str) or not plan_order_id:
                _reject("missing_plan_order_id", f"{row_path}.plan_order_id")
            if not isinstance(bucket_id, str) or not bucket_id:
                _reject("missing_bucket_id", f"{row_path}.bucket_id")
            if bucket_id not in bucket_ids:
                _reject(
                    "unknown_bucket",
                    f"{row_path}.bucket_id",
                    bucket_id=bucket_id,
                    detail="the outcome bucket is not present in the document ledgers",
                )
            if plan_order_id in seen:
                _reject(
                    "duplicate_plan_order_outcome",
                    f"{row_path}.plan_order_id",
                    bucket_id=bucket_id,
                    detail="every plan line has exactly one terminal outcome",
                )
            seen.add(plan_order_id)
            line = expected.get(plan_order_id) if expected is not None else None
            if expected is not None and line is None:
                _reject(
                    "unknown_plan_order",
                    f"{row_path}.plan_order_id",
                    bucket_id=bucket_id,
                    detail="the outcome does not link to a plan line",
                )
            if line is not None and line.bucket_id != bucket_id:
                _reject(
                    "plan_bucket_mismatch",
                    f"{row_path}.bucket_id",
                    bucket_id=bucket_id,
                    detail="the outcome bucket disagrees with its plan line",
                )
            if target_keys and (bucket_id, row.get("symbol"), row.get("currency")) not in target_keys:
                _reject(
                    "unknown_plan_line",
                    row_path,
                    bucket_id=bucket_id,
                    detail="the generated outcome does not match a target-weight plan line",
                )
            if line is not None:
                for subfield in _PLAN_LINE_FIELDS:
                    if row.get(subfield) != getattr(line, subfield):
                        _reject(
                            "plan_line_mismatch",
                            f"{row_path}.{subfield}",
                            bucket_id=bucket_id,
                            detail=f"outcome {subfield} disagrees with its plan line",
                        )

    rejected_or_canceled = bool(payload["rejected_orders"]) or bool(
        payload["canceled_orders"]
    )
    if payload["complete"] is not (not rejected_or_canceled):
        _reject(
            "inconsistent_complete",
            "complete",
            detail="rejects/cancels must force complete=false and a clean run true",
        )

    if expected is not None:
        missing = sorted(set(expected) - seen)
        if missing:
            _reject(
                "missing_plan_outcome",
                "execution",
                detail=f"no terminal outcome for {', '.join(missing)}",
            )

    for index, issue in enumerate(_require_list(payload, "errors")):
        if not isinstance(issue, dict):
            _reject("invalid_issue", f"errors[{index}]")
        detail = issue.get("detail")
        if not isinstance(detail, str) or not detail:
            _reject("missing_field", f"errors[{index}].detail")
        bucket_id = issue.get("bucket_id")
        if bucket_id is not None:
            if not isinstance(bucket_id, str) or not bucket_id:
                _reject("missing_bucket_id", f"errors[{index}].bucket_id")
            if bucket_id not in bucket_ids:
                _reject("unknown_bucket", f"errors[{index}].bucket_id", bucket_id=bucket_id)


def build_success_payload(document: Any) -> JsonObject:
    """Serialize one step result into the public pt-v2.0 success document.

    Accepts a :class:`PortfolioStepResult` (preferred, because its internal
    ``order_plan`` provides the plan-line linkage), a :class:`PortfolioResult`,
    or an already-dumped JSON object for independent re-validation. Floats,
    ``Decimal`` values and non-finite numbers are rejected, never coerced.
    """
    raw, order_plan = _coerce_success(document)
    payload = _normalize_json(raw, "$")
    if not isinstance(payload, dict):
        _reject("invalid_document", "$", detail="the public document must be an object")
    _assert_success_header(payload)
    _assert_required_nested_members(payload)
    _assert_decimal_strings(payload, "$")
    _assert_result_model(payload)
    _assert_success_links(payload, order_plan=order_plan)
    return payload


def error_code_for_exception(exc: BaseException) -> OrchestrationCode:
    """Return the stable code an exception class maps to, including ``INTERNAL``."""
    if isinstance(exc, PortfolioSessionError):
        return exc.code
    if isinstance(exc, PortfolioRequestError):
        return "INVALID_REQUEST"
    if isinstance(exc, OrchestrationError):
        return exc.code
    return "INTERNAL"


def build_error_payload(
    raw_input: Any,
    *,
    code: OrchestrationCode,
    reason: str,
    path: str = "$",
    detail: str = "",
    bucket_id: str | None = None,
) -> JsonObject:
    """Serialize one stable in-band pt-v2.0 error envelope.

    The document contains exactly the packaged error-envelope fields and never
    a ledger/fill member. ``INTERNAL`` is deliberately refused: it is an engine
    fault, not a public in-band code, so :class:`PortfolioWireError` is raised
    and the caller keeps the transport/internal distinction. Every error detail
    ends with ``input_sha256=<digest>`` from :func:`compute_raw_input_hash`.
    """
    if code == "INTERNAL":
        _reject(
            "internal_error_not_in_band",
            path,
            bucket_id=bucket_id,
            detail="INTERNAL faults are transport/engine errors, not pt-v2.0 envelopes",
        )
    if code not in PUBLIC_ERROR_CODES:
        _reject("invalid_error_code", path, detail=f"unsupported public error code {code!r}")
    stable_reason = (
        _wire_text(reason) if isinstance(reason, str) and reason else "invalid_request"
    )
    stable_path = _wire_text(path) if isinstance(path, str) and path else "$"
    stable_detail = (
        _wire_text(detail) if isinstance(detail, str) and detail else stable_reason
    )
    issue: JsonObject = {
        "reason": stable_reason,
        "path": stable_path,
        "detail": _with_input_hash(stable_detail, raw_input),
    }
    if isinstance(bucket_id, str) and bucket_id:
        issue["bucket_id"] = _wire_text(bucket_id)
    payload: JsonObject = {
        "status": "error",
        "tool": WIRE_TOOL,
        "schema_version": WIRE_SCHEMA_VERSION,
        "mode": WIRE_MODE,
        "account_id": _wire_text(_raw_account_id(raw_input)),
        "code": code,
        "error": issue,
    }
    return payload


def build_error_from_exception(
    raw_input: Any,
    exc: BaseException,
    *,
    path: str | None = None,
    detail: str | None = None,
) -> JsonObject:
    """Map a known request/data exception to an in-band error document.

    ``PortfolioRequestError`` -> ``INVALID_REQUEST``; ``PortfolioSessionError``
    keeps its declared code; ``OrchestrationError`` keeps its code but an
    ``INTERNAL`` stage fault is re-raised as :class:`PortfolioWireError` rather
    than masked as a public envelope.
    """
    code = error_code_for_exception(exc)
    if isinstance(exc, (PortfolioRequestError, PortfolioSessionError, OrchestrationError)):
        reason = exc.reason
        resolved_path = path if path is not None else exc.path
        resolved_detail = detail if detail is not None else (exc.detail or str(exc))
        bucket_id = exc.bucket_id
    else:
        reason = "internal_wire_failure"
        resolved_path = path if path is not None else "$"
        resolved_detail = detail if detail is not None else f"{type(exc).__name__}: {exc}"[:200]
        bucket_id = None
        code = "INTERNAL"
    return build_error_payload(
        raw_input,
        code=code,
        reason=reason,
        path=resolved_path,
        detail=resolved_detail,
        bucket_id=bucket_id,
    )


def dumps_payload(payload: Any) -> str:
    """Serialize a public payload with the deterministic strict-JSON spelling.

    Sorted keys + compact separators keep bytes stable; ``ensure_ascii=False``
    keeps UTF-8 raw; every float/Decimal/non-finite/invalid-UTF-8 value is
    rejected before ``json.dumps`` can emit a non-standard token.
    """
    normalized = _normalize_json(payload, "$")
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def serialize_success(document: Any) -> str:
    """Build and dump the public success document in one call."""
    return dumps_payload(build_success_payload(document))


def serialize_error(
    raw_input: Any,
    *,
    code: OrchestrationCode,
    reason: str,
    path: str = "$",
    detail: str = "",
    bucket_id: str | None = None,
) -> str:
    """Build and dump one public error envelope in one call."""
    return dumps_payload(
        build_error_payload(
            raw_input,
            code=code,
            reason=reason,
            path=path,
            detail=detail,
            bucket_id=bucket_id,
        )
    )
