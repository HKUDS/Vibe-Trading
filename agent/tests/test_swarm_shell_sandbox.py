"""A swarm node's shell commands are held to that node's workspace (VIBE_TRADING_SWARM_SHELL_SANDBOX)."""

from __future__ import annotations

import json
import logging
import platform
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from src.config.accessor import get_env_config, reset_env_config
from src.config.paths import get_runtime_root
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.product.tool_policy import ToolPolicy
from src.session.thread import ThreadLog
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.swarm.task_store import TaskStore
from src.tools import build_registry
import src.swarm.node as node


def _host_backend_works() -> bool:
    """Probe the platform sandbox the way a real command would use it."""
    if platform.system() == "Darwin" and shutil.which("sandbox-exec"):
        argv = ["sandbox-exec", "-p", "(version 1)(allow default)", "/bin/sh", "-c", ":"]
    elif platform.system() == "Linux" and shutil.which("bwrap"):
        argv = ["bwrap", "--die-with-parent", "--new-session", "--ro-bind", "/", "/", "--unshare-net",
                "/bin/sh", "-c", ":"]
    else:
        return False
    try:
        return subprocess.run(argv, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


requires_backend = pytest.mark.skipif(not _host_backend_works(), reason="no working OS sandbox backend on this host")


class _Script:
    def __init__(self, *responses):
        self.responses = iter(responses)

    def stream_chat(self, messages, **kwargs):
        return next(self.responses)

    def close(self):
        pass


def _call(call_id, name, **arguments):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(call_id, name, arguments)],
                       finish_reason="tool_calls")


@pytest.fixture
def mode(monkeypatch):
    """Set VIBE_TRADING_SWARM_SHELL_SANDBOX (None leaves the default) and reload the config."""
    def apply(value: str | None) -> None:
        if value is None:
            monkeypatch.delenv("VIBE_TRADING_SWARM_SHELL_SANDBOX", raising=False)
        else:
            monkeypatch.setenv("VIBE_TRADING_SWARM_SHELL_SANDBOX", value)
        reset_env_config()
    yield apply
    reset_env_config()


@pytest.fixture
def no_backend(monkeypatch):
    """Make the sandbox probe report that no backend works on this host."""
    import src.tools.sandbox as sandbox

    monkeypatch.setattr(sandbox, "_probe_backend", lambda backend, network: f"{backend} cannot run here (test)", raising=False)


def _run_node(root: Path, monkeypatch, *calls, tools=("bash",)):
    """Run a real node whose model issues the given tool calls; return its workspace and tool results."""
    answer = LLMResponse(content="Done; the outputs are in the workspace.", finish_reason="stop")
    monkeypatch.setattr(node, "ChatLLM", lambda **kw: _Script(*calls, answer))
    task = SwarmTask(id="t", agent_id="analyst", prompt_template="Compute.")
    TaskStore(root).save_task(task)
    result = node.run_node(
        SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="Compute.", tools=list(tools)),
        task, {}, {}, root, include_shell_tools=True, policy=ToolPolicy.from_config(get_env_config()),
    )
    assert result.status == "completed", result
    results = {
        item.get("tool_call_id"): json.loads(item.get("content"))
        for item in ThreadLog(node.node_thread(root, "analyst", "t")).read() if item.type == "tool_result"
    }
    return node.agent_artifact_dir(root, "analyst", "t").resolve(), results


