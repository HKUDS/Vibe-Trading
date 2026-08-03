#!/usr/bin/env python3
"""Vibe-Trading MCP Server — expose finance research tools to any MCP client.

Works with OpenClaw, Claude Desktop, Cursor, and any MCP-compatible client.
Zero API key required for HK/US/crypto research markets (yfinance, OKX,
AKShare are free). Trading connector tools are profile-scoped and require the
selected connector's own local app or OAuth setup.

Surfaces 55 tools: skills, research goals, backtest/factor/options/pattern
analysis, market data, fundamentals & capital-flow & news & discovery
(get_fund_flow / get_dragon_tiger / get_northbound_flow / get_margin_trading /
get_block_trades / get_shareholder_count / get_lockup_expiry / get_sector_info /
get_research_reports / get_stock_news / get_sec_filings /
get_financial_statements / get_options_chain / get_stock_profile /
screen_market / search_symbol / get_macro_series / iwencai_search), read-only
trading-connector reads, swarm orchestration, trade-journal and shadow-account
analysis. Every exposed tool is read-only or research-only; no order-placing or
order-cancelling tool is ever surfaced via MCP.

This module is a thin assembler: it owns the FastMCP instance, the network
transport / DNS-rebinding security wiring, and the CLI entry point, while the
tool implementations live in domain modules under ``src/mcp_tools/``
(skills / goals / analysis / web_files / trading / swarm / market_data /
research_data), each exposing a ``register(mcp)`` function. The split mirrors
the ``api_server.py`` + ``src/api/*_routes.py`` pattern.

Usage:
    python mcp_server.py                    # stdio transport (default)
    python mcp_server.py --transport sse    # legacy SSE transport (GET /sse + POST /messages/)
    python mcp_server.py --transport http   # Streamable HTTP transport (single POST/GET /mcp endpoint)

The ``http`` (Streamable HTTP) transport is the current MCP spec default
(2025-03-26+). Modern clients (e.g. QwenPaw, and clients that negotiate by
POSTing an InitializeRequest) require it; the legacy ``sse`` transport is
deprecated. The single endpoint is served at ``/mcp``, so point HTTP clients
at ``http://<host>:<port>/mcp`` (NOT ``/sse``, which is a legacy-SSE artifact).

OpenClaw config (~/.openclaw/config.yaml):
    skills:
      - name: vibe-trading
        command: python /path/to/agent/mcp_server.py

Claude Desktop config:
    {
      "mcpServers": {
        "vibe-trading": {
          "command": "python",
          "args": ["/path/to/agent/mcp_server.py"]
        }
      }
    }
"""

from __future__ import annotations

# ruff: noqa: E402

import logging
import sys
from pathlib import Path
from typing import Any

# Ensure agent/ is on sys.path
AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from fastmcp import FastMCP

from cli._version import __version__ as APP_VERSION
from src.mcp_tools import register_all
from src.mcp_tools._shared import (
    get_registry as _get_registry,
    reset_registry as _reset_registry,
    resolve_session_id as _resolve_session_id,
    set_include_shell_tools as _set_include_shell_tools,
)
from src.mcp_tools.swarm import _build_run_payload, _run_to_dict

mcp = FastMCP("Vibe-Trading", version=APP_VERSION)

register_all(mcp)

logger = logging.getLogger(__name__)

# Fail-closed default mirrored from ``src.mcp_tools._shared`` so module-level
# consumers (tests, importers) see the safe default without touching the
# registry. ``main()`` syncs both this and the shared flag on opt-in.
_include_shell_tools = False


# ---------------------------------------------------------------------------
# Network-transport DNS-rebinding hardening (GHSA-p3c9)
#
# The stdio transport is a private parent/child pipe and needs no host guard.
# The network transports (``--transport sse`` / ``http``) bind a TCP port, so
# a page in the user's browser could POST to the local MCP endpoint via
# DNS-rebinding and reach every MCP tool. fastmcp ships NO host/origin
# protection, so we wrap the ASGI app with a Host allow-list
# (_HostGuardMiddleware) plus an Origin allow-list before the MCP session is
# reached. Default = loopback-only, so a local HTTP/SSE MCP still works.
# ---------------------------------------------------------------------------

_DEFAULT_MCP_ALLOWED_HOSTS = ("127.0.0.1", "::1", "localhost")


