#!/usr/bin/env python3
"""Vibe-Trading MCP Server — expose finance research tools to any MCP client.

Works with OpenClaw, Claude Desktop, Cursor, and any MCP-compatible client.
Zero API key required for HK/US/crypto research markets (yfinance, OKX,
AKShare are free). Trading connector tools are profile-scoped and require the
selected connector's own local app or OAuth setup.

Surfaces 74 tools: skills, research goals, strategy discovery,
backtest/factor/options/pattern
analysis, market data, fundamentals & capital-flow & news & discovery
(get_fund_flow / get_dragon_tiger / get_northbound_flow / get_margin_trading /
get_block_trades / get_shareholder_count / get_lockup_expiry / get_sector_info /
get_research_reports / get_stock_news / get_sec_filings /
get_financial_statements / get_options_chain / get_stock_profile /
screen_market / search_symbol / get_macro_series / iwencai_search /
qveris_search / qveris_inspect / qveris_execute),
institutional-research and alternative data (get_institutional_holdings /
etf_holdings / prediction_market / research_papers), read-only finance math and
market analytics (quantlib_call / cashflow_performance / orderbook_depth /
sentiment / technical_indicators / get_fundamentals), read-only
trading-connector reads, swarm orchestration, trade-journal and shadow-account
analysis. Every exposed tool is read-only or research-only except
refresh_strategy_evidence, which writes ONLY the disposable facade-owned
strategy-evidence cache from local run artifacts; no order-placing or
order-cancelling tool is ever surfaced via MCP. The QVeris tools additionally
require QVeris paid routing (QVERIS_API_KEY + paid mode), and qveris_execute
is billable research-data execution only — it never places orders.

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

import json
import logging
import sys
from copy import deepcopy
from importlib import import_module
from pathlib import Path
from typing import Annotated, Any

# Ensure agent/ is on sys.path
AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from fastmcp import Context, FastMCP
from pydantic import BeforeValidator

from cli._version import __version__ as APP_VERSION
from src.market_data import (
    DEFAULT_MAX_ROWS,
    cap_rows,
    detect_source,
    get_loader,
)

mcp = FastMCP("Vibe-Trading", version=APP_VERSION)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy-loaded singletons
# ---------------------------------------------------------------------------

_skills_loader = None
_registry = None
_goal_store = None
# Fail-closed default: bash / background_run / cancel_background form a remote
# process-control surface once the MCP server is reachable by any client (stdio,
# SSE, or Streamable HTTP), so they stay OFF unless an operator explicitly opts
# in. main() may flip this on via --enable-shell-tools or the
# VIBE_TRADING_ENABLE_SHELL_TOOLS env var. Keeping the module-level default off
# means an ASGI/import deployment that never calls main() also stays safe.
_include_shell_tools = False


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


def _get_skills_loader():
    global _skills_loader
    if _skills_loader is None:
        from src.agent.skills import SkillsLoader

        _skills_loader = SkillsLoader()
    return _skills_loader


def _get_registry():
    global _registry
    if _registry is None:
        from src.tools import build_registry

        _registry = build_registry(include_shell_tools=_include_shell_tools)
    return _registry


def _get_goal_store():
    """Return the shared finance goal store."""
    global _goal_store
    if _goal_store is None:
        from src.goal import GoalStore

        _goal_store = GoalStore()
    return _goal_store


_mcp_session_id: str | None = None


def _resolve_session_id(session_id: str = "", ctx: Context | None = None) -> str:
    """Resolve the goal session: explicit id, then per-connection id, then
    one id per server process.

    The in-process tool registry injects the host session and keeps
    ``session_id`` out of its required schema. MCP has no such injection point,
    so these tools used to mark the id required — asking the model to invent an
    internal identifier it has no way to know, the opposite contract from the
    local path (#885). Default instead to a session id, while still honouring
    an explicit id from a client that tracks its own conversations.

    A single server process can serve many concurrent MCP connections (the
    http/sse transports this file documents), so the process-wide fallback on
    its own would collapse every such caller onto one goal session. ``ctx``,
    when available, carries FastMCP's own per-connection session id (the real
    ``mcp-session-id`` header for StreamableHTTP, a cached id for the other
    transports) and takes precedence over the process fallback for exactly
    that reason.

    Args:
        session_id: Optional client-supplied session id.
        ctx: Optional MCP request context; supplies a per-connection id when
            the tool is invoked through a live MCP request.

    Returns:
        A non-empty session id.
    """
    global _mcp_session_id
    if cleaned := session_id.strip():
        return cleaned
    if ctx is not None:
        try:
            return ctx.session_id
        except RuntimeError:
            pass
    if _mcp_session_id is None:
        import uuid

        _mcp_session_id = f"mcp-{uuid.uuid4().hex[:12]}"
    return _mcp_session_id


def _json_ok(**payload: Any) -> str:
    """Return a standard MCP JSON success envelope."""
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False, indent=2)


def _json_error(error: str, *, error_type: str = "error") -> str:
    """Return a standard MCP JSON error envelope."""
    return json.dumps(
        {"status": "error", "error_type": error_type, "error": error},
        ensure_ascii=False,
        indent=2,
    )


def _default_goal_criteria() -> list[str]:
    """Return the MVP finance protocol checklist."""
    from src.goal.context import default_goal_criteria

    return default_goal_criteria()


def _clean_list(value: list[str] | None) -> list[str]:
    """Strip empty list values from MCP payloads."""
    return [item.strip() for item in (value or []) if item and item.strip()]


def _blank_to_none(value: str | None) -> str | None:
    """Normalize blank MCP strings to None."""
    if value is None:
        return None
    value = value.strip()
    return value or None


def _coerce_json_string(value: Any) -> Any:
    """Decode JSON array/object strings some MCP clients send for list/dict args.

    FastMCP publishes optional list/dict parameters as ``anyOf`` schemas, and
    several MCP clients (observed with Claude Desktop / Claude Code) do not
    surface ``anyOf`` to the model as a concrete type — the model then serializes
    the argument as a JSON string (``'["us"]'``), which strict pydantic
    validation rejects before the tool body ever runs (issue #987). This
    validator is attached as a ``BeforeValidator`` to every list/dict MCP
    parameter, so it runs *before* type checking and decodes such a string into
    the list/dict it encodes.

    Non-string values pass through untouched. A string that is not a JSON array
    or object is returned unchanged so pydantic still raises its normal, precise
    type error rather than a confusing JSON parse failure.

    Args:
        value: The raw argument received from the MCP client.

    Returns:
        The decoded list/dict when the value is a JSON array/object string,
        otherwise the value unchanged.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("[", "{"):
            try:
                return json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                return value
    return value


# Lenient list/dict parameter types for the @mcp.tool signatures below
# (issue #987). Each wraps the real type with _coerce_json_string so a
# JSON-encoded string from a client is decoded before pydantic validates it,
# while the published JSON schema — and thus every well-behaved client — is left
# exactly as before.
_lenient = BeforeValidator(_coerce_json_string)
_lenient_str_list = Annotated[list[str], _lenient]
_lenient_str_list_opt = Annotated[list[str] | None, _lenient]
_lenient_float_list_opt = Annotated[list[float] | None, _lenient]
_lenient_dict_list = Annotated[list[dict[str, Any]], _lenient]
_lenient_dict_list_opt = Annotated[list[dict[str, Any]] | None, _lenient]
_lenient_dict_any_opt = Annotated[dict[str, Any] | None, _lenient]
_lenient_dict_str_str = Annotated[dict[str, str], _lenient]


def _audit_rows_from_payload(value: list[dict[str, Any]] | None):
    """Parse MCP completion audit rows."""
    from src.goal import AuditRow

    rows = []
    for item in value or []:
        criterion_id = str(item.get("criterion_id") or "").strip()
        result = str(item.get("result") or "").strip()
        if not criterion_id or not result:
            raise ValueError("audit rows require criterion_id and result")
        rows.append(
            AuditRow(
                criterion_id=criterion_id,
                result=result,
                evidence_ids=_clean_list(item.get("evidence_ids") or []),
                notes=str(item.get("notes") or ""),
            )
        )
    return rows


def _risk_tier_from_text(value: str):
    """Parse and validate goal risk tier."""
    from src.goal import RiskTier

    risk_tier = RiskTier(value)
    if risk_tier is RiskTier.LIVE_TRADING_OR_EXECUTION:
        raise ValueError("live trading or execution goals are not supported")
    return risk_tier


# ---------------------------------------------------------------------------
# Skill tools
# ---------------------------------------------------------------------------


@mcp.tool
def list_skills() -> str:
    """List all available finance skills with names and descriptions.

    Returns a JSON array of {name, description} for all loaded skills.
    Use load_skill(name) to get the full documentation for any skill.
    """
    loader = _get_skills_loader()
    skills = [{"name": s.name, "description": s.description} for s in loader.skills]
    return json.dumps(skills, ensure_ascii=False, indent=2)


@mcp.tool
def load_skill(name: str, section: str | None = None, offset: int | None = None) -> str:
    """Load documentation for a named finance skill.

    A skill over the tool-result cap is returned as a skeleton (outline plus
    per-section summaries) instead of being silently cut off. Request a
    specific section by name, or page through one with offset, to read the
    rest. Use list_skills() first to discover available skills.

    Args:
        name: Skill name (e.g. 'strategy-generate', 'risk-analysis', 'technical-basic').
        section: Optional section title to expand (see the skeleton's outline).
        offset: Optional character offset to resume a long section/document from.
    """
    registry = _get_registry()
    params: dict[str, Any] = {"name": name}
    if section is not None:
        params["section"] = section
    if offset is not None:
        params["offset"] = offset
    return registry.execute("load_skill", params)


# ---------------------------------------------------------------------------
# Goal tools
# ---------------------------------------------------------------------------


@mcp.tool
def start_research_goal(
    objective: str,
    session_id: str = "",
    criteria: _lenient_str_list_opt = None,
    ui_summary: str = "",
    protocol: str = "thesis_review",
    risk_tier: str = "research_general",
    token_budget: int | None = None,
    turn_budget: int | None = None,
    time_budget_seconds: int | None = None,
    ctx: Context | None = None,
) -> str:
    """Create or replace the current finance research goal for a session.

    This is the MCP entry point for long-running, research-only finance tasks.
    It creates an auditable goal with checklist criteria and supersedes any
    previous current goal for the same session.

    Args:
        objective: Research-only objective, not a trade execution request.
        session_id: Optional conversation id. Omit it unless the client tracks
            its own sessions; this server then uses one id per process.
        criteria: Optional checklist. Defaults to the MVP finance protocol.
        ui_summary: Optional compact label for UI surfaces.
        protocol: Research protocol name. Defaults to thesis_review.
        risk_tier: One of the supported non-execution risk tiers.
        token_budget: Optional token budget.
        turn_budget: Optional turn budget.
        time_budget_seconds: Optional wall-clock budget.
    """
    try:
        clean_criteria = _clean_list(criteria) or _default_goal_criteria()
        goal = _get_goal_store().replace_goal(
            session_id=_resolve_session_id(session_id, ctx),
            objective=objective,
            criteria=clean_criteria,
            ui_summary=ui_summary,
            source="mcp",
            protocol=protocol,
            risk_tier=_risk_tier_from_text(risk_tier),
            token_budget=token_budget,
            turn_budget=turn_budget,
            time_budget_seconds=time_budget_seconds,
        )
        snapshot = _get_goal_store().get_goal_snapshot(goal.goal_id)
        return _json_ok(snapshot=snapshot)
    except ValueError as exc:
        return _json_error(str(exc), error_type="validation")


@mcp.tool
def get_research_goal(session_id: str = "", ctx: Context | None = None) -> str:
    """Return the current finance research goal snapshot for a session.

    Args:
        session_id: Optional conversation id. Omit it unless the client tracks
            its own sessions; this server then uses one id per process.
    """
    try:
        snapshot = _get_goal_store().get_current_snapshot(_resolve_session_id(session_id, ctx))
    except ValueError as exc:
        return _json_error(str(exc), error_type="validation")
    if snapshot is None:
        return _json_error("No current goal", error_type="not_found")
    return _json_ok(snapshot=snapshot)


@mcp.tool
def add_goal_evidence(
    text: str,
    goal_id: str = "",
    expected_goal_id: str = "",
    session_id: str = "",
    criterion_id: str | None = None,
    claim_id: str | None = None,
    evidence_type: str = "evidence",
    tool_call_id: str | None = None,
    run_id: str | None = None,
    source_provider: str | None = None,
    source_type: str | None = None,
    source_uri: str | None = None,
    symbol_universe: _lenient_str_list_opt = None,
    benchmark: _lenient_str_list_opt = None,
    timeframe: str | None = None,
    method: str | None = None,
    assumptions: _lenient_dict_any_opt = None,
    artifact_path: str | None = None,
    artifact_hash: str | None = None,
    data_as_of: str | None = None,
    confidence: str | None = None,
    caveat: str | None = None,
    contradicts_claim_ids: _lenient_str_list_opt = None,
    ctx: Context | None = None,
) -> str:
    """Append traceable evidence to a finance research goal.

    Args:
        text: Evidence note or result summary.
        goal_id: Optional goal id. Defaults to the current goal for this
            session.
        expected_goal_id: Optional stale-write guard captured before the
            tool/model turn started. Defaults to goal_id.
        session_id: Optional conversation id. Omit it unless the client tracks
            its own sessions; this server then uses one id per process.
        criterion_id: Optional criterion this evidence satisfies.
        claim_id: Optional claim this evidence supports or contradicts.
        evidence_type: Evidence category, default evidence.
        tool_call_id: Source tool call id for traceability; it does not verify evidence by itself.
        run_id: Vibe-Trading run id. It verifies evidence only when the run directory exists.
        source_provider: Data/provider name such as yfinance, OKX, tushare.
            Defaults to "agent_tool" when omitted.
        source_type: Source category such as market_data, document, backtest.
            Defaults to "tool_note" when omitted.
        source_uri: Optional source URL/path.
        symbol_universe: Symbols covered by the evidence.
        benchmark: Benchmark symbols covered by the evidence.
        timeframe: Market timeframe.
        method: Research method used.
        assumptions: Structured assumptions.
        artifact_path: Artifact path. It verifies evidence only when allowed by path policy and paired with a matching sha256 hash.
        artifact_hash: Required sha256 when artifact_path should verify evidence.
        data_as_of: ISO timestamp/date for data freshness.
        confidence: Optional confidence label.
        caveat: Optional limitation note.
        contradicts_claim_ids: Claim ids contradicted by this evidence.
    """
    try:
        from src.goal import EvidenceInput, StaleGoalError

        store = _get_goal_store()
        resolved_session_id = _resolve_session_id(session_id, ctx)
        resolved_goal_id = goal_id.strip()
        if not resolved_goal_id:
            snapshot = store.get_current_snapshot(resolved_session_id)
            if snapshot is None:
                return _json_error("no current goal for this session", error_type="not_found")
            resolved_goal_id = str(snapshot["goal"]["goal_id"])
        resolved_expected_goal_id = expected_goal_id.strip() or resolved_goal_id

        evidence = store.append_evidence(
            session_id=resolved_session_id,
            goal_id=resolved_goal_id,
            expected_goal_id=resolved_expected_goal_id,
            evidence=EvidenceInput(
                criterion_id=_blank_to_none(criterion_id),
                claim_id=_blank_to_none(claim_id),
                evidence_type=evidence_type,
                text=text,
                tool_call_id=_blank_to_none(tool_call_id),
                run_id=_blank_to_none(run_id),
                source_provider=_blank_to_none(source_provider) or "agent_tool",
                source_type=_blank_to_none(source_type) or "tool_note",
                source_uri=_blank_to_none(source_uri),
                symbol_universe=_clean_list(symbol_universe),
                benchmark=_clean_list(benchmark),
                timeframe=_blank_to_none(timeframe),
                method=_blank_to_none(method),
                assumptions=assumptions or {},
                artifact_path=_blank_to_none(artifact_path),
                artifact_hash=_blank_to_none(artifact_hash),
                data_as_of=_blank_to_none(data_as_of),
                confidence=_blank_to_none(confidence),
                caveat=_blank_to_none(caveat),
                contradicts_claim_ids=_clean_list(contradicts_claim_ids),
            ),
        )
        snapshot = store.get_goal_snapshot(resolved_goal_id)
        if snapshot is None:
            return _json_error("Goal snapshot could not be reloaded")
        from dataclasses import asdict

        return _json_ok(evidence=asdict(evidence), snapshot=snapshot)
    except StaleGoalError as exc:
        return _json_error(str(exc), error_type="stale_goal")
    except ValueError as exc:
        return _json_error(str(exc), error_type="validation")


@mcp.tool
def update_research_goal_status(
    status: str,
    goal_id: str = "",
    expected_goal_id: str = "",
    session_id: str = "",
    audit: _lenient_dict_list_opt = None,
    recap: str | None = None,
    ctx: Context | None = None,
) -> str:
    """Update a finance research goal status after an audit.

    Use this to complete, cancel, block, pause, or otherwise move the current
    goal through its lifecycle. ``complete`` requires one audit row per
    required criterion and verified evidence for satisfied rows.

    Args:
        status: Goal lifecycle status, e.g. complete, cancelled, blocked.
        goal_id: Optional goal id. Defaults to the current goal for this
            session.
        expected_goal_id: Optional stale-write guard captured before the
            tool/model turn started. Defaults to goal_id.
        session_id: Optional conversation id. Omit it unless the client tracks
            its own sessions; this server then uses one id per process.
        audit: Optional list of criterion audit rows.
        recap: Optional concise status recap.
    """
    try:
        from src.goal import GoalStatus, StaleGoalError

        store = _get_goal_store()
        resolved_session_id = _resolve_session_id(session_id, ctx)
        resolved_goal_id = goal_id.strip()
        if not resolved_goal_id:
            snapshot = store.get_current_snapshot(resolved_session_id)
            if snapshot is None:
                return _json_error("no current goal for this session", error_type="not_found")
            resolved_goal_id = str(snapshot["goal"]["goal_id"])
        resolved_expected_goal_id = expected_goal_id.strip() or resolved_goal_id

        updated = store.update_status(
            session_id=resolved_session_id,
            goal_id=resolved_goal_id,
            expected_goal_id=resolved_expected_goal_id,
            status=GoalStatus(status),
            audit=_audit_rows_from_payload(audit),
            recap=_blank_to_none(recap),
        )
        snapshot = store.get_goal_snapshot(updated.goal_id)
        if snapshot is None:
            return _json_error("Goal snapshot could not be reloaded")
        return _json_ok(goal=snapshot["goal"], snapshot=snapshot)
    except StaleGoalError as exc:
        return _json_error(str(exc), error_type="stale_goal")
    except ValueError as exc:
        return _json_error(str(exc), error_type="validation")


# ---------------------------------------------------------------------------
# Backtest tool
# ---------------------------------------------------------------------------


@mcp.tool
def backtest(run_dir: str) -> str:
    """Run a vectorized backtest using config.json and code/signal_engine.py.

    The run_dir must contain:
    - config.json: backtest configuration (source, codes, dates, etc.)
    - code/signal_engine.py: strategy signal generation code

    Supported data sources (set in config.json "source" field):
    - "yfinance": HK/US equities (free, no API key needed)
    - "okx": cryptocurrency (free, no API key needed)
    - "tushare": China A-shares (requires TUSHARE_TOKEN env var)
    - "akshare": A-shares, US, HK, futures, forex (free, no API key)
    - "ccxt": crypto from 100+ exchanges (free, no API key)
    - "auto": auto-detect based on symbol format (with fallback)

    Returns metrics (Sharpe, return, drawdown, etc.) and artifact paths.

    Args:
        run_dir: Path to the run directory containing config.json and code/.
    """
    from src.tools.backtest_tool import run_backtest

    return run_backtest(run_dir)


# ---------------------------------------------------------------------------
# Factor analysis tool
# ---------------------------------------------------------------------------


@mcp.tool
def factor_analysis(
    factor_csv: str,
    return_csv: str,
    output_dir: str,
    n_groups: int = 5,
) -> str:
    """Compute factor IC/IR analysis and layered backtest from prepared CSVs.

    Analyzes factor predictive power using Spearman rank IC, IR (IC/std),
    and quantile group return spreads.

    Args:
        factor_csv: Path to factor values CSV (index=date, columns=codes).
        return_csv: Path to returns CSV (same structure as factor_csv).
        output_dir: Directory for output files (ic_series.csv, ic_summary.json, group_equity.csv).
        n_groups: Number of quantile groups (default 5).
    """
    registry = _get_registry()
    return registry.execute(
        "factor_analysis",
        {
            "factor_csv": factor_csv,
            "return_csv": return_csv,
            "output_dir": output_dir,
            "n_groups": n_groups,
        },
    )


@mcp.tool
def alpha_zoo(
    action: str,
    alpha_id: str | None = None,
    zoo: str | None = None,
    theme: str | None = None,
    universe: str | None = None,
    limit: int = 50,
) -> str:
    """Browse the bundled Alpha Zoo registry.

    Args:
        action: ``list_alphas``, ``get_alpha``, or ``health``.
        alpha_id: Alpha id required by ``get_alpha``.
        zoo: Optional zoo filter for ``list_alphas``.
        theme: Optional theme filter for ``list_alphas``.
        universe: Optional universe filter for ``list_alphas``.
        limit: Maximum number of alphas returned by ``list_alphas``.
    """
    registry = _get_registry()
    params: dict[str, Any] = {"action": action, "limit": limit}
    if alpha_id is not None:
        params["alpha_id"] = alpha_id
    if zoo is not None:
        params["zoo"] = zoo
    if theme is not None:
        params["theme"] = theme
    if universe is not None:
        params["universe"] = universe
    return registry.execute("alpha_zoo", params)


@mcp.tool
def alpha_bench(
    universe: str,
    period: str,
    alpha_id: str | None = None,
    zoo: str | None = None,
    top: int = 20,
    output_dir: str | None = None,
) -> str:
    """Benchmark one Alpha Zoo alpha or a complete zoo on a universe.

    Args:
        universe: Universe to benchmark, such as ``sp500`` or ``csi300``.
        period: ``YYYY-YYYY`` or ``YYYY-MM-DD/YYYY-MM-DD``.
        alpha_id: Optional single alpha id; mutually exclusive with ``zoo``.
        zoo: Optional zoo id; mutually exclusive with ``alpha_id``.
        top: Number of top-ranked alphas to include in the report.
        output_dir: Optional directory for the generated HTML report.
    """
    if not alpha_id and not zoo:
        return json.dumps(
            {
                "status": "error",
                "error": "alpha_id or zoo is required for MCP alpha_bench",
            },
            ensure_ascii=False,
        )
    if alpha_id and zoo:
        return json.dumps(
            {
                "status": "error",
                "error": "alpha_id and zoo are mutually exclusive",
            },
            ensure_ascii=False,
        )

    try:
        from datetime import date

        from src.tools.alpha_bench_tool import _parse_period

        start_raw, end_raw = _parse_period(period)
        start_date = date.fromisoformat(start_raw)
        end_date = date.fromisoformat(end_raw)
        try:
            max_end = start_date.replace(year=start_date.year + 10)
        except ValueError:
            max_end = start_date.replace(year=start_date.year + 10, day=28)
        if end_date > max_end:
            return json.dumps(
                {
                    "status": "error",
                    "error": "MCP alpha_bench period must be no more than 10 years",
                },
                ensure_ascii=False,
            )
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    if top <= 0 or top > 100:
        return json.dumps(
            {
                "status": "error",
                "error": "MCP alpha_bench top must be between 1 and 100",
            },
            ensure_ascii=False,
        )

    params: dict[str, Any] = {
        "universe": universe,
        "period": period,
        "top": top,
    }
    if alpha_id is not None:
        params["alpha_id"] = alpha_id
    if zoo is not None:
        params["zoo"] = zoo

    if output_dir:
        from src.config.paths import get_runtime_root
        from src.tools.path_utils import allowed_write_roots, resolve_safe_path

        try:
            report_roots = [
                Path.home() / ".vibe-trading" / "reports",
                get_runtime_root() / "reports",
                *allowed_write_roots(),
            ]
            params["output_dir"] = str(
                resolve_safe_path(
                    output_dir,
                    None,
                    report_roots,
                    purpose="alpha bench report",
                )
            )
        except ValueError as exc:
            return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)

    registry = _get_registry()
    return registry.execute("alpha_bench", params)


