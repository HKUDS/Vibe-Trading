"""CLI shell tools: off by default, refused with live authority, confirmed per command.

A host shell can import a broker connector and call ``place_order`` directly,
so it bypasses the live-order gate. These tests pin the three guards. No
command is ever executed for real: the "bash" tool here is a recording fake.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.tools import _shell_safety


class _FakeBash(BaseTool):
    name = "bash"
    description = "fake"
    parameters = {"type": "object", "properties": {"command": {"type": "string"}}}
    is_readonly = False

    def __init__(self) -> None:
        self.ran: list[str] = []

    def execute(self, **kwargs: Any) -> str:
        self.ran.append(kwargs["command"])
        return json.dumps({"status": "ok"})


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    yield
    _shell_safety.set_shell_confirm(None)


def _registry() -> tuple[ToolRegistry, _FakeBash]:
    registry = ToolRegistry()
    tool = _FakeBash()
    registry.register(tool)
    return registry, tool


# --------------------------------------------------------------------------- #
# Registry hook
# --------------------------------------------------------------------------- #


def test_declined_command_never_runs() -> None:
    registry, tool = _registry()
    asked: list[tuple[str, str]] = []
    _shell_safety.set_shell_confirm(lambda name, cmd: asked.append((name, cmd)) or False)

    result = json.loads(registry.execute("bash", {"command": "echo hi"}))

    assert result["skipped"] is True and "declined" in result["error"]
    assert asked == [("bash", "echo hi")]
    assert tool.ran == []


def test_approved_command_runs_and_no_hook_means_no_prompt() -> None:
    registry, tool = _registry()
    _shell_safety.set_shell_confirm(lambda name, cmd: True)
    registry.execute("bash", {"command": "echo ok"})
    _shell_safety.set_shell_confirm(None)  # API/MCP: operator opt-in, no prompt
    registry.execute("bash", {"command": "echo api"})
    assert tool.ran == ["echo ok", "echo api"]


def test_lazy_loading_registry_copy_is_also_confirmed() -> None:
    from src.agent.tool_loading import DeferredToolRegistry

    source, tool = _registry()
    _shell_safety.set_shell_confirm(lambda name, cmd: False)
    json.loads(DeferredToolRegistry(source).execute("bash", {"command": "rm -rf x"}))
    assert tool.ran == []


# --------------------------------------------------------------------------- #
# Live-authority detection
# --------------------------------------------------------------------------- #


def test_no_live_authority_on_a_fresh_install() -> None:
    assert _shell_safety.live_trading_signals() == []


def test_mandate_and_oauth_tokens_count_as_live_authority(tmp_path) -> None:
    from src.live.paths import live_root

    (live_root() / "alpaca").mkdir(parents=True)
    (live_root() / "alpaca" / "mandate.json").write_text("{}", encoding="utf-8")
    (live_root() / "robinhood" / "oauth").mkdir(parents=True)
    (live_root() / "robinhood" / "oauth" / "token").write_text("TEST-TOKEN-CANARY", encoding="utf-8")

    reasons = _shell_safety.live_trading_signals()
    assert any("mandate" in r and "alpaca" in r for r in reasons)
    assert any("OAuth" in r and "robinhood" in r for r in reasons)


def test_selected_live_trade_profile_counts_as_live_authority() -> None:
    from src.trading.profiles import config_path, save_selected_profile_id

    save_selected_profile_id("alpaca-live-trade")
    assert config_path().exists()
    assert any("alpaca-live-trade" in r for r in _shell_safety.live_trading_signals())
    save_selected_profile_id("alpaca-paper-trade")
    assert _shell_safety.live_trading_signals() == []


def test_unreadable_trading_config_fails_closed() -> None:
    from src.trading.connections import ConnectionStore

    path = ConnectionStore().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert any("could not be read" in r for r in _shell_safety.live_trading_signals())


# --------------------------------------------------------------------------- #
# CLI wiring (needs the CLI's rich dependency)
# --------------------------------------------------------------------------- #


@pytest.fixture
def legacy(monkeypatch):
    pytest.importorskip("rich")
    from cli import _legacy
    from src.config.accessor import reset_env_config

    monkeypatch.delenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", raising=False)
    reset_env_config()
    yield _legacy
    monkeypatch.delenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", raising=False)
    reset_env_config()


def _opt_in(monkeypatch) -> None:
    from src.config.accessor import reset_env_config

    monkeypatch.setenv("VIBE_TRADING_ENABLE_SHELL_TOOLS", "1")
    reset_env_config()


def test_cli_shell_tools_off_by_default(legacy) -> None:
    assert legacy._cli_shell_tools_enabled(lambda msg: None) is False
    assert _shell_safety._shell_confirm is None


def test_cli_opt_in_installs_confirmation(legacy, monkeypatch) -> None:
    _opt_in(monkeypatch)
    assert legacy._cli_shell_tools_enabled(lambda msg: None) is True
    assert _shell_safety._shell_confirm is legacy._confirm_shell_command


def test_cli_opt_in_refused_with_live_authority(legacy, monkeypatch) -> None:
    from src.live.paths import live_root

    (live_root() / "okx").mkdir(parents=True)
    (live_root() / "okx" / "mandate.json").write_text("{}", encoding="utf-8")
    _opt_in(monkeypatch)
    warnings: list[str] = []

    assert legacy._cli_shell_tools_enabled(warnings.append) is False
    assert _shell_safety._shell_confirm is None
    assert warnings and "mandate" in warnings[0]


@pytest.mark.parametrize("tty,answer,expected", [
    (False, "y", False),
    (True, "y", True),
    (True, "YES", True),
    (True, "", False),
    (True, "n", False),
])
def test_confirm_prompt(legacy, monkeypatch, tty, answer, expected) -> None:
    monkeypatch.setattr(legacy.sys.stdin, "isatty", lambda: tty, raising=False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": answer)
    assert legacy._confirm_shell_command("bash", "echo hi") is expected


def test_confirm_prompt_eof_declines(legacy, monkeypatch) -> None:
    def _eof(_prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr(legacy.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", _eof)
    assert legacy._confirm_shell_command("background_run", "sleep 1") is False
