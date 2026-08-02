"""MT5 order operations: sizing hook, place, cancel/close (risk-reducing).

Validation runs before any SDK touch and every failure returns a fail-closed
``{"status": "error", ...}`` payload. Connector-level size guards
(``max_order_volume`` / ``max_order_notional_usd``) apply to demo AND live —
defense-in-depth underneath the live mandate gate.

Hedging note: MT5 accounts (Exness default) are usually HEDGING accounts — an
opposite-side ``place_order`` OPENS a hedge, it does not close the existing
position. Closing goes through :func:`cancel_order`/:func:`close_position`
with the position ticket, which pins the deal to ``position=`` so it can only
ever reduce exposure. ``src.live.runtime.flatten`` submits via the generic
``place_order`` and therefore hedges rather than closes on MT5 — acceptable
(net exposure to price moves is neutralized) but a ticket-pinned flatten is a
documented follow-up.
"""

from __future__ import annotations

import math
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
    _resolve_symbol,
    _usd_contract_value,
)

_MT5_ERRORS = (MT5DependencyError, MT5ConfigError, MT5ConnectionError, MT5ProfileMismatchError)

_ORDER_COMMENT = "vibe-trading"
_ORDER_MAGIC = 862_001


def quantity_notional_usd(config: MT5Config | None, symbol: str, quantity: float) -> float | None:
    """USD notional of ``quantity`` LOTS of ``symbol`` — the live gate's sizing hook.

    The gate (``src.live.sdk_order_gate._implied_notional``) treats this as
    AUTHORITATIVE: MT5 quantities are lots (1 lot EURUSD == 100,000 EUR), so
    ``quantity x quote`` would under-state notional ~contract-size-fold.
    Returns ``None`` on any failure (→ fail-closed DENY upstream).
    """
    cfg = config or _client.load_config()
    try:
        with _client._session(cfg) as mt5:
            name = _resolve_symbol(mt5, cfg, symbol)
            return _usd_contract_value(mt5, cfg, name, float(quantity))
    except Exception:  # noqa: BLE001 - sizing must fail closed, never raise
        return None