# ---------------------------------------------------------------------------
# Options pricing tool
# ---------------------------------------------------------------------------


@mcp.tool
def analyze_options(
    spot: float,
    strike: float,
    expiry_days: int,
    risk_free_rate: float = 0.03,
    volatility: float = 0.25,
    option_type: str = "call",
) -> str:
    """Calculate Black-Scholes option price and Greeks (Delta, Gamma, Theta, Vega).

    Args:
        spot: Current underlying price.
        strike: Strike price.
        expiry_days: Days until expiration.
        risk_free_rate: Annual risk-free rate (default 0.03 = 3%).
        volatility: Annual volatility (default 0.25 = 25%).
        option_type: "call" or "put".
    """
    registry = _get_registry()
    return registry.execute(
        "options_pricing",
        {
            "spot": spot,
            "strike": strike,
            "expiry_days": expiry_days,
            "risk_free_rate": risk_free_rate,
            "volatility": volatility,
            "option_type": option_type,
        },
    )


@mcp.tool
def analyze_options_payoff(
    legs: _lenient_dict_list,
    entry_spot: float,
    expiry_days: float,
    risk_free_rate: float = 0.05,
    volatility: float = 0.3,
    multiplier: float = 1.0,
    commission_rate: float = 0.001,
    spot_min: float | None = None,
    spot_max: float | None = None,
    spot_points: int = 121,
    scenario_iv_values: _lenient_float_list_opt = None,
) -> str:
    """Analyze a multi-leg option strategy's payoff and spot/IV scenarios.

    The expiry summary is analytic rather than chart-grid dependent. Returns
    entry debit/credit and commission, breakevens, bounded or unbounded maximum
    profit/loss, an expiry curve, and a Black-Scholes spot/IV P&L matrix.
    Research only; this tool cannot place orders.

    Args:
        legs: Option leg objects with ``option_type`` (call/put), positive
            ``strike``, signed integer ``qty``, and optional per-share
            ``premium``. Positive quantity is long; negative is short.
        entry_spot: Positive underlying spot at entry.
        expiry_days: Non-negative calendar days to expiry.
        risk_free_rate: Annual continuously compounded risk-free rate.
        volatility: Annualized entry volatility, e.g. 0.3 for 30%.
        multiplier: Currency multiplier per option price unit.
        commission_rate: Entry commission fraction, aligned with the options
            backtest engine.
        spot_min: Optional non-negative chart/scenario lower bound.
        spot_max: Optional chart/scenario upper bound above ``spot_min``.
        spot_points: Display-grid size from 21 through 501.
        scenario_iv_values: Optional positive annualized IV scenarios. Omit for
            50%, 75%, 100%, 125%, and 150% of entry volatility.
    """
    params: dict[str, Any] = {
        "legs": legs,
        "entry_spot": entry_spot,
        "expiry_days": expiry_days,
        "risk_free_rate": risk_free_rate,
        "volatility": volatility,
        "multiplier": multiplier,
        "commission_rate": commission_rate,
        "spot_points": spot_points,
    }
    if spot_min is not None:
        params["spot_min"] = spot_min
    if spot_max is not None:
        params["spot_max"] = spot_max
    if scenario_iv_values is not None:
        params["scenario_iv_values"] = scenario_iv_values
    registry = _get_registry()
    return registry.execute("options_payoff", params)


