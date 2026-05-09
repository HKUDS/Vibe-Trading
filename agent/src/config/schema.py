"""Structured agent config schema for MCP client integration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class MCPServerConfig(ConfigBase):
    """Single external MCP server definition."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    tool_timeout: int = Field(default=30, ge=1)
    enabled_tools: list[str] = Field(default_factory=lambda: ["*"])

    @model_validator(mode="after")
    def validate_v1_stdio_only(self) -> "MCPServerConfig":
        """Reject non-stdio transports for the first release.

        Returns:
            The validated MCP server config instance.

        Raises:
            ValueError: If the config implies a non-stdio transport, uses
                HTTP-only fields, or omits the command required for stdio.
        """
        transport = self.type
        if transport is None:
            if self.command:
                transport = "stdio"
            elif self.url:
                transport = "sse" if self.url.rstrip("/").endswith("/sse") else "streamableHttp"

        if transport and transport != "stdio":
            raise ValueError("Only stdio MCP servers are supported in v1")
        if self.url or self.headers:
            raise ValueError("HTTP MCP transports are not supported in v1")
        if not self.command.strip():
            raise ValueError("stdio MCP servers require a command")
        return self


class MCPServerConfigOverride(ConfigBase):
    """Partial MCP server override used for runtime config layering."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    tool_timeout: int | None = Field(default=None, ge=1)
    enabled_tools: list[str] | None = None


class AgentConfig(ConfigBase):
    """Top-level structured agent config."""

    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


class AgentConfigOverride(ConfigBase):
    """Partial top-level config override used for runtime layering."""

    mcp_servers: dict[str, MCPServerConfigOverride] = Field(default_factory=dict)