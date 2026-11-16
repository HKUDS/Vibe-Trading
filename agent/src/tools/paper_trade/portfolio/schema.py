"""Internal pt-v2.0 portfolio parser and packaged JSON contract loader.

This module is intentionally not connected to the legacy ``paper_trade_step``
registration or execution path. It only parses public-shaped input into typed
immutable models and resolves the packaged Draft 2020-12 contract.
"""

from __future__ import annotations

import json
from datetime import timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, Literal

from pydantic import ValidationError

from .errors import PortfolioRequestError as PortfolioRequestError
from .models import FxSnapshot, JsonObject, JsonValue, PortfolioRequest
from .numeric import _CANONICAL_CURRENCIES, _reject

CONTRACT_PATH: Final = Path(__file__).resolve().parent.parent / "paper_trade_step-v2.0.json"
_LEGACY_FIELDS: Final = (
    "market",
    "account_state",
    "from_date",
    "to_date",
    "strategy_path",
    "volume_share",
    "order_volume_ratio",
    "path_model",
    "session",
    "fee_model",
)


def _object(value: JsonValue) -> JsonObject | None:
    if isinstance(value, dict):
        return value
    return None


def _items(value: JsonValue) -> list[JsonValue] | None:
    if isinstance(value, list):
        return value
    return None


def _check_bucket_currency(bucket: JsonObject, path: str) -> None:
    bucket_id = bucket.get("bucket_id")
    identity = bucket_id if isinstance(bucket_id, str) else None
    market = bucket.get("market")
    currency = bucket.get("currency")
    if isinstance(market, str) and market in _CANONICAL_CURRENCIES:
        if currency != _CANONICAL_CURRENCIES[market]:
            _reject("invalid_bucket_currency", f"{path}.currency", bucket_id=identity)
    fee_model = _object(bucket.get("fee_model"))
    fee_currency = fee_model.get("currency") if fee_model is not None else None
    if fee_currency is not None:
        if market == "hk" and fee_currency != "HKD":
            _reject("non_hkd_hk_counter", f"{path}.fee_model.currency", bucket_id=identity)
        if fee_currency != currency:
            _reject("invalid_fee_currency", f"{path}.fee_model.currency", bucket_id=identity)
    if "positions" not in bucket:
        _reject("missing_positions", f"{path}.positions", bucket_id=identity)
    positions = _items(bucket.get("positions")) or []
    for index, raw_position in enumerate(positions):
        position = _object(raw_position)
        if position is None:
            continue
        _check_counter_currency(position, bucket, f"{path}.positions[{index}]")


def _check_counter_currency(row: JsonObject, bucket: JsonObject, path: str) -> None:
    bucket_id = bucket.get("bucket_id")
    identity = bucket_id if isinstance(bucket_id, str) else None
    market = bucket.get("market")
    currency = row.get("currency")
    if market == "hk" and currency != "HKD":
        _reject("non_hkd_hk_counter", f"{path}.currency", bucket_id=identity)
    if currency != bucket.get("currency"):
        _reject("instrument_currency_mismatch", f"{path}.currency", bucket_id=identity)


def _check_plan_counters(payload: JsonObject, field: str, buckets: dict[str, JsonObject]) -> None:
    rows = _items(payload.get(field)) or []
    for index, raw_row in enumerate(rows):
        row = _object(raw_row)
        if row is None:
            continue
        bucket_id = row.get("bucket_id")
        if not isinstance(bucket_id, str) or bucket_id not in buckets:
            continue
        _check_counter_currency(row, buckets[bucket_id], f"{field}[{index}]")


def _preflight(payload: JsonValue) -> None:
    request = _object(payload)
    if request is None:
        return
    for field in ("mode", "schema_version"):
        if field not in request:
            _reject(f"missing_{field}", field)
    if request.get("mode") != "portfolio":
        _reject("invalid_mode", "mode")
    if request.get("schema_version") != "pt-v2.0":
        _reject("invalid_schema_version", "schema_version")
    base_currency = request.get("base_currency")
    if isinstance(base_currency, str) and base_currency not in set(_CANONICAL_CURRENCIES.values()):
        _reject("invalid_base_currency", "base_currency")
    for field in _LEGACY_FIELDS:
        if field in request:
            _reject("legacy_field_forbidden", field)
    if request.get("interval", "1d") != "1d":
        _reject("unsupported_interval", "interval")
    if request.get("fill_model", "all_or_none") != "all_or_none":
        _reject("unsupported_fill_model", "fill_model")
    has_orders = request.get("orders") is not None
    has_targets = request.get("target_weights") is not None
    if "orders" in request and "target_weights" in request:
        _reject("conflicting_order_plan", "orders")
    if not has_orders and not has_targets:
        _reject("missing_order_plan", "$")
    state = _object(request.get("portfolio_state"))
    raw_buckets = _items(state.get("buckets")) if state is not None else None
    buckets: dict[str, JsonObject] = {}
    for index, raw_bucket in enumerate(raw_buckets or []):
        bucket = _object(raw_bucket)
        if bucket is None:
            continue
        _check_bucket_currency(bucket, f"portfolio_state.buckets[{index}]")
        bucket_id = bucket.get("bucket_id")
        if isinstance(bucket_id, str):
            buckets[bucket_id] = bucket
    for field in ("orders", "target_weights"):
        _check_plan_counters(request, field, buckets)


def _location_path(location: tuple[str | int, ...]) -> str:
    path = ""
    for part in location:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += ("." if path else "") + part
    return path or "$"


