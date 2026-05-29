"""Structured agent config schema for MCP client integration."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Live-broker MCP server keys. These channels place real orders, so a wildcard
# ``enabled_tools`` (which would re-admit every WRITE/UNKNOWN tool) is rejected
# at config-load time — a live channel must pin an explicit read-only allowlist.
LIVE_BROKER_SERVER_KEYS: frozenset[str] = frozenset({"robinhood"})

# Live-broker URL host suffixes. Detecting a live broker by config key alone is
# bypassable: a Robinhood agentic URL placed under any other key (e.g. ``rh``)
# would otherwise dodge BOTH the wildcard rejection AND the classification gate,
# exposing ``place_order`` ungated. So a server whose ``url`` host matches one of
# these suffixes is treated as a live broker regardless of its config key. The
# name-key path (``LIVE_BROKER_SERVER_KEYS``) stays as a fallback for stdio /
# non-URL live channels and for keys that intentionally name a known broker.
LIVE_BROKER_URL_HOST_SUFFIXES: tuple[str, ...] = ("robinhood.com",)


def _url_host(url: str) -> str:
    """Return the lower-cased hostname of an http(s) URL, or ``""``.

    Args:
        url: A candidate MCP server URL.

    Returns:
        The lower-cased host with any port stripped, or ``""`` when the URL is
        empty or has no parseable host.
    """
    if not url or not url.strip():
        return ""
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError:
        return ""
    return (host or "").lower()


def is_live_broker_url(url: str) -> bool:
    """Return whether a URL points at a known live-broker host.

    A live broker is detected by host so an aliased config key cannot bypass the
    wildcard rejection / gate. Match is on the host or any subdomain of a known
    suffix (``agent.robinhood.com`` and ``robinhood.com`` both match), never a
    substring (``robinhood.com.evil.test`` does NOT match).

    Args:
        url: The MCP server ``url`` from config.

    Returns:
        ``True`` when the URL host equals or is a subdomain of a live-broker
        host suffix.
    """
    host = _url_host(url)
    if not host:
        return False
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in LIVE_BROKER_URL_HOST_SUFFIXES
    )


def is_live_broker_entry(server_key: str, server: "MCPServerConfig | MCPServerConfigOverride") -> bool:
    """Return whether a configured MCP server is a live broker.

    Detection is by config key (``LIVE_BROKER_SERVER_KEYS``) OR by URL host
    (``is_live_broker_url``), so a live-broker URL parked under an arbitrary key
    is still gated and still subject to the wildcard-allowlist rejection.

    Args:
        server_key: The MCP server key from config.
        server: The server config (or override) carrying the ``url``.

    Returns:
        ``True`` when either the key or the URL host identifies a live broker.
    """
    if server_key.strip().lower() in LIVE_BROKER_SERVER_KEYS:
        return True
    return is_live_broker_url(getattr(server, "url", "") or "")

# Canonical seed for the operator-side ``~/.vibe-trading/agent.json`` mcpServers
# entry that wires the Robinhood Agentic Trading channel. It ships OFF-by-default
# read-only: an explicit READ allowlist (never ``["*"]``), OAuth auth, and the
# streamableHttp transport. Operators copy this block into their protected config
# file; WRITE/order tools are only ever added by the user editing that file by
# hand (never via agent tool args), and only take effect once a mandate exists.
# Documented here (not invented elsewhere) because the operator config file is a
# runtime artifact, not checked into the repo. See SPEC §7.2 / Transport §1–§6.
ROBINHOOD_MCP_SERVER_SEED: dict[str, object] = {
    "type": "streamableHttp",
    "url": "https://agent.robinhood.com/mcp/trading",
    "auth": {
        "type": "oauth",
        "scopes": ["trading.read"],
        "client_name": "Vibe-Trading",
        "cache_dir": "~/.vibe-trading/live/robinhood/oauth",
    },
    # Seed the OFF-by-default READ allowlist to EXACTLY the canonical curated
    # READ tool names (``src.live.robinhood_classification.ROBINHOOD_TOOL_CLASS``).
    # These MUST match the curated map's READ entries: a name here that the map
    # does not classify READ would resolve UNKNOWN -> gated -> refused, silently
    # hiding the real read tool. Canonical READ catalog: get_account,
    # get_positions, get_quotes, list_orders. WRITE (place_order, cancel_order)
    # is never seeded — the user adds those by hand once a mandate exists.
    "enabled_tools": [
        "get_account",
        "get_positions",
        "get_quotes",
        "list_orders",
    ],
}


def _to_camel(name: str) -> str:
    """Convert snake_case names to camelCase aliases.

    Args:
        name: Field name in snake_case form.

    Returns:
        The camelCase alias used for external config compatibility.
    """
    parts = name.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class ConfigBase(BaseModel):
    """Base config model accepting both snake_case and camelCase keys."""

    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True, extra="forbid")


class MCPOAuthConfig(ConfigBase):
    """OAuth authentication for a remote (HTTP) MCP server.

    The OAuth provider owns the runtime ``Authorization`` header, so a server
    using OAuth must not also set static ``headers`` (mutually exclusive — see
    :meth:`MCPServerConfig.validate_transport_config`). OAuth is only valid on an
    HTTPS HTTP transport: a refresh token must never traverse cleartext.

    Attributes:
        type: Auth discriminator. Only ``"oauth"`` is supported today.
        scopes: OAuth scopes requested at authorization time.
        client_name: Client name presented during dynamic client registration.
        cache_dir: Directory for the persistent OAuth token cache. ``~`` is
            expanded and the directory is created ``0700`` at first write by the
            client. This is the single canonical field name (wire alias
            ``cacheDir``) — every consumer reads ``auth.cache_dir`` (the OAuth
            wiring in :func:`src.tools.mcp.MCPServerAdapter._build_client`, the
            ``live revoke`` CLI cache sweep, and the seed below) so there is no
            silent default-path fallback from a name mismatch. (``docs/live-
            trading/SPEC.md`` §2 names this ``token_cache_path``; the shipped
            field name is ``cache_dir`` to stay consistent with the existing CLI
            consumer, which is the authoritative wire name.)
        callback_port: Fixed loopback port for the browser redirect callback.
            ``None`` (default) lets the OAuth provider pick a free port.
        client_id: Optional pre-registered OAuth client id (skips dynamic
            client registration when provided).
    """

    type: Literal["oauth"] = "oauth"
    scopes: list[str] = Field(default_factory=list)
    client_name: str = "Vibe-Trading"
    cache_dir: str = "~/.vibe-trading/live/robinhood/oauth"
    callback_port: int | None = Field(default=None, ge=1, le=65535)
    client_id: str | None = None


class MCPServerConfig(ConfigBase):
    """Single external MCP server definition."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    auth: MCPOAuthConfig | None = None
    tool_timeout: float = Field(default=30.0, ge=0.1)
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])

    def resolved_transport(self) -> Literal["stdio", "sse", "streamableHttp"]:
        """Resolve the effective transport from explicit type or implied fields."""
        if self.type is not None:
            return self.type
        if self.command.strip() or self.args or self.env:
            return "stdio"
        if self.url.strip():
            raise ValueError("HTTP MCP servers require an explicit type of 'sse' or 'streamableHttp'")
        return "stdio"

    @model_validator(mode="after")
    def validate_transport_config(self) -> "MCPServerConfig":
        """Validate transport-specific MCP server configuration.

        Returns:
            The validated MCP server config instance.

        Raises:
            ValueError: If required fields are missing for the resolved
                transport or conflicting fields are provided.
        """
        transport = self.resolved_transport()

        if transport == "stdio":
            if not self.command.strip():
                raise ValueError("stdio MCP servers require a command")
            if self.url.strip() or self.headers:
                raise ValueError("stdio MCP servers do not accept url/headers")
            if self.auth is not None:
                raise ValueError("stdio MCP servers do not accept auth (OAuth is HTTP-only)")
            return self

        if not self.url.strip():
            raise ValueError(f"{transport} MCP servers require a url")
        if self.command.strip() or self.args or self.env:
            raise ValueError(f"{transport} MCP servers do not accept command/args/env")

        if self.auth is not None:
            # The OAuth provider owns the runtime Authorization header; a
            # hand-set static header alongside it is always a config error.
            if self.headers:
                raise ValueError(
                    "MCP servers using auth must not also set static headers "
                    "(the OAuth provider owns the Authorization header)"
                )
            # A refresh token must never traverse cleartext.
            if not self.url.strip().lower().startswith("https://"):
                raise ValueError("OAuth MCP servers require an https url")
        return self