def _wait_for(path: Path, seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return path.exists()


@requires_backend
def test_node_bash_writes_its_workspace_but_not_outside_it(tmp_path, monkeypatch, mode):
    mode(None)  # the default is auto
    root, outside = tmp_path / "run", tmp_path / "outside"
    outside.mkdir()
    workspace, results = _run_node(
        root, monkeypatch,
        _call("in", "bash", command="printf 'a,b\\n1,2\\n' > table.csv"),
        _call("out", "bash", command=f"cd {outside} && touch escaped.txt"),
        _call("abs", "bash", command=f"touch {outside / 'absolute.txt'}"),
    )
    assert (workspace / "table.csv").read_text() == "a,b\n1,2\n"
    # The produced-file receipt still names what the sandboxed command wrote.
    assert results["in"]["status"] == "ok" and [ref["path"] for ref in results["in"]["artifacts"]] == ["table.csv"]
    assert "sandbox" not in results["in"]
    assert results["out"]["status"] == "error" and results["abs"]["status"] == "error"
    assert list(outside.iterdir()) == []


@requires_backend
def test_node_background_run_is_held_to_its_workspace(tmp_path, monkeypatch, mode):
    mode("auto")
    root, outside = tmp_path / "run", tmp_path / "outside"
    outside.mkdir()
    workspace, results = _run_node(
        root, monkeypatch,
        _call("bg", "background_run", command=f"touch {outside / 'bg.txt'}; touch done.txt"),
        tools=("background_run",),
    )
    assert results["bg"]["status"] == "ok"
    assert _wait_for(workspace / "done.txt")
    assert list(outside.iterdir()) == []


def test_required_refuses_before_starting_when_no_backend_works(tmp_path, monkeypatch, mode, no_backend):
    mode("required")
    root = tmp_path / "run"
    workspace, results = _run_node(
        root, monkeypatch,
        _call("b", "bash", command="touch marker.txt"),
        _call("bg", "background_run", command="touch bg_marker.txt"),
        tools=("bash", "background_run"),
    )
    assert results["b"]["status"] == "error" and results["b"]["error_code"] == "sandbox_unavailable"
    assert results["bg"]["status"] == "error" and results["bg"]["error_code"] == "sandbox_unavailable"
    time.sleep(0.3)
    assert not (workspace / "marker.txt").exists() and not (workspace / "bg_marker.txt").exists()


def test_auto_without_a_backend_runs_in_the_workspace_and_says_so(tmp_path, monkeypatch, mode, no_backend, caplog):
    mode("auto")
    import src.tools.sandbox as sandbox

    monkeypatch.setattr(sandbox, "_WARNED_UNAVAILABLE", set(), raising=False)
    root = tmp_path / "run"
    with caplog.at_level(logging.WARNING, logger="src.tools.sandbox"):
        workspace, results = _run_node(
            root, monkeypatch,
            _call("p", "bash", command="pwd -P"),
            _call("w", "bash", command="echo x > made.txt"),
            _call("bg", "background_run", command="touch bg_done.txt"),
            tools=("bash", "background_run"),
        )
    assert results["p"]["stdout"].strip() == str(workspace)
    assert results["p"]["sandbox"] == "unavailable" and results["w"]["sandbox"] == "unavailable"
    assert results["bg"]["status"] == "ok" and results["bg"]["sandbox"] == "unavailable"
    assert (workspace / "made.txt").exists() and _wait_for(workspace / "bg_done.txt")
    warnings = [record for record in caplog.records if "unconfined" in record.getMessage()]
    assert len(warnings) == 1, [record.getMessage() for record in caplog.records]


def test_auto_never_confines_less_than_the_global_sandbox(tmp_path, monkeypatch, mode, no_backend):
    monkeypatch.setenv("VIBE_TRADING_SANDBOX_ENABLED", "1")
    mode("auto")
    workspace, results = _run_node(tmp_path / "run", monkeypatch, _call("b", "bash", command="touch marker.txt"))
    assert results["b"]["error_code"] == "sandbox_unavailable"
    assert not (workspace / "marker.txt").exists()


def test_off_keeps_todays_unconfined_node_shell(tmp_path, monkeypatch, mode):
    mode("off")
    root, outside = tmp_path / "run", tmp_path / "outside"
    outside.mkdir()
    workspace, results = _run_node(
        root, monkeypatch,
        _call("p", "bash", command="pwd -P"),
        _call("out", "bash", command=f"touch {outside / 'written.txt'}"),
    )
    assert results["p"]["stdout"].strip() == str(workspace)
    assert results["out"]["status"] == "ok" and "sandbox" not in results["out"]
    assert (outside / "written.txt").exists()


@pytest.mark.parametrize("value", ["required", "auto"])
def test_main_agent_bash_is_unchanged_by_the_swarm_setting(tmp_path, mode, no_backend, value):
    mode(value)
    outside = tmp_path / "outside"
    outside.mkdir()
    registry = build_registry(policy=ToolPolicy.from_config(get_env_config()), include_shell_tools=True)
    result = json.loads(registry.get("bash").execute(command=f"touch {outside / 'x.txt'}; pwd -P",
                                                     run_dir=str(tmp_path)))
    assert result["status"] == "ok" and "sandbox" not in result
    assert result["stdout"].strip() == str(tmp_path.resolve())
    assert (outside / "x.txt").exists()


def test_sandbox_runtime_root_is_the_runtime_root(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path / "home"))
    mode(None)
    sandbox = ToolPolicy.from_config(get_env_config()).sandbox
    assert sandbox.runtime_root == get_runtime_root() == tmp_path / "home"


@requires_backend
def test_main_sandbox_runs_in_a_run_dir_under_vibe_trading_home(tmp_path, monkeypatch, mode):
    home = (tmp_path / "home").resolve()
    run_dir = home / "runs" / "r1"
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("VIBE_TRADING_HOME", str(home))
    monkeypatch.setenv("VIBE_TRADING_SANDBOX_ENABLED", "1")
    mode(None)
    registry = build_registry(policy=ToolPolicy.from_config(get_env_config()), include_shell_tools=True)
    result = json.loads(registry.get("bash").execute(command="pwd -P; touch made.txt", run_dir=str(run_dir)))
    assert result["status"] == "ok", result
    assert result["stdout"].strip() == str(run_dir)
    assert (run_dir / "made.txt").exists()


@requires_backend
def test_sandboxed_shell_can_use_dev_null_and_a_temporary_file(tmp_path, monkeypatch, mode):
    mode(None)
    workspace, results = _run_node(
        tmp_path / "run", monkeypatch,
        _call("t", "bash", command="echo hidden > /dev/null && python3 -c 'import tempfile; tempfile.TemporaryFile().close(); print(\"ok\")'"),
    )
    assert results["t"]["status"] == "ok", results["t"]
    assert results["t"]["stdout"].strip() == "ok"


@requires_backend
def test_the_enabled_main_sandbox_profile_allows_dev_null_and_tmp(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("VIBE_TRADING_SANDBOX_ENABLED", "1")
    mode(None)
    registry = build_registry(policy=ToolPolicy.from_config(get_env_config()), include_shell_tools=True)
    result = json.loads(registry.get("bash").execute(
        command="echo hidden > /dev/null && python3 -c 'import tempfile; tempfile.TemporaryFile().close(); print(\"ok\")'",
        run_dir=str(get_runtime_root() / "runs" / "r1")))
    assert result["status"] == "ok", result
    assert result["stdout"].strip() == "ok"


def test_env_example_documents_the_swarm_shell_sandbox():
    assert get_env_config().api.vibe_trading_swarm_shell_sandbox == "auto"
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(encoding="utf-8")
    assert "# VIBE_TRADING_SWARM_SHELL_SANDBOX=auto" in example