def _validation_reason(path: str) -> str:
    field = path.rsplit(".", maxsplit=1)[-1].split("[", maxsplit=1)[0]
    if field in {"planning_at", "valuation_at", "as_of", "observed_at"}:
        return "invalid_timestamp"
    if field == "trade_date":
        return "invalid_date"
    if field == "status" and path.startswith("sessions"):
        return "invalid_session"
    return "invalid_field"


def _zero_decimal(value: str) -> bool:
    whole, separator, fraction = value.partition(".")
    return whole == "0" and (not separator or set(fraction) <= {"0"})


def _benchmark_value(value: str, path: str) -> None:
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        _reject("invalid_benchmark_value", path)
    if not parsed.is_finite() or parsed <= 0:
        _reject("invalid_benchmark_value", path)


def _check_benchmark(request: PortfolioRequest, rates: dict[str, FxSnapshot]) -> None:
    """Validate the optional caller benchmark before any provider call."""
    benchmark = request.benchmark
    if benchmark is None:
        return
    for leg, observation in (("start", benchmark.start), ("end", benchmark.end)):
        path = f"benchmark.{leg}"
        _benchmark_value(observation.value, f"{path}.value")
        if observation.currency == request.base_currency:
            if observation.rate_id is not None:
                _reject("unexpected_benchmark_fx_rate", f"{path}.rate_id")
            continue
        if observation.rate_id is None:
            _reject("missing_benchmark_fx_rate", f"{path}.rate_id")
        snapshot = rates.get(observation.rate_id)
        if snapshot is None:
            _reject("unknown_fx_rate", f"{path}.rate_id")
        expected = (observation.currency, request.base_currency)
        pair = (snapshot.from_currency, snapshot.to_currency)
        if pair == (expected[1], expected[0]):
            _reject("inverse_fx_rate_only", f"{path}.rate_id")
        if pair != expected:
            _reject("fx_pair_mismatch", f"{path}.rate_id")
        if snapshot.as_of > observation.observed_at:
            _reject("future_fx_rate", f"{path}.rate_id")
    if benchmark.start.currency != benchmark.end.currency:
        _reject("benchmark_currency_mismatch", "benchmark.end.currency")
    if benchmark.start.observed_at >= benchmark.end.observed_at:
        _reject("invalid_benchmark_observation_order", "benchmark.end.observed_at")
    if benchmark.end.observed_at > request.valuation_at:
        _reject("future_benchmark_observation", "benchmark.end.observed_at")
    if benchmark.end.observed_at.astimezone(timezone.utc).date() != request.trade_date:
        _reject("stale_benchmark_observation", "benchmark.end.observed_at")
    if request.valuation_at - benchmark.end.observed_at > timedelta(days=1):
        _reject("stale_benchmark_observation", "benchmark.end.observed_at")


def _check_semantics(request: PortfolioRequest) -> None:
    if request.base_currency not in set(_CANONICAL_CURRENCIES.values()):
        _reject("invalid_base_currency", "base_currency")
    if request.planning_at >= request.valuation_at:
        _reject("invalid_timestamp_order", "valuation_at")
    if request.orders is not None and not _zero_decimal(request.rebalance_band):
        _reject("unexpected_rebalance_band", "rebalance_band")
    buckets = {bucket.bucket_id: bucket for bucket in request.portfolio_state.buckets}
    session_markets: set[str] = set()
    for index, session in enumerate(request.sessions):
        if session.market in session_markets:
            _reject("duplicate_session", f"sessions[{index}].market")
        session_markets.add(session.market)
    for bucket in request.portfolio_state.buckets:
        if bucket.market not in session_markets:
            _reject("missing_session", "sessions", bucket_id=bucket.bucket_id)
    rates = {}
    for index, snapshot in enumerate(request.fx_snapshots):
        if snapshot.rate_id in rates:
            bucket_id = next(
                (
                    conversion.from_bucket_id
                    for conversion in request.fx_conversions
                    if conversion.rate_id == snapshot.rate_id
                ),
                None,
            )
            _reject("duplicate_fx_rate", f"fx_snapshots[{index}].rate_id", bucket_id=bucket_id)
        rates[snapshot.rate_id] = snapshot
    _check_benchmark(request, rates)
    for index, conversion in enumerate(request.fx_conversions):
        snapshot = rates.get(conversion.rate_id)
        if snapshot is None:
            _reject("unknown_fx_rate", f"fx_conversions[{index}].rate_id", bucket_id=conversion.from_bucket_id)
        source = buckets.get(conversion.from_bucket_id)
        target = buckets.get(conversion.to_bucket_id)
        if source is None:
            _reject("unknown_bucket", f"fx_conversions[{index}].from_bucket_id", bucket_id=conversion.from_bucket_id)
        if target is None:
            _reject("unknown_bucket", f"fx_conversions[{index}].to_bucket_id", bucket_id=conversion.to_bucket_id)
        if snapshot.from_currency != source.currency or snapshot.to_currency != target.currency:
            _reject("fx_pair_mismatch", f"fx_conversions[{index}].rate_id", bucket_id=conversion.from_bucket_id)


def parse_portfolio_request(payload: JsonValue) -> PortfolioRequest:
    """Parse one JSON-shaped payload into the typed pt-v2.0 request envelope."""
    _preflight(payload)
    try:
        request = PortfolioRequest.model_validate(payload)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = tuple(part for part in first["loc"] if isinstance(part, (str, int)))
        path = _location_path(location)
        _reject(_validation_reason(path), path)
    _check_semantics(request)
    return request


def load_portfolio_contract_schema(
    name: Literal["request", "result", "error_envelope"] = "request",
) -> JsonObject:
    """Load one schema from the packaged pt-v2.0 contract, never the mirror."""
    document: JsonObject = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    schemas = document["schemas"]
    assert isinstance(schemas, dict)
    schema = schemas[name]
    assert isinstance(schema, dict)
    return schema
