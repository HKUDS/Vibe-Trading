"""A tool's ``output_dir`` stays inside the run directory and the write roots.

``factor_analysis`` and ``alpha_bench`` used to write wherever ``output_dir``
pointed: a relative path landed in the server process's working directory and
an absolute one anywhere, also from a swarm node or a spawned child whose file
writes are confined to its workspace.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import mcp_server
import src.swarm.node as node
from src.config.accessor import get_env_config
from src.config.paths import get_runtime_root
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.product.tool_policy import ToolPolicy
from src.session.thread import ThreadLog
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.swarm.task_store import TaskStore
from src.tools import alpha_bench_tool as alpha_bench_module
from src.tools import build_registry
from src.tools.spawn_agent_tool import child_registry

_FACTOR_FILES = {"ic_series.csv", "ic_summary.json", "group_equity.csv"}
_MCP_FACTOR_ANALYSIS = getattr(mcp_server.factor_analysis, "fn", None) or getattr(
    mcp_server.factor_analysis, "__wrapped__", mcp_server.factor_analysis
)


@pytest.fixture
def places(tmp_path, monkeypatch):
    """A run directory inside the run roots, a separate cwd, and a directory outside every root."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))  # a runtime root and report root of this test's own
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path / "runs"))
    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    outside = tmp_path / "outside"
    outside.mkdir()
    return SimpleNamespace(run_dir=run_dir.resolve(), cwd=cwd, outside=outside)


def _registry():
    return build_registry(policy=ToolPolicy.from_config(get_env_config()))


def _csvs(directory: Path) -> tuple[str, str]:
    rng = np.random.default_rng(0)
    dates = pd.date_range("2026-01-01", periods=30)
    columns = [f"S{i}" for i in range(8)]
    paths = []
    for name, scale in (("f.csv", 1), ("r.csv", 0.01)):
        path = directory / name
        pd.DataFrame(rng.normal(size=(30, 8)) * scale, index=dates, columns=columns).to_csv(path)
        paths.append(str(path))
    return paths[0], paths[1]


@pytest.fixture
def stub_bench(monkeypatch):
    """Make alpha_bench run offline on one fake alpha."""
    monkeypatch.setattr(
        "src.factors.registry.get_default_registry",
        lambda: SimpleNamespace(get=lambda alpha_id: SimpleNamespace(meta=None)),
    )
    monkeypatch.setattr(alpha_bench_module, "_select_alpha_ids", lambda registry, alpha_id, zoo: ["alpha101_001"])
    monkeypatch.setattr(alpha_bench_module, "_split_alphas_by_universe_support", lambda registry, ids, universe: (ids, []))
    monkeypatch.setattr(alpha_bench_module, "_validate_bench_data_requirements", lambda *args: None)
    monkeypatch.setattr(alpha_bench_module, "_load_universe_panel", lambda *args, **kwargs: {})
    monkeypatch.setattr(alpha_bench_module, "_prepare_bench_panel", lambda registry, ids, panel, *args: panel)
    monkeypatch.setattr(alpha_bench_module, "_compute_forward_returns", lambda panel, horizon=1: {})
    monkeypatch.setattr(alpha_bench_module, "build_availability_contract", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        alpha_bench_module,
        "_bench_one_alpha",
        lambda *args, **kwargs: {
            "id": "alpha101_001", "zoo": "alpha101", "theme": [], "formula_latex": "1",
            "ic_mean": 0.1, "ic_std": 0.2, "ir": 0.5, "ic_positive_ratio": 0.5, "ic_count": 1,
        },
    )


def _bench_args(**extra):
    return {"universe": "sp500", "period": "2020-2021", "alpha_id": "alpha101_001", **extra}


def _reports(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.rglob("alpha_bench_*.html"))


def test_factor_analysis_relative_output_dir_lands_in_the_run_dir(places):
    factor, returns = _csvs(places.run_dir)
    result = json.loads(_registry().get("factor_analysis").execute(
        factor_csv=factor, return_csv=returns, output_dir="factor", run_dir=str(places.run_dir),
    ))
    assert result["status"] == "ok", result
    assert {path.name for path in (places.run_dir / "factor").iterdir()} == _FACTOR_FILES
    assert list(places.cwd.iterdir()) == []


@pytest.mark.parametrize("spelling", ["absolute", "climbing"])
def test_factor_analysis_refuses_an_output_dir_outside_the_write_roots(places, spelling):
    factor, returns = _csvs(places.run_dir)
    target = places.outside / "factor"
    output_dir = str(target) if spelling == "absolute" else os.path.relpath(target, places.run_dir)
    result = json.loads(_registry().get("factor_analysis").execute(
        factor_csv=factor, return_csv=returns, output_dir=output_dir, run_dir=str(places.run_dir),
    ))
    assert result["status"] == "error" and result["error_code"] == "outside_write_roots", result
    assert "Allowed roots" in result["error"] and str(places.run_dir) in result["error"]
    assert not target.exists()


def test_factor_analysis_output_dir_in_a_write_root_is_accepted(places):
    factor, returns = _csvs(places.run_dir)
    target = get_runtime_root() / "runs" / "factor-out"
    result = json.loads(_registry().get("factor_analysis").execute(
        factor_csv=factor, return_csv=returns, output_dir=str(target), run_dir=str(places.run_dir),
    ))
    assert result["status"] == "ok", result
    assert {path.name for path in target.iterdir()} == _FACTOR_FILES


