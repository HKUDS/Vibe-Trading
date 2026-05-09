"""Unit tests for structured agent config loading."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import (
    AgentConfig,
    get_config_path,
    get_data_dir,
    get_runtime_root,
    load_agent_config,
    load_runtime_agent_config,
)


def test_load_agent_config_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "agent.json"

    config = load_agent_config(config_path)

    assert config == AgentConfig()
    assert get_config_path(config_path) == config_path


def test_load_agent_config_accepts_camel_case_json(tmp_path: Path) -> None:
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            "demo": {
              "command": "uvx",
              "args": ["demo-server"],
              "toolTimeout": 15,
              "enabledTools": ["alpha"]
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_agent_config(config_path)

    assert config.mcp_servers["demo"].command == "uvx"
    assert config.mcp_servers["demo"].args == ["demo-server"]
    assert config.mcp_servers["demo"].tool_timeout == 15
    assert config.mcp_servers["demo"].enabled_tools == ["alpha"]


def test_load_agent_config_supports_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        """
        mcpServers:
          demo:
            command: uvx
            args:
              - demo-server
        """.strip(),
        encoding="utf-8",
    )

    config = load_agent_config(config_path)

    assert config.mcp_servers["demo"].command == "uvx"
    assert config.mcp_servers["demo"].args == ["demo-server"]


def test_schema_rejects_non_stdio_transports() -> None:
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(
            {
                "mcpServers": {
                    "demo": {
                        "type": "sse",
                        "url": "http://localhost:8900/sse",
                    }
                }
            }
        )


def test_load_agent_config_warns_and_falls_back_on_invalid_file(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    config_path = tmp_path / "agent.json"
    config_path.write_text("{not-json}", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        config = load_agent_config(config_path)

    assert config == AgentConfig()
    assert "Failed to load agent config" in caplog.text


def test_runtime_overrides_take_precedence_and_merge_nested_servers(tmp_path: Path) -> None:
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        """
        {
          "mcpServers": {
            "demo": {
              "command": "base-server",
              "args": ["--base"],
              "enabledTools": ["alpha"]
            },
            "audit": {
              "command": "audit-server"
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_runtime_agent_config(
        config_path,
        overrides={
            "mcpServers": {
                "demo": {
                    "tool_timeout": 45,
                },
                "research": {
                    "command": "research-server",
                },
            }
        },
    )

    assert config.mcp_servers["demo"].command == "base-server"
    assert config.mcp_servers["demo"].args == ["--base"]
    assert config.mcp_servers["demo"].tool_timeout == 45
    assert config.mcp_servers["demo"].enabled_tools == ["alpha"]
    assert config.mcp_servers["audit"].command == "audit-server"
    assert config.mcp_servers["research"].command == "research-server"


def test_explicit_config_path_does_not_mutate_default_runtime_root(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "agent.json"
    load_agent_config(config_path)

    assert get_runtime_root(config_path) == config_path.parent
    assert get_runtime_root() == Path.home() / ".vibe-trading"
    assert get_config_path(config_path) == config_path


def test_get_data_dir_uses_explicit_config_parent(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "agent.json"

    assert get_runtime_root(config_path) == config_path.parent
    assert get_data_dir(config_path) == config_path.parent
    assert config_path.parent.exists()