# ---------------------------------------------------------------------------
# Pattern recognition tool
# ---------------------------------------------------------------------------


@mcp.tool
def pattern_recognition(run_dir: str) -> str:
    """Detect technical chart patterns (head-and-shoulders, double top/bottom,
    triangles, wedges, channels) in OHLCV data.

    Reads price data from run_dir/artifacts/ohlcv_*.csv files.
    Can be called before coding (to inform strategy) or after backtest (to analyse).

    Args:
        run_dir: Path to run directory containing artifacts/ohlcv_*.csv.
    """
    registry = _get_registry()
    return registry.execute("pattern", {"run_dir": run_dir})


# ---------------------------------------------------------------------------
# Web & document reading tools
# ---------------------------------------------------------------------------


@mcp.tool
def read_url(url: str) -> str:
    """Fetch a web page and convert it to clean Markdown text.

    Strips ads, navigation, and styling. Useful for reading API docs,
    financial articles, research reports, and GitHub READMEs.

    Args:
        url: Target URL to read.
    """
    from src.tools.web_reader_tool import read_url as _read_url

    return _read_url(url)


@mcp.tool
def read_document(file_path: str) -> str:
    """Extract text from a PDF document with OCR fallback for scanned pages.

    Supports text-based and image-based PDFs. Automatically uses OCR
    for pages with insufficient extractable text.

    Args:
        file_path: Absolute path to the PDF file.
    """
    registry = _get_registry()
    return registry.execute("read_document", {"file_path": file_path})


# ---------------------------------------------------------------------------
# Web search tool
# ---------------------------------------------------------------------------


