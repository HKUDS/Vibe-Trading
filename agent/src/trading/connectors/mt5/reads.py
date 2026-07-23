"""MT5 read operations: status, account, positions, orders, quote, history.

Every read runs through :func:`_client._session` (identity guard included)
and returns a fail-closed ``{"status": "error", ...}`` envelope instead of
raising, so tools and CLI degrade cleanly when the SDK/terminal is absent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.trading.connectors.mt5 import _client
from src.trading.connectors.mt5._client import (
    GUARD_MARKER,
    MT5Config,
    MT5ConfigError,
    MT5ConnectionError,
    MT5DependencyError,
    MT5ProfileMismatchError,
    _missing_fields,
    _public_config,
    _resolve_symbol,
    _usd_contract_value,
)

_MT5_ERRORS = (MT5DependencyError, MT5ConfigError, MT5ConnectionError, MT5ProfileMismatchError)

#: Canonical period token → MetaTrader5 timeframe constant name. Resolved via
#: ``getattr`` on the module so fakes only need the integers. NOTE ``1m``
#: (minute) and ``1M`` (month) differ by case, matching the other connectors.
_TIMEFRAME_MAP = {
    "1m": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15",
    "30m": "TIMEFRAME_M30", "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4",
    "1d": "TIMEFRAME_D1", "1w": "TIMEFRAME_W1", "1M": "TIMEFRAME_MN1",
}


def _envelope(cfg: MT5Config, **extra: Any) -> dict[str, Any]:
    """Common payload header stamped on every read result."""
    payload: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "is_demo": cfg.is_demo,
        "paper_guard": GUARD_MARKER,
    }
    payload.update(extra)
    return payload


def _error(cfg: MT5Config, message: str, **extra: Any) -> dict[str, Any]:
    """Fail-closed error payload carrying profile/guard context."""
    payload = _envelope(cfg, **extra)
    payload["status"] = "error"
    payload["error"] = message
    return payload


def check_status(config: MT5Config | None = None) -> dict[str, Any]:
    """Check SDK readiness, config completeness, and terminal/account identity."""
    cfg = config or _client.load_config()
    report: dict[str, Any] = {
        "status": "ok",
        "config": _public_config(cfg),
        "sdk": {"package": "MetaTrader5", "installed": _client.mt5_available()},
        "paper_guard": GUARD_MARKER,
    }
    missing = _missing_fields(cfg)
    if missing:
        report["status"] = "error"
        report["error"] = f"MT5 connector not configured: missing {', '.join(missing)}."
        return report
    if not report["sdk"]["installed"]:
        report["status"] = "error"
        report["error"] = (
            "Optional dependency missing: install with `pip install \"vibe-trading-ai[mt5]\"` "
            "(Windows-only; requires a local MT5 terminal)."
        )
        return report
    try:
        with _client._session(cfg) as mt5:
            account = mt5.account_info()
            report["account"] = {
                "login": int(getattr(account, "login", 0) or 0),
                "server": getattr(account, "server", ""),
                "currency": getattr(account, "currency", ""),
                "leverage": getattr(account, "leverage", None),
                "balance": getattr(account, "balance", None),
                "equity": getattr(account, "equity", None),
                "trade_mode": getattr(account, "trade_mode", None),
                "is_demo": cfg.is_demo,
            }
    except _MT5_ERRORS as exc:
        report["status"] = "error"
        report["error"] = str(exc)
    return report


def get_account_snapshot(config: MT5Config | None = None) -> dict[str, Any]:
    """Fetch account balance/equity/margin for the configured account."""
    cfg = config or _client.load_config()
    try:
        with _client._session(cfg) as mt5:
            account = mt5.account_info()
            payload = {
                "login": int(getattr(account, "login", 0) or 0),
                "name": getattr(account, "name", ""),
                "server": getattr(account, "server", ""),
                "currency": getattr(account, "currency", ""),
                "balance": getattr(account, "balance", None),
                "equity": getattr(account, "equity", None),
                "margin": getattr(account, "margin", None),
                "margin_free": getattr(account, "margin_free", None),
                "margin_level": getattr(account, "margin_level", None),
                "leverage": getattr(account, "leverage", None),
                "trade_mode": getattr(account, "trade_mode", None),
                "is_demo": cfg.is_demo,
            }
    except _MT5_ERRORS as exc:
        return _error(cfg, str(exc))
    return _envelope(cfg, account=payload)


def get_positions(config: MT5Config | None = None) -> dict[str, Any]:
    """Fetch open positions with a USD ``market_value`` per row.

    ``market_value`` is ``None`` when the position cannot be priced in USD —
    the live gate's exposure math treats that as unparseable and fails closed
    rather than under-counting exposure.
    """
    cfg = config or _client.load_config()
    try:
        with _client._session(cfg) as mt5:
            sell_type = getattr(mt5, "POSITION_TYPE_SELL", 1)
            rows = []
            for pos in mt5.positions_get() or ():
                symbol = getattr(pos, "symbol", "")
                rows.append(
                    {
                        "ticket": getattr(pos, "ticket", None),
                        "symbol": symbol,
                        "side": "sell" if getattr(pos, "type", 0) == sell_type else "buy",
                        "volume": getattr(pos, "volume", None),
                        "price_open": getattr(pos, "price_open", None),
                        "price_current": getattr(pos, "price_current", None),
                        "sl": getattr(pos, "sl", None),
                        "tp": getattr(pos, "tp", None),
                        "swap": getattr(pos, "swap", None),
                        "profit": getattr(pos, "profit", None),
                        "time": getattr(pos, "time", None),
                        "market_value": _usd_contract_value(
                            mt5, cfg, symbol, float(getattr(pos, "volume", 0.0) or 0.0)
                        ),
                    }
                )
    except _MT5_ERRORS as exc:
        return _error(cfg, str(exc))
    return _envelope(cfg, positions=rows)


def get_open_orders(config: MT5Config | None = None, *, include_executions: bool = False) -> dict[str, Any]:
    """Fetch pending orders (open positions are a separate read) and, optionally, recent deals."""
    cfg = config or _client.load_config()
    try:
        with _client._session(cfg) as mt5:
            rows = []
            for order in mt5.orders_get() or ():
                rows.append(
                    {
                        "order_id": str(getattr(order, "ticket", "")),
                        "symbol": getattr(order, "symbol", ""),
                        "order_type": getattr(order, "type", None),
                        "volume": getattr(order, "volume_initial", None),
                        "volume_current": getattr(order, "volume_current", None),
                        "price_open": getattr(order, "price_open", None),
                        "sl": getattr(order, "sl", None),
                        "tp": getattr(order, "tp", None),
                        "time_setup": getattr(order, "time_setup", None),
                        "state": getattr(order, "state", None),
                    }
                )
            executions = None
            if include_executions:
                now = datetime.now(timezone.utc)
                deals = mt5.history_deals_get(now - timedelta(days=7), now) or ()
                executions = [
                    {
                        "deal_id": str(getattr(deal, "ticket", "")),
                        "order_id": str(getattr(deal, "order", "")),
                        "symbol": getattr(deal, "symbol", ""),
                        "volume": getattr(deal, "volume", None),
                        "price": getattr(deal, "price", None),
                        "profit": getattr(deal, "profit", None),
                        "time": getattr(deal, "time", None),
                    }
                    for deal in deals
                ]
    except _MT5_ERRORS as exc:
        return _error(cfg, str(exc))
    result = _envelope(cfg, open_orders=rows)
    if include_executions:
        result["executions"] = executions
    return result


def get_quote(symbol: str, *, config: MT5Config | None = None, **_: Any) -> dict[str, Any]:
    """Fetch the current tick for ``symbol`` (suffix-aware broker resolution).

    ``last`` is omitted when the terminal reports 0 (common on forex ticks) so
    the live gate's quote parser falls through to bid/ask instead of a zero.
    """
    cfg = config or _client.load_config()
    clean = str(symbol or "").strip().upper()
    try:
        with _client._session(cfg) as mt5:
            name = _resolve_symbol(mt5, cfg, symbol)
            tick = mt5.symbol_info_tick(name)
            if tick is None:
                return _error(cfg, f"no tick data for {name!r}", symbol=clean)
            quote: dict[str, Any] = {
                "bid": getattr(tick, "bid", None),
                "ask": getattr(tick, "ask", None),
                "time": getattr(tick, "time", None),
            }
            last = float(getattr(tick, "last", 0.0) or 0.0)
            if last > 0:
                quote["last"] = last
            info = mt5.symbol_info(name)
            if info is not None:
                quote["spread"] = getattr(info, "spread", None)
    except _MT5_ERRORS as exc:
        return _error(cfg, str(exc), symbol=clean)
    return _envelope(cfg, symbol=clean, resolved_symbol=name, quote=quote)


def get_historical_bars(
    symbol: str,
    *,
    config: MT5Config | None = None,
    period: str = "1d",
    limit: int = 90,
    **_: Any,
) -> dict[str, Any]:
    """Fetch recent OHLCV bars from the terminal's local history."""
    cfg = config or _client.load_config()
    clean = str(symbol or "").strip().upper()
    timeframe_name = _TIMEFRAME_MAP.get(period.strip(), "TIMEFRAME_D1")
    try:
        with _client._session(cfg) as mt5:
            name = _resolve_symbol(mt5, cfg, symbol)
            timeframe = getattr(mt5, timeframe_name)
            rates = mt5.copy_rates_from_pos(name, timeframe, 0, int(limit))
            bars = [_rate_to_dict(rate) for rate in (rates if rates is not None else ())]
    except _MT5_ERRORS as exc:
        return _error(cfg, str(exc), symbol=clean)
    return _envelope(
        cfg, symbol=clean, resolved_symbol=name, period=period,
        timeframe=timeframe_name, bars=bars,
    )


def _int_or_none(value: Any) -> int | None:
    """Cast *value* to a plain Python int (handles numpy scalars). Return None for None."""
    if value is None:
        return None
    return int(value)


def _float_or_none(value: Any) -> float | None:
    """Cast *value* to a plain Python float (handles numpy scalars). Return None for None."""
    if value is None:
        return None
    return float(value)


def _rate_to_dict(rate: Any) -> dict[str, Any]:
    """Map one rates row (numpy structured row, mapping, or object) defensively."""

    def _get(key: str) -> Any:
        try:
            return rate[key]  # numpy structured rows and mappings
        except (TypeError, KeyError, IndexError, ValueError):
            return getattr(rate, key, None)

    volume = _get("tick_volume")
    return {
        "time": _int_or_none(_get("time")),
        "open": _float_or_none(_get("open")),
        "high": _float_or_none(_get("high")),
        "low": _float_or_none(_get("low")),
        "close": _float_or_none(_get("close")),
        "volume": _int_or_none(volume),
        "spread": _int_or_none(_get("spread")),
        "real_volume": _int_or_none(_get("real_volume")),
    }
