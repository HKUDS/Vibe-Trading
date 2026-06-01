"""Connector-first trading operations used by CLI, MCP, and agent tools."""

from __future__ import annotations

from typing import Any

from src.trading.profiles import list_profiles, profile_by_id
from src.trading.types import TradingProfile

RUNNER_CAPABILITY = "runner.manage.requires_mandate"


def check_connection(profile_id: str | None = None, **overrides: Any) -> dict[str, Any]:
    """Check a connector profile without mutating broker state."""
    profile = profile_by_id(profile_id)
    if profile.transport == "local_tws":
        from src.trading.connectors.ibkr.local import check_local_status

        cfg = _ibkr_config(profile, overrides)
        report = check_local_status(cfg)
        report["profile_id"] = profile.id
        report["connector"] = profile.connector
        report["environment"] = profile.environment
        report["transport"] = profile.transport
        return report

    return _remote_status(profile)


def get_account(profile_id: str | None = None, **overrides: Any) -> dict[str, Any]:
    """Read account summary for a connector profile."""
    profile = profile_by_id(profile_id)
    if profile.transport == "local_tws":
        from src.trading.connectors.ibkr.local import get_account_snapshot

        return _with_profile(profile, get_account_snapshot(_ibkr_config(profile, overrides)))
    return _call_remote(profile, "account", {})


def get_positions(profile_id: str | None = None, **overrides: Any) -> dict[str, Any]:
    """Read positions for a connector profile."""
    profile = profile_by_id(profile_id)
    if profile.transport == "local_tws":
        from src.trading.connectors.ibkr.local import get_positions as _get_positions

        return _with_profile(profile, _get_positions(_ibkr_config(profile, overrides)))
    return _call_remote(profile, "positions", {})


def get_open_orders(
    profile_id: str | None = None,
    *,
    include_executions: bool = False,
    **overrides: Any,
) -> dict[str, Any]:
    """Read open orders for a connector profile."""
    profile = profile_by_id(profile_id)
    if profile.transport == "local_tws":
        from src.trading.connectors.ibkr.local import get_open_orders as _get_open_orders

        return _with_profile(
            profile,
            _get_open_orders(_ibkr_config(profile, overrides), include_executions=include_executions),
        )
    return _call_remote(profile, "orders", {})


def get_quote(
    symbol: str,
    profile_id: str | None = None,
    *,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    **overrides: Any,
) -> dict[str, Any]:
    """Read a quote for a connector profile."""
    profile = profile_by_id(profile_id)
    if profile.transport == "local_tws":
        from src.trading.connectors.ibkr.local import get_quote as _get_quote

        return _with_profile(
            profile,
            _get_quote(
                symbol,
                config=_ibkr_config(profile, overrides),
                exchange=exchange,
                currency=currency,
                sec_type=sec_type,
            ),
        )
    return _call_remote(profile, "quote", {"symbols": [symbol], "symbol": symbol})


def get_history(
    symbol: str,
    profile_id: str | None = None,
    *,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    duration: str = "30 D",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
    **overrides: Any,
) -> dict[str, Any]:
    """Read historical bars for a connector profile."""
    profile = profile_by_id(profile_id)
    if profile.transport == "local_tws":
        from src.trading.connectors.ibkr.local import get_historical_bars

        return _with_profile(
            profile,
            get_historical_bars(
                symbol,
                config=_ibkr_config(profile, overrides),
                exchange=exchange,
                currency=currency,
                sec_type=sec_type,
                duration=duration,
                bar_size=bar_size,
                what_to_show=what_to_show,
                use_rth=use_rth,
            ),
        )
    return _unsupported(profile, "history.read")


def profile_supports_live_runner(profile: TradingProfile) -> bool:
    """Return whether a profile can run the managed live runner."""
    return (
        profile.environment == "live"
        and profile.transport == "remote_mcp"
        and RUNNER_CAPABILITY in profile.capabilities
    )


def live_runner_profile_for_broker(broker: str) -> TradingProfile | None:
    """Return the live-runner profile for a broker, if one exists."""
    key = str(broker or "").strip().lower()
    if not key:
        return None
    for profile in list_profiles():
        if profile.connector == key and profile_supports_live_runner(profile):
            return profile
    return None


def broker_supports_live_runner(broker: str) -> bool:
    """Return whether any configured profile exposes live runner management."""
    return live_runner_profile_for_broker(broker) is not None


def connector_profile_id_for_broker(broker: str) -> str:
    """Return the preferred connector profile id for a broker on-ramp."""
    key = str(broker or "").strip().lower()
    if not key:
        raise ValueError("broker must not be blank")

    candidates = [profile for profile in list_profiles() if profile.connector == key and profile.environment == "live"]
    for profile in candidates:
        if profile.transport == "remote_mcp":
            return profile.id
    if candidates:
        return candidates[0].id
    return f"{key}-live-mcp"


def runner_tool_name(connector: str, operation: str) -> str | None:
    """Map a runner operation to a connector-specific remote MCP tool name."""
    if connector == "robinhood":
        from src.trading.connectors.robinhood.mcp import runner_tool_name as _runner_tool_name

        return _runner_tool_name(operation)
    return None