@mcp.tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web via DuckDuckGo and return top results.

    Returns titles, URLs, and snippets. Use read_url() to fetch full content
    from any result URL. Free, no API key required.

    Args:
        query: Search query string.
        max_results: Maximum results to return (default 5, max 10).
    """
    registry = _get_registry()
    return registry.execute(
        "web_search",
        {
            "query": query,
            "max_results": min(max_results, 10),
        },
    )


# ---------------------------------------------------------------------------
# File I/O tools (sandboxed to workspace)
# ---------------------------------------------------------------------------


@mcp.tool
def write_file(path: str, content: str) -> str:
    """Write content to a file. Used to create config.json and signal_engine.py
    for backtesting workflows.

    Args:
        path: File path (relative to workspace or absolute).
        content: File content to write.
    """
    registry = _get_registry()
    return registry.execute("write_file", {"path": path, "content": content})


@mcp.tool
def read_file(path: str) -> str:
    """Read the contents of a file.

    Args:
        path: File path to read.
    """
    registry = _get_registry()
    return registry.execute("read_file", {"path": path})


# ---------------------------------------------------------------------------
# Strategy discovery tools
# ---------------------------------------------------------------------------


def _strategy_discovery_execute(tool_name: str, params: dict[str, Any]) -> str:
    """Delegate to a strategy-discovery agent tool with an honest error envelope.

    Registry or facade failures never propagate to the MCP client as a bare
    exception — silent, confident failure is exactly the mode this feature
    exists to prevent (see the phantom-tool rejection of PR #896). The
    envelope carries a generic message only; raw exception text can leak
    internal paths and stays in the server logs via ``logger.exception``.
    """
    try:
        registry = _get_registry()
        return registry.execute(tool_name, params)
    except Exception:  # noqa: BLE001 - honest error beats a raw traceback
        logger.exception("strategy discovery tool %s unavailable", tool_name)
        return json.dumps(
            {
                "status": "error",
                "error": "strategy discovery unavailable; see server logs",
            },
            ensure_ascii=False,
        )


@mcp.tool
def list_strategies(limit: int = 20, offset: int = 0, source: str | None = None) -> str:
    """List discoverable strategies across the Alpha Zoo and the SDM strategy store.

    Read-only catalogue of what strategies exist and what state they are in.
    Rows carry identification metadata plus evidence status; use
    get_strategy_evidence for the per-regime evidence behind any strategy.
    Nothing returned is a recommendation — rows below the evidence threshold
    are flagged insufficient/marginal rather than recommended.

    Args:
        limit: Maximum number of strategies to return (default 20).
        offset: Pagination offset for stable browsing (default 0).
        source: Optional source filter — "alpha_zoo" or "sdm". Omit to
            browse both sources.
    """
    return _strategy_discovery_execute(
        "list_strategies",
        {"limit": limit, "offset": offset, "source": source},
    )


@mcp.tool
def query_strategies(
    regime: str | None = None,
    min_sharpe: float | None = None,
    min_evidence_quality: str = "adequate",
    min_trades: int = 10,
    cost_feasible: bool = True,
    limit: int = 10,
    include_stale: bool = False,
) -> str:
    """Query strategies whose computed per-regime evidence passes the filters.

    Evidence-gated discovery: strategies are ranked by per-regime evidence
    rows from reproducible backtests instead of boolean scenario tags.
    Strategies below the evidence thresholds (trade count, coverage) are
    flagged insufficient/marginal rather than recommended, and the
    sizing-corrected cost screen keeps only strategies that clear their
    breakeven.

    Args:
        regime: Optional market-regime filter — "bear_market",
            "bull_market", or "structural". Omit to query across all regimes.
        min_sharpe: Optional minimum Sharpe on the per-regime evidence rows.
        min_evidence_quality: Minimum evidence quality to keep — "adequate"
            (default), "marginal", "insufficient", or "any". "any" only
            removes the quality floor; rows must still pass the other
            filters (min_trades, cost_feasible, min_sharpe) to be kept.
        min_trades: Minimum executed-trade count for evidence to count
            (default 10; fewer trades reads as insufficient evidence).
        cost_feasible: Keep only strategies that pass the sizing-corrected
            cost-breakeven screen (default True).
        limit: Maximum number of strategies to return (default 10).
        include_stale: Also keep rows whose evidence window is stale (default
            False). Stale rows fail closed out of default recommendations;
            True inspects them with their stale-evidence: warnings, sorted
            after non-stale rows. Relaxes the staleness gate only.
    """
    return _strategy_discovery_execute(
        "query_strategies",
        {
            "regime": regime,
            "min_sharpe": min_sharpe,
            "min_evidence_quality": min_evidence_quality,
            "min_trades": min_trades,
            "cost_feasible": cost_feasible,
            "limit": limit,
            "include_stale": include_stale,
        },
    )


@mcp.tool
def get_strategy_evidence(strategy_id: str, regime: str | None = None) -> str:
    """Return the computed per-regime evidence rows for one strategy.

    Read-only evidence detail: shows what reproducible backtests support the
    strategy in each regime — trade count, coverage, Sharpe, and the
    sizing-corrected cost breakeven. Rows below the evidence thresholds are
    flagged insufficient/marginal rather than recommended; the facade refuses
    regime assessments without computed evidence, so absent regimes are an
    honest empty, not a guess.

    Args:
        strategy_id: Strategy identifier from list_strategies or
            query_strategies.
        regime: Optional regime filter — "bear_market", "bull_market", or
            "structural". Omit for every regime with evidence.
    """
    return _strategy_discovery_execute(
        "get_strategy_evidence",
        {"strategy_id": strategy_id, "regime": regime},
    )


@mcp.tool
def refresh_strategy_evidence(manifest_path: str | None = None, runs: list | None = None) -> str:
    """Rebuild the strategy-discovery evidence cache from backtest run artifacts.

    WRITE tool with disposable-cache-only scope: it replaces the facade-owned
    strategy-evidence cache (drop-and-rebuild by contract) from local run
    artifacts and NEVER touches the Alpha Zoo or SDM sources of truth. No
    network access, no credentials, no broker paths.

    Provide EXACTLY ONE of the two parameters:
    - manifest_path: path to a JSON manifest — an object with a "runs" array
      ({"runs": [{strategy_id, run_dir, position_size?}, ...]}) or a bare
      JSON array of the same entries.
    - runs: inline array of {strategy_id, run_dir, position_size?} objects.

    Supplying both or neither returns an error envelope. Runs that fail the
    ingestion gates (unhealthy artifacts, run_dir outside the allowed run
    roots) are skipped with machine-readable reasons while the rest still
    process.

    Args:
        manifest_path: Path to the JSON manifest file (see above).
        runs: Inline run specs (see above).
    """
    return _strategy_discovery_execute(
        "refresh_strategy_evidence",
        {"manifest_path": manifest_path, "runs": runs},
    )


# ---------------------------------------------------------------------------
# Trading connector tools
# ---------------------------------------------------------------------------


def _trading_common_args(
    *,
    connection: str | None = None,
    connection_id: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
) -> dict[str, Any]:
    """Build shared optional trading connector arguments."""
    payload: dict[str, Any] = {}
    if connection:
        payload["connection"] = connection
    if connection_id:
        payload["connection_id"] = connection_id
    if host:
        payload["host"] = host
    if port is not None:
        payload["port"] = port
    if client_id is not None:
        payload["client_id"] = client_id
    if account:
        payload["account"] = account
    return payload


@mcp.tool
def trading_connections() -> str:
    """List selectable trading connector profiles.

    The connector is the first-level choice. Paper/live is an attribute of each
    profile under that connector.
    """
    registry = _get_registry()
    return registry.execute("trading_connections", {})


@mcp.tool
def trading_select_connection(connection: str) -> str:
    """Select the default trading connector profile for later trading_* calls.

    Args:
        connection: Profile id, e.g. ``ibkr-paper-local`` or ``robinhood-live-mcp``.
    """
    registry = _get_registry()
    return registry.execute("trading_select_connection", {"connection": connection})


@mcp.tool
def trading_check(
    connection: str | None = None,
    connection_id: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
) -> str:
    """Check whether a trading connector profile is configured and reachable.

    This never places orders. For local profiles, it checks the user's local
    app/socket. For remote MCP profiles, it reports config and OAuth-token
    presence without returning secrets.

    Args:
        connection: Optional profile id. Defaults to the selected profile.
        connection_id: Optional local connection id whose OS-vault credentials are used.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
    """
    registry = _get_registry()
    return registry.execute(
        "trading_check",
        _trading_common_args(
            connection=connection,
            connection_id=connection_id,
            host=host,
            port=port,
            client_id=client_id,
            account=account,
        ),
    )


@mcp.tool
def trading_account(
    connection: str | None = None,
    connection_id: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
) -> str:
    """Read account data from the selected trading connector profile.

    Args:
        connection: Optional profile id. Defaults to the selected profile.
        connection_id: Optional local connection id whose OS-vault credentials are used.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
    """
    registry = _get_registry()
    return registry.execute(
        "trading_account",
        _trading_common_args(
            connection=connection,
            connection_id=connection_id,
            host=host,
            port=port,
            client_id=client_id,
            account=account,
        ),
    )


@mcp.tool
def trading_positions(
    connection: str | None = None,
    connection_id: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
) -> str:
    """Read positions from the selected trading connector profile.

    Args:
        connection: Optional profile id. Defaults to the selected profile.
        connection_id: Optional local connection id whose OS-vault credentials are used.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
    """
    registry = _get_registry()
    return registry.execute(
        "trading_positions",
        _trading_common_args(
            connection=connection,
            connection_id=connection_id,
            host=host,
            port=port,
            client_id=client_id,
            account=account,
        ),
    )


@mcp.tool
def trading_orders(
    connection: str | None = None,
    connection_id: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    include_executions: bool = False,
) -> str:
    """Read open orders from the selected trading connector profile.

    Read-only: this tool does not place, cancel, modify, or replace orders.

    Args:
        connection: Optional profile id. Defaults to the selected profile.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
        include_executions: Include recent executions when available.
    """
    params = _trading_common_args(
        connection=connection, connection_id=connection_id, host=host, port=port, client_id=client_id, account=account
    )
    params["include_executions"] = include_executions
    registry = _get_registry()
    return registry.execute("trading_orders", params)


@mcp.tool
def trading_quote(
    symbol: str,
    connection: str | None = None,
    connection_id: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
) -> str:
    """Read a quote snapshot from the selected trading connector profile.

    Args:
        symbol: Symbol such as AAPL.
        connection: Optional profile id. Defaults to the selected profile.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
        exchange: Exchange routing, default SMART.
        currency: Contract currency, default USD.
        sec_type: Security type, default STK.
    """
    params = _trading_common_args(
        connection=connection, connection_id=connection_id, host=host, port=port, client_id=client_id, account=account
    )
    params.update({"symbol": symbol, "exchange": exchange, "currency": currency, "sec_type": sec_type})
    registry = _get_registry()
    return registry.execute("trading_quote", params)


@mcp.tool
def trading_history(
    symbol: str,
    connection: str | None = None,
    connection_id: str | None = None,
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
    account: str | None = None,
    exchange: str = "SMART",
    currency: str = "USD",
    sec_type: str = "STK",
    duration: str = "30 D",
    bar_size: str = "1 day",
    what_to_show: str = "TRADES",
    use_rth: bool = True,
    period: str = "1d",
    limit: int = 90,
) -> str:
    """Read historical bars from the selected trading connector profile.

    Args:
        symbol: Symbol such as AAPL.
        connection: Optional profile id. Defaults to the selected profile.
        host: Optional local host override.
        port: Optional local socket port override.
        client_id: Optional local client id override.
        account: Optional account code filter.
        exchange: Exchange routing, default SMART.
        currency: Contract currency, default USD.
        sec_type: Security type, default STK.
        duration: IBKR duration string, default 30 D.
        bar_size: IBKR bar size, default 1 day.
        what_to_show: Data type, default TRADES.
        use_rth: Use regular trading hours.
        period: Bar interval for SDK connectors (broker_sdk): 1m/5m/1h/1d/1w.
        limit: Number of bars for SDK connectors.
    """
    params = _trading_common_args(
        connection=connection, connection_id=connection_id, host=host, port=port, client_id=client_id, account=account
    )
    params.update(
        {
            "symbol": symbol,
            "exchange": exchange,
            "currency": currency,
            "sec_type": sec_type,
            "duration": duration,
            "bar_size": bar_size,
            "what_to_show": what_to_show,
            "use_rth": use_rth,
            "period": period,
            "limit": limit,
        }
    )
    registry = _get_registry()
    return registry.execute("trading_history", params)


# ---------------------------------------------------------------------------
# Swarm team tool
# ---------------------------------------------------------------------------


@mcp.tool
def list_swarm_presets() -> str:
    """List available swarm multi-agent team presets.

    Each preset defines a team of specialized agents (e.g. investment committee,
    quant desk, risk committee) that collaborate on complex research tasks.
    Returns preset names, descriptions, agent counts, and required variables.
    """
    from src.swarm.presets import list_presets

    presets = list_presets()
    return json.dumps(presets, ensure_ascii=False, indent=2)


@mcp.tool
async def run_swarm(
    preset_name: str,
    variables: _lenient_dict_str_str,
    wait_seconds: int = 3600,
    start_only: bool = False,
    ctx: Context | None = None,
) -> str:
    """Run a swarm multi-agent team and stream progress back to the caller.

    Assembles a team of specialized agents that collaborate through a DAG workflow.
    For example, the 'investment_committee' preset runs bull analyst, bear analyst,
    risk officer, and portfolio manager in sequence.

    Use list_swarm_presets() to see available presets and their required variables.

    The tool keeps the MCP call open via ``Context.report_progress`` while the
    swarm runs, so the caller sees live "N/M tasks complete" updates instead
    of timing out silently. Only if ``wait_seconds`` is exhausted does the
    tool return early with the current ``run_id`` — call ``get_run_result``
    afterwards to fetch the final report.

    Args:
        preset_name: Swarm preset name (e.g. 'investment_committee', 'quant_strategy_desk').
        variables: Required variables for the preset (e.g. {"target": "AAPL.US", "market": "US"}).
        wait_seconds: Maximum seconds to keep the MCP call open. Default 3600
            (1 hour); the progress-notification keepalive means the transport
            stays connected for the full budget.
        start_only: If True, kick off the run and return immediately with
            ``run_id`` + current status. Ignores ``wait_seconds``.
    """
    import asyncio
    import time
    from src.config import load_swarm_agent_config
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore, swarm_runs_root

    swarm_dir = swarm_runs_root()
    store = SwarmStore(base_dir=swarm_dir)
    # Boot-time / operator-trusted: resolved from env var or on-disk config.
    # The MCP caller (this tool's invoker) cannot influence the path — the
    # ``variables`` arg below is template data, never config (R-06).
    agent_config = load_swarm_agent_config()
    runtime = SwarmRuntime(store=store, agent_config=agent_config)

    try:
        run = runtime.start_run(preset_name, variables, include_shell_tools=_include_shell_tools)
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": f"DAG validation failed: {exc}"}, ensure_ascii=False)

    if start_only or wait_seconds <= 0:
        return json.dumps(
            _build_run_payload(store, run.id, preset_name, timed_out=False),
            ensure_ascii=False,
            indent=2,
        )

    # Surface the run_id immediately in a fixed-format progress message so a
    # caller whose transport drops mid-run (or whose MCP client enforces a
    # hard tool-call timeout that ignores progress notifications) can still
    # recover the run via ``get_run_result(run_id)``. Parsers should match
    # ``swarm_started run_id=<id>`` literally; later frames are free-form.
    if ctx is not None:
        try:
            await ctx.report_progress(
                progress=0,
                total=1,
                message=f"swarm_started run_id={run.id} preset={preset_name}",
            )
        except Exception:
            pass

    terminal = {"completed", "failed", "cancelled"}
    started_at = time.monotonic()
    deadline = started_at + wait_seconds
    while True:
        payload = _build_run_payload(store, run.id, preset_name, timed_out=False)
        if payload["status"] == "error":
            return json.dumps(payload, ensure_ascii=False)
        if payload["status"] in terminal:
            return json.dumps(payload, ensure_ascii=False, indent=2)

        # Emit a progress frame every loop, NOT only on state change — MCP
        # clients use these as transport keepalive. A long task that doesn't
        # transition for 30 minutes still needs ticks or the client times out.
        # ``elapsed`` keeps the message content fresh so dedup-on-message
        # clients still see updates.
        if ctx is not None:
            tasks = payload.get("tasks") or []
            total = max(1, len(tasks))
            done = sum(1 for t in tasks if t.get("status") in terminal)
            elapsed = int(time.monotonic() - started_at)
            try:
                await ctx.report_progress(
                    progress=done,
                    total=total,
                    message=f"{done}/{total} tasks complete · {elapsed}s elapsed (run {run.id})",
                )
            except Exception:
                pass

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            payload = _build_run_payload(store, run.id, preset_name, timed_out=True)
            return json.dumps(payload, ensure_ascii=False, indent=2)
        await asyncio.sleep(min(5.0, remaining))


# ---------------------------------------------------------------------------
# Market data tool
# ---------------------------------------------------------------------------


def _detect_source(code: str) -> str:
    return detect_source(code)


def _get_loader(source: str):
    """Get loader class via registry with fallback support."""
    return get_loader(source)


def _cap_rows(records: list, max_rows: int) -> list | dict[str, object]:
    """Bound a per-symbol row list to keep the MCP payload within budget.

    max_rows==0 disables the cap (full list, unchanged shape). A negative
    max_rows is invalid and enforces the default cap (never unbounded).
    Otherwise an oversized symbol is *evenly strided* — every step-th bar,
    with the last bar pinned — so the returned series spans the full range
    (no head+tail gap, no synthetic ``_gap`` sentinel). Symbols within the
    cap are returned unchanged (plain list) — small queries are
    byte-identical.
    """
    return cap_rows(records, max_rows)


@mcp.tool
def get_market_data(
    codes: _lenient_str_list,
    start_date: str,
    end_date: str,
    source: str = "auto",
    interval: str = "1D",
    max_rows: int = DEFAULT_MAX_ROWS,
) -> str:
    """Fetch OHLCV market data for stocks, crypto, or mixed symbols.

    Supported sources:
    - "yfinance" / "yahoo": HK/US/Canada equities (free, e.g. AAPL.US,
      700.HK, TD.TO, PNG.V)
    - "okx": cryptocurrency (free, e.g. BTC-USDT, ETH-USDT)
    - "tushare": China A-shares (requires TUSHARE_TOKEN, e.g. 000001.SZ)
    - "baostock": China A-shares via TCP protocol, bypasses HTTP CDN blocks (e.g. 000001.SZ, 601595.SH)
    - "tencent": China A-shares via Tencent Finance API (e.g. 000001.SZ, 601595.SH)
    - "akshare": A-shares, US, HK, futures, forex (free, e.g. 000001.SZ, AAPL.US)
    - "ccxt": crypto from 100+ exchanges (free, e.g. BTC/USDT)
    - "mt5": forex/metals from a local MetaTrader 5 terminal (Windows; e.g. EUR/USD, XAUUSD.FX)
    - "auto": auto-detect based on symbol format (with fallback)

    Args:
        codes: List of symbols (e.g. ["AAPL.US", "TD.TO", "BTC-USDT", "000001.SZ"]).
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        source: Data source. Prefer ``auto``; ``yahoo``/``yfinance`` serve
            Canada, US, and HK equities.
        interval: Bar size (1m/5m/15m/30m/1H/4H/1D, default "1D").
        max_rows: Per-symbol row cap (default 250) so the response stays
            within the MCP token budget. A symbol exceeding it returns an
            even-stride downsample (every step-th bar, last bar pinned)
            plus truncation metadata. Set max_rows=0 for all rows
            (unbounded, legacy behavior).

    Volume units: the ``volume`` column unit is source- and market-dependent
    (A-share sources report board lots of 100 shares; HK/US sources report
    single shares). Each symbol's ``_provenance.volume_unit`` states the unit
    of the returned rows ("lots" / "shares"; null = source undeclared) — read
    it before interpreting or comparing volume values across symbols/sources.

    Price caliber: which source served a symbol decides what its prices mean
    (some adjust for splits and dividends, others serve raw quotes). Each
    symbol's ``_provenance.adjustment`` states the caliber ("raw" / "split" /
    "split_dividend" / "na" / "unknown") — read it before comparing price
    levels across symbols.
    """
    registry = _get_registry()
    return registry.execute(
        "get_market_data",
        {
            "codes": codes,
            "start_date": start_date,
            "end_date": end_date,
            "source": source,
            "interval": interval,
            "max_rows": max_rows,
            # Internal hook, not an agent-facing parameter: keeps the MCP
            # surface resolving loaders through mcp_server._get_loader (the
            # contract the regression tests and the server's own loader
            # diagnostics rely on) instead of the tool's default resolver.
            "loader_resolver": _get_loader,
        },
    )


# ---------------------------------------------------------------------------
# Read-only fundamentals, flow, news & discovery tools
#
# Each wrapper delegates to the auto-discovered local registry, exactly like
# factor_analysis / pattern_recognition above. The registry returns a clean
# JSON error envelope when a key-gated tool (get_macro_series needs
# FRED_API_KEY, iwencai_search needs VIBE_TRADING_IWENCAI_KEY, the qveris_*
# tools need QVeris paid routing: QVERIS_API_KEY + paid mode) is absent — see
# ``_execute_key_gated`` below, which honours that contract even though the
# tool is excluded from the registry by ``check_available()``. Every tool below
# is read-only or research-only data — no order/trading tool is ever surfaced
# via MCP (qveris_execute spends QVeris credits on data calls, never orders).
# ---------------------------------------------------------------------------


# Map of key-gated MCP tools to their concrete tool class. When the required
# API key is unset the class' ``check_available()`` returns False, so the tool
# is excluded from the auto-discovered registry and ``registry.execute`` would
# answer with a generic "Tool not found". That contradicts the documented
# contract above (a clean, env-var-named error). For these tools we therefore
# fall through to the tool's own ``execute()`` — whose missing-key envelope
# names the exact env var (``FRED_API_KEY`` / ``VIBE_TRADING_IWENCAI_KEY``),
# or the missing QVeris paid-routing setup (``QVERIS_API_KEY`` + paid mode).
def _key_gated_tool_classes() -> dict[str, Any]:
    """Return the {tool_name: tool_class} map for key-gated MCP tools.

    Imported lazily so a missing optional dependency in any mapped module
    degrades to the registry path rather than breaking module import.

    Returns:
        Mapping of MCP tool name to its ``BaseTool`` subclass.
    """
    from src.tools.fred_macro_tool import FredMacroTool
    from src.tools.iwencai_tool import IWenCaiSearchTool
    from src.tools.qveris_tool import (
        QVerisExecuteTool,
        QVerisInspectTool,
        QVerisSearchTool,
    )

    return {
        "get_macro_series": FredMacroTool,
        "iwencai_search": IWenCaiSearchTool,
        "qveris_search": QVerisSearchTool,
        "qveris_inspect": QVerisInspectTool,
        "qveris_execute": QVerisExecuteTool,
    }


def _execute_key_gated(name: str, params: dict[str, Any]) -> str:
    """Run a key-gated MCP tool, preserving its env-var-named error.

    Prefers the auto-discovered registry (present when the API key is set and,
    for the qveris_* tools, paid mode is on). When the gating is absent the
    tool is excluded from the registry, so we invoke its concrete ``execute()``
    directly to surface the documented missing-key error that names the exact
    env var — or the missing QVeris paid routing — never a generic "Tool not
    found".

    Args:
        name: MCP tool name (``get_macro_series``, ``iwencai_search``,
            ``qveris_search``, ``qveris_inspect`` or ``qveris_execute``).
        params: Keyword arguments forwarded to the tool.

    Returns:
        The tool's JSON envelope as a string.
    """
    registry = _get_registry()
    if registry.get(name) is not None:
        return registry.execute(name, params)
    tool_cls = _key_gated_tool_classes().get(name)
    if tool_cls is None:
        return registry.execute(name, params)
    return tool_cls().execute(**params)


@mcp.tool
def get_fund_flow(codes: _lenient_str_list, period: str = "daily", days: int = 30) -> str:
    """Fetch order-bucket net capital inflow (main/super-large/large/medium/small).

    Markets: A-share (.SH/.SZ/.BJ), Hong Kong (.HK) and US (.US). Use this to
    gauge whether large/main-force money is flowing in or out, as daily history
    or the current session's per-minute line. One unresolvable symbol is
    reported per-symbol and does not abort the batch.

    Args:
        codes: Symbols with market suffix, e.g. ["600519.SH", "00700.HK"].
        period: "daily" (daily net-inflow history) or "min" (per-minute line).
        days: For period="daily", number of most-recent daily bars to keep.
    """
    registry = _get_registry()
    return registry.execute("get_fund_flow", {"codes": codes, "period": period, "days": days})


@mcp.tool
def get_dragon_tiger(date: str, code: str | None = None) -> str:
    """Fetch the A-share dragon-tiger board (龙虎榜) for a trade date (Eastmoney).

    Markets: China A-share (SH/SZ). Omit ``code`` for the full-market list of
    every security on the board that day; supply ``code`` to also get that
    security's ranked top buy/sell brokerage seats. Read-only, no auth.

    Args:
        date: Trade date in YYYY-MM-DD format (e.g. 2024-01-02).
        code: Optional A-share symbol or bare code (e.g. "600519.SH" or "600519").
    """
    params: dict[str, Any] = {"date": date}
    if code:
        params["code"] = code
    registry = _get_registry()
    return registry.execute("get_dragon_tiger", params)


@mcp.tool
def get_northbound_flow(lookback_days: int = 30) -> str:
    """Fetch Northbound (Stock-Connect) net capital flow for China A-shares.

    Returns the latest realtime net inflow plus recent daily history, split into
    Shanghai-Connect (沪股通) and Shenzhen-Connect (深股通) channels (units: 10k
    CNY) from Eastmoney. Read-only; China A-share market only.

    Args:
        lookback_days: Trailing trading days of daily net-inflow history to return.
    """
    registry = _get_registry()
    return registry.execute("get_northbound_flow", {"lookback_days": lookback_days})


@mcp.tool
def get_margin_trading(code: str, days: int = 30) -> str:
    """Fetch an A-share stock's daily margin-trading (融资融券) balances (Eastmoney).

    Returns outstanding financing balance, financing buy amount,
    securities-lending balance, and combined RZRQ balance, one row per trading
    day (most recent first). Read-only, no credentials, A-shares only (SH/SZ).

    Args:
        code: A-share code: bare ("600519"), suffixed ("600519.SH"), or
            exchange-prefixed ("sh600519").
        days: Number of most-recent trading days to return.
    """
    registry = _get_registry()
    return registry.execute("get_margin_trading", {"code": code, "days": days})


@mcp.tool
def get_block_trades(code: str, days: int = 30) -> str:
    """Fetch recent A-share block trades (大宗交易) for one symbol (Eastmoney).

    Returns per-deal price, volume, amount, the premium/discount versus that
    day's close, and the buyer/seller broker seats (营业部). Markets: China
    A-share only (.SH/.SZ/.BJ). Read-only.

    Args:
        code: A-share symbol with exchange suffix, e.g. "600519.SH", "830799.BJ".
        days: Lookback window in calendar days ending today.
    """
    registry = _get_registry()
    return registry.execute("get_block_trades", {"code": code, "days": days})


@mcp.tool
def get_shareholder_count(code: str, max_periods: int = 24) -> str:
    """Fetch mainland A-share quarterly shareholder count (股东户数) (Eastmoney).

    Returns holder count per report period, quarter-over-quarter change
    (absolute and percent), and average holding (shares and market value) per
    account. Markets: China A-shares only (.SH/.SZ/.BJ).

    Args:
        code: A-share symbol in <code>.<exchange> form (SH/SZ/BJ).
        max_periods: Maximum number of most-recent report periods to return.
    """
    registry = _get_registry()
    return registry.execute("get_shareholder_count", {"code": code, "max_periods": max_periods})


@mcp.tool
def get_lockup_expiry(code: str | None = None, horizon_days: int = 90) -> str:
    """Fetch Chinese A-share lockup-expiry (restricted-share unlock, 限售解禁) data.

    Pass an A-share ``code`` to get that stock's full historical unlock
    schedule, or omit it for a market-wide calendar of upcoming unlocks within
    the next ``horizon_days`` (Eastmoney). A large near-term unlock adds
    tradable supply and often pressures the stock. Read-only.

    Args:
        code: A-share symbol (e.g. "600519", "600519.SH"). Omit for a
            market-wide upcoming-unlock calendar.
        horizon_days: Upcoming-unlock window in days for the market-wide
            calendar; ignored when ``code`` is given (full history is returned).
    """
    params: dict[str, Any] = {"horizon_days": horizon_days}
    if code:
        params["code"] = code
    registry = _get_registry()
    return registry.execute("get_lockup_expiry", params)


@mcp.tool
def get_sector_info(code: str | None = None, mode: str = "membership", limit: int = 30) -> str:
    """Look up Chinese A-share sector / concept board info (Eastmoney, no auth).

    Two modes: (1) membership — given a stock ``code``, list the industry and
    concept boards it belongs to; (2) ranking — set ``mode="ranking"`` to rank
    industry boards by today's percent change (with up/down constituent counts
    and the leading stock). Market: A-share stocks.

    Args:
        code: A-share stock symbol with market suffix. Required when
            mode="membership"; ignored when mode="ranking".
        mode: "membership" (default) or "ranking".
        limit: For mode="ranking", number of top boards to return.
    """
    params: dict[str, Any] = {"mode": mode, "limit": limit}
    if code:
        params["code"] = code
    registry = _get_registry()
    return registry.execute("get_sector_info", params)


@mcp.tool
def get_research_reports(
    code: str,
    limit: int = 20,
    beginTime: str | None = None,
    endTime: str | None = None,
) -> str:
    """Fetch mainland A-share sell-side research coverage and consensus forecasts.

    Returns recent broker research reports (title, brokerage, analyst, publish
    date, rating) with each broker's per-year EPS and PE forecasts from
    Eastmoney, plus the market consensus (mean) EPS forecast per forward fiscal
    year from THS (同花顺). Markets: China A-shares only (.SH/.SZ/.BJ).

    Args:
        code: A-share symbol in <code>.<exchange> form (SH/SZ/BJ).
        limit: Maximum number of most-recent research reports to return.
        beginTime: Earliest report publish date (inclusive), 'YYYYMMDD'.
            Optional; defaults to the start of a trailing two-year window.
        endTime: Latest report publish date (inclusive), 'YYYYMMDD'.
            Optional; defaults to today.
    """
    params: dict[str, Any] = {"code": code, "limit": limit}
    if beginTime:
        params["beginTime"] = beginTime
    if endTime:
        params["endTime"] = endTime
    registry = _get_registry()
    return registry.execute("get_research_reports", params)


@mcp.tool
def get_stock_news(code: str | None = None, scope: str = "stock", limit: int = 20) -> str:
    """Fetch recent financial news headlines, read-only and no auth.

    Markets: China A-share (SH/SZ/BJ) headlines from Eastmoney; US (.US) and
    Hong Kong (.HK) related-instrument matches from Yahoo Finance. Use scope
    "stock" with a ``code`` for one security's headlines, or scope "global"
    (no code) for broad China-market finance news.

    Args:
        code: Symbol whose news to fetch (e.g. "600519.SH", "AAPL.US").
            Required when scope="stock"; ignored when scope="global".
        scope: "stock" (default) or "global".
        limit: Maximum number of headlines to return.
    """
    params: dict[str, Any] = {"scope": scope, "limit": limit}
    if code:
        params["code"] = code
    registry = _get_registry()
    return registry.execute("get_stock_news", params)


@mcp.tool
def get_sec_filings(
    ticker: str,
    form: str | None = None,
    metric: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """Fetch U.S. SEC EDGAR filings or reported XBRL financials for a company.

    Returns a list of recent filings (10-K / 10-Q / 8-K, etc.) with accession
    number, filing and report dates, and the primary-document URL; or, when
    ``metric`` is given, the reported XBRL us-gaap financial series for that
    concept (e.g. Revenues, NetIncomeLoss, Assets). Markets: United States only.

    Args:
        ticker: U.S. equity ticker, case-insensitive (e.g. "AAPL").
        form: Optional SEC form type filter (e.g. "10-K", "10-Q", "8-K").
        metric: Optional XBRL us-gaap concept name (e.g. "Revenues").
        limit: Maximum number of most-recent filings and metric points to return.
        offset: Index of the first filing to return, newest first; defaults
            to 0. Results are returned whole and only as many as fit one
            response — read paging.total and paging.next_offset and call
            again with that offset to continue.
    """
    params: dict[str, Any] = {"ticker": ticker, "limit": limit, "offset": offset}
    if form:
        params["form"] = form
    if metric:
        params["metric"] = metric
    registry = _get_registry()
    return registry.execute("get_sec_filings", params)


@mcp.tool
def get_financial_statements(code: str, statement: str = "indicators", period: str = "annual", offset: int = 0) -> str:
    """Fetch a stock's financial statements or key per-period indicators.

    Markets: A-share (.SH/.SZ/.BJ, via Sina), US (.US) and Hong Kong (.HK, via
    Eastmoney). Reports come back newest-first as flat per-period rows. Use this
    to read fundamentals before building a valuation or screen.

    Args:
        code: Single symbol with a market suffix (e.g. "600519.SH", "AAPL.US").
        statement: "balance", "income", "cashflow", or "indicators".
        period: "annual" or "quarter".
        offset: Index of the first period to return, newest first; defaults
            to 0. Periods are returned whole and only as many as fit one
            response — read paging.total and paging.next_offset and call
            again with that offset to continue.
    """
    registry = _get_registry()
    return registry.execute(
        "get_financial_statements",
        {"code": code, "statement": statement, "period": period, "offset": offset},
    )


@mcp.tool
def get_options_chain(ticker: str, expiration: int | None = None) -> str:
    """Fetch the US-listed options chain (calls and puts) for one expiration.

    Returns per-contract strike, bid/ask, last price, volume, open interest,
    implied volatility, and in-the-money flag, plus the list of available
    expirations (epoch seconds) via Yahoo Finance. Read-only US options data.

    Args:
        ticker: US underlying symbol (e.g. "AAPL" or "AAPL.US").
        expiration: Optional expiration as Unix epoch seconds (one of the
            returned expirations). Omit for the nearest expiration.
    """
    params: dict[str, Any] = {"ticker": ticker}
    if expiration is not None:
        params["expiration"] = expiration
    registry = _get_registry()
    return registry.execute("get_options_chain", params)


@mcp.tool
def get_stock_profile(ticker: str, sections: _lenient_str_list_opt = None) -> str:
    """Fetch a read-only company profile for a US, HK, or UK (LSE .L) listing (Yahoo Finance).

    Returns valuation key statistics, analyst price targets and
    earnings/revenue estimates, institutional and insider ownership, and the
    analyst recommendation trend. Use this for fundamentals and consensus
    context, not for OHLCV price bars (use get_market_data).

    Args:
        ticker: US (bare or .US suffix), HK (zero-padded .HK code), or
            UK (LSE .L, e.g. VOD.L) symbol.
        sections: Profile sections to return, any of: key_stats, financials,
            earnings_trend, institution_ownership, insider_holders,
            recommendation_trend. Defaults to all sections.
    """
    params: dict[str, Any] = {"ticker": ticker}
    clean_sections = _clean_list(sections)
    if clean_sections:
        params["sections"] = clean_sections
    registry = _get_registry()
    return registry.execute("get_stock_profile", params)


@mcp.tool
def screen_market(market: str, sort_by: str = "change_pct", top_n: int = 30) -> str:
    """Screen a market's listed instruments and rank the top names by a metric.

    Use this to find today's biggest movers or most-actively-traded names
    without fetching every symbol. Markets: A-share ("a"), US ("us"), Hong
    Kong ("hk").

    Args:
        market: Market universe: "a", "us", or "hk".
        sort_by: Ranking metric (descending): "change_pct", "volume",
            "amount", or "turnover".
        top_n: Number of top-ranked instruments to return.
    """
    registry = _get_registry()
    return registry.execute("screen_market", {"market": market, "sort_by": sort_by, "top_n": top_n})


@mcp.tool
def search_symbol(query: str, limit: int = 10) -> str:
    """Resolve a company name or ticker fragment to candidate trading symbols.

    Returns candidates with their market in the project's symbol convention
    (A-shares 600519.SH, Hong Kong 00700.HK, U.S. AAPL.US, Canada TD.TO/PNG.V,
    plus crypto/index/FX from Yahoo). Searches Eastmoney and Yahoo and, for U.S.
    equities, attaches the SEC CIK. Use this to turn an ambiguous name into a
    concrete symbol before calling get_market_data or get_sec_filings.

    Args:
        query: Free-text company name or ticker fragment (Chinese or English).
        limit: Maximum number of merged candidates to return.
    """
    registry = _get_registry()
    return registry.execute("search_symbol", {"query": query, "limit": limit})


@mcp.tool
def get_macro_series(
    series_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 2000,
) -> str:
    """Fetch a FRED macroeconomic time series from the St. Louis Fed.

    Returns dated observations of indicators such as CPI (CPIAUCSL),
    unemployment (UNRATE), real GDP (GDPC1), the federal funds rate (FEDFUNDS),
    or the 10-year Treasury yield (DGS10). Markets: US / global macro data.
    Requires a free FRED API key (FRED_API_KEY); without it the tool returns a
    not-available error.

    Args:
        series_id: FRED series identifier (e.g. "CPIAUCSL", "UNRATE").
        start_date: Inclusive window start, YYYY-MM-DD. Omit for full history.
        end_date: Inclusive window end, YYYY-MM-DD. Omit for the latest date.
        limit: Maximum number of most-recent observations to return.
    """
    params: dict[str, Any] = {"series_id": series_id, "limit": limit}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _execute_key_gated("get_macro_series", params)


@mcp.tool
def iwencai_search(query: str, limit: int = 20) -> str:
    """Run a natural-language A-share research query against iWenCai (问财).

    iWenCai is a Chinese-market semantic stock screener. Phrase the question in
    plain language (Chinese works best) and get back the matching China A-share
    (SH/SZ) securities with the metric columns iWenCai parsed from the question.
    Read-only; requires the VIBE_TRADING_IWENCAI_KEY access key (without it the
    tool returns a not-available error).

    Args:
        query: Natural-language research question (Chinese phrasing yields the
            best parse, e.g. "市盈率低于15的银行股").
        limit: Maximum securities to return.
    """
    return _execute_key_gated("iwencai_search", {"query": query, "limit": limit})


@mcp.tool
def qveris_search(query: str, limit: int = 20, session_id: str | None = None) -> str:
    """Search the QVeris premium data/tool marketplace for capabilities.

    Discovery is free. Returns candidate tools with ``tool_id``, ``provider``,
    ``parameters``, ``expected_cost`` and ``stats.success_rate``; choose by
    expected cost and success rate before any paid execute. Requires QVeris
    paid routing (``QVERIS_API_KEY`` and paid mode via ``vibe-trading data
    mode paid`` or Settings -> QVeris) — without it the tool returns a
    not-available error.

    Args:
        query: Capability search query, e.g. "US listed options chain implied
            volatility Greeks AAPL".
        limit: Maximum candidates to return.
        session_id: Optional QVeris session id linking follow-up calls.
    """
    params: dict[str, Any] = {"query": query, "limit": limit}
    if session_id:
        params["session_id"] = session_id
    return _execute_key_gated("qveris_search", params)


@mcp.tool
def qveris_inspect(
    tool_ids: list[str],
    search_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Inspect full parameter schemas of QVeris tools before executing them.

    Fetches the complete descriptors for one or more ``tool_ids`` returned by
    ``qveris_search``. Inspection is free: verify required parameters, enum
    values, date formats and output shape before a paid call. Requires QVeris
    paid routing (``QVERIS_API_KEY`` and paid mode via ``vibe-trading data
    mode paid`` or Settings -> QVeris) — without it the tool returns a
    not-available error.

    Args:
        tool_ids: QVeris tool ids taken from ``qveris_search`` results.
        search_id: Optional search id from the ``qveris_search`` response.
        session_id: Optional QVeris session id linking follow-up calls.
    """
    params: dict[str, Any] = {"tool_ids": tool_ids}
    if search_id:
        params["search_id"] = search_id
    if session_id:
        params["session_id"] = session_id
    return _execute_key_gated("qveris_inspect", params)


@mcp.tool
def qveris_execute(
    tool_id: str,
    parameters: dict[str, Any],
    search_id: str | None = None,
    session_id: str | None = None,
    model: str | None = None,
    max_response_size: int = 20480,
) -> str:
    """Execute one QVeris capability after discovery and inspection.

    Runs the ``tool_id`` selected via ``qveris_search`` / ``qveris_inspect``.
    MAY BE BILLABLE — provider calls are charged by QVeris when billable
    (failed or empty calls are not charged), and the tool enforces the local
    per-session credit budget before sending the request; the result preserves
    ``cost`` and ``remaining_credits``. Research/data execution only — it
    never places orders. Requires QVeris paid routing (``QVERIS_API_KEY`` and
    paid mode via ``vibe-trading data mode paid`` or Settings -> QVeris) —
    without it the tool returns a not-available error.

    Args:
        tool_id: QVeris tool id to execute.
        parameters: Provider call parameters matching the inspected schema.
        search_id: Optional search id from the ``qveris_search`` response.
        session_id: Optional QVeris session id used for budget accounting.
        model: Optional provider model override.
        max_response_size: Provider response truncation budget (default
            20480; -1 disables truncation).
    """
    params: dict[str, Any] = {
        "tool_id": tool_id,
        "parameters": parameters,
        "max_response_size": max_response_size,
    }
    if search_id:
        params["search_id"] = search_id
    if session_id:
        params["session_id"] = session_id
    if model:
        params["model"] = model
    return _execute_key_gated("qveris_execute", params)


