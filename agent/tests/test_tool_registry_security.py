"""Security regression tests for default tool exposure."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import pytest

from src.tools import build_registry


def test_shell_tools_absent_from_default_registry(monkeypatch: pytest.MonkeyPatch, registry_goal_db) -> None:
    monkeypatch.delenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", raising=False)

    registry = build_registry(policy=ToolPolicy.from_config(get_env_config()))

    assert "bash" not in registry.tool_names
    assert "background_run" not in registry.tool_names
    assert "cancel_background" not in registry.tool_names


def test_shell_tools_require_registry_opt_in(monkeypatch: pytest.MonkeyPatch, registry_goal_db) -> None:
    monkeypatch.delenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", raising=False)

    registry = build_registry(policy=ToolPolicy.from_config(get_env_config()), include_shell_tools=True)

    assert "bash" in registry.tool_names
    assert "background_run" in registry.tool_names
    assert "cancel_background" in registry.tool_names