def _with_profile(profile: TradingProfile, payload: dict[str, Any]) -> dict[str, Any]:
    """Add connector profile metadata to an operation payload."""
    result = dict(payload)
    result["profile_id"] = profile.id
    result["connector"] = profile.connector
    result["environment"] = profile.environment
    result["transport"] = profile.transport
    return result


def _ibkr_config(profile: TradingProfile, overrides: dict[str, Any]):
    """Build an IBKR local config from a trading profile and call overrides."""
    from src.trading.connectors.ibkr.local import IBKRLocalConfig, config_path, load_config

    default_cfg = IBKRLocalConfig.from_mapping(profile.config)
    base = load_config()
    if config_path().exists() and base.profile == default_cfg.profile:
        cfg = base
    else:
        cfg = default_cfg
    return cfg.with_overrides(
        host=_clean(overrides.get("host")),
        port=_int_or_none(overrides.get("port")),
        client_id=_int_or_none(overrides.get("client_id")),
        account=_clean(overrides.get("account")),
    )


def _remote_status(profile: TradingProfile) -> dict[str, Any]:
    """Return local authorization/config status for a remote MCP profile."""
    from src.config.loader import load_agent_config
    from src.live.registry import has_cached_oauth_token

    server_name = str(profile.config.get("server") or profile.connector)
    server = (load_agent_config().mcp_servers or {}).get(server_name)
    auth = getattr(server, "auth", None) if server is not None else None
    token_present = False
    if server is not None and auth is not None:
        token_present = has_cached_oauth_token(server.url, auth.cache_dir)
    return {
        "status": "ok" if token_present else "not_authorized",
        "profile_id": profile.id,
        "connector": profile.connector,
        "environment": profile.environment,
        "transport": profile.transport,
        "configured": server is not None,
        "oauth_token_present": token_present,
        "capabilities": list(profile.capabilities),
        "readonly": profile.readonly,
        "notes": profile.notes,
    }


def _call_remote(profile: TradingProfile, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call a known read operation on a remote MCP connector profile."""
    from src.config.loader import load_agent_config
    from src.live.registry import has_cached_oauth_token
    from src.tools.mcp import MCPServerAdapter

    remote_name = _remote_tool_name(profile.connector, operation)
    if remote_name is None:
        return _unsupported(profile, f"{operation}.read")

    server_name = str(profile.config.get("server") or profile.connector)
    server = (load_agent_config().mcp_servers or {}).get(server_name)
    if server is None:
        return {
            "status": "error",
            "profile_id": profile.id,
            "connector": profile.connector,
            "environment": profile.environment,
            "transport": profile.transport,
            "error": f"remote MCP server '{server_name}' is not configured",
        }

    enabled_tools = list(getattr(server, "enabled_tools", None) or [])
    if "*" not in enabled_tools and remote_name not in enabled_tools:
        return {
            "status": "error",
            "profile_id": profile.id,
            "connector": profile.connector,
            "environment": profile.environment,
            "transport": profile.transport,
            "error": f"remote tool '{remote_name}' is not enabled for connector profile '{profile.id}'",
            "enabled_tools": enabled_tools,
        }

    auth = getattr(server, "auth", None)
    if profile.environment == "live" and auth is None:
        return {
            "status": "error",
            "profile_id": profile.id,
            "connector": profile.connector,
            "environment": profile.environment,
            "transport": profile.transport,
            "error": f"connector profile '{profile.id}' has no OAuth auth configured",
        }
    if auth is not None and not has_cached_oauth_token(server.url, auth.cache_dir):
        return {
            "status": "not_authorized",
            "profile_id": profile.id,
            "connector": profile.connector,
            "environment": profile.environment,
            "transport": profile.transport,
            "error": (
                f"connector profile '{profile.id}' is not authorized. "
                f"Run `vibe-trading connector authorize {profile.id}` from a desktop session."
            ),
        }

    adapter = MCPServerAdapter(server_name, server)
    return _with_profile(
        profile,
        adapter.call_tool(remote_name, _remote_arguments(profile.connector, operation, arguments)),
    )


def _remote_tool_name(connector: str, operation: str) -> str | None:
    """Map generic read operations to current remote MCP tool names."""
    if connector == "robinhood":
        from src.trading.connectors.robinhood.mcp import remote_tool_name

        return remote_tool_name(operation)
    return None


def _remote_arguments(connector: str, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Normalize generic arguments for a remote MCP operation."""
    if connector == "robinhood":
        from src.trading.connectors.robinhood.mcp import remote_arguments

        return remote_arguments(operation, arguments)
    return {}


def _unsupported(profile: TradingProfile, capability: str) -> dict[str, Any]:
    """Return a standard unsupported-capability payload."""
    return {
        "status": "error",
        "profile_id": profile.id,
        "connector": profile.connector,
        "environment": profile.environment,
        "transport": profile.transport,
        "error": f"profile '{profile.id}' does not support {capability} through the generic trading tool yet",
        "capabilities": list(profile.capabilities),
    }


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)
