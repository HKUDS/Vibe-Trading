"""Files an upstream node produced reach its consumers through the evidence handoff."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.config.accessor import get_env_config, reset_env_config
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.product.tool_policy import ToolPolicy
from src.swarm.evidence_handoff import prepare_handoff, selected_inputs
from src.swarm.models import SwarmAgentSpec, SwarmTask
from src.swarm.task_store import TaskStore
from src.tools.bash_tool import BashTool
from src.tools.read_file_tool import ReadFileTool
from src.tools.sandbox import SandboxSettings
import src.swarm.node as node
import src.product.tool_execution as execution


class _Script:
    def __init__(self, *responses):
        self.responses = iter(responses)

    def stream_chat(self, messages, **kwargs):
        response = next(self.responses)
        return response() if callable(response) else response

    def close(self):
        pass


def _call(call_id, name, **arguments):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(call_id, name, arguments)],
                       finish_reason="tool_calls")


def _policy():
    return ToolPolicy.from_config(get_env_config())


def _produce(root: Path, monkeypatch, *calls, agent="analyst", task="p", tools=("write_file", "edit_file", "bash")):
    """Run a real producer node whose model issues the given tool calls, then answers."""
    answer = LLMResponse(content="Analysis delivered; outputs are in the workspace files.", finish_reason="stop")
    monkeypatch.setattr(node, "ChatLLM", lambda **kw: _Script(*calls, answer))
    producer = SwarmTask(id=task, agent_id=agent, prompt_template="Compute the statistics.")
    TaskStore(root).save_task(producer)
    result = node.run_node(
        SwarmAgentSpec(id=agent, role="Analyst", system_prompt="Compute.", tools=list(tools)),
        producer, {}, {}, root, include_shell_tools=True, policy=_policy(),
    )
    assert result.status == "completed", result
    return node.agent_artifact_dir(root, agent, task)


def _consume(root: Path, sources: dict[str, str]):
    consumer = SwarmTask(id="c", agent_id="editor", prompt_template="Edit", input_from=sources,
                         depends_on=sorted(set(sources.values())))
    TaskStore(root).save_task(consumer)
    destination = node.agent_artifact_dir(root, "editor", "c")
    destination.mkdir(parents=True, exist_ok=True)
    note = prepare_handoff(root, consumer, destination)
    index = json.loads((destination / "upstream" / "index.json").read_text())
    return destination, note, index


def _sandbox(tmp_path):
    return SandboxSettings(enabled=False, runtime_root=tmp_path)


@pytest.mark.parametrize("prompt", ["Create stats.json and compute.py; read source.csv.", "Save the result as a JSON file."])
def test_shell_receipt_records_changed_files_whatever_the_task_wording(tmp_path, prompt):
    (tmp_path / "req.json").write_text(json.dumps({"prompt": prompt}))
    (tmp_path / "source.csv").write_text("x\n2\n5\n")
    (tmp_path / "tool-results").mkdir()
    tool = BashTool(_sandbox(tmp_path))
    result = json.loads(tool.execute(
        command="printf '{\"sum\":7}' > stats.json; printf 'result=2+5' > compute.py; "
                "echo x > tool-results/r.json; echo x > state.json",
        run_dir=str(tmp_path)))
    assert result["status"] == "ok"
    # Existing inputs and runtime state are not outputs of this command.
    assert {ref["path"] for ref in result["artifacts"]} == {"stats.json", "compute.py"}
    assert {ref["path"]: ref["bytes"] for ref in result["artifacts"]}["stats.json"] == 9
    again = json.loads(tool.execute(command="cat stats.json", run_dir=str(tmp_path)))
    assert again["artifacts"] == []  # A read is not another producer.
    (tmp_path.parent / "outside.json").write_text("{}")
    (tmp_path / "outside.json").symlink_to(tmp_path.parent / "outside.json")
    assert json.loads(tool.execute(command="echo x > outside.json", run_dir=str(tmp_path)))["artifacts"] == []


def test_shell_receipt_does_not_walk_a_directory_that_is_not_a_run_workspace(tmp_path):
    result = json.loads(BashTool(_sandbox(tmp_path)).execute(command="echo x > made.txt", run_dir=str(tmp_path)))
    assert result["status"] == "ok" and "artifacts" not in result


def test_written_and_shell_produced_files_are_copied_by_hash_and_indexed(tmp_path, monkeypatch):
    source = _produce(
        tmp_path, monkeypatch,
        _call("w1", "write_file", path="notes/calc.md", content="sum = 2 + 5 = 7"),
        _call("e1", "edit_file", path="notes/calc.md", old_text="= 7", new_text="= 7 (checked)"),
        _call("b1", "bash", command="printf 'a,b\\n1,2\\n' > table.csv"),
        _call("b2", "bash", command="printf 'partial' > failed.csv; exit 3"),
    )
    destination, note, index = _consume(tmp_path, {"stats": "p"})
    files = {entry["original_path"]: entry for entry in index["files"]}
    assert set(files) == {"notes/calc.md", "table.csv"}, index
    for original, entry in files.items():
        data = (source / original).read_bytes()
        copy = destination / entry["path"]
        assert entry["path"].startswith("upstream/files/")
        assert copy.read_bytes() == data
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        assert entry["size"] == len(data)
        assert entry["source_task"] == "p"
    assert files["notes/calc.md"]["tool"] == "edit_file"
    assert files["table.csv"]["tool"] == "bash"
    assert "upstream/index.json" in note and "2 files" in note
    assert not any("failed.csv" in json.dumps(entry) for entry in index["files"])


def test_symlinks_and_paths_outside_the_producer_workspace_are_never_copied(tmp_path, monkeypatch):
    secret = tmp_path / "secret.txt"
    secret.write_text("outside the workspace")
    _produce(
        tmp_path, monkeypatch,
        _call("b1", "bash", command=f"ln -s {secret} leak.txt; printf ok > kept.txt"),
    )
    thread = node.node_thread(tmp_path, "analyst", "p")
    forged = {"type": "tool_result", "seq": 10_000, "turn_id": "forged", "tool_call_id": "w9",
              "name": "write_file", "status": "ok",
              "content": json.dumps({"status": "ok", "path": str(secret)})}
    with thread.open("a") as log:
        log.write(json.dumps({"type": "assistant", "seq": 9_999, "turn_id": "forged",
                              "tool_calls": [{"id": "w9", "type": "function",
                                              "function": {"name": "write_file", "arguments": "{}"}}]}) + "\n")
        log.write(json.dumps(forged) + "\n")
    destination, _, index = _consume(tmp_path, {"stats": "p"})
    assert [entry["original_path"] for entry in index["files"]] == ["kept.txt"]
    copied = [path for path in (destination / "upstream" / "files").rglob("*") if path.is_file()]
    assert all(path.read_text() != "outside the workspace" for path in copied)


def test_copy_budget_is_configurable_and_skipped_files_are_reported(tmp_path, monkeypatch):
    _produce(
        tmp_path, monkeypatch,
        _call("w1", "write_file", path="small.txt", content="x" * 10),
        _call("w2", "write_file", path="large.txt", content="y" * 100),
    )
    monkeypatch.setenv("SWARM_HANDOFF_MAX_FILE_BYTES", "50")
    reset_env_config()
    _, note, index = _consume(tmp_path, {"stats": "p"})
    assert [entry["original_path"] for entry in index["files"]] == ["small.txt"]
    assert any("large.txt" in reason and "50" in reason for reason in index["unavailable"])
    assert "1 files" in note


def test_text_outputs_are_redacted_like_observations(tmp_path, monkeypatch):
    _produce(
        tmp_path, monkeypatch,
        _call("w1", "write_file", path="headers.txt",
              content="Authorization: Bearer sk-live-0123456789abcdefghijklmnop\nclose=101.5\n"),
    )
    destination, _, index = _consume(tmp_path, {"stats": "p"})
    [entry] = index["files"]
    copied = (destination / entry["path"]).read_text()
    assert "sk-live-0123456789abcdefghijklmnop" not in copied
    assert "close=101.5" in copied
    assert entry["redacted"] is True
    assert entry["sha256"] == hashlib.sha256(copied.encode()).hexdigest()


def test_rehomed_run_resolves_files_in_its_own_workspace(tmp_path, monkeypatch):
    original = tmp_path / "first"
    _produce(original, monkeypatch, _call("w1", "write_file", path="calc.md", content="sum=7"))
    moved = tmp_path / "second"
    shutil.copytree(original, moved)
    shutil.rmtree(original)
    destination, _, index = _consume(moved, {"stats": "p"})
    [entry] = index["files"]
    assert entry["original_path"] == "calc.md"
    assert (destination / entry["path"]).read_text() == "sum=7"


def test_consumer_node_is_told_where_the_files_are(tmp_path, monkeypatch):
    _produce(tmp_path, monkeypatch, _call("w1", "write_file", path="calc.md", content="sum=7"))
    consumer = SwarmTask(id="c", agent_id="editor", prompt_template="Edit", input_from={"stats": "p"},
                         depends_on=["p"])
    TaskStore(tmp_path).save_task(consumer)
    seen = []

    class Reader(_Script):
        def stream_chat(self, messages, **kwargs):
            seen.append(messages)
            return super().stream_chat(messages, **kwargs)

    monkeypatch.setattr(node, "ChatLLM", lambda **kw: Reader(LLMResponse(content="Edited.", finish_reason="stop")))
    node.run_node(SwarmAgentSpec(id="editor", role="Editor", system_prompt="Edit."), consumer,
                  {"stats": "Upstream summary."}, {}, tmp_path, policy=_policy())
    data = seen[0][1]["content"]
    assert "1 files" in data and "upstream/index.json" in data


def test_observation_saved_under_a_nested_run_dir_reaches_the_consumer(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    original = tmp_path / "first"
    source = _produce(
        original, monkeypatch,
        _call("b1", "bash", command="mkdir -p data"),
        _call("q1", "quantlib_call", action="call", module="risk", function="historical_var",
              kwargs={"returns": [-.03, .01, -.01, .02, -.02], "confidence": .95}, run_dir="data"),
        tools=("bash", "quantlib_call"),
    )
    assert list((source / "data" / "tool-results").glob("*/result.json"))
    # A resumed run is a copy; its receipts still name the first run's workspace.
    moved = tmp_path / "second"
    shutil.copytree(original, moved)
    shutil.rmtree(original)
    destination, _, index = _consume(moved, {"risk": "p"})
    assert not any("q1" in reason for reason in index["unavailable"]), index["unavailable"]
    [entry] = [entry for entry in index["observations"] if entry["call_id"] == "q1"]
    assert json.loads((destination / entry["path"]).read_text())["result"] == pytest.approx(.03)


def test_shell_calculation_command_and_output_reach_the_consumer_redacted(tmp_path, monkeypatch):
    secret = "sk-live-0123456789abcdefghijklmnop"
    command = f'TOKEN="Bearer {secret}" python3 -c "print(sum([2, 8]) / sum([10, 100]))"'
    _produce(
        tmp_path, monkeypatch,
        _call("b1", "bash", command=command),
        _call("b2", "bash", command="python3 -c 'print(1/0)'"),
    )
    destination, note, index = _consume(tmp_path, {"risk": "p"})
    [entry] = [entry for entry in index["observations"] if entry["tool"] == "bash"]
    assert entry["call_id"] == "b1"
    assert "sum([2, 8]) / sum([10, 100])" in entry["request"]["command"]
    assert json.loads((destination / entry["path"]).read_text())["stdout"] == "0.09090909090909091\n"
    assert "bash" in note
    upstream = [path.read_text() for path in (destination / "upstream").rglob("*") if path.is_file()]
    assert upstream and not any(secret in text for text in upstream)


@pytest.mark.parametrize("select", [False, True], ids=["report", "selection"])
def test_failed_tool_call_is_visible_without_becoming_evidence(tmp_path, monkeypatch, select):
    """Carry redacted diagnostics through reports and selections without supplying failed data.

    Args:
        tmp_path: Isolated workspaces for the producer and its consumers.
        monkeypatch: Fixture for the scripted provider.
        select: Whether the direct consumer uses a selected binding.
    """
    secret = "sk-live-0123456789abcdefghijklmnop"
    _produce(
        tmp_path, monkeypatch,
        _call("good", "bash", command="echo 42"),
        _call("failed", "bash", command=f"echo 'lookup failed; Bearer {secret}' >&2; exit 3"),
    )
    binding = {"task": "p", "kinds": ["calculation"]} if select else "p"
    consumer = SwarmTask(id="c", agent_id="editor", prompt_template="Edit", depends_on=["p"],
                         input_from={"stats": binding})
    TaskStore(tmp_path).save_task(consumer)
    destination = node.agent_artifact_dir(tmp_path, "editor", "c")
    destination.mkdir(parents=True)
    note = prepare_handoff(tmp_path, consumer, destination)
    index = json.loads((destination / "upstream/index.json").read_text())
    assert [entry["call_id"] for entry in index["observations"]] == ["good"]
    if select:
        assert len(selected_inputs(destination)["inputs"]["stats"]) == 1

    path = "upstream/failed-calls.json"
    assert path in note and "lookup failed" in note and secret not in note
    [failure] = json.loads((destination / path).read_text())
    assert failure["source_task"] == "p" and failure["call_id"] == "failed"
    assert failure["status"] == "failed" and failure["tool"] == "bash"
    assert "lookup failed" in failure["error"] and secret not in failure["error"]

    reader = SwarmTask(id="r", agent_id="reader", prompt_template="Read", depends_on=["c"],
                       input_from={"stats": "c"})
    downstream = node.agent_artifact_dir(tmp_path, "reader", "r")
    assert path in prepare_handoff(tmp_path, reader, downstream)
    assert json.loads((downstream / path).read_text()) == [failure]


def test_files_written_by_other_tools_reach_the_consumer(tmp_path, monkeypatch):
    workspace = node.agent_artifact_dir(tmp_path, "analyst", "p")
    rng = np.random.default_rng(0)
    dates = pd.date_range("2026-01-01", periods=30)
    columns = [f"S{i}" for i in range(8)]
    factor, returns = (pd.DataFrame(rng.normal(size=(30, 8)) * scale, index=dates, columns=columns).to_csv()
                       for scale in (1, .01))
    _produce(
        tmp_path, monkeypatch,
        _call("w1", "write_file", path="f.csv", content=factor),
        _call("w2", "write_file", path="r.csv", content=returns),
        _call("fa", "factor_analysis", factor_csv=str(workspace / "f.csv"), return_csv=str(workspace / "r.csv"),
              output_dir=str(workspace / "factor")),
        tools=("write_file", "factor_analysis"),
    )
    written = {"factor/ic_series.csv", "factor/ic_summary.json", "factor/group_equity.csv"}
    assert written <= {str(path.relative_to(workspace)) for path in workspace.rglob("*")}
    destination, _, index = _consume(tmp_path, {"factors": "p"})
    files = {entry["original_path"]: entry for entry in index["files"]}
    assert written | {"f.csv", "r.csv"} == set(files), index
    assert (files["f.csv"]["tool"], files["f.csv"]["call_id"]) == ("write_file", "w1")
    for original in written:
        assert (destination / files[original]["path"]).read_bytes() == (workspace / original).read_bytes()


def test_failed_factor_tool_outputs_are_not_handed_downstream(tmp_path, monkeypatch) -> None:
    """Send valid inputs and record gaps for the failed factor output.

    Args:
        tmp_path: Isolated swarm run.
        monkeypatch: Scripted provider fixture.
    """
    factor = ",A,B,C,D,E\n2026-01-01,1,2,3,4,5\n"
    returns = ",A,B,C,D,E\n2026-01-01,.01,.02,.03,.04,.05\n"
    source = _produce(
        tmp_path, monkeypatch,
        _call("w1", "write_file", path="f.csv", content=factor),
        _call("w2", "write_file", path="r.csv", content=returns),
        _call("fa", "factor_analysis", factor_csv="f.csv", return_csv="r.csv",
              output_dir="factor", n_groups=6),
        tools=("write_file", "factor_analysis"),
    )
    assert {path.name for path in (source / "factor").iterdir()} == {"ic_series.csv", "ic_summary.json"}
    destination, _, index = _consume(tmp_path, {"factors": "p"})
    failures = json.loads((destination / "upstream/failed-calls.json").read_text())
    assert [(failure["call_id"], failure["tool"]) for failure in failures] == [("fa", "factor_analysis")]
    assert {entry["original_path"] for entry in index["files"]} == {"f.csv", "r.csv"}, index["files"]
    for path in ("factor/ic_series.csv", "factor/ic_summary.json"):
        assert any(path in gap and "fa" in gap and "failed" in gap for gap in index["unavailable"])


@pytest.mark.parametrize("exit_code", [3, 0, None], ids=["failed", "successful", "running"])
def test_background_output_overlapping_successful_bash(tmp_path, monkeypatch, exit_code) -> None:
    """Require a successful exit from a background task that overlapped a successful bash.

    Args:
        tmp_path: Isolated swarm run.
        monkeypatch: Scripted provider fixture.
        exit_code: Child exit code, or None to keep it running through node completion.
    """
    workspace = node.agent_artifact_dir(tmp_path, "analyst", "p")
    managers = []
    build_registry = node.build_swarm_registry

    def remember_registry(*args, **kwargs):
        registry = build_registry(*args, **kwargs)
        managers.append(registry.get("background_run").background)
        return registry

    def wait_for_outcome(expected):
        manager = managers[0]
        [summary] = manager.check().splitlines()
        task_id = summary.split(":", 1)[0]
        deadline = time.monotonic() + 4
        while True:
            task = json.loads(manager.check(task_id))
            if task["status"] == expected or time.monotonic() >= deadline:
                break
            time.sleep(.02)
        assert task["status"] == expected, task

    def finish():
        wait_for_outcome({3: "error", 0: "completed", None: "running"}[exit_code])
        return LLMResponse(content="Done.", finish_reason="stop")

    monkeypatch.setattr(node, "build_swarm_registry", remember_registry)
    wait_go = 'i=0; while [ ! -f .go ] && [ "$i" -lt 200 ]; do sleep .02; i=$((i+1)); done; '
    wait_done = 'i=0; while [ ! -f .done ] && [ "$i" -lt 200 ]; do sleep .02; i=$((i+1)); done; '
    wait_release = 'i=0; while [ ! -f .release ] && [ "$i" -lt 200 ]; do sleep .02; i=$((i+1)); done; '
    outcome = f"exit {exit_code}" if exit_code is not None else wait_release + "exit 0"
    try:
        _produce(
            tmp_path, monkeypatch,
            _call("bg", "background_run", command=wait_go +
                  "test -f .go || exit 4; printf partial > partial.csv; touch .done; " + outcome),
            _call("fg", "bash", command="touch .go; " + wait_done + "test -f .done"),
            finish,
            tools=("background_run", "bash"),
        )
        assert (workspace / "partial.csv").read_text() == "partial"
        results = {item.get("tool_call_id"): item for item in node.ThreadLog(
            node.node_thread(tmp_path, "analyst", "p")).read() if item.type == "tool_result"}
        assert results["fg"].get("status") == "ok"
        _, _, index = _consume(tmp_path, {"producer": "p"})
        paths = [entry["original_path"] for entry in index["files"]]
        if exit_code == 0:
            assert paths == ["partial.csv"], index
        else:
            assert paths == [], index["files"]
            task_id = json.loads(results["bg"].get("content"))["task_id"]
            reason = "failed" if exit_code == 3 else "running"
            assert any("partial.csv" in gap and "bg" in gap and task_id in gap and reason in gap
                       for gap in index["unavailable"]), index
    finally:
        if exit_code is None and managers:
            (workspace / ".release").touch()
            wait_for_outcome("completed")


def test_any_failed_writer_blocks_a_file_even_after_successful_overwrite(tmp_path, monkeypatch) -> None:
    """Keep a failed writer in the file's history across a later rewrite.

    Args:
        tmp_path: Isolated swarm run.
        monkeypatch: Scripted provider fixture.
    """
    _produce(
        tmp_path, monkeypatch,
        _call("fail", "bash", command="printf partial > replaced.txt; exit 3"),
        _call("ok", "write_file", path="replaced.txt", content="replacement"),
        _call("only-ok", "write_file", path="clean.txt", content="clean"),
    )
    _, _, index = _consume(tmp_path, {"producer": "p"})
    assert [entry["original_path"] for entry in index["files"]] == ["clean.txt"], index["files"]
    assert any("replaced.txt" in gap and "bash" in gap and "fail" in gap for gap in index["unavailable"])


def test_unattributed_files_are_gaps_but_runtime_files_stay_private(tmp_path, monkeypatch) -> None:
    """Report preexisting visible files as gaps and omit excluded paths.

    Args:
        tmp_path: Isolated swarm run.
        monkeypatch: Scripted provider fixture.
    """
    workspace = node.agent_artifact_dir(tmp_path, "analyst", "p")
    workspace.mkdir(parents=True)
    (workspace / "old.txt").write_text("Already present")
    _produce(tmp_path, monkeypatch,
             _call("b", "bash", command="touch .hidden; mkdir -p tool-results; touch tool-results/private.json"))
    _, _, index = _consume(tmp_path, {"producer": "p"})
    assert index["files"] == [], index["files"]
    assert any("old.txt" in gap and "no candidate" in gap for gap in index["unavailable"])
    assert not any(".hidden" in gap or "tool-results" in gap for gap in index["unavailable"])


def test_legacy_run_without_workspace_receipt_keeps_original_handoff(tmp_path, monkeypatch) -> None:
    """Keep legacy explicit writes and receiptless outputs available for handoff.

    Args:
        tmp_path: Isolated swarm run.
        monkeypatch: Scripted provider fixture.
    """
    source = _produce(tmp_path, monkeypatch, _call("write", "write_file", path="explicit.txt", content="old"))
    thread = node.node_thread(tmp_path, "analyst", "p")
    thread.with_name("workspace-writes.json").unlink(missing_ok=True)
    (source / "receiptless.txt").write_text("Older export")
    _, _, index = _consume(tmp_path, {"producer": "p"})
    assert {entry["original_path"]: entry["call_id"] for entry in index["files"]} == {
        "explicit.txt": "write", "receiptless.txt": None,
    }


def test_swarm_read_only_batch_dispatch_is_serial(tmp_path, monkeypatch) -> None:
    """Pin serial dispatch even when all calls in the same batch declare read-only.

    Args:
        tmp_path: Isolated swarm run.
        monkeypatch: Scripted provider fixture.
    """
    observed = []
    execute_batch = execution.execute_batch
    execute_read = ReadFileTool.execute
    active = threading.Lock()
    entered = []

    def capture(calls, cancelled):
        observed.append([call.parallel for call in calls])
        return execute_batch(calls, cancelled)

    def observe_read(tool, **arguments):
        acquired = active.acquire(blocking=False)
        entered.append((arguments["path"], acquired))
        try:
            # Leave a window in which a concurrently dispatched call can enter.
            time.sleep(.05)
            return execute_read(tool, **arguments)
        finally:
            if acquired:
                active.release()

    monkeypatch.setattr(execution, "execute_batch", capture)
    monkeypatch.setattr(ReadFileTool, "execute", observe_read)
    _produce(
        tmp_path, monkeypatch,
        LLMResponse(content=None, finish_reason="tool_calls", tool_calls=[
            ToolCallRequest("first", "read_file", {"path": "req.json"}),
            ToolCallRequest("second", "read_file", {"path": "state.json"}),
        ]),
        tools=("read_file",),
    )
    assert observed == [[False, False]], observed
    assert entered == [("req.json", True), ("state.json", True)], entered