def place_order(
    config: MT5Config | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | str | None = None,
    notional: float | str | None = None,
    order_type: str = "market",
    limit_price: float | str | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    """Place a market or pending-limit order on the configured MT5 account.

    Args:
        config: Resolved connector config; loaded from disk when ``None``.
        symbol: Project or broker symbol (``EUR/USD``, ``EURUSD``, ``EURUSDm``).
        side: ``"buy"`` or ``"sell"``.
        quantity: Size in LOTS. Exactly one of ``quantity``/``notional``.
        notional: USD amount, converted to lots and floored to the symbol's
            ``volume_step`` (never rounded up).
        order_type: ``"market"`` or ``"limit"`` (limit → pending order).
        limit_price: Required for limit orders.
        time_in_force: ``"day"`` (default) or ``"gtc"`` — pending orders only.

    Returns:
        ``{"status": "ok", "order_id", ...}`` on ``TRADE_RETCODE_DONE``; a
        fail-closed ``{"status": "error", "error": ...}`` payload otherwise.
    """
    cfg = config or _client.load_config()

    clean_side = str(side or "").strip().lower()
    if clean_side not in ("buy", "sell"):
        return _order_error(cfg, "side must be 'buy' or 'sell'", symbol=symbol, side=side)

    clean_type = str(order_type or "").strip().lower()
    if clean_type not in ("market", "limit"):
        return _order_error(cfg, "order_type must be 'market' or 'limit'", symbol=symbol, side=clean_side)

    clean_symbol = str(symbol or "").strip().upper()
    if not clean_symbol:
        return _order_error(cfg, "symbol is required", symbol=symbol, side=clean_side)

    has_qty = quantity is not None
    has_notional = notional is not None
    if has_qty == has_notional:
        return _order_error(
            cfg, "exactly one of quantity or notional is required", symbol=clean_symbol, side=clean_side
        )
    if clean_type == "limit" and limit_price is None:
        return _order_error(cfg, "limit order requires limit_price", symbol=clean_symbol, side=clean_side)

    missing = _missing_fields(cfg)
    if missing:
        return _order_error(
            cfg, f"MT5 connector not configured: missing {', '.join(missing)}.", symbol=clean_symbol, side=clean_side
        )

    try:
        with _client._session(cfg) as mt5:
            name = _resolve_symbol(mt5, cfg, symbol)
            info = mt5.symbol_info(name)
            if info is None:
                return _order_error(cfg, f"no symbol info for {name!r}", symbol=clean_symbol, side=clean_side)

            volume = _sized_volume(mt5, cfg, name, info, quantity, notional)
            if isinstance(volume, str):  # sizing error message
                return _order_error(cfg, volume, symbol=clean_symbol, side=clean_side)

            guard_error = _size_guards(mt5, cfg, name, volume)
            if guard_error is not None:
                return _order_error(cfg, guard_error, symbol=clean_symbol, side=clean_side)

            request = _build_request(
                mt5,
                cfg,
                name,
                info,
                side=clean_side,
                order_type=clean_type,
                volume=volume,
                limit_price=limit_price,
                time_in_force=time_in_force,
            )
            if isinstance(request, str):
                return _order_error(cfg, request, symbol=clean_symbol, side=clean_side)

            check = mt5.order_check(request)
            done = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
            check_code = getattr(check, "retcode", None)
            if check is None or check_code not in (0, done):
                comment = getattr(check, "comment", "no response") if check is not None else "no response"
                return _order_error(
                    cfg,
                    f"MT5 order_check rejected the order (retcode={check_code}): {comment}",
                    symbol=clean_symbol,
                    side=clean_side,
                )

            result = mt5.order_send(request)
            return _order_result(
                cfg,
                mt5,
                result,
                symbol=clean_symbol,
                resolved_symbol=name,
                side=clean_side,
                order_type=clean_type,
                volume=volume,
            )
    except _MT5_ERRORS as exc:
        return _order_error(cfg, str(exc), symbol=clean_symbol, side=clean_side)


def cancel_order(
    config: MT5Config | None = None,
    order_id: str = "",
    *,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Cancel a pending order OR close an open position by ticket (risk-reducing).

    MT5 separates pending orders from open positions; a single "cancel" ticket
    id may name either. Both branches strictly reduce risk — removing a
    resting order, or sending an opposite deal pinned to ``position=`` capped
    at the position's own volume — which is why this path stays un-gated (but
    live-audited) like every other connector's cancel.
    """
    cfg = config or _client.load_config()
    try:
        ticket = int(str(order_id).strip())
    except (TypeError, ValueError):
        return _order_error(cfg, f"MT5 cancel requires a numeric ticket, got {order_id!r}", symbol=symbol)

    try:
        with _client._session(cfg) as mt5:
            pending = mt5.orders_get(ticket=ticket) or ()
            if pending:
                request = {
                    "action": getattr(mt5, "TRADE_ACTION_REMOVE", 8),
                    "order": ticket,
                    "comment": _ORDER_COMMENT,
                }
                result = mt5.order_send(request)
                return _order_result(cfg, mt5, result, action="order_cancelled", order_ticket=ticket)

            positions = mt5.positions_get(ticket=ticket) or ()
            if positions:
                return _close(mt5, cfg, positions[0], requested_volume=None)

            return _order_error(cfg, f"no pending order or open position with ticket {ticket}")
    except _MT5_ERRORS as exc:
        return _order_error(cfg, str(exc), order_id=str(ticket))


def close_position(
    config: MT5Config | None = None,
    position_id: int = 0,
    *,
    volume: float | None = None,
) -> dict[str, Any]:
    """Close (fully or partially) an open position by ticket."""
    cfg = config or _client.load_config()
    try:
        ticket = int(position_id)
    except (TypeError, ValueError):
        return _order_error(cfg, f"close_position requires a numeric ticket, got {position_id!r}")
    try:
        with _client._session(cfg) as mt5:
            positions = mt5.positions_get(ticket=ticket) or ()
            if not positions:
                return _order_error(cfg, f"no open position with ticket {ticket}")
            return _close(mt5, cfg, positions[0], requested_volume=volume)
    except _MT5_ERRORS as exc:
        return _order_error(cfg, str(exc), position_id=str(ticket))


# --------------------------------------------------------------------------- #
# Internals                                                                    #
# --------------------------------------------------------------------------- #


def _sized_volume(
    mt5: Any,
    cfg: MT5Config,
    name: str,
    info: Any,
    quantity: float | str | None,
    notional: float | str | None,
) -> float | str:
    """Resolve the order volume in lots, or return an error message string."""
    volume_min = float(getattr(info, "volume_min", 0.01) or 0.01)
    volume_max = float(getattr(info, "volume_max", 100.0) or 100.0)
    step = float(getattr(info, "volume_step", 0.01) or 0.01)

    if quantity is not None:
        volume = float(quantity)
    else:
        unit_usd = _usd_contract_value(mt5, cfg, name, 1.0)
        if unit_usd is None or unit_usd <= 0:
            return f"cannot size {name!r} by notional: USD contract value unavailable (fail-closed)"
        raw = float(notional) / unit_usd
        # Floor to the volume step — a notional budget must never round UP.
        volume = math.floor(raw / step + 1e-9) * step
        volume = round(volume, 8)
    if volume > volume_max:
        volume = volume_max
    if volume < volume_min:
        return f"order volume {volume} lots is below the symbol minimum {volume_min} for {name!r}"
    return volume


def _size_guards(mt5: Any, cfg: MT5Config, name: str, volume: float) -> str | None:
    """Connector-level per-order guards (demo AND live), fail-closed."""
    if volume > cfg.max_order_volume:
        return (
            f"order volume {volume} lots exceeds the connector max_order_volume "
            f"guard ({cfg.max_order_volume}); raise it in mt5.json if intended"
        )
    usd = _usd_contract_value(mt5, cfg, name, volume)
    if usd is None:
        return (
            f"order for {name!r} could not be priced in USD, so the "
            "max_order_notional_usd guard is unenforceable (fail-closed)"
        )
    if usd > cfg.max_order_notional_usd:
        return (
            f"order notional ~${usd:,.0f} exceeds the connector max_order_notional_usd "
            f"guard (${cfg.max_order_notional_usd:,.0f}); raise it in mt5.json if intended"
        )
    return None


def _build_request(
    mt5: Any,
    cfg: MT5Config,
    name: str,
    info: Any,
    *,
    side: str,
    order_type: str,
    volume: float,
    limit_price: float | str | None,
    time_in_force: str,
) -> dict[str, Any] | str:
    """Build the ``order_send`` request dict, or return an error message string."""
    request: dict[str, Any] = {
        "symbol": name,
        "volume": volume,
        "magic": _ORDER_MAGIC,
        "comment": _ORDER_COMMENT,
    }
    if order_type == "market":
        tick = mt5.symbol_info_tick(name)
        if tick is None:
            return f"no tick data for {name!r}; cannot price a market order"
        price = getattr(tick, "ask", None) if side == "buy" else getattr(tick, "bid", None)
        if not price or float(price) <= 0:
            return f"no {'ask' if side == 'buy' else 'bid'} price for {name!r}"
        request.update(
            {
                "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
                "type": getattr(mt5, "ORDER_TYPE_BUY", 0) if side == "buy" else getattr(mt5, "ORDER_TYPE_SELL", 1),
                "price": float(price),
                "deviation": cfg.deviation_points,
                "type_filling": _filling_mode(mt5, info, pending=False),
            }
        )
    else:
        tif = str(time_in_force or "").strip().lower()
        request.update(
            {
                "action": getattr(mt5, "TRADE_ACTION_PENDING", 5),
                "type": (
                    getattr(mt5, "ORDER_TYPE_BUY_LIMIT", 2)
                    if side == "buy"
                    else getattr(mt5, "ORDER_TYPE_SELL_LIMIT", 3)
                ),
                "price": float(limit_price),
                "type_time": getattr(mt5, "ORDER_TIME_GTC", 0) if tif == "gtc" else getattr(mt5, "ORDER_TIME_DAY", 1),
                "type_filling": _filling_mode(mt5, info, pending=True),
            }
        )
    return request


def _filling_mode(mt5: Any, info: Any, *, pending: bool) -> int:
    """Negotiate a filling mode from the symbol's allowed-modes bitmask."""
    if pending:
        return getattr(mt5, "ORDER_FILLING_RETURN", 2)
    mask = int(getattr(info, "filling_mode", 0) or 0)
    if mask & int(getattr(mt5, "SYMBOL_FILLING_IOC", 2)):
        return getattr(mt5, "ORDER_FILLING_IOC", 1)
    if mask & int(getattr(mt5, "SYMBOL_FILLING_FOK", 1)):
        return getattr(mt5, "ORDER_FILLING_FOK", 0)
    return getattr(mt5, "ORDER_FILLING_RETURN", 2)


def _close(mt5: Any, cfg: MT5Config, position: Any, *, requested_volume: float | None) -> dict[str, Any]:
    """Send an opposite deal pinned to the position ticket (risk-reducing only)."""
    name = getattr(position, "symbol", "")
    ticket = int(getattr(position, "ticket", 0) or 0)
    position_volume = float(getattr(position, "volume", 0.0) or 0.0)
    volume = position_volume if requested_volume is None else min(float(requested_volume), position_volume)
    sell_type = getattr(mt5, "POSITION_TYPE_SELL", 1)
    is_short = getattr(position, "type", 0) == sell_type
    tick = mt5.symbol_info_tick(name)
    if tick is None:
        return _order_error(cfg, f"no tick data for {name!r}; cannot close position {ticket}")
    price = getattr(tick, "ask", None) if is_short else getattr(tick, "bid", None)
    if not price or float(price) <= 0:
        return _order_error(cfg, f"no close price for {name!r} (position {ticket})")
    request = {
        "action": getattr(mt5, "TRADE_ACTION_DEAL", 1),
        "symbol": name,
        "position": ticket,
        "volume": volume,
        "type": getattr(mt5, "ORDER_TYPE_BUY", 0) if is_short else getattr(mt5, "ORDER_TYPE_SELL", 1),
        "price": float(price),
        "deviation": cfg.deviation_points,
        "type_filling": _filling_mode(mt5, mt5.symbol_info(name), pending=False),
        "magic": _ORDER_MAGIC,
        "comment": _ORDER_COMMENT,
    }
    result = mt5.order_send(request)
    return _order_result(cfg, mt5, result, action="position_closed", position=ticket, volume=volume)


def _order_result(cfg: MT5Config, mt5: Any, result: Any, **extra: Any) -> dict[str, Any]:
    """Interpret an ``order_send`` response, failing closed on any non-DONE retcode."""
    if result is None:
        return _order_error(cfg, f"MT5 order_send returned no result ({_client._last_error(mt5)})", **extra)
    retcode = getattr(result, "retcode", None)
    done = getattr(mt5, "TRADE_RETCODE_DONE", 10009)
    partial = getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)
    if retcode not in (done, partial):
        comment = getattr(result, "comment", "")
        return _order_error(cfg, f"MT5 rejected order (retcode={retcode}): {comment}", **extra)
    payload: dict[str, Any] = {
        "status": "ok",
        "profile": cfg.profile,
        "is_demo": cfg.is_demo,
        "paper_guard": GUARD_MARKER,
        "order_id": str(getattr(result, "order", "")),
        "deal_id": str(getattr(result, "deal", "")),
        "filled_volume": getattr(result, "volume", None),
        "filled_price": getattr(result, "price", None),
        "retcode": retcode,
    }
    if retcode == partial:
        payload["partial"] = True
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return payload


def _order_error(cfg: MT5Config, message: str, **extra: Any) -> dict[str, Any]:
    """Build a fail-closed error payload carrying profile/guard context."""
    payload: dict[str, Any] = {
        "status": "error",
        "error": message,
        "profile": cfg.profile,
        "is_demo": cfg.is_demo,
        "paper_guard": GUARD_MARKER,
    }
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return payload
