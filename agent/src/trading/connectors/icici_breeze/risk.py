"""Risk controls for the ICICI Breeze local paper connector.

The policy is persisted under ``~/.vibe-trading`` and applies only to the
local ICICI paper ledger. It never calls an ICICI broker-write endpoint.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.config.paths import get_runtime_root

RISK_POLICY_FILENAME = "icici_breeze_paper_risk.json"

DEFAULT_POLICY: dict[str, Any] = {
    "version": 1,
    "approved_symbols": ["ICICIBANK"],
    "max_order_value_inr": 5000.0,
    "max_orders_per_day": 3,
    "max_daily_loss_inr": 500.0,
    "manual_confirmation_required": True,
    "slippage_bps": 5.0,
    "emergency_stop": False,
}


def policy_path() -> Path:
    return get_runtime_root() / RISK_POLICY_FILENAME


def load_policy() -> dict[str, Any]:
    path = policy_path()
    if not path.exists():
        policy = dict(DEFAULT_POLICY)
        save_policy(policy)
        return policy

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        raw = {}

    policy = dict(DEFAULT_POLICY)
    if isinstance(raw, Mapping):
        policy.update(dict(raw))
    return _normalize(policy)


def save_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize(policy)
    path = policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return normalized


def update_policy(**changes: Any) -> dict[str, Any]:
    allowed = set(DEFAULT_POLICY) - {"version"}
    unknown = sorted(set(changes) - allowed)
    if unknown:
        raise ValueError(
            "unknown ICICI paper-risk setting(s): " + ", ".join(unknown)
        )
    policy = load_policy()
    policy.update(changes)
    return save_policy(policy)


def set_emergency_stop(enabled: bool) -> dict[str, Any]:
    return update_policy(emergency_stop=bool(enabled))


def orders_created_today(orders: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    today = datetime.now().astimezone().date()
    return [
        order
        for order in orders
        if _local_date(order.get("created_at")) == today
    ]


def daily_realized_pnl(orders: list[Mapping[str, Any]]) -> float:
    return round(
        sum(
            _number(order.get("realized_pnl"))
            for order in orders_created_today(orders)
            if str(order.get("status") or "").lower() == "filled"
        ),
        8,
    )


def status(
    *,
    orders: list[Mapping[str, Any]],
    unrealized_pnl: float,
) -> dict[str, Any]:
    policy = load_policy()
    today_orders = orders_created_today(orders)
    realized = daily_realized_pnl(orders)
    daily_pnl = realized + float(unrealized_pnl or 0.0)
    return {
        "status": "ok",
        "policy": policy,
        "orders_today": len(today_orders),
        "daily_realized_pnl": round(realized, 8),
        "current_unrealized_pnl": round(float(unrealized_pnl or 0.0), 8),
        "estimated_daily_pnl": round(daily_pnl, 8),
        "daily_loss_limit_triggered": (
            daily_pnl <= -float(policy["max_daily_loss_inr"])
        ),
        "emergency_stop": bool(policy["emergency_stop"]),
    }


def evaluate_order(
    *,
    ledger: Mapping[str, Any],
    symbol: str,
    side: str,
    quantity: int,
    estimated_value_inr: float,
    confirmed: bool,
    current_position_qty: int,
    unrealized_pnl: float,
) -> dict[str, Any]:
    policy = load_policy()
    clean_symbol = str(symbol or "").strip().upper()
    side_token = str(side or "").strip().lower()
    approved = {
        str(item or "").strip().upper()
        for item in policy["approved_symbols"]
        if str(item or "").strip()
    }
    orders = [
        item for item in list(ledger.get("orders") or [])
        if isinstance(item, Mapping)
    ]
    today_orders = orders_created_today(orders)
    realized = daily_realized_pnl(orders)
    daily_pnl = realized + float(unrealized_pnl or 0.0)
    risk_reducing = (
        side_token == "sell"
        and int(quantity) > 0
        and int(current_position_qty) >= int(quantity)
    )

    preview = {
        "approved_symbols": sorted(approved),
        "max_order_value_inr": policy["max_order_value_inr"],
        "max_orders_per_day": policy["max_orders_per_day"],
        "max_daily_loss_inr": policy["max_daily_loss_inr"],
        "manual_confirmation_required": policy[
            "manual_confirmation_required"
        ],
        "slippage_bps": policy["slippage_bps"],
        "emergency_stop": policy["emergency_stop"],
        "orders_today": len(today_orders),
        "estimated_daily_pnl": round(daily_pnl, 8),
        "estimated_order_value_inr": round(
            float(estimated_value_inr or 0.0), 8
        ),
        "risk_reducing_sell": risk_reducing,
    }

    def deny(reason: str, *, code: str = "risk_rejected") -> dict[str, Any]:
        return {
            "status": code,
            "allowed": False,
            "error": reason,
            "risk_preview": preview,
            "paper": True,
            "broker_write_called": False,
        }

    if clean_symbol not in approved:
        return deny(
            f"symbol {clean_symbol} is not on the approved paper-trading list"
        )

    if bool(policy["manual_confirmation_required"]) and not bool(confirmed):
        return deny(
            "manual confirmation is required; repeat the paper order with "
            "confirmed=True only after the user explicitly approves it",
            code="confirmation_required",
        )

    if bool(policy["emergency_stop"]) and not risk_reducing:
        return deny(
            "ICICI paper emergency stop is active; only a risk-reducing "
            "sell up to the available paper holding is allowed"
        )

    if (
        float(estimated_value_inr) > float(policy["max_order_value_inr"])
        and not risk_reducing
    ):
        return deny(
            "estimated paper-order value exceeds the configured INR "
            f"{float(policy['max_order_value_inr']):.2f} cap"
        )

    if (
        len(today_orders) >= int(policy["max_orders_per_day"])
        and not risk_reducing
    ):
        return deny(
            "daily paper-order count limit has been reached"
        )

    if (
        daily_pnl <= -float(policy["max_daily_loss_inr"])
        and not risk_reducing
    ):
        return deny(
            "daily paper-loss limit has been reached; only a "
            "risk-reducing sell is allowed"
        )

    return {
        "status": "approved",
        "allowed": True,
        "risk_preview": preview,
        "paper": True,
        "broker_write_called": False,
    }


def slippage_price(
    *,
    price: float,
    side: str,
    limit_price: float | None,
    tick_size: float = 0.05,
) -> float:
    policy = load_policy()
    base = float(price)
    bps = float(policy["slippage_bps"])
    if base <= 0 or bps <= 0:
        return base

    side_token = str(side or "").strip().lower()
    if side_token == "buy":
        raw = base * (1.0 + bps / 10000.0)
        slipped = math.ceil(raw / tick_size) * tick_size
        if limit_price is not None:
            slipped = min(slipped, float(limit_price))
    else:
        raw = base * (1.0 - bps / 10000.0)
        slipped = math.floor(raw / tick_size) * tick_size
        if limit_price is not None:
            slipped = max(slipped, float(limit_price))
    return round(slipped, 8)


def _normalize(policy: Mapping[str, Any]) -> dict[str, Any]:
    approved = policy.get("approved_symbols")
    if isinstance(approved, str):
        symbols = [
            item.strip().upper()
            for item in approved.split(",")
            if item.strip()
        ]
    else:
        symbols = [
            str(item or "").strip().upper()
            for item in list(approved or [])
            if str(item or "").strip()
        ]
    if not symbols:
        raise ValueError("approved_symbols must contain at least one symbol")

    max_order = _positive(
        policy.get("max_order_value_inr"),
        "max_order_value_inr",
    )
    max_orders = int(
        _positive(policy.get("max_orders_per_day"), "max_orders_per_day")
    )
    max_loss = _positive(
        policy.get("max_daily_loss_inr"),
        "max_daily_loss_inr",
    )
    slippage = float(policy.get("slippage_bps") or 0.0)
    if not math.isfinite(slippage) or slippage < 0 or slippage > 1000:
        raise ValueError("slippage_bps must be between 0 and 1000")

    return {
        "version": 1,
        "approved_symbols": list(dict.fromkeys(symbols)),
        "max_order_value_inr": round(max_order, 8),
        "max_orders_per_day": max_orders,
        "max_daily_loss_inr": round(max_loss, 8),
        "manual_confirmation_required": _boolean(
            policy.get("manual_confirmation_required"), True
        ),
        "slippage_bps": round(slippage, 8),
        "emergency_stop": _boolean(
            policy.get("emergency_stop"), False
        ),
    }


def _local_date(value: Any):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).astimezone().date()
    except ValueError:
        return None


def _positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be positive")
    return number


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _boolean(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    token = str(value).strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return default
