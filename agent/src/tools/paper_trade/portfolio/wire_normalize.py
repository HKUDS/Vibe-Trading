"""Strict-JSON normalization and Pydantic rejection-reason mapping.

``_normalize_json`` deep-copies a document into hostile-numeric-free JSON and
``_assert_decimal_strings`` enforces canonical fixed-point spellings; the
reason helpers translate one Pydantic validation error into the stable public
reason/path pair the wire contract promises.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

from pydantic import ValidationError

from .models import JsonObject, JsonValue, PortfolioModel
from .wire_contract import _DECIMAL_KEYS, _DECIMAL_PATTERN
from .wire_errors import _reject

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