# ---------------------------------------------------------------------------
# Institutional-research & alternative-data tools (schema mirrored from source)
#
# get_institutional_holdings / etf_holdings / prediction_market /
# research_papers carry large multi-mode JSON Schemas (mode enums, per-mode
# required arguments, paging bounds) that live on the tool class itself.
# Re-declaring them here as Python signatures — the pattern used by the
# single-purpose tools above — would create a SECOND definition that silently
# drifts from the agent-side one every time a mode or bound changes. So these
# four are registered with the tool class' own ``parameters`` and
# ``description``: an MCP client sees byte-identical argument documentation to
# what the agent sees, from one source.
#
# Read-only is structural here, not a comment: _register_mirrored_tool refuses
# any class whose ``is_readonly`` is not True, so an order-placing tool cannot
# be surfaced through this path even if someone adds it to the list below.
# ``trading_place_order`` / ``trading_cancel_order`` are never MCP-exposed.
#
# Tradeoff accepted: fastmcp validates call arguments against the wrapper's
# Python signature, not against ``parameters``, so a mirrored tool receives its
# arguments unvalidated by the server (we only drop nulls and undeclared keys).
# That is the same contract the tool already has with the agent — every one of
# these tools parses/clamps its own ``**kwargs`` — and ToolRegistry.execute
# turns any failure into a JSON error envelope rather than a transport error.
# KNOWN DIVERGENCE from the hand-written wrappers above, which declare
# ``additionalProperties: false`` and therefore REJECT an undeclared argument:
# here an undeclared argument is dropped instead. Every identity argument is
# still enforced by the tool itself (a missing symbol/manager/query fails
# closed), so the residual risk is a mistyped OPTIONAL argument silently
# falling back to its default. Closing this belongs on the tool classes —
# adding ``additionalProperties: false`` to their ``parameters`` fixes the
# agent side and this surface at once, since the schema here is theirs.
# ---------------------------------------------------------------------------


