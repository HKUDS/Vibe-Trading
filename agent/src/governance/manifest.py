"""Tool governance manifest models."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ToolSurface(str, Enum):
    """Execution surfaces where a tool call may originate."""

    CLI = "cli"
    LOCAL_API = "local_api"
    REMOTE_API = "remote_api"
    MCP_STDIO = "mcp_stdio"
    MCP_SSE = "mcp_sse"
    MCP_HTTP = "mcp_http"
    SWARM = "swarm"
    SCHEDULER = "scheduler"
    BACKTEST_SUBPROCESS = "backtest_subprocess"
    LIVE_CONNECTOR = "live_connector"
    CHANNEL_BOT = "channel_bot"


class RiskLevel(str, Enum):
    """Governance risk tiers for tool calls."""

    R0_READ = "R0_READ"
    R1_WRITE_LOCAL = "R1_WRITE_LOCAL"
    R2_NETWORK = "R2_NETWORK"
    R3_TRADE_READ = "R3_TRADE_READ"
    R4_TRADE_WRITE = "R4_TRADE_WRITE"
    R5_SHELL = "R5_SHELL"
    UNCLASSIFIED = "UNCLASSIFIED"


SecretAccess = Literal["none", "market_data_read", "llm", "api_auth", "broker"]
AllowedMode = Literal["research", "paper", "advisory", "live"]


class ToolManifest(BaseModel):
    """Governance metadata derived from an existing BaseTool."""

    model_config = ConfigDict(extra="allow")

    name: str
    surface: ToolSurface
    readonly: bool
    repeatable: bool
    risk_level: RiskLevel
    requires_auth: bool
    requires_consent: bool
    allowed_modes: list[AllowedMode]
    secret_access: SecretAccess
    timeout_seconds: int
    side_effects: list[str]
    live_classification: str | None = None

    @property
    def is_readonly(self) -> bool:
        """Compatibility alias for BaseTool-style readonly metadata."""
        return self.readonly
