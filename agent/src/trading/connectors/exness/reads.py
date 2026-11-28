"""Exness read adapters: status, account, positions, orders, quote, bars, search.

Every function returns a ``{"status": "ok" | "error", ...}`` envelope and
never raises. Positions carry a USD ``market_value`` (``None`` when
unpriceable) so the live gate's exposure math fails closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.trading.connectors.exness import _client, _market
from src.trading.connectors.exness._client import (
    GUARD_MARKER,
    ExnessAPIError,
    ExnessConfig,
    ExnessConfigError,
    _missing_fields,
    credential_source,
    missing_credential_code,
    public_config,
)
from src.trading.connectors.exness._market import SymbolResolutionError, to_float
from src.trading.connectors.mt5.symbols import classify_mt5_symbol

ERRORS = (ExnessAPIError, ExnessConfigError, SymbolResolutionError)

#: Canonical period token → Exness timeframe (``1m`` minute vs ``1M`` month by case).
TIMEFRAME_MAP = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "1H": "H1", "4h": "H4", "4H": "H4",
    "1d": "D1", "1D": "D1", "1w": "W1", "1W": "W1", "1M": "MN",
}
_MAX_BAR_PAGES = 20
_DEALS_LOOKBACK_DAYS = 7
_DEALS_PAGE_SIZE = 200
_AUTH_CODES = {1000: "auth_failed", 1001: "auth_failed", 1002: "auth_permission_denied", 1003: "rate_limited"}


def envelope(cfg: ExnessConfig, **extra: Any) -> dict[str, Any]:
    """Common payload header stamped on every result."""
    payload: dict[str, Any] = {"status": "ok", "profile": cfg.profile, "environment": cfg.environment,
                               "guard": GUARD_MARKER}
    payload.update(extra)
    return payload


def error(cfg: ExnessConfig, message: str, **extra: Any) -> dict[str, Any]:
    """Fail-closed error payload carrying profile/guard context."""
    payload = envelope(cfg, **extra)
    payload["status"] = "error"
    payload["error"] = message
    return payload


def error_code(exc: Exception) -> str:
    """Stable machine code for an exception (auth / rate limit / network / api)."""
    if isinstance(exc, ExnessAPIError):
        if exc.code in _AUTH_CODES:
            return _AUTH_CODES[exc.code]
        if exc.status == 429:
            return "rate_limited"
        return "network_error" if exc.status is None else "api_error"
    if isinstance(exc, SymbolResolutionError):
        return "unknown_symbol"
    return "config_error"


def _account_settings(client: _client.ExnessClient) -> dict[str, Any]:
    payload = client.get(client.account_path("configuration", "account"))
    settings = (payload or {}).get("settings") or {}
    return {
        "account_name": payload.get("account_name"),
        "currency": settings.get("currency"),
        "leverage": settings.get("leverage"),
        "trade_mode": settings.get("trade_mode"),
        "account_status": settings.get("account_status"),
        "execution_mode": settings.get("execution_mode"),
    }


def check_status(config: ExnessConfig | None = None) -> dict[str, Any]:
    """Check config completeness, host discovery and key validity (reads ``/account``)."""
    try:
        cfg = config or _client.load_config()
    except ExnessConfigError as exc:
        return {"status": "error", "configured": False, "connection_state": "not_configured",
                "error_code": "config_error", "error": str(exc), "guard": GUARD_MARKER}
    report = envelope(cfg, configured=False, credential_source=credential_source(), config=public_config(cfg),
                      connection_state="not_configured")
    missing = _missing_fields(cfg)
    if missing:
        report.update(status="error", error_code=missing_credential_code(cfg),
                      error=f"Exness connector not configured: missing {', '.join(missing)}.")
        return report
    report["configured"] = True
    try:
        report["account"] = _account_settings(_client.make_client(cfg))
    except ERRORS as exc:
        report.update(status="error", connection_state="error", error_code=error_code(exc), error=str(exc))
        return report
    report["connection_state"] = "connected"
    return report


def get_account_snapshot(config: ExnessConfig | None = None) -> dict[str, Any]:
    """Balance / equity / margin (account currency) plus account settings."""
    cfg = config or _client.load_config()
    try:
        client = _client.make_client(cfg)
        state = (client.get(client.account_path("trading", "snapshot")) or {}).get("account_state") or {}
        settings = _account_settings(client)
    except ERRORS as exc:
        return error(cfg, str(exc), error_code=error_code(exc))
    equity = to_float(state.get("equity"))
    used = to_float(state.get("used_margin"))
    account = {
        **settings,
        "balance": to_float(state.get("balance")),
        "equity": equity,
        "margin": used,
        "margin_free": (equity - used) if equity is not None and used is not None else None,
    }
    return envelope(cfg, account=account)


def get_positions(config: ExnessConfig | None = None) -> dict[str, Any]:
    """Open positions with a USD ``market_value`` per row (``None`` when unpriceable)."""
    cfg = config or _client.load_config()
    try:
        client = _client.make_client(cfg)
        snapshot = client.get(client.account_path("trading", "snapshot")) or {}
        rows = []
        for pos in snapshot.get("positions") or []:
            name = str(pos.get("instrument") or "")
            lots = to_float(pos.get("volume")) or 0.0
            rows.append({
                "position_id": str(pos.get("position_id") or ""),
                "symbol": name,
                "side": "sell" if pos.get("direction") == "sell" else "buy",
                "quantity": lots,
                "price_open": to_float(pos.get("open_price")),
                "swap": to_float(pos.get("swap")),
                "commission": to_float(pos.get("commission")),
                "time": pos.get("create_time"),
                "market_value": _market.usd_value(client, name, lots) if name else None,
            })
    except ERRORS as exc:
        return error(cfg, str(exc), error_code=error_code(exc))
    return envelope(cfg, positions=rows)


def _order_row(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_id": str(order.get("order_id") or ""),
        "position_id": order.get("position_id"),
        "symbol": order.get("instrument"),
        "side": order.get("direction"),
        "order_type": order.get("order_type"),
        "state": order.get("state"),
        "quantity": to_float(order.get("volume")),
        "limit_price": to_float(order.get("price")),
        "stop_loss": to_float(order.get("stop_loss_price")),
        "take_profit": to_float(order.get("take_profit_price")),
        "time": order.get("create_time"),
    }


def _recent_deals(client: _client.ExnessClient) -> list[dict[str, Any]]:
    path = client.account_path("history", "deals")
    start = (_market.utc_now() - timedelta(days=_DEALS_LOOKBACK_DAYS)).isoformat()
    params: dict[str, Any] = {"from": start, "limit": _DEALS_PAGE_SIZE}
    deals: list[dict[str, Any]] = []
    for _ in range(_MAX_BAR_PAGES):
        page = client.get(path, params=params) or {}
        for item in page.get("items") or []:
            deal = item.get("deal") or {}
            deals.append({
                "deal_id": str(deal.get("deal_id") or ""),
                "order_id": deal.get("order_id"),
                "position_id": deal.get("position_id"),
                "type": deal.get("type"),
                "symbol": deal.get("instrument"),
                "side": deal.get("direction"),
                "quantity": to_float(deal.get("volume")),
                "price": to_float(deal.get("price")),
                "profit": to_float((deal.get("profit") or {}).get("amount")),
                "time": deal.get("create_time") or item.get("event_time"),
            })
        cursor = page.get("next_cursor")
        if not page.get("has_more") or not cursor:
            break
        params = {"cursor": cursor, "limit": _DEALS_PAGE_SIZE}
    return deals


def get_open_orders(config: ExnessConfig | None = None, *, include_executions: bool = False) -> dict[str, Any]:
    """Pending orders (positions are a separate read) and, optionally, the last 7 days of deals."""
    cfg = config or _client.load_config()
    try:
        client = _client.make_client(cfg)
        snapshot = client.get(client.account_path("trading", "snapshot")) or {}
        rows = [_order_row(o) for o in snapshot.get("orders") or []]
        executions = _recent_deals(client) if include_executions else None
    except ERRORS as exc:
        return error(cfg, str(exc), error_code=error_code(exc))
    result = envelope(cfg, open_orders=rows)
    if include_executions:
        result["executions"] = executions
    return result


def _price_rounder(client: _client.ExnessClient, name: str):
    """Round to the instrument's ``point_digits`` (Exness JSON prices carry float noise).

    Unknown precision leaves values untouched rather than guessing.
    """
    digits = _market.conditions(client, name).get("point_digits")
    if not isinstance(digits, int) or digits < 0:
        return lambda value: value
    return lambda value: round(value, digits) if isinstance(value, float) else value


def get_quote(symbol: str, *, config: ExnessConfig | None = None, **_: Any) -> dict[str, Any]:
    """Latest bid/ask from the most recent M1 candle (labelled ``quote_source: candle``)."""
    cfg = config or _client.load_config()
    clean = str(symbol or "").strip().upper()
    try:
        client = _client.make_client(cfg)
        name = _market.resolve_symbol(client, symbol)
        quote = _market.latest_bid_ask(client, name)
        rnd = _price_rounder(client, name)
    except ERRORS as exc:
        return error(cfg, str(exc), symbol=clean, error_code=error_code(exc))
    if quote is None:
        return error(cfg, f"no recent candle data for {name!r}", symbol=clean, resolved_symbol=name)
    return envelope(cfg, symbol=clean, resolved_symbol=name, quote={
        "bid": rnd(quote["bid"]), "ask": rnd(quote["ask"]), "time": quote["time"], "quote_source": "candle",
    })


def search_instruments(query: str, *, config: ExnessConfig | None = None, limit: int = 10) -> dict[str, Any]:
    """Filter the account's instrument catalog by substring (case-insensitive)."""
    cfg = config or _client.load_config()
    try:
        bounded = max(1, min(int(limit), 50))
    except (TypeError, ValueError, OverflowError):
        bounded = 10
    needle = str(query or "").strip().upper().replace("/", "")
    try:
        names = _market.catalog(_client.make_client(cfg))
    except ERRORS as exc:
        return {"status": "error", "error": str(exc), "instruments": [], "catalog_only": True}
    instruments = []
    for name in names:
        if needle and needle not in name.upper():
            continue
        kind, _ = classify_mt5_symbol(name)
        instruments.append({"symbol": name, "native_symbol": name, "market": "fx" if kind.value == "forex" else "cfd",
                            "type": kind.value, "exchange": "Exness", "venue": "Exness"})
        if len(instruments) >= bounded:
            break
    return {"status": "ok", "query": query, "instruments": instruments, "catalog_only": True}