_MIRRORED_TOOL_SOURCES = (
    ("src.tools.institutional_holdings_tool", "InstitutionalHoldingsTool"),
    ("src.tools.etf_holdings_tool", "EtfHoldingsTool"),
    ("src.tools.prediction_market_tool", "PredictionMarketTool"),
    ("src.tools.research_papers_tool", "ResearchPapersTool"),
    # Read-only compute and market-data tools that had reached the agent but
    # not MCP. Mirroring is the right path for all of them: each already owns a
    # multi-mode ``parameters`` schema, so re-declaring Python signatures here
    # would create the second definition this block exists to avoid.
    ("src.tools.quantlib_tool", "QuantlibCallTool"),
    ("src.tools.cashflow_analytics_tool", "CashFlowPerformanceTool"),
    ("src.tools.orderbook_depth_tool", "OrderBookDepthTool"),
    ("src.tools.sentiment_tool", "SentimentTool"),
    ("src.tools.technical_indicator_tool", "TechnicalIndicatorTool"),
    ("src.tools.get_fundamentals_tool", "GetFundamentalsTool"),
)


def _mirrored_tool_classes() -> list[Any]:
    """Return the read-only tool classes exposed with their own JSON Schema.

    Each module is imported lazily AND independently: a missing optional
    dependency or a broken module costs exactly the one tool it defines, and
    the other three still reach the MCP surface. Importing them together in a
    single ``from ... import`` block would make one bad module drop all four.

    Returns:
        The ``BaseTool`` subclasses to mirror onto the MCP surface, in
        declaration order, minus any whose module failed to import.
    """
    classes: list[Any] = []
    for module_path, class_name in _MIRRORED_TOOL_SOURCES:
        try:
            classes.append(getattr(import_module(module_path), class_name))
        except Exception:  # noqa: BLE001 - one unavailable module, not four
            logger.exception("Tool module %s is unavailable; its MCP tool will be absent", module_path)
    return classes


def _string_result_output_schema() -> dict[str, Any] | None:
    """Return the output schema fastmcp derives for a ``-> str`` tool.

    Derived from a probe function instead of hardcoded so the mirrored tools
    keep announcing the same result envelope as the ``@mcp.tool`` wrappers
    above across fastmcp versions (currently a wrapped ``{"result": str}``).

    Returns:
        The derived output schema, or None if this fastmcp version declares none.
    """
    from fastmcp.tools import FunctionTool

    def _probe() -> str:  # pragma: no cover - shape probe only
        return ""

    return FunctionTool.from_function(_probe, name="probe").output_schema


