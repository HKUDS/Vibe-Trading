"""Connector-first trading tools.

Tools take an optional ``connection`` profile id. If omitted, they use the
selected profile from ``~/.vibe-trading/trading-connections.json``.
"""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.trading.profiles import (
    list_profiles,
    load_selected_profile_id,
    profile_by_id,
    save_selected_profile_id,
)
from src.trading.service import (
    check_connection,
    get_account,
    get_history,
    get_open_orders,
    get_positions,
    get_quote,
)


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _connection(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


TRADING_COMMON_PARAMETERS = {
    "connection": {
        "type": "string",
        "description": "Trading connector profile id, e.g. ibkr-paper-local or robinhood-live-mcp. Defaults to the selected profile.",
    },
    "host": {
        "type": "string",
        "description": "Optional local TWS/Gateway host override for local profiles.",
    },
    "port": {
        "type": "integer",
        "description": "Optional local TWS/Gateway port override for local profiles.",
    },
    "client_id": {
        "type": "integer",
        "description": "Optional local TWS/Gateway client id override for local profiles.",
    },
    "account": {
        "type": "string",
        "description": "Optional account code filter when supported by the connector.",
    },
}


def _overrides(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "host": _connection(kwargs.get("host")),
        "port": _int_or_none(kwargs.get("port")),
        "client_id": _int_or_none(kwargs.get("client_id")),
        "account": _connection(kwargs.get("account")),
    }


class TradingConnectionsTool(BaseTool):
    """List available trading connector profiles."""

    name = "trading_connections"
    description = (
        "List selectable trading connector profiles. Connectors come first; paper/live is a profile attribute."
    )
    parameters = {"type": "object", "properties": {}, "required": []}
    repeatable = True
    is_readonly = True

    def execute(self, **_: Any) -> str:
        """List connector profiles and mark the selected one."""
        try:
            selected = load_selected_profile_id()
            return _json_result(
                {
                    "status": "ok",
                    "selected_profile": selected,
                    "profiles": [profile.to_dict(selected=profile.id == selected) for profile in list_profiles()],
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingSelectConnectionTool(BaseTool):
    """Select the default trading connector profile."""

    name = "trading_select_connection"
    description = "Select the default trading connector profile for subsequent trading_* tool calls."
    parameters = {
        "type": "object",
        "properties": {
            "connection": {
                "type": "string",
                "description": "Profile id to select, e.g. ibkr-paper-local.",
            }
        },
        "required": ["connection"],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        """Persist the selected profile id."""
        try:
            profile = profile_by_id(str(kwargs["connection"]).strip())
            path = save_selected_profile_id(profile.id)
            return _json_result({"status": "ok", "selected_profile": profile.id, "path": str(path)})
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingCheckTool(BaseTool):
    """Check a trading connector profile."""

    name = "trading_check"
    description = "Check whether a trading connector profile is configured and reachable. This never places orders."
    parameters = {
        "type": "object",
        "properties": TRADING_COMMON_PARAMETERS,
        "required": [],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Check connector readiness."""
        try:
            return _json_result(check_connection(_connection(kwargs.get("connection")), **_overrides(kwargs)))
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingAccountTool(BaseTool):
    """Read account summary from a trading connector profile."""

    name = "trading_account"
    description = "Read account summary from the selected trading connector profile. Read-only."
    parameters = TradingCheckTool.parameters
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read account summary."""
        try:
            return _json_result(get_account(_connection(kwargs.get("connection")), **_overrides(kwargs)))
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingPositionsTool(BaseTool):
    """Read positions from a trading connector profile."""

    name = "trading_positions"
    description = "Read positions from the selected trading connector profile. Read-only."
    parameters = TradingCheckTool.parameters
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read positions."""
        try:
            return _json_result(get_positions(_connection(kwargs.get("connection")), **_overrides(kwargs)))
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingOrdersTool(BaseTool):
    """Read open orders from a trading connector profile."""

    name = "trading_orders"
    description = "Read open orders from the selected trading connector profile. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TRADING_COMMON_PARAMETERS,
            "include_executions": {"type": "boolean", "default": False},
        },
        "required": [],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read open orders."""
        try:
            return _json_result(
                get_open_orders(
                    _connection(kwargs.get("connection")),
                    include_executions=bool(kwargs.get("include_executions", False)),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingQuoteTool(BaseTool):
    """Read a quote from a trading connector profile."""

    name = "trading_quote"
    description = "Read a quote snapshot from the selected trading connector profile. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TRADING_COMMON_PARAMETERS,
            "symbol": {"type": "string", "description": "Symbol, e.g. AAPL"},
            "exchange": {"type": "string", "default": "SMART"},
            "currency": {"type": "string", "default": "USD"},
            "sec_type": {"type": "string", "default": "STK"},
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read quote snapshot."""
        try:
            return _json_result(
                get_quote(
                    str(kwargs["symbol"]),
                    _connection(kwargs.get("connection")),
                    exchange=str(kwargs.get("exchange") or "SMART"),
                    currency=str(kwargs.get("currency") or "USD"),
                    sec_type=str(kwargs.get("sec_type") or "STK"),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})


class TradingHistoryTool(BaseTool):
    """Read historical bars from a trading connector profile."""

    name = "trading_history"
    description = "Read historical bars from the selected trading connector profile. Read-only."
    parameters = {
        "type": "object",
        "properties": {
            **TradingQuoteTool.parameters["properties"],
            "duration": {"type": "string", "default": "30 D"},
            "bar_size": {"type": "string", "default": "1 day"},
            "what_to_show": {"type": "string", "default": "TRADES"},
            "use_rth": {"type": "boolean", "default": True},
        },
        "required": ["symbol"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Read historical bars."""
        try:
            return _json_result(
                get_history(
                    str(kwargs["symbol"]),
                    _connection(kwargs.get("connection")),
                    exchange=str(kwargs.get("exchange") or "SMART"),
                    currency=str(kwargs.get("currency") or "USD"),
                    sec_type=str(kwargs.get("sec_type") or "STK"),
                    duration=str(kwargs.get("duration") or "30 D"),
                    bar_size=str(kwargs.get("bar_size") or "1 day"),
                    what_to_show=str(kwargs.get("what_to_show") or "TRADES"),
                    use_rth=bool(kwargs.get("use_rth", True)),
                    **_overrides(kwargs),
                )
            )
        except Exception as exc:  # noqa: BLE001
            return _json_result({"status": "error", "error": str(exc)})
