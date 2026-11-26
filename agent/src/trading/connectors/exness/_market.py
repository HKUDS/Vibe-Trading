"""Instrument catalog, conditions, limits and USD pricing for the Exness connector.

Shared by reads (position ``market_value``) and orders (the live gate's
``quantity_notional_usd`` hook). Every pricing helper returns ``None`` rather
than guessing, so the mandate gate fails closed on anything it cannot price.

Caches are per process and keyed by account id: the catalog, conditions and
limits are static or semi-static configuration per the API docs.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from src.trading.connectors.exness._client import ExnessClient
from src.trading.connectors.mt5.symbols import normalize_base, split_suffix

_CATALOG: dict[str, list[str]] = {}
_CONDITIONS: dict[tuple[str, str], dict[str, Any]] = {}
_CANDLE_LIMIT: dict[str, int] = {}
_QUOTES: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
DEFAULT_CANDLE_LIMIT = 500
QUOTE_CACHE_SECONDS = 2.0


class SymbolResolutionError(ValueError):
    """The requested symbol is unknown or ambiguous on this account."""


def reset_caches() -> None:
    """Clear catalog/conditions/limits caches (tests; or after an account change)."""
    _CATALOG.clear()
    _CONDITIONS.clear()
    _CANDLE_LIMIT.clear()
    _QUOTES.clear()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_now() -> datetime:
    """Current UTC time (patchable through ``_utc_now_iso`` in tests)."""
    return datetime.fromisoformat(_utc_now_iso())


def to_float(value: Any) -> float | None:
    """Parse an API decimal string/number; ``None`` when absent or malformed."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def catalog(client: ExnessClient) -> list[str]:
    """Instrument names tradable on the account (cached)."""
    key = client.cfg.account_id
    if key not in _CATALOG:
        payload = client.get(client.account_path("configuration", "instruments"))
        names = payload.get("instruments") if isinstance(payload, dict) else None
        _CATALOG[key] = [str(n) for n in (names or []) if str(n).strip()]
    return _CATALOG[key]


def resolve_symbol(client: ExnessClient, symbol: str) -> str:
    """Map ``EUR/USD`` / ``eurusd`` / ``EURUSD.FX`` to the account's instrument name.

    Exact (normalized) matches win; otherwise a single broker-suffixed variant
    is accepted. Several variants is an error — never an arbitrary pick.

    Raises:
        SymbolResolutionError: Unknown or ambiguous symbol.
    """
    wanted = normalize_base(str(symbol or ""))
    if not wanted:
        raise SymbolResolutionError("symbol is required")
    names = catalog(client)
    for name in names:
        if normalize_base(name) == wanted:
            return name
    variants = [n for n in names if split_suffix(normalize_base(n))[0] == wanted]
    if len(variants) == 1:
        return variants[0]
    if variants:
        raise SymbolResolutionError(
            f"{symbol!r} matches several Exness instruments ({', '.join(variants[:5])}); pass the exact name"
        )
    raise SymbolResolutionError(f"{symbol!r} is not an instrument on this Exness account")


def conditions(client: ExnessClient, name: str) -> dict[str, Any]:
    """Trading conditions for one instrument (contract size, volume rules, currencies)."""
    key = (client.cfg.account_id, name)
    if key not in _CONDITIONS:
        payload = client.get(client.account_path("configuration", "instruments", name, "conditions"))
        _CONDITIONS[key] = payload if isinstance(payload, dict) else {}
    return _CONDITIONS[key]


def candle_limit(client: ExnessClient) -> int:
    """``max_candles_per_request`` for ``getCandleHistory`` (cached; conservative default)."""
    key = client.cfg.account_id
    if key not in _CANDLE_LIMIT:
        limit = DEFAULT_CANDLE_LIMIT
        payload = client.get(client.account_path("configuration", "limits"))
        methods = (((payload or {}).get("limits") or {}).get("rest") or {}).get("methods") or []
        for method in methods:
            if isinstance(method, dict) and method.get("api_operation_id") == "getCandleHistory":
                value = (method.get("limits") or {}).get("max_candles_per_request")
                if isinstance(value, int) and value > 0:
                    limit = value
        _CANDLE_LIMIT[key] = limit
    return _CANDLE_LIMIT[key]


def latest_bid_ask(client: ExnessClient, name: str) -> dict[str, Any] | None:
    """Bid/ask from the most recent M1 candle (the REST API has no quote endpoint).

    Reused for ``QUOTE_CACHE_SECONDS``: one live order prices the same
    instrument several times (gate sizing, connector guards, instant price)
    and ``getCandleHistory`` is limited to 2 requests/second.
    """
    key = (client.cfg.account_id, name)
    cached = _QUOTES.get(key)
    if cached and time.monotonic() - cached[0] < QUOTE_CACHE_SECONDS:
        return cached[1]
    quote = _fetch_bid_ask(client, name)
    if quote is not None:
        _QUOTES[key] = (time.monotonic(), quote)
    return quote


def _fetch_bid_ask(client: ExnessClient, name: str) -> dict[str, Any] | None:
    payload = client.get(
        client.account_path("market-data", "candles"),
        params={"instrument": name, "timeframe": "M1", "price_type": "both", "from": _utc_now_iso(), "count": -1},
    )
    candles = payload.get("candles") if isinstance(payload, dict) else None
    if not candles:
        return None
    last = candles[-1]
    bid = to_float((last.get("bid") or {}).get("close"))
    ask = to_float((last.get("ask") or {}).get("close"))
    if not bid or not ask or bid <= 0 or ask <= 0:
        return None
    return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0, "time": last.get("time")}


def _mid(client: ExnessClient, name: str) -> float | None:
    quote = latest_bid_ask(client, name)
    return quote["mid"] if quote else None


def usd_value(client: ExnessClient, name: str, lots: float) -> float | None:
    """USD value of ``lots`` of instrument ``name``; ``None`` on any failure (fail-closed).

    1 lot == ``contract_size`` units of the base currency. Base=USD is exact;
    quote=USD prices through the latest mid; crosses convert the base through
    the account's ``<BASE>USD`` / ``USD<BASE>`` instrument when offered.
    """
    try:
        info = conditions(client, name)
        size = to_float(info.get("contract_size")) or 0.0
        if size <= 0 or lots <= 0:
            return None
        base = str(info.get("base_currency") or "").upper()
        quote = str(info.get("quote_currency") or "").upper()
        units = lots * size
        if base == "USD":
            return units
        if quote == "USD":
            mid = _mid(client, name)
            return units * mid if mid else None
        names = {normalize_base(n): n for n in catalog(client)}
        direct = names.get(base + "USD")
        if direct:
            mid = _mid(client, direct)
            return units * mid if mid else None
        inverse = names.get("USD" + base)
        if inverse:
            mid = _mid(client, inverse)
            return units / mid if mid else None
    except Exception:  # noqa: BLE001 - pricing must fail closed, never raise
        return None
    return None