def _mirrored_call_params(schema: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Reduce raw MCP call arguments to the ones the tool actually declares.

    Drops ``None`` values (no mirrored schema declares a nullable property, so
    an explicit null means "not supplied") and keys the schema does not declare,
    matching the ``additionalProperties: false`` behaviour of the hand-written
    wrappers.

    Args:
        schema: The tool's own ``parameters`` JSON Schema.
        kwargs: Arguments as received from the MCP client.

    Returns:
        The filtered keyword arguments to forward to the registry.
    """
    declared = schema.get("properties") or {}
    params: dict[str, Any] = {}
    for key, value in kwargs.items():
        if value is None or key not in declared:
            continue
        # A mirrored tool has no Python signature for fastmcp to validate
        # against, so the JSON-string arguments the BeforeValidator decodes on
        # the annotated wrappers arrive here untouched and would reach the tool
        # as a str where it expects a list. Decode off the DECLARED type, which
        # covers every mirrored tool and every future one, rather than the
        # three array parameters that happen to exist today
        # (prediction_market.ids, research_papers.categories/paper_ids).
        if _declares_json_container(declared[key]):
            value = _coerce_json_string(value)
        params[key] = value
    return params


def _declares_json_container(prop_schema: Any) -> bool:
    """Return whether a property's schema admits a JSON array or object.

    Args:
        prop_schema: One entry from a JSON Schema ``properties`` map.

    Returns:
        True when the declared type is ``array``/``object``, including when it
        appears inside an ``anyOf`` union.
    """
    if not isinstance(prop_schema, dict):
        return False
    types = {prop_schema.get("type")}
    for variant in prop_schema.get("anyOf") or ():
        if isinstance(variant, dict):
            types.add(variant.get("type"))
    return bool(types & {"array", "object"})


def _register_mirrored_tool(tool_cls: Any) -> bool:
    """Register one read-only tool on the MCP surface using its own schema.

    Args:
        tool_cls: A ``BaseTool`` subclass with ``name`` / ``description`` /
            ``parameters``.

    Returns:
        True when the tool was registered; False when it was refused (not
        read-only) or this fastmcp version rejected the registration.
    """
    name = getattr(tool_cls, "name", "")
    if getattr(tool_cls, "is_readonly", False) is not True:
        logger.error(
            "Refusing to expose non-read-only tool %r via MCP; only read-only tools are ever surfaced.",
            name or tool_cls,
        )
        return False

    try:
        from fastmcp.tools import FunctionTool

        schema = deepcopy(getattr(tool_cls, "parameters", None)) or {
            "type": "object",
            "properties": {},
            "required": [],
        }

        def _call(**kwargs: Any) -> str:
            """Forward an MCP call to the auto-discovered local tool registry."""
            return _get_registry().execute(name, _mirrored_call_params(schema, kwargs))

        mcp.add_tool(
            FunctionTool(
                fn=_call,
                name=name,
                description=tool_cls.description,
                parameters=schema,
                output_schema=_string_result_output_schema(),
                return_type=str,
            )
        )
    except Exception:  # noqa: BLE001 - never let one tool break server startup
        logger.exception("Failed to expose tool %r via MCP", name)
        return False
    return True


for _mirrored_cls in _mirrored_tool_classes():
    _register_mirrored_tool(_mirrored_cls)


# ---------------------------------------------------------------------------
# Swarm status & history tools
# ---------------------------------------------------------------------------


def _get_swarm_store():
    from src.swarm.store import SwarmStore, swarm_runs_root

    swarm_dir = swarm_runs_root()
    swarm_dir.mkdir(parents=True, exist_ok=True)
    return SwarmStore(base_dir=swarm_dir)


def _run_to_dict(run, *, timed_out: bool = False, is_stale: bool = False) -> dict:
    """Public projection of a (live-hydrated) :class:`SwarmRun`.

    ``timed_out`` flips on only for the ``run_swarm`` wait-budget path. It does
    not change the run's actual status — callers can still see ``running`` and
    fetch the final report later via :func:`get_run_result`.

    ``is_stale`` is a read-only signal: ``True`` means the run is still
    ``running`` but its events.jsonl has been silent past the per-run
    threshold. No disk state is changed by setting this — the explicit
    :func:`reap_stale_runs` tool is what finalizes a stale run.
    """
    from src.swarm.models import (
        public_model_metadata,
        public_provider_metadata,
        public_reasoning_effort,
    )
    from src.swarm.serialization import run_level_error, serialize_task

    return {
        "run_id": run.id,
        "status": run.status.value,
        "preset": run.preset_name,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "error": run_level_error(run),
        "tasks": [serialize_task(t) for t in run.tasks],
        "final_report": run.final_report,
        "total_input_tokens": run.total_input_tokens,
        "total_output_tokens": run.total_output_tokens,
        "provider": public_provider_metadata(run.provider),
        "model": public_model_metadata(run.model),
        "reasoning_effort": public_reasoning_effort(run.reasoning_effort),
        "use_responses_api": run.use_responses_api,
        "timed_out": timed_out,
        "is_stale": is_stale,
    }


def _build_run_payload(store, run_id: str, preset_name: str | None, *, timed_out: bool) -> dict:
    """Reconcile + project a run for the MCP response.

    Used by ``run_swarm`` (polling + start_only). Returns a normal payload on
    success and a ``{"status": "error", ...}`` envelope when the run record
    disappears (mid-run directory wipe / sandbox eviction).
    """
    run = store.load_run(run_id)
    if run is None:
        return {"status": "error", "error": "Run record lost", "run_id": run_id}
    reconciled = store.reconcile_run(run, write=True)
    payload = _run_to_dict(
        reconciled,
        timed_out=timed_out,
        is_stale=store.is_run_stale(reconciled),
    )
    if preset_name:
        payload["preset"] = preset_name
    return payload


@mcp.tool
def get_swarm_status(run_id: str) -> str:
    """Get the current status of a swarm run.

    Returns status, task progress, token usage, and an ``is_stale`` flag for
    the specified run. Use this to poll a long-running swarm without blocking.

    Args:
        run_id: The run ID returned by run_swarm.
    """
    store = _get_swarm_store()
    try:
        run = store.load_run(run_id)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    if run is None:
        return json.dumps({"status": "error", "error": f"Run {run_id} not found"}, ensure_ascii=False)
    reconciled = store.reconcile_run(run, write=True)
    return json.dumps(
        _run_to_dict(reconciled, is_stale=store.is_run_stale(reconciled)),
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool
def get_run_result(run_id: str) -> str:
    """Get the final report and task summaries of a swarm run.

    Reconciles the run on read: an orphaned ``running`` run whose host
    process exited will be transitioned to its real terminal status
    (``completed`` / ``failed`` / ``cancelled`` derived from the task
    statuses), so the caller never sees a permanent zombie.

    Args:
        run_id: The run ID returned by run_swarm.
    """
    store = _get_swarm_store()
    try:
        run = store.load_run(run_id)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    if run is None:
        return json.dumps({"status": "error", "error": f"Run {run_id} not found"}, ensure_ascii=False)
    reconciled = store.reconcile_run(run, write=True)
    payload = _run_to_dict(reconciled, is_stale=store.is_run_stale(reconciled))
    payload["ready"] = payload["status"] in {"completed", "failed", "cancelled"}
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool
def list_runs(limit: int = 20) -> str:
    """List recent swarm runs sorted by creation time (newest first).

    Each row includes task counts and an ``is_stale`` flag so callers can
    spot abandoned runs without a follow-up status call.

    Args:
        limit: Maximum number of runs to return (default 20).
    """
    from src.swarm.models import (
        public_model_metadata,
        public_provider_metadata,
        public_reasoning_effort,
    )

    store = _get_swarm_store()
    runs = store.list_runs(limit=limit)
    items = []
    for run in runs:
        # write=True so a zombie listed alongside live runs gets finalized;
        # the cost is bounded by ``limit`` (default 20) and most rows are
        # already terminal — reconcile is a no-op for those.
        reconciled = store.reconcile_run(run, write=True)
        counts = {"total": len(reconciled.tasks)}
        for t in reconciled.tasks:
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        items.append(
            {
                "run_id": reconciled.id,
                "preset": reconciled.preset_name,
                "status": reconciled.status.value,
                "is_stale": store.is_run_stale(reconciled),
                "created_at": reconciled.created_at,
                "completed_at": reconciled.completed_at,
                "task_counts": counts,
                "total_input_tokens": reconciled.total_input_tokens,
                "total_output_tokens": reconciled.total_output_tokens,
                "provider": public_provider_metadata(reconciled.provider),
                "model": public_model_metadata(reconciled.model),
                "reasoning_effort": public_reasoning_effort(reconciled.reasoning_effort),
                "use_responses_api": reconciled.use_responses_api,
            }
        )
    return json.dumps(items, ensure_ascii=False, indent=2)


@mcp.tool
def reap_stale_runs() -> str:
    """Mark every ``running`` run whose host process died as ``failed``.

    Walks the swarm store, applies the per-run stale threshold, and
    finalizes any run that has gone silent past it (writes ``run.json`` +
    ``tasks/*.json`` + appends a ``run_reaped`` event). Already-terminal
    runs and still-alive runs are left untouched.

    Returns:
        JSON list of reaped run IDs (empty when nothing was stale).
    """
    store = _get_swarm_store()
    reaped = store.reap_stale_running_runs()
    return json.dumps({"reaped": reaped}, ensure_ascii=False, indent=2)


@mcp.tool
def retry_run(run_id: str, resume: bool = False) -> str:
    """Retry a failed, stale, or cancelled swarm run.

    Re-launches a brand-new run with the same preset and variables as the
    original; the original run is left untouched as a record. Use this after
    spotting a ``failed`` or stale run via ``list_runs``. A still-``running``
    run cannot be retried — cancel or reap it first.

    With ``resume=True`` (replay), completed upstream tasks and their artifacts
    are carried into the new run as-is and only the failed/cancelled subgraph
    re-executes — completed independent branches are not re-run. ``resume``
    only applies to a ``failed`` or ``cancelled`` run; ``resume=True`` for any
    other status is refused with an error (a plain retry without ``resume``
    remains available for any non-running run).

    Args:
        run_id: ID of the run to retry (from ``list_runs`` / ``get_swarm_status``).
        resume: Replay the failed/cancelled subgraph instead of re-running the
            whole preset. Default ``False`` preserves the existing full re-run.

    Returns:
        JSON payload for the newly created run (``run_id`` / ``status`` /
        ``preset`` …), or an ``error`` object if the run is missing or active.
    """
    from src.config import load_swarm_agent_config
    from src.swarm.models import RunStatus
    from src.swarm.runtime import SwarmRuntime

    store = _get_swarm_store()
    try:
        loaded = store.load_run(run_id)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    if loaded is None:
        return json.dumps({"status": "error", "error": f"Run {run_id} not found"}, ensure_ascii=False)

    # Reconcile first so a zombie "running" run whose host died is demoted
    # before we gate on status; only a genuinely active run blocks retry.
    reconciled = store.reconcile_run(loaded, write=True)
    if reconciled.status == RunStatus.running:
        return json.dumps(
            {"status": "error", "error": "Cannot retry a running run. Cancel or reap it first."},
            ensure_ascii=False,
        )
    if resume and reconciled.status not in (RunStatus.failed, RunStatus.cancelled):
        return json.dumps(
            {
                "status": "error",
                "error": (
                    f"Cannot resume a run in status '{reconciled.status.value}'; "
                    "resume only applies to failed or cancelled runs."
                ),
            },
            ensure_ascii=False,
        )

    agent_config = load_swarm_agent_config()
    runtime = SwarmRuntime(store=store, agent_config=agent_config)
    try:
        new_run = runtime.start_run(
            reconciled.preset_name,
            reconciled.user_vars or {},
            include_shell_tools=_include_shell_tools,
            resume_from=reconciled if resume else None,
        )
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": f"DAG validation failed: {exc}"}, ensure_ascii=False)

    return json.dumps(
        _build_run_payload(store, new_run.id, new_run.preset_name, timed_out=False),
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# Trade journal tool
# ---------------------------------------------------------------------------


@mcp.tool
def analyze_trade_journal(
    file_path: str,
    analysis_type: str = "full",
    filter_expr: str = "",
) -> str:
    """Analyze a user's trade journal (CSV/Excel broker export) and return
    a trading profile plus behavior diagnostics.

    Parses 同花顺 / 东方财富 / 富途 / generic formats (encoding auto-detected).
    Output (JSON):
      - profile: holding days, frequency, win rate, PnL ratio, top symbols,
                 market distribution, hourly distribution
      - behaviors: disposition effect, overtrading, chasing momentum,
                   anchoring (each with severity + numeric evidence)

    Args:
        file_path: Absolute path to the uploaded CSV/Excel file.
        analysis_type: "full" | "profile" | "behavior" | "strategy".
        filter_expr: Optional filter (e.g. "2026-01 to 2026-03",
                     "symbol=600519.SH", "market=china_a").
    """
    registry = _get_registry()
    return registry.execute(
        "analyze_trade_journal",
        {
            "file_path": file_path,
            "analysis_type": analysis_type,
            "filter_expr": filter_expr,
        },
    )


# ---------------------------------------------------------------------------
# Shadow Account tools (4)
# ---------------------------------------------------------------------------


@mcp.tool
def extract_shadow_strategy(
    journal_path: str,
    min_support: int = 3,
    max_rules: int = 5,
) -> str:
    """Extract a Shadow Account profile (3-5 human-readable if-then rules)
    from the user's profitable roundtrips in a trade journal.

    Run `analyze_trade_journal` first if the journal hasn't been parsed.
    Returns shadow_id + rules preview. Profile persists to
    ~/.vibe-trading/shadow_accounts/.

    Args:
        journal_path: Path to the CSV/Excel broker export.
        min_support: Minimum profitable roundtrips required to back one rule.
        max_rules: Maximum rules to return (typically 3-5).
    """
    registry = _get_registry()
    return registry.execute(
        "extract_shadow_strategy",
        {
            "journal_path": journal_path,
            "min_support": min_support,
            "max_rules": max_rules,
        },
    )


@mcp.tool
def run_shadow_backtest(
    shadow_id: str,
    window_start: str = "",
    window_end: str = "",
    markets: _lenient_str_list_opt = None,
    journal_path: str = "",
) -> str:
    """Run a multi-market backtest (A股/港股/美股/crypto) on a Shadow Account
    profile and compute delta-PnL attribution vs the user's realized trades.

    Markets are backtested per settlement currency (CNY / HKD / USD pools;
    us + crypto share the USD pool); the headline PnL uses the profile's
    source-market currency.

    Requires `extract_shadow_strategy` to have run first.

    Args:
        shadow_id: ID returned by extract_shadow_strategy.
        window_start: ISO date, default today-1y.
        window_end: ISO date, default today.
        markets: Subset of ["china_a", "hk", "us", "crypto"], default all four.
        journal_path: Original journal path (enables attribution), optional.
    """
    registry = _get_registry()
    params: dict[str, Any] = {"shadow_id": shadow_id}
    if window_start:
        params["window_start"] = window_start
    if window_end:
        params["window_end"] = window_end
    if markets:
        params["markets"] = markets
    if journal_path:
        params["journal_path"] = journal_path
    return registry.execute("run_shadow_backtest", params)


@mcp.tool
def render_shadow_report(
    shadow_id: str,
    include_today_signals: bool = True,
    window_start: str = "",
    window_end: str = "",
    journal_path: str = "",
) -> str:
    """Render the Shadow Account HTML/PDF report (8 sections + charts) for
    a shadow_id. If no cached backtest, one is run automatically.

    Args:
        shadow_id: Shadow Account ID.
        include_today_signals: Include today's market scan section.
        window_start: Optional backtest window override.
        window_end: Optional backtest window override.
        journal_path: Original journal path (for attribution), optional.
    """
    registry = _get_registry()
    params: dict[str, Any] = {
        "shadow_id": shadow_id,
        "include_today_signals": include_today_signals,
    }
    if window_start:
        params["window_start"] = window_start
    if window_end:
        params["window_end"] = window_end
    if journal_path:
        params["journal_path"] = journal_path
    return registry.execute("render_shadow_report", params)


@mcp.tool
def scan_shadow_signals(
    shadow_id: str,
    date: str = "",
    per_market: int = 3,
) -> str:
    """List today's symbols that match the Shadow Account's entry cadence
    (research use only — not a trade recommendation).

    Args:
        shadow_id: Shadow Account ID.
        date: ISO YYYY-MM-DD target date, default today.
        per_market: Max signals per market.
    """
    registry = _get_registry()
    params: dict[str, Any] = {"shadow_id": shadow_id, "per_market": per_market}
    if date:
        params["date"] = date
    return registry.execute("scan_shadow_signals", params)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Entry point for `vibe-trading-mcp` CLI command."""
    global _include_shell_tools, _registry
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

    _include_shell_tools = _resolve_include_shell_tools(args.enable_shell_tools)
    _registry = None
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