def _normalize_host(host: str) -> str:
    """Normalize a Host header value (or allow-list entry) for comparison.

    Strips the port and any IPv6 brackets, then lowercases: ``[::1]:8900``
    becomes ``::1``, ``Example.COM:8900`` becomes ``example.com``. A value
    with more than one colon and no brackets is treated as a bare IPv6
    literal and kept whole (never split into a fake ``host:port`` pair).

    Args:
        host: Raw Host header value or allow-list entry.

    Returns:
        The comparable hostname, lowercased.
    """
    value = host.strip()
    if value.startswith("["):
        # Bracketed IPv6 literal, optionally followed by ``:port``.
        end = value.find("]")
        if end != -1:
            return value[1:end].lower()
    elif value.count(":") == 1:
        # ``name:port`` — bare IPv6 (multiple colons) is kept whole.
        value = value.rsplit(":", 1)[0]
    return value.lower()


def _parse_allowed_hosts(raw: str | None) -> list[str]:
    """Parse ``VIBE_TRADING_MCP_ALLOWED_HOSTS`` into a Host/Origin allow-list.

    Entries are normalized like Host header values (case-insensitive, IPv6
    brackets stripped); wildcard forms (``*``, ``*.``) pass through apart
    from lowercasing.

    Args:
        raw: Comma-separated env value (may be ``None`` / empty).

    Returns:
        The parsed host list, or the loopback-only default
        (``127.0.0.1``, ``::1``, ``localhost``) when unset/blank so a local
        HTTP/SSE MCP keeps working while DNS-rebinding hosts are rejected.
    """
    hosts = []
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        hosts.append(entry.lower() if entry.startswith("*") else _normalize_host(entry))
    return hosts or list(_DEFAULT_MCP_ALLOWED_HOSTS)


def _host_matches(host: str, pattern: str) -> bool:
    """Return whether ``host`` matches an allow-list ``pattern``.

    Mirrors Starlette's TrustedHostMiddleware semantics: ``*`` allows any host
    and a leading ``*.`` matches the bare domain plus any subdomain.
    """
    if pattern == "*":
        return True
    if pattern.startswith("*."):
        return host == pattern[2:] or host.endswith(pattern[1:])
    return host == pattern


def _origin_allowed(origin: str | None, allowed_hosts: list[str]) -> bool:
    """Return whether a request ``Origin`` header is trusted.

    A missing/blank Origin is allowed: non-browser MCP clients (curl, the
    Python SDK) never send one, and DNS-rebinding is a browser-only attack. A
    present Origin is trusted only when its hostname matches the allow-list.

    Args:
        origin: The raw ``Origin`` header value, or ``None`` when absent.
        allowed_hosts: Trusted hostnames (same list used for Host validation).
    """
    if not origin:
        return True
    from urllib.parse import urlparse

    host = urlparse(origin).hostname
    if not host:
        return False
    return any(_host_matches(host, pattern) for pattern in allowed_hosts)


