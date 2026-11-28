"""Exness order operations: sizing hook, place, cancel/close (risk-reducing).

Validation runs before any network call and every failure returns a
fail-closed ``{"status": "error", ...}`` payload. Connector size guards
(``max_order_volume`` / ``max_order_notional_usd``) sit underneath the live
mandate gate as defense in depth.

Async model: mutations return ``202 {operation_id}``; the final outcome is
polled from ``operations/{id}``. An accepted-but-unconfirmed order is reported
as ``status: ok`` with ``order_state: pending`` — the broker has it, so the
gate must count it, and it must never be blindly re-submitted. POSTs are
never retried automatically.

Hedging note: Exness accounts are typically hedging accounts — an opposite-side
``place_order`` OPENS a hedge. Close through :func:`cancel_order` /
:func:`close_position` with the position id, which can only reduce exposure.
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any

from src.trading.connectors.exness import _client, _market
from src.trading.connectors.exness._client import GUARD_MARKER, ExnessConfig, new_idempotency_key
from src.trading.connectors.exness._market import to_float
from src.trading.connectors.exness.reads import ERRORS

_ORDER_COMMENT = "vibe-trading"
_POLL_INTERVAL_SECONDS = 0.5
_MAX_QUOTE_AGE_SECONDS = 300
_sleep = time.sleep


def quantity_notional_usd(config: ExnessConfig | None, symbol: str, quantity: float) -> float | None:
    """USD notional of ``quantity`` LOTS of ``symbol`` — the live gate's sizing hook.

    ``src.live.sdk_order_gate._implied_notional`` treats this as authoritative
    (``quantity × quote`` would understate lots ~contract-size-fold). Returns
    ``None`` on any failure, which the gate turns into a DENY.
    """
    try:
        cfg = config or _client.load_config()
        client = _client.make_client(cfg)
        return _market.usd_value(client, _market.resolve_symbol(client, symbol), float(quantity))
    except Exception:  # noqa: BLE001 - sizing must fail closed, never raise
        return None


def place_order(
    config: ExnessConfig | None = None,
    *,
    symbol: str,
    side: str,
    quantity: float | str | None = None,
    notional: float | str | None = None,
    order_type: str = "market",
    limit_price: float | str | None = None,
    time_in_force: str = "day",
) -> dict[str, Any]:
    """Open a market position or place a pending limit order.

    Args:
        config: Resolved connector config; loaded from disk when ``None``.
        symbol: Project or broker symbol (``EUR/USD``, ``EURUSD``).
        side: ``"buy"`` or ``"sell"``.
        quantity: Size in LOTS. Exactly one of ``quantity`` / ``notional``.
        notional: USD amount, converted to lots and floored to the volume step.
        order_type: ``"market"`` or ``"limit"``.
        limit_price: Required for limit orders (``point_digits`` precision).
        time_in_force: Limit orders must pass ``"gtc"`` — Exness pending
            orders carry no expiry, so a ``"day"`` order is refused rather than
            silently extended. Ignored for market orders.

    Returns:
        ``ok`` with ``order_state`` ``confirmed`` or ``pending``; otherwise a
        fail-closed error payload.
    """
    cfg = config or _client.load_config()
    if cfg.is_readonly:
        return _error(cfg, "Exness read-only profile cannot place orders")
    clean_side = str(side or "").strip().lower()
    clean_type = str(order_type or "").strip().lower()
    clean_symbol = str(symbol or "").strip().upper()
    ctx = {"symbol": clean_symbol, "side": clean_side}
    problem = _validate(clean_side, clean_type, clean_symbol, quantity, notional, limit_price, time_in_force)
    if problem:
        return _error(cfg, problem, **ctx)

    key = new_idempotency_key()
    try:
        client = _client.make_client(cfg)
        name = _market.resolve_symbol(client, symbol)
        info = _market.conditions(client, name)
        if str(info.get("trade_mode") or "enabled") != "enabled":
            return _error(cfg, f"trading is disabled for {name!r} (trade_mode={info.get('trade_mode')})", **ctx)
        instant = clean_type == "market" and str(info.get("exec_mode") or "") == "instant"
        volume =_sized_volume(client, name, info, quantity, notional)
        if isinstance(volume, str):
            return _error(cfg, volume, **ctx)
        guard = _size_guards(client, cfg, name, volume)
        if guard:
            return _error(cfg, guard, **ctx)
        body: dict[str, Any] = {"instrument": name, "side": clean_side}
        if clean_type == "limit":
            price = _format_price(limit_price, info)
            if price is None:
                return _error(cfg, f"limit_price has more decimal places than {name!r} allows "
                                   f"(point_digits={info.get('point_digits')})", **ctx)
            body.update(type="limit", volume=_fmt(volume), price=price)
            path = client.account_path("trading", "orders")
        else:
            body["volume"] = _fmt(volume)
            path = client.account_path("trading", "positions")
        requested: float | None = None
        if instant:
            quoted = _instant_price(client, name, info, clean_side)
            if isinstance(quoted, str):
                return _error(cfg, quoted, **ctx)
            requested = quoted
            body.update(price=_fmt(quoted), deviation=str(cfg.deviation_points))
        body["comment"] = _ORDER_COMMENT
    except ERRORS as exc:
        return _error(cfg, str(exc), **ctx)

    extra = {**ctx, "resolved_symbol": name, "order_type": clean_type, "quantity": float(volume),
             "client_order_id": key, "requested_price": requested,
             "deviation_points": cfg.deviation_points if instant else None}
    try:
        ack = client.post(path, body, idempotency_key=key)
    except ERRORS as exc:
        return _error(cfg, f"{exc} — outcome unknown if this was a network error: check open positions/orders "
                           "before re-submitting", **extra)
    return _await_operation(client, cfg, ack, **extra)


def cancel_order(config: ExnessConfig | None = None, order_id: str = "", *, symbol: str | None = None) -> dict[str, Any]:
    """Cancel a pending order OR close an open position by id (both risk-reducing)."""
    cfg = config or _client.load_config()
    if cfg.is_readonly:
        return _error(cfg, "Exness read-only profile cannot cancel orders")
    ident = str(order_id or "").strip()
    if not ident.isdigit():
        return _error(cfg, f"Exness cancel requires a numeric order or position id, got {order_id!r}", symbol=symbol)
    try:
        client = _client.make_client(cfg)
        snapshot = client.get(client.account_path("trading", "snapshot")) or {}
        if any(str(o.get("order_id")) == ident for o in snapshot.get("orders") or []):
            key = new_idempotency_key()
            ack = client.delete(client.account_path("trading", "orders", ident), idempotency_key=key)
            return _await_operation(client, cfg, ack, action="order_cancelled", order_id=ident, client_order_id=key)
        position = next((p for p in snapshot.get("positions") or [] if str(p.get("position_id")) == ident), None)
        if position is not None:
            return _close(client, cfg, position, None)
    except ERRORS as exc:
        return _error(cfg, str(exc), order_id=ident)
    return _error(cfg, f"no pending order or open position with id {ident}")


def close_position(config: ExnessConfig | None = None, position_id: str = "", *,
                   volume: float | None = None) -> dict[str, Any]:
    """Close (fully, or partially with ``volume`` lots) an open position by id."""
    cfg = config or _client.load_config()
    if cfg.is_readonly:
        return _error(cfg, "Exness read-only profile cannot close positions")
    ident = str(position_id or "").strip()
    if not ident.isdigit():
        return _error(cfg, f"close_position requires a numeric position id, got {position_id!r}")
    try:
        client = _client.make_client(cfg)
        snapshot = client.get(client.account_path("trading", "snapshot")) or {}
        position = next((p for p in snapshot.get("positions") or [] if str(p.get("position_id")) == ident), None)
        if position is None:
            return _error(cfg, f"no open position with id {ident}")
        if volume is not None:
            held = to_float(position.get("volume")) or 0.0
            if not _positive_number(volume):
                return _error(cfg, "close volume must be a positive number", position_id=ident)
            if float(volume) > held:
                return _error(cfg, f"close volume {volume} exceeds the open position volume {held}",
                              position_id=ident)
        return _close(client, cfg, position, volume)
    except ERRORS as exc:
        return _error(cfg, str(exc), position_id=ident)


# --------------------------------------------------------------------------- #
# Internals                                                                    #
# --------------------------------------------------------------------------- #


def _positive_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _validate(side: str, order_type: str, symbol: str, quantity: Any, notional: Any, limit_price: Any,
              time_in_force: str) -> str | None:
    if side not in ("buy", "sell"):
        return "side must be 'buy' or 'sell'"
    if order_type not in ("market", "limit"):
        return "order_type must be 'market' or 'limit'"
    if not symbol:
        return "symbol is required"
    if (quantity is None) == (notional is None):
        return "exactly one of quantity or notional is required"
    if not _positive_number(quantity if quantity is not None else notional):
        return "order size must be a positive, finite number"
    if order_type == "limit":
        if limit_price is None:
            return "limit order requires limit_price"
        if not _positive_number(limit_price):
            return "limit_price must be a positive, finite number"
        if str(time_in_force or "").strip().lower() != "gtc":
            return "Exness pending orders have no expiry; pass time_in_force='gtc' for limit orders"
    return None


def _dec(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _fmt(value: Decimal | float) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _format_price(price: Any, info: dict[str, Any]) -> str | None:
    value = _dec(price)
    digits = info.get("point_digits")
    if value is None:
        return None
    if isinstance(digits, int) and digits >= 0 and value != value.quantize(Decimal(1).scaleb(-digits)):
        return None
    return _fmt(value)


def _sized_volume(client: Any, name: str, info: dict[str, Any], quantity: Any, notional: Any) -> Decimal | str:
    vmin = _dec(info.get("volume_min") or "0.01")
    vmax = _dec(info.get("volume_max") or "100")
    step = _dec(info.get("volume_step") or "0.01")
    if not vmin or not vmax or not step or step <= 0:
        return f"volume rules for {name!r} are unavailable (fail-closed)"
    if quantity is not None:
        volume = _dec(quantity)
    else:
        unit_usd = _market.usd_value(client, name, 1.0)
        if not unit_usd or unit_usd <= 0:
            return f"cannot size {name!r} by notional: USD contract value unavailable (fail-closed)"
        raw = Decimal(str(float(notional) / unit_usd))
        steps = ((raw - vmin) / step).to_integral_value(rounding=ROUND_FLOOR)
        volume = vmin + max(steps, Decimal(0)) * step if raw >= vmin else raw
    if volume is None:
        return "order size is not a valid number"
    if volume < vmin:
        return f"order volume {_fmt(volume)} lots is below the instrument minimum {_fmt(vmin)} for {name!r}"
    if volume > vmax:
        return f"order volume {_fmt(volume)} lots exceeds the instrument maximum {_fmt(vmax)} for {name!r}"
    if (volume - vmin) % step != 0:
        return f"order volume {_fmt(volume)} lots is not on the {_fmt(step)} volume step for {name!r}"
    return volume


def _size_guards(client: Any, cfg: ExnessConfig, name: str, volume: Decimal) -> str | None:
    lots = float(volume)
    if lots > cfg.max_order_volume:
        return (f"order volume {lots} lots exceeds the connector max_order_volume guard "
                f"({cfg.max_order_volume}); raise it in exness.json if intended")
    usd = _market.usd_value(client, name, lots)
    if usd is None:
        return f"order for {name!r} could not be priced in USD, so max_order_notional_usd is unenforceable (fail-closed)"
    if usd > cfg.max_order_notional_usd:
        return (f"order notional ~${usd:,.0f} exceeds the connector max_order_notional_usd guard "
                f"(${cfg.max_order_notional_usd:,.0f}); raise it in exness.json if intended")
    return None


def _instant_price(client: Any, name: str, info: dict[str, Any], side: str) -> float | str:
    """Price to request on an instant-execution instrument, or an error message.

    Buys request the latest ask, sells the latest bid, rounded to ``point_digits``.
    The REST API has no quote endpoint, so the price comes from the newest M1
    candle; a missing or stale (> ``_MAX_QUOTE_AGE_SECONDS``) candle is refused
    rather than risk a fill against an outdated price.
    """
    quote = _market.latest_bid_ask(client, name)
    if quote is None:
        return f"no current quote for {name!r}; instant execution needs a price (fail-closed)"
    try:
        age = (_market.utc_now() - datetime.fromisoformat(str(quote["time"]).replace("Z", "+00:00"))).total_seconds()
    except (TypeError, ValueError):
        return f"quote time for {name!r} is unreadable; refusing instant execution (fail-closed)"
    if age > _MAX_QUOTE_AGE_SECONDS or age < -_MAX_QUOTE_AGE_SECONDS:
        return (f"latest quote for {name!r} is stale ({int(age)}s old); market may be closed — "
                "refusing instant execution (fail-closed)")
    price = quote["ask"] if side == "buy" else quote["bid"]
    digits = info.get("point_digits")
    return round(price, digits) if isinstance(digits, int) and digits >= 0 else price


def _close(client: Any, cfg: ExnessConfig, position: dict[str, Any], volume: float | None) -> dict[str, Any]:
    """Close by position id. Risk-reducing, so a missing quote never blocks the close."""
    position_id = str(position.get("position_id"))
    key = new_idempotency_key()
    params: dict[str, Any] = {"volume": _fmt(volume)} if volume is not None else {}
    name = str(position.get("instrument") or "")
    try:
        info = _market.conditions(client, name) if name else {}
        if str(info.get("exec_mode") or "") == "instant":
            closing_side = "sell" if position.get("direction") == "buy" else "buy"
            quoted = _instant_price(client, name, info, closing_side)
            if not isinstance(quoted, str):
                params.update(price=_fmt(quoted), deviation=str(cfg.deviation_points))
    except ERRORS:
        pass  # close without a requested price; the broker decides
    ack = client.delete(client.account_path("trading", "positions", position_id), params or None,
                        idempotency_key=key)
    return _await_operation(client, cfg, ack, action="position_closed", position_id=position_id,
                            volume=volume, client_order_id=key)


def _await_operation(client: Any, cfg: ExnessConfig, ack: Any, **extra: Any) -> dict[str, Any]:
    """Poll the async operation; accepted-but-unconfirmed is ``ok`` / ``pending``."""
    op_id = str((ack or {}).get("operation_id") or "")
    if not op_id.isdigit():
        return _error(cfg, "Exness accepted the request but returned no operation id", **extra)
    attempts = max(1, math.ceil(cfg.operation_wait_seconds / _POLL_INTERVAL_SECONDS))
    status = "pending"
    detail: dict[str, Any] = {}
    for attempt in range(attempts):
        try:
            detail = client.get(client.account_path("trading", "operations", op_id)) or {}
        except ERRORS:
            break
        status = str(detail.get("status") or "pending")
        if status != "pending":
            break
        if attempt + 1 < attempts:
            _sleep(_POLL_INTERVAL_SECONDS)
    if status in ("rejected", "failed"):
        reason = str(detail.get("error_message") or status)
        if "REQUOTE" in reason:
            reason += (f" — the price moved more than deviation_points ({cfg.deviation_points}) before execution; "
                       "retry, or widen deviation_points in exness.json if you accept more slippage")
        return _error(cfg, f"Exness {status} the request: {reason}", operation_id=op_id,
                      broker_error_code=detail.get("error_code"), **extra)
    payload = _ok(cfg, operation_id=op_id, order_state="confirmed" if status == "confirmed" else "pending", **extra)
    if payload["order_state"] == "pending":
        payload["warning"] = (f"Accepted by Exness but not yet confirmed; check operation_id {op_id} "
                              "(or open positions/orders) before re-submitting.")
    return payload


def _ok(cfg: ExnessConfig, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"status": "ok", "profile": cfg.profile, "environment": cfg.environment,
                               "guard": GUARD_MARKER}
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def _error(cfg: ExnessConfig, message: str, **extra: Any) -> dict[str, Any]:
    payload = _ok(cfg, **extra)
    payload["status"] = "error"
    payload["error"] = message
    return payload