def _bar(candle: dict[str, Any]) -> dict[str, Any]:
    return {"time": candle.get("time"), "open": to_float(candle.get("open")), "high": to_float(candle.get("high")),
            "low": to_float(candle.get("low")), "close": to_float(candle.get("close")),
            "volume": to_float(candle.get("volume"))}


def get_historical_bars(symbol: str, *, config: ExnessConfig | None = None, period: str = "1d",
                        limit: int = 90, **_: Any) -> dict[str, Any]:
    """Most recent ``limit`` bid OHLCV bars, paged backwards within ``max_candles_per_request``."""
    cfg = config or _client.load_config()
    clean = str(symbol or "").strip().upper()
    timeframe = TIMEFRAME_MAP.get(str(period or "").strip())
    if timeframe is None:
        return error(cfg, f"unsupported period {period!r}; use one of {', '.join(sorted(set(TIMEFRAME_MAP)))}",
                     symbol=clean)
    wanted = max(1, int(limit or 1))
    try:
        client = _client.make_client(cfg)
        name = _market.resolve_symbol(client, symbol)
        rnd = _price_rounder(client, name)
        page_cap = _market.candle_limit(client)
        bars: dict[str, dict[str, Any]] = {}
        cursor = _market._utc_now_iso()
        for _ in range(_MAX_BAR_PAGES):
            remaining = wanted - len(bars)
            if remaining <= 0:
                break
            page = client.get(client.account_path("market-data", "candles"), params={
                "instrument": name, "timeframe": timeframe, "price_type": "bid",
                "from": cursor, "count": -min(remaining, page_cap),
            }) or {}
            fresh = [c for c in page.get("candles") or [] if c.get("time") and c["time"] not in bars]
            if not fresh:
                break
            for candle in fresh:
                bars[candle["time"]] = _bar(candle)
            cursor = min(fresh, key=lambda c: _parse_time(c["time"]))["time"]
    except ERRORS as exc:
        return error(cfg, str(exc), symbol=clean, error_code=error_code(exc))
    ordered = [
        {**bar, **{k: rnd(bar[k]) for k in ("open", "high", "low", "close")}}
        for bar in sorted(bars.values(), key=lambda b: _parse_time(b["time"]))[-wanted:]
    ]
    return envelope(cfg, symbol=clean, resolved_symbol=name, period=period, timeframe=timeframe, bars=ordered)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