class _HostGuardMiddleware:
    """ASGI middleware rejecting requests with an untrusted Host header.

    Same role as Starlette's TrustedHostMiddleware, but normalizes the
    header first: Starlette's plain ``split(":")`` mangles bracketed IPv6
    (``[::1]:8900`` → ``"["``) and matches case-sensitively, which locked
    out ``--host ::1`` deployments and ``LOCALHOST`` clients entirely.
    """

    def __init__(self, app: Any, allowed_hosts: list[str]) -> None:
        self.app = app
        self.allowed_hosts = list(allowed_hosts)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            host: str | None = None
            for key, value in scope.get("headers", []):
                if key == b"host":
                    host = value.decode("latin-1")
                    break
            normalized = _normalize_host(host) if host else ""
            if not any(_host_matches(normalized, pattern) for pattern in self.allowed_hosts):
                from starlette.responses import PlainTextResponse

                await PlainTextResponse("Invalid host header", status_code=400)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class _OriginGuardMiddleware:
    """ASGI middleware rejecting untrusted cross-origin browser requests.

    Complements TrustedHostMiddleware: it blocks a request whose ``Origin``
    header names a host outside the allow-list before the MCP session handler
    runs, returning ``403`` so a rebinding page cannot invoke MCP tools.
    """

    def __init__(self, app: Any, allowed_hosts: list[str]) -> None:
        self.app = app
        self.allowed_hosts = list(allowed_hosts)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") == "http":
            origin: str | None = None
            for key, value in scope.get("headers", []):
                if key == b"origin":
                    origin = value.decode("latin-1")
                    break
            if not _origin_allowed(origin, self.allowed_hosts):
                from starlette.responses import PlainTextResponse

                await PlainTextResponse("Origin not allowed", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _security_middleware(allowed_hosts: list[str]) -> list[Any]:
    """Build the Host + Origin allow-list middleware for network MCP transports.

    Args:
        allowed_hosts: Trusted hostnames from ``_parse_allowed_hosts``.

    Returns:
        A middleware list suitable for ``FastMCP.http_app(middleware=...)``.
    """
    from starlette.middleware import Middleware

    return [
        Middleware(_HostGuardMiddleware, allowed_hosts=allowed_hosts),
        Middleware(_OriginGuardMiddleware, allowed_hosts=allowed_hosts),
    ]


def _build_network_app(transport: str, allowed_hosts: list[str]):
    """Build a DNS-rebinding-hardened FastMCP ASGI app for a network transport.

    Args:
        transport: ``"sse"`` or ``"streamable-http"``.
        allowed_hosts: Trusted Host/Origin hostnames.

    Returns:
        A Starlette ASGI app (with MCP lifespan) ready for ``uvicorn.run``.
    """
    return mcp.http_app(transport=transport, middleware=_security_middleware(allowed_hosts))


def _env_shell_tools_enabled() -> bool:
    """Return whether shell tools were explicitly enabled via the environment."""
    from src.config.accessor import get_env_config

    return get_env_config().api.vibe_trading_enable_shell_tools


def _resolve_include_shell_tools(cli_opt_in: bool) -> bool:
    """Resolve whether the MCP server should register shell tools.

    Process-control tools (``bash`` / ``background_run`` /
    ``cancel_background``) run commands or terminate tracked command trees and
    are an RCE surface regardless of transport. They are therefore disabled for
    every transport unless the operator explicitly opts in. Transport type never
    implicitly grants shell access: previously ``stdio`` force-enabled these
    tools with no opt-out (GHSA-6wjh-cc6v-xfrx), which also widened the reachable
    surface of the ``bash`` OS-command-injection issue (GHSA-m768-22r9-h4x7).

    Args:
        cli_opt_in: Whether ``--enable-shell-tools`` was passed on the command line.

    Returns:
        True only when the operator opted in via the flag or the
        ``VIBE_TRADING_ENABLE_SHELL_TOOLS`` environment variable.
    """
    return bool(cli_opt_in) or _env_shell_tools_enabled()


# Tool-function re-exports so ``mcp_server.<tool>`` keeps resolving for callers
# and tests that invoke the tools directly (moved implementations live in
# ``src/mcp_tools``). Keep this list in sync with ``src/mcp_tools/__init__.py``.
from src.mcp_tools.analysis import (  # noqa: E402
    analyze_options,
    analyze_options_payoff,
    backtest,
    factor_analysis,
    pattern_recognition,
)
from src.mcp_tools.goals import (  # noqa: E402
    add_goal_evidence,
    get_research_goal,
    start_research_goal,
    update_research_goal_status,
)
from src.mcp_tools.market_data import get_market_data  # noqa: E402
from src.mcp_tools.research_data import (  # noqa: E402
    analyze_trade_journal,
    extract_shadow_strategy,
    get_block_trades,
    get_dragon_tiger,
    get_financial_statements,
    get_fund_flow,
    get_lockup_expiry,
    get_macro_series,
    get_margin_trading,
    get_northbound_flow,
    get_options_chain,
    get_research_reports,
    get_sec_filings,
    get_sector_info,
    get_shareholder_count,
    get_stock_news,
    get_stock_profile,
    iwencai_search,
    render_shadow_report,
    run_shadow_backtest,
    scan_shadow_signals,
    screen_market,
    search_symbol,
)
from src.mcp_tools.skills import list_skills, load_skill  # noqa: E402
from src.mcp_tools.swarm import (  # noqa: E402
    get_run_result,
    get_swarm_status,
    list_runs,
    list_swarm_presets,
    reap_stale_runs,
    retry_run,
    run_swarm,
)
from src.mcp_tools.trading import (  # noqa: E402
    trading_account,
    trading_check,
    trading_connections,
    trading_history,
    trading_orders,
    trading_positions,
    trading_quote,
    trading_select_connection,
)
from src.mcp_tools.web_files import read_document, read_file, read_url, web_search, write_file  # noqa: E402

# Intentional re-exports: ``mcp_server.<tool>`` and the private helpers are part
# of the module's public surface for callers and tests that invoke the tools
# directly (implementations live in ``src/mcp_tools``).
__all__ = [
    "list_skills",
    "load_skill",
    "start_research_goal",
    "get_research_goal",
    "add_goal_evidence",
    "update_research_goal_status",
    "backtest",
    "factor_analysis",
    "analyze_options",
    "analyze_options_payoff",
    "pattern_recognition",
    "read_url",
    "read_document",
    "web_search",
    "write_file",
    "read_file",
    "trading_connections",
    "trading_select_connection",
    "trading_check",
    "trading_account",
    "trading_positions",
    "trading_orders",
    "trading_quote",
    "trading_history",
    "list_swarm_presets",
    "run_swarm",
    "get_swarm_status",
    "get_run_result",
    "list_runs",
    "reap_stale_runs",
    "retry_run",
    "get_market_data",
    "get_fund_flow",
    "get_dragon_tiger",
    "get_northbound_flow",
    "get_margin_trading",
    "get_block_trades",
    "get_shareholder_count",
    "get_lockup_expiry",
    "get_sector_info",
    "get_research_reports",
    "get_stock_news",
    "get_sec_filings",
    "get_financial_statements",
    "get_options_chain",
    "get_stock_profile",
    "screen_market",
    "search_symbol",
    "get_macro_series",
    "iwencai_search",
    "analyze_trade_journal",
    "extract_shadow_strategy",
    "run_shadow_backtest",
    "render_shadow_report",
    "scan_shadow_signals",
    "_get_registry",
    "_resolve_session_id",
    "_run_to_dict",
    "_build_run_payload",
]


def main():
    """Entry point for `vibe-trading-mcp` CLI command."""
    import argparse

    parser = argparse.ArgumentParser(description="Vibe-Trading MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "http"],
        default="stdio",
        help="MCP transport (default: stdio). 'http' = Streamable HTTP (current spec default), "
        "served at POST/GET /mcp. 'sse' = legacy deprecated SSE (GET /sse + POST /messages/).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Network bind host for --transport sse / http (default: 127.0.0.1)",
    )
    parser.add_argument("--port", type=int, default=8900, help="SSE/HTTP port (default: 8900)")
    parser.add_argument(
        "--enable-shell-tools",
        action="store_true",
        help="Register bash / background_run / cancel_background (OS process "
        "control — RCE surface). OFF by default for every transport; equivalent "
        "to setting VIBE_TRADING_ENABLE_SHELL_TOOLS=1.",
    )
    args = parser.parse_args()

    # One-time move of pre-#904 code-relative state into the runtime root.
    # A failed migration must never block the server.
    try:
        from src.config import migrate as _migrate

        _migrate.migrate_legacy_state()
    except Exception:  # pragma: no cover — best-effort
        logging.getLogger(__name__).warning("Legacy state migration failed", exc_info=True)

    global _include_shell_tools
    _include_shell_tools = _resolve_include_shell_tools(args.enable_shell_tools)
    _set_include_shell_tools(_include_shell_tools)
    _reset_registry()
    _get_registry()  # pre-warm: avoids deadlock when first tools/call lazy-inits inside FastMCP worker thread

    if args.transport in ("sse", "http"):
        # Network transports bind a TCP port and are therefore reachable by a
        # DNS-rebinding page in the user's browser. fastmcp 3.2.4 has no
        # built-in host/origin guard, so wrap the ASGI app with a Host + Origin
        # allow-list (default loopback-only) and serve via uvicorn directly.
        # 'http' = Streamable HTTP (single /mcp endpoint, MCP spec 2025-03-26+),
        # replacing the deprecated two-endpoint SSE transport for modern clients.
        import uvicorn

        from src.config.accessor import get_env_config

        allowed_hosts = _parse_allowed_hosts(get_env_config().api.vibe_trading_mcp_allowed_hosts)
        transport = "streamable-http" if args.transport == "http" else "sse"
        app = _build_network_app(transport, allowed_hosts)
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