def test_mcp_factor_analysis_refuses_an_output_dir_outside_the_write_roots(places, monkeypatch):
    monkeypatch.setattr(mcp_server, "_get_registry", _registry)
    factor, returns = _csvs(places.run_dir)
    for output_dir in ("factor", str(places.outside / "factor")):
        result = json.loads(_MCP_FACTOR_ANALYSIS(factor_csv=factor, return_csv=returns, output_dir=output_dir))
        assert result["status"] == "error" and result["error_code"] == "outside_write_roots", result
    assert list(places.cwd.iterdir()) == [] and list(places.outside.iterdir()) == []


def test_alpha_bench_relative_output_dir_lands_in_the_run_dir(places, stub_bench):
    result = json.loads(_registry().get("alpha_bench").execute(
        **_bench_args(output_dir="bench", run_dir=str(places.run_dir)),
    ))
    assert result["status"] == "ok", result
    assert len(_reports(places.run_dir / "bench")) == 1
    assert list(places.cwd.iterdir()) == []


@pytest.mark.parametrize("spelling", ["absolute", "climbing"])
def test_alpha_bench_refuses_an_output_dir_outside_the_write_roots(places, stub_bench, spelling):
    target = places.outside / "bench"
    output_dir = str(target) if spelling == "absolute" else os.path.relpath(target, places.run_dir)
    result = json.loads(_registry().get("alpha_bench").execute(
        **_bench_args(output_dir=output_dir, run_dir=str(places.run_dir)),
    ))
    assert result["status"] == "error" and result["error_code"] == "outside_write_roots", result
    assert "Allowed roots" in result["error"] and str(places.run_dir) in result["error"]
    assert not target.exists()


def test_alpha_bench_default_and_report_root_still_work(places, stub_bench):
    tool = _registry().get("alpha_bench")
    default = alpha_bench_module._default_output_dir()
    assert json.loads(tool.execute(**_bench_args(run_dir=str(places.run_dir))))["status"] == "ok"
    assert len(_reports(default)) == 1
    named = default / "named"
    result = json.loads(tool.execute(**_bench_args(output_dir=str(named), run_dir=str(places.run_dir))))
    assert result["status"] == "ok", result
    assert len(_reports(named)) == 1


def test_spawned_child_output_dir_stays_in_its_workspace(places, stub_bench, tmp_path):
    workspace = places.run_dir / "child"
    workspace.mkdir()
    child = child_registry(_registry(), workspace)
    factor, returns = _csvs(workspace)
    for output_dir in (str(places.outside / "factor"), os.path.relpath(places.outside / "factor", workspace)):
        result = json.loads(child.get("factor_analysis").execute(
            factor_csv=factor, return_csv=returns, output_dir=output_dir, run_dir=str(workspace),
        ))
        assert result["error_code"] == "outside_write_roots", result
    # The parent's report root is not this child's to write.
    result = json.loads(child.get("alpha_bench").execute(
        **_bench_args(output_dir=str(alpha_bench_module._default_output_dir()), run_dir=str(workspace)),
    ))
    assert result["error_code"] == "outside_write_roots", result
    assert json.loads(child.get("alpha_bench").execute(**_bench_args(run_dir=str(workspace))))["status"] == "ok"
    assert len(_reports(workspace)) == 1
    assert _reports(alpha_bench_module._default_output_dir()) == []
    assert list(places.outside.iterdir()) == []


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


def test_swarm_node_output_dir_stays_in_its_workspace(tmp_path, monkeypatch):
    root = tmp_path / "run"
    outside = tmp_path / "outside"
    outside.mkdir()
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    workspace = node.agent_artifact_dir(root, "analyst", "t")
    workspace.mkdir(parents=True)
    factor, returns = _csvs(workspace)
    answer = LLMResponse(content="Done; the outputs are in the workspace.", finish_reason="stop")
    monkeypatch.setattr(node, "ChatLLM", lambda **kw: _Script(
        _call("in", "factor_analysis", factor_csv=factor, return_csv=returns, output_dir="factor"),
        _call("abs", "factor_analysis", factor_csv=factor, return_csv=returns, output_dir=str(outside / "a")),
        _call("up", "factor_analysis", factor_csv=factor, return_csv=returns, output_dir=os.path.relpath(outside / "b", workspace)),
        answer,
    ))
    task = SwarmTask(id="t", agent_id="analyst", prompt_template="Compute.")
    TaskStore(root).save_task(task)
    result = node.run_node(
        SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="Compute.", tools=["factor_analysis"]),
        task, {}, {}, root, include_shell_tools=False, policy=ToolPolicy.from_config(get_env_config()),
    )
    assert result.status == "completed", result
    results = {
        item.get("tool_call_id"): json.loads(item.get("content"))
        for item in ThreadLog(node.node_thread(root, "analyst", "t")).read() if item.type == "tool_result"
    }
    assert results["in"]["status"] == "ok", results["in"]
    assert {path.name for path in (workspace.resolve() / "factor").iterdir()} == _FACTOR_FILES
    for call_id in ("abs", "up"):
        assert results[call_id]["error_code"] == "outside_write_roots", results[call_id]
    assert list(outside.iterdir()) == [] and list(cwd.iterdir()) == []
