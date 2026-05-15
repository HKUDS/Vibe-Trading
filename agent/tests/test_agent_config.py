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
    sanitize_session_overrides,
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


# ---------------------------------------------------------------------------
# sanitize_session_overrides – security gate for mcpServers
# ---------------------------------------------------------------------------

def test_sanitize_strips_mcp_servers_by_default() -> None:
    raw = {
        "mcpServers": {"evil": {"command": "/bin/sh", "args": ["-c", "id"]}},
        "include_shell_tools": True,
    }
    result = sanitize_session_overrides(raw)

    assert "mcpServers" not in result
    assert result["include_shell_tools"] is True


def test_sanitize_strips_snake_case_key_by_default() -> None:
    raw = {"mcp_servers": {"evil": {"command": "bad"}}}
    result = sanitize_session_overrides(raw)

    assert "mcp_servers" not in result


def test_sanitize_logs_warning_when_stripping(caplog: pytest.LogCaptureFixture) -> None:
    raw = {"mcpServers": {"s": {"command": "uvx"}}}

    with caplog.at_level(logging.WARNING, logger="src.config.loader"):
        sanitize_session_overrides(raw)

    assert "mcpServers" in caplog.text
    assert "ALLOW_SESSION_MCP_SERVERS" in caplog.text


def test_sanitize_passes_through_when_env_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOW_SESSION_MCP_SERVERS", "1")
    raw = {
        "mcpServers": {"search": {"command": "uvx", "args": ["search-mcp"]}},
        "include_shell_tools": False,
    }
    result = sanitize_session_overrides(raw)

    assert "mcpServers" in result
    assert result["mcpServers"] == raw["mcpServers"]


def test_sanitize_passes_through_true_and_yes_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("true", "yes", "True", "YES"):
        monkeypatch.setenv("ALLOW_SESSION_MCP_SERVERS", val)
        result = sanitize_session_overrides({"mcpServers": {"s": {"command": "x"}}})
        assert "mcpServers" in result, f"Expected opt-in to work for ALLOW_SESSION_MCP_SERVERS={val!r}"


def test_sanitize_empty_overrides_returns_empty() -> None:
    assert sanitize_session_overrides({}) == {}


def test_sanitize_non_mcp_keys_always_pass_through() -> None:
    raw = {"include_shell_tools": True, "some_other_key": "value"}
    result = sanitize_session_overrides(raw)
    assert result == raw


# ---------------------------------------------------------------------------
# End-to-end sanitize + load + merge regression
#
# Locks the `extra="ignore"` invariant on AgentConfigOverride: if it gets
# flipped back to "forbid", a session whose config carries unrelated keys
# (e.g. `include_shell_tools`, which SessionService injects at line ~118)
# would raise a ValidationError and silently drop the entire override,
# including any valid `mcpServers`. That regression would not show up in
# any test that only exercises sanitize_session_overrides in isolation.
# ---------------------------------------------------------------------------

def test_runtime_load_drops_mcp_servers_when_mixed_with_unknown_keys(
    tmp_path: Path,
) -> None:
    """Default path: session overrides with mcpServers + unknown keys must
    strip mcpServers and still merge cleanly on top of the disk config."""
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        '{"mcpServers": {"trusted": {"command": "uvx", "args": ["t"]}}}',
        encoding="utf-8",
    )

    session_overrides = {
        "include_shell_tools": True,
        "mcpServers": {"evil": {"command": "/bin/sh", "args": ["-c", "id"]}},
    }
    safe = sanitize_session_overrides(session_overrides)
    merged = load_runtime_agent_config(config_path=config_path, overrides=safe)

    assert set(merged.mcp_servers.keys()) == {"trusted"}
    assert merged.mcp_servers["trusted"].command == "uvx"


def test_runtime_load_preserves_mcp_servers_when_opted_in_with_unknown_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opt-in path: with ALLOW_SESSION_MCP_SERVERS=1, valid mcpServers must
    survive the merge even when the session payload also carries unknown
    keys like include_shell_tools.  Guards AgentConfigOverride extra='ignore'."""
    monkeypatch.setenv("ALLOW_SESSION_MCP_SERVERS", "1")
    config_path = tmp_path / "agent.json"
    config_path.write_text(
        '{"mcpServers": {"base": {"command": "uvx", "args": ["base"]}}}',
        encoding="utf-8",
    )

    session_overrides = {
        "include_shell_tools": False,
        "some_future_field": "ignored",
        "mcpServers": {"session": {"command": "uvx", "args": ["session-mcp"]}},
    }
    safe = sanitize_session_overrides(session_overrides)
    merged = load_runtime_agent_config(config_path=config_path, overrides=safe)

    assert set(merged.mcp_servers.keys()) == {"base", "session"}
    assert merged.mcp_servers["session"].command == "uvx"
    assert merged.mcp_servers["session"].args == ["session-mcp"]