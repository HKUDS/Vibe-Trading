"""Field-level data availability contracts for alpha benchmarks.

The benchmark already exposes universe and run metadata. This module adds a
small, extensible description of when each input can be known. It deliberately
does not replace ``RunManifest`` or ``run_card.json``; callers attach the
returned contract to their existing ``meta`` payload.

Adapters provide market identity and field semantics. A future market can
register an adapter without changing the bench runner or the wire schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol


AVAILABILITY_SCHEMA = "alpha-bench.data-availability/v1"
VALID_STATUSES = frozenset({"verified", "assumed", "unknown", "failed"})
_PRICE_FIELDS = frozenset({"open", "high", "low", "close", "volume", "amount", "vwap"})


@dataclass(frozen=True)
class MarketContext:
    """Stable identity fields shared by all records in one bench."""

    asset_class: str
    venue: str
    currency: str
    timezone: str
    calendar: str


class AvailabilityAdapter(Protocol):
    """Extension point for a market-specific availability policy."""

    name: str

    def context(self, universe: str, metadata: Mapping[str, Any]) -> MarketContext:
        """Return market identity for a panel and its loader metadata."""

    def field_policy(self, field: str, metadata: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return semantics such as ``kind`` and ``availability_mode``."""


@dataclass(frozen=True)
class _BuiltinAdapter:
    name: str
    market: MarketContext

    def context(self, universe: str, metadata: Mapping[str, Any]) -> MarketContext:
        del universe, metadata
        return self.market

    def field_policy(self, field: str, metadata: Mapping[str, Any]) -> Mapping[str, Any]:
        del metadata
        if field == "universe:membership":
            return {"kind": "membership", "availability_mode": "effective_date"}
        if field.startswith("fund:"):
            return {"kind": "event", "availability_mode": "filing_date"}
        if field.startswith("val:"):
            return {"kind": "market", "availability_mode": "session_date"}
        if field == "sector":
            return {"kind": "classification", "availability_mode": "effective_date"}
        if field in _PRICE_FIELDS:
            return {"kind": "bar", "availability_mode": "bar_close"}
        return {"kind": "unknown", "availability_mode": "unknown"}


_ADAPTERS: dict[str, AvailabilityAdapter] = {
    "csi300": _BuiltinAdapter(
        "cn_equity",
        MarketContext("equity", "XSHG+XSHE", "CNY", "Asia/Shanghai", "SSE/SZSE"),
    ),
    "sp500": _BuiltinAdapter(
        "us_equity",
        MarketContext("equity", "XNYS+XNAS", "USD", "America/New_York", "NYSE/NASDAQ"),
    ),
    "hsi": _BuiltinAdapter(
        "hk_equity",
        MarketContext("equity", "XHKG", "HKD", "Asia/Hong_Kong", "XHKG"),
    ),
    "btc-usdt": _BuiltinAdapter(
        "crypto",
        MarketContext("crypto", "global", "USDT", "UTC", "24/7"),
    ),
}
_GENERIC_ADAPTER = _BuiltinAdapter(
    "generic",
    MarketContext("unknown", "unknown", "unknown", "UTC", "unknown"),
)


def register_availability_adapter(universe: str, adapter: AvailabilityAdapter) -> None:
    """Register or replace the adapter used for one universe key.

    Adapters are process-local and intentionally do not alter the benchmark
    registry. Applications that add a new market can register one at startup,
    while the persisted contract remains schema-compatible.
    """
    key = str(universe).strip().lower()
    if not key:
        raise ValueError("universe must be a non-empty string")
    if not getattr(adapter, "name", None):
        raise ValueError("availability adapter must expose a non-empty name")
    _ADAPTERS[key] = adapter


def _metadata(panel: Mapping[str, Any]) -> dict[str, Any]:
    raw = panel.get("_meta")
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        return dict(raw.to_dict())
    except Exception:  # noqa: BLE001 - metadata must never break a bench
        return {"raw": str(raw)}


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return value.date().isoformat()
    except AttributeError:
        text = str(value)
        return text[:10] if text else None


def _json_text(value: Any) -> Any:
    """Keep timestamps and date-like values JSON-safe without losing precision."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


def _panel_window(panel: Mapping[str, Any]) -> dict[str, str | None]:
    starts: list[Any] = []
    ends: list[Any] = []
    for value in panel.values():
        index = getattr(value, "index", None)
        if index is None or len(index) == 0:
            continue
        starts.append(index[0])
        ends.append(index[-1])
    return {
        "start": _date_text(min(starts)) if starts else None,
        "end": _date_text(max(ends)) if ends else None,
    }

def _validation(value: Any) -> dict[str, Any]:
    if not hasattr(value, "notna") or not hasattr(value, "shape"):
        return {"present": value is not None}
    rows, columns = value.shape[:2]
    cells = rows * columns
    if cells == 0:
        return {"present": False, "rows": rows, "symbols": columns, "non_null_ratio": 0.0}
    try:
        non_null = int(value.notna().to_numpy().sum())
    except (AttributeError, TypeError, ValueError):
        return {"present": True, "rows": rows, "symbols": columns}
    return {
        "present": True,
        "rows": rows,
        "symbols": columns,
        "non_null_ratio": round(non_null / cells, 6),
    }


def _source_for(field: str, metadata: Mapping[str, Any], universe: str) -> str | None:
    field_sources = metadata.get("field_sources")
    if isinstance(field_sources, Mapping) and field_sources.get(field):
        return str(field_sources[field])
    if field == "universe:membership":
        return str(metadata["constituent_source"]) if metadata.get("constituent_source") else None
    if field == "sector":
        return str(metadata["sector_source"]) if metadata.get("sector_source") else None
    if field.startswith("fund:"):
        return str(metadata["fundamental_source"]) if metadata.get("fundamental_source") else None
    if field.startswith("val:"):
        return str(metadata["valuation_source"]) if metadata.get("valuation_source") else None
    price_sources = metadata.get("price_sources")
    if isinstance(price_sources, (list, tuple, set)) and price_sources:
        return ",".join(sorted(str(item) for item in price_sources))
    if universe == "csi300":
        return "tushare"
    if universe == "btc-usdt":
        return str(metadata["price_source"]) if metadata.get("price_source") else None
    return None


def _field_status(
    field: str,
    *,
    present: bool,
    source: str | None,
    policy: Mapping[str, Any],
    field_metadata: Mapping[str, Any],
    metadata: Mapping[str, Any],
    required: bool,
) -> tuple[str, bool, str | None]:
    explicit = field_metadata.get("status")
    if explicit in VALID_STATUSES:
        status = str(explicit)
    elif not present:
        status = "failed" if required else "unknown"
    elif field_metadata.get("available_at") or field_metadata.get("availability_timestamp"):
        status = "verified"
    elif policy.get("kind") == "membership":
        status = "verified" if metadata.get("pit_membership") is True else "unknown"
    elif field.startswith("fund:"):
        # A one-bar shift is useful protection, but date-only filings do not
        # prove the exact publication time. Keep this explicitly non-PIT-safe.
        status = "unknown"
    elif source:
        status = "assumed"
    else:
        status = "unknown"

    pit_safe = bool(field_metadata.get("pit_safe", status == "verified"))
    if status != "verified":
        pit_safe = False
    reason = field_metadata.get("reason")
    if reason is None and status == "unknown" and field.startswith("fund:"):
        reason = "source exposes a filing date but no precise publication timestamp"
    return status, pit_safe, str(reason) if reason is not None else None


def build_availability_contract(
    panel: Mapping[str, Any],
    *,
    universe: str,
    period: str | None = None,
    required_fields: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build a JSON-safe field-level availability contract for a bench panel.

    ``required_fields`` may include declared alpha inputs that were absent from
    the loaded panel. Those records receive ``failed`` and make missing inputs
    visible without changing factor calculations.
    """
    universe_key = str(universe).strip().lower()
    metadata = _metadata(panel)
    adapter = _ADAPTERS.get(universe_key, _GENERIC_ADAPTER)
    context = adapter.context(universe_key, metadata)
    required = {str(field) for field in (required_fields or ())}
    observed = {str(field) for field in panel if not str(field).startswith("_")}
    if metadata.get("pit_membership") is not None or metadata.get("survivorship_bias") is not None:
        observed.add("universe:membership")
    fields = sorted(observed | required)
    window = _panel_window(panel)
    contract_fields: list[dict[str, Any]] = []
    field_availability = metadata.get("field_availability")
    if not isinstance(field_availability, Mapping):
        field_availability = {}

    for field in fields:
        value = panel.get(field)
        present = field == "universe:membership" or value is not None
        field_metadata = field_availability.get(field, {})
        if not isinstance(field_metadata, Mapping):
            field_metadata = {}
        policy = adapter.field_policy(field, metadata)
        source = _source_for(field, metadata, universe_key)
        fingerprint = field_metadata.get("fingerprint")
        field_fingerprints = metadata.get("field_fingerprints")
        if not fingerprint and isinstance(field_fingerprints, Mapping):
            fingerprint = field_fingerprints.get(field)
        status, pit_safe, reason = _field_status(
            field,
            present=present,
            source=source,
            policy=policy,
            field_metadata=field_metadata,
            metadata=metadata,
            required=field in required,
        )
        record: dict[str, Any] = {
            "field": field,
            "source": source,
            "observation_date": _json_text(field_metadata.get("observation_date")),
            "observation_window": dict(window),
            "availability_mode": _json_text(
                field_metadata.get("availability_mode", policy.get("availability_mode", "unknown"))
            ),
            "available_at": _json_text(
                field_metadata.get("available_at")
                or field_metadata.get("availability_timestamp")
            ),
            "fingerprint": _json_text(fingerprint),
            "status": status,
            "pit_safe": pit_safe,
            "validation": _validation(value) if field != "universe:membership" else {
                "present": True,
                "pit_membership": metadata.get("pit_membership"),
                "survivorship_bias": metadata.get("survivorship_bias"),
            },
        }
        if reason:
            record["reason"] = reason
        if field_metadata.get("effective_from") is not None:
            record["effective_from"] = _json_text(field_metadata["effective_from"])
        contract_fields.append(record)

    warnings: list[str] = []
    if metadata.get("survivorship_bias"):
        warnings.append("universe membership is not point-in-time and may be survivorship-biased")
    if any(item["status"] == "unknown" for item in contract_fields):
        warnings.append("one or more fields lack a verified availability timestamp")
    return {
        "schema": AVAILABILITY_SCHEMA,
        "adapter": adapter.name,
        "asset_class": context.asset_class,
        "venue": context.venue,
        "currency": context.currency,
        "timezone": context.timezone,
        "calendar": context.calendar,
        "period": {"requested": period, **window},
        "fields": contract_fields,
        "warnings": warnings,
    }
