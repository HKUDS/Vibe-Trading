"""Focused coverage for command hooks, shell sandboxing and host tools."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent.hooks import HookManager
from src.agent.tool_lifecycle import ToolCallLifecycle
from src.agent.tools import BaseTool, ToolRegistry
from src.tools.bash_tool import BashTool
from src.tools.sandbox import SandboxSettings, enumerate_protected_runtime_paths
from src.tools.spawn_agent_tool import child_registry
from src.tools import _discover_subclasses


class _ProbeTool(BaseTool):
    name = "hook_probe"
    description = "probe"
    parameters = {"type": "object", "properties": {}}
    calls: list[str] = []

    def execute(self, **kwargs: object) -> str:
        del kwargs
        self.calls.append("called")
        return json.dumps({"status": "ok", "value": "done"})


class _HostTool(BaseTool):
    name = "host_probe"
    description = "host probe"

    def execute(self, **kwargs: object) -> str:
        del kwargs
        return json.dumps({"status": "ok"})


class _TradingHostTool(_HostTool):
    name = "host_trading_probe"
    is_trading_tool = True


class _Lifecycle(ToolCallLifecycle):
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.memory = SimpleNamespace(run_dir=None)
        self._cancel_event = threading.Event()
        self._emit = lambda *_args, **_kwargs: None


def _write_hooks(root: Path, event: str, command: str, matcher: str = "*") -> None:
    (root / "hooks.json").write_text(
        json.dumps({"hooks": {event: [{"matcher": matcher, "hooks": [{"type": "command", "command": command}]}]}}),
        encoding="utf-8",
    )


def test_pre_tool_hook_denies_without_running_tool_and_audits(tmp_path: Path) -> None:
    _write_hooks(tmp_path, "PreToolUse", "printf '{\"decision\":\"deny\",\"reason\":\"operator rule\"}'")
    manager = HookManager(tmp_path)
    registry = ToolRegistry()
    tool = _ProbeTool()
    tool.calls = []
    registry.register(tool)
    registry.hooks = manager
    result, _elapsed = _Lifecycle(registry)._invoke_tool("hook_probe", {}, call_id="c1")
    payload = json.loads(result)
    assert payload["error_code"] == "hook_denied"
    assert tool.calls == []


def test_pre_tool_hook_crash_and_timeout_deny(tmp_path: Path) -> None:
    _write_hooks(tmp_path, "PreToolUse", "exit 7")
    assert HookManager(tmp_path).run("PreToolUse", {"tool_name": "x"}).denied
    _write_hooks(tmp_path, "PreToolUse", "sleep 1")
    assert HookManager(tmp_path, timeout_seconds=0.01).run("PreToolUse", {"tool_name": "x"}).denied


def test_allowing_hook_cannot_bypass_tool_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "hook-ran"
    _write_hooks(tmp_path, "PreToolUse", f"touch {marker}")
    monkeypatch.setattr("src.providers.tool_policy._deny_prefixes", lambda: ("blocked_",))
    tool = _ProbeTool()
    tool.name = "blocked_probe"
    tool.calls = []
    registry = ToolRegistry()
    registry.register(tool)
    registry.hooks = HookManager(tmp_path)
    result, _elapsed = _Lifecycle(registry)._invoke_tool("blocked_probe", {}, call_id="c1")
    assert json.loads(result)["skipped"] is True
    assert not marker.exists()
    assert tool.calls == []


def test_child_registry_keeps_parent_hooks(tmp_path: Path) -> None:
    manager = HookManager(tmp_path)
    parent = ToolRegistry()
    parent.hooks = manager
    parent.register(_ProbeTool())
    child = child_registry(parent, tmp_path / "child")
    assert child.hooks is manager


def test_sandbox_profile_derives_credential_paths_and_network_rule(tmp_path: Path) -> None:
    protected = enumerate_protected_runtime_paths(tmp_path)
    assert tmp_path / "connectors" in protected
    assert tmp_path / "auth" in protected
    assert tmp_path / "live" in protected
    profile = SandboxSettings(enabled=True, network=False, backend="sandbox-exec", runtime_root=tmp_path).profile_text(tmp_path / "workspace")
    assert '(deny file-read* (subpath "' + str(tmp_path / "connectors") in profile
    assert "allow network*" not in profile


def test_enabled_sandbox_refuses_when_backend_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.tools.sandbox.shutil.which", lambda _name: None)
    settings = SandboxSettings(enabled=True, backend="bwrap", runtime_root=tmp_path)
    result = json.loads(BashTool(settings).execute(command="echo should-not-run", run_dir=str(tmp_path)))
    assert result["status"] == "error"
    assert result["error_code"] == "sandbox_unavailable"


def test_host_registration_is_explicit_and_rejects_collisions() -> None:
    registry = ToolRegistry()
    registry.register(_ProbeTool())
    registry.register_host_tool(_HostTool())
    assert registry.get("host_probe") is not None
    with pytest.raises(ValueError, match="collides"):
        registry.register_host_tool(_HostTool())
    with pytest.raises(ValueError, match="trading"):
        registry.register_host_tool(_TradingHostTool())
    assert "host_probe" not in {cls.name for cls in _discover_subclasses()}



def test_hook_reason_is_redacted_before_return_and_thread_audit(tmp_path, monkeypatch) -> None:
    """Hook output is untrusted text even when its command is operator-owned."""
    from tests.recording_helpers import recorder_at

    secret = "sk-" + "a" * 40
    _write_hooks(tmp_path, "PreToolUse", "unused-command")
    monkeypatch.setattr(
        "src.agent.hooks.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"decision": "deny", "reason": f"api_key={secret}"}),
        ),
    )
    recorder = recorder_at(tmp_path)
    manager = HookManager(tmp_path)
    manager.set_audit_sink(recorder)
    decision = manager.run("PreToolUse", {"tool_name": "probe"})
    recorder.close()
    assert decision.denied
    assert secret not in decision.reason
    persisted = (tmp_path / "thread.jsonl").read_text()
    assert "hook_decision" in persisted
    assert secret not in persisted