class MCPServerConfigOverride(ConfigBase):
    """Partial MCP server override used for runtime config layering."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    auth: MCPOAuthConfig | None = None
    tool_timeout: float | None = Field(default=None, ge=0.1)
    enabled_tools: list[str] | None = None


class AgentConfig(ConfigBase):
    """Top-level structured agent config."""

    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_live_broker_servers(self) -> "AgentConfig":
        """Reject wildcard allowlists on live-broker MCP server entries.

        A live-broker channel places real orders, so a wildcard
        ``enabled_tools`` of ``["*"]`` — which would re-admit every WRITE/UNKNOWN
        tool — is a config error. Live channels must pin an explicit read-only
        allowlist. A server is a live broker by config key OR by URL host
        (:func:`is_live_broker_entry`), so a Robinhood URL parked under an
        aliased key (e.g. ``rh``) cannot dodge this rejection. The server key is
        only known at this top-level scope, which is why the check lives here
        rather than on :class:`MCPServerConfig`.

        Returns:
            The validated agent config instance.

        Raises:
            ValueError: If a live-broker server entry uses ``["*"]``.
        """
        for server_key, server in self.mcp_servers.items():
            if is_live_broker_entry(server_key, server) and "*" in server.enabled_tools:
                raise ValueError(
                    f"Live-broker MCP server '{server_key}' may not use a wildcard "
                    "enabledTools allowlist ('*'); pin an explicit read-only tool list"
                )
        return self


class AgentConfigOverride(ConfigBase):
    """Partial top-level config override used for runtime layering."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        # Load-bearing: SessionService passes the entire session.config dict
        # (which carries unrelated keys like include_shell_tools) through
        # merge_agent_config_overrides.  Flipping this back to "forbid" makes
        # any such payload raise ValidationError and silently drops the whole
        # override, including any valid mcpServers.  Regression test:
        # tests/test_agent_config.py::
        #   test_runtime_load_preserves_mcp_servers_when_opted_in_with_unknown_keys
        extra="ignore",
    )

    mcp_servers: dict[str, MCPServerConfigOverride] = Field(default_factory=dict)