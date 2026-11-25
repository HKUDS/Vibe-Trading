"""Success-document validation and build for the public pt-v2.0 wire.

Every success payload passes the header, nested-member, decimal-string,
Pydantic-model and plan-linkage gates before it can be published; each gate
raises :class:`~.wire_errors.PortfolioWireError` (INTERNAL transport) rather
than shipping a document an auditor cannot route.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from .models import JsonObject, JsonValue, PortfolioModel, PortfolioResult
from .wire_analytics import (
    _analytics_sum,
    _assert_attribution,
    _assert_benchmark,
    _decimal_value,
)
from .wire_contract import (
    WIRE_MODE,
    WIRE_SCHEMA_VERSION,
    WIRE_TOOL,
    _BUCKET_REQUIRED_KEYS,
    _CURRENCY_VALUES,
    _HASH_PATTERN,
    _PLAN_LINE_FIELDS,
    _REQUIRED_SUCCESS_KEYS,
    _SUCCESS_KEYS,
    _PlanLine,
)
from .wire_errors import _reject
from .wire_normalize import (
    _assert_decimal_strings,
    _first_result_error,
    _location_path,
    _normalize_json,
    _pydantic_reason,
)


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


def _assert_analytics(payload: JsonObject) -> None:
    """When present, analytics must agree with the public bucket ledger."""
    raw = payload.get("analytics")
    if raw is None:
        return
    if not isinstance(raw, dict):
        _reject("invalid_analytics", "analytics", detail="analytics must be an object")
    base_currency = payload["base_currency"]
    if raw.get("base_currency") != base_currency:
        _reject(
            "analytics_base_currency_mismatch",
            "analytics.base_currency",
            detail="analytics must use the document base currency",
        )
    nav = _decimal_value(raw.get("nav_base"), "analytics.nav_base")
    bucket_nav = sum(
        (
            _decimal_value(row.get("nav_base"), f"bucket_results[{index}].nav_base")
            for index, row in enumerate(_require_list(payload, "bucket_results"))
            if isinstance(row, dict)
        ),
        Decimal(0),
    )
    if nav != bucket_nav:
        _reject(
            "analytics_nav_mismatch",
            "analytics.nav_base",
            detail="analytics NAV differs from the bucket ledger NAV",
        )
    bridge = _require_mapping(raw, "nav_bridge")
    bridge_nav = _decimal_value(bridge.get("nav_base"), "analytics.nav_bridge.nav_base")
    if bridge_nav != nav:
        _reject(
            "analytics_nav_mismatch",
            "analytics.nav_bridge.nav_base",
            detail="the NAV bridge headline differs from analytics NAV",
        )
    bridge_cash = _decimal_value(
        bridge.get("cash_base"), "analytics.nav_bridge.cash_base"
    )
    bridge_positions = _decimal_value(
        bridge.get("position_value_base"), "analytics.nav_bridge.position_value_base"
    )
    bridge_rounding = _decimal_value(
        bridge.get("valuation_rounding"), "analytics.nav_bridge.valuation_rounding"
    )
    if bridge_cash + bridge_positions + bridge_rounding != nav:
        _reject(
            "analytics_nav_bridge_mismatch",
            "analytics.nav_bridge",
            detail="cash plus positions plus rounding must equal NAV",
        )
    positions = _decimal_value(
        raw.get("position_value_base"), "analytics.position_value_base"
    )
    bucket_values = _analytics_sum(
        _require_list(raw, "bucket_exposures"), "analytics.bucket_exposures"
    )
    if bucket_values != nav:
        _reject(
            "analytics_bucket_nav_mismatch",
            "analytics.bucket_exposures",
            detail="bucket exposure values must sum to NAV",
        )
    if _analytics_sum(
        _require_list(raw, "currency_exposures"), "analytics.currency_exposures"
    ) != nav:
        _reject(
            "analytics_currency_nav_mismatch",
            "analytics.currency_exposures",
            detail="currency exposure values must sum to NAV",
        )
    if _analytics_sum(
        _require_list(raw, "market_exposures"), "analytics.market_exposures"
    ) != nav:
        _reject(
            "analytics_market_nav_mismatch",
            "analytics.market_exposures",
            detail="market exposure values must sum to NAV",
        )
    if _analytics_sum(
        _require_list(raw, "sector_exposures"), "analytics.sector_exposures"
    ) != positions:
        _reject(
            "analytics_sector_mismatch",
            "analytics.sector_exposures",
            detail="sector values including unclassified must sum to position value",
        )
    exact_nav = _decimal_value(raw.get("exact_nav_base"), "analytics.exact_nav_base")
    attribution = raw.get("attribution")
    if attribution is not None:
        if not isinstance(attribution, dict):
            _reject(
                "invalid_analytics",
                "analytics.attribution",
                detail="attribution must be an object",
            )
        _assert_attribution(
            attribution,
            nav=nav,
            exact_nav=exact_nav,
            base_currency=base_currency,
        )
    if "benchmark" not in raw:
        return
    benchmark = raw.get("benchmark")
    if benchmark is None:
        return
    if not isinstance(benchmark, dict):
        _reject(
            "invalid_analytics",
            "analytics.benchmark",
            detail="benchmark must be an object or null",
        )
    _assert_benchmark(benchmark, nav=nav, exact_nav=exact_nav)


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

    _assert_analytics(payload)


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
