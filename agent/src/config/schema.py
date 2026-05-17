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
            return self

        if not self.url.strip():
            raise ValueError(f"{transport} MCP servers require a url")
        if self.command.strip() or self.args or self.env:
            raise ValueError(f"{transport} MCP servers do not accept command/args/env")
        return self


class MCPServerConfigOverride(ConfigBase):
    """Partial MCP server override used for runtime config layering."""

    type: Literal["stdio", "sse", "streamableHttp"] | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    tool_timeout: float | None = Field(default=None, ge=0.1)
    enabled_tools: list[str] | None = None


class AgentConfig(ConfigBase):
    """Top-level structured agent config."""

    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


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