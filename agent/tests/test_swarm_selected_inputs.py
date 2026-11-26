"""Task tool narrowing, selected evidence inputs and the research preset, on the node runtime.

Ported from claude/agent-runtime-simplify (test_swarm_task_inputs.py, test_swarm_selected_files.py,
51de3f537 and earlier). Producers here are real child turns driven by a scripted model, so the
handoff reads the same thread records and workspaces a live run leaves.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.agent.tools import BaseTool
from src.config.accessor import get_env_config
from src.kernel.contracts import LLMResponse, ToolCallRequest
from src.product.tool_policy import ToolPolicy
from src.swarm import presets
from src.swarm.evidence_handoff import prepare_handoff, selected_inputs
from src.swarm.models import SwarmAgentSpec, SwarmTask, TaskStatus
from src.swarm.presets import build_run_from_preset, inspect_preset
from src.swarm.runtime import _task_definition_changed
from src.swarm.serialization import serialize_task
from src.swarm.task_store import TaskStore, validate_dag
from src.tools.path_utils import FileRoots
from src.tools.read_file_tool import ReadFileTool
import src.swarm.node as node

PROSE = "Correlation proves operator negligence."


class _Records(BaseTool):
    """Offline source tool; the required constructor argument keeps it out of registry discovery."""

    name = "fetch_records"
    description = "Offline observation."
    parameters = {"type": "object", "properties": {"station": {"type": "string"}}}

    def __init__(self, calls):
        self.calls = calls

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return json.dumps({"status": "ok", "readings": [11, 17, 23, 25],
                           "coverage": {"calendar_checked": False}, "source": "instrument log"})


class _Script:
    def __init__(self, *responses, seen=None):
        self.responses = iter(responses)
        self.seen = seen

    def stream_chat(self, messages, **kwargs):
        if self.seen is not None:
            self.seen.append({"messages": json.dumps(messages), "tools": json.dumps(kwargs.get("tools"))})
        return next(self.responses)

    def close(self):
        pass


def _call(call_id, name, **arguments):
    return LLMResponse(content=None, tool_calls=[ToolCallRequest(call_id, name, arguments)],
                       finish_reason="tool_calls")


def _answer(text):
    return LLMResponse(content=text, finish_reason="stop")


def _policy():
    return ToolPolicy.from_config(get_env_config())


@pytest.fixture(autouse=True)
def _workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    calls = []
    original = node.build_swarm_registry

    def registry(names, **kwargs):
        built = original([name for name in names if name != "fetch_records"], **kwargs)
        if "fetch_records" in names:
            built.register(_Records(calls))
        return built

    monkeypatch.setattr(node, "build_swarm_registry", registry)
    return calls


def _run(root, monkeypatch, spec, task, *responses, upstream=None, seen=None, user_vars=None):
    monkeypatch.setattr(node, "ChatLLM", lambda **kw: _Script(*responses, seen=seen))
    TaskStore(root).save_task(task)
    result = node.run_node(spec, task, upstream or {}, user_vars or {}, root, include_shell_tools=True, policy=_policy())
    if result.status == "completed":
        TaskStore(root).update_status(task.id, TaskStatus.completed, summary=result.summary)
    return result


def _collect(root, monkeypatch, task_id="collect"):
    spec = SwarmAgentSpec(id=task_id, role="Data", system_prompt="Collect.", tools=["fetch_records"])
    result = _run(root, monkeypatch, spec, SwarmTask(id=task_id, agent_id=task_id, prompt_template="Collect"),
                  _call("raw", "fetch_records", station="north"), _answer(f"Collected readings. {PROSE}"))
    assert result.status == "completed", result


def _analyze(root, monkeypatch, task_id="analyze", value=19, depends=("collect",)):
    """A producer that observes, computes metrics.json with a recorded command and writes a draft."""
    spec = SwarmAgentSpec(id=task_id, role="Analyst", system_prompt="Compute.",
                          tools=["fetch_records", "bash", "write_file", "quantlib_call"])
    task = SwarmTask(id=task_id, agent_id=task_id, prompt_template="Compute", depends_on=list(depends))
    command = (f"printf 'result = sum([11, 17, 23, 25]) / 4' > compute.py; "
               f"printf '{{\"measured\": {value}}}' > metrics.json; echo mean=$((4*{value}/4))")
    result = _run(root, monkeypatch, spec, task,
                  _call("raw", "fetch_records", station="north"),
                  _call("listing", "bash", command="ls"),
                  _call("calc", "bash", command=command),
                  _call("q", "quantlib_call", action="call", module="units", function="compare_rates",
                        kwargs={"left": 0.05, "right": 0.03}),
                  _call("draft", "write_file", path="draft.md", content=PROSE),
                  _answer(f"Computed metrics.json. {PROSE}"))
    assert result.status == "completed", result
    return node.agent_artifact_dir(root, task_id, task_id)


def _consumer(root, input_from, task_id="publish", agent_id="editor"):
    task = SwarmTask(id=task_id, agent_id=agent_id, prompt_template="Present", input_from=input_from,
                     depends_on=sorted({b if isinstance(b, str) else b["task"] for b in input_from.values()}))
    TaskStore(root).save_task(task)
    directory = node.agent_artifact_dir(root, agent_id, task_id)
    directory.mkdir(parents=True, exist_ok=True)
    return task, directory


METRIC_SELECTION = {"task": "analyze", "kinds": ["observation"],
                    "files": [{"path": "metrics.json", "copy_to": "metrics.json", "execution": True},
                              "compute.py"]}


# --- Validation before dispatch -----------------------------------------------------------------

@pytest.mark.parametrize("binding", [
    {}, {"task": "s"}, {"task": "s", "kinds": ["facts"]}, {"task": "", "kinds": ["observation"]},
    {"task": "s", "files": "../secret"}, {"task": "s", "files": ["/etc/hosts"]},
    {"task": "s", "files": ["../x"]}, {"task": "s", "files": ["a/../x"]}, {"task": "s", "files": [42]},
    {"task": "s", "kinds": ["observation"], "summary": True},
    {"task": "s", "files": [{"path": "metrics.json"}]},
    {"task": "s", "files": [{"path": "metrics.json", "pointer": "/x", "copy_to": "copy.json"}]},
    {"task": "s", "files": [{"path": "metrics.json", "copy_to": "../metrics.json"}]},
    {"task": "s", "files": [{"path": "metrics.json", "copy_to": "thread.jsonl"}]},
    {"task": "s", "files": [{"path": "metrics.json", "copy_to": "upstream/audit.json"}]},
    {"task": "s", "files": [{"path": "metrics.json", "copy_to": "tool-results/x.json"}]},
    {"task": "s", "files": [{"path": "metrics.json", "execution": "yes"}]},
])
def test_invalid_selection_is_rejected(binding):
    with pytest.raises(ValueError):
        SwarmTask(id="t", agent_id="a", prompt_template="", input_from={"data": binding})


def test_selected_dependencies_and_permissions_are_not_advisory():
    source = SwarmTask(id="s", agent_id="a", prompt_template="")
    task = SwarmTask(id="t", agent_id="a", prompt_template="", tools=[],
                     input_from={"data": {"task": "s", "kinds": ["observation"]}})
    with pytest.raises(ValueError, match="not upstream"):
        validate_dag([source, task])
    task.depends_on = ["s"]
    validate_dag([source, task])
    with pytest.raises(ValueError, match="unknown task|not upstream"):
        validate_dag([task.model_copy(update={"input_from": {"data": {"task": "ghost", "kinds": ["observation"]}}})])
    agent = SwarmAgentSpec(id="a", role="Worker", system_prompt="", tools=["read_file"])
    assert task.effective_tools(agent) == []
    assert task.model_copy(update={"tools": None}).effective_tools(agent) == ["read_file"]
    task.tools = ["bash"]
    with pytest.raises(ValueError, match="subset"):
        task.effective_tools(agent)


def _user_preset(tmp_path, monkeypatch, definition):
    (tmp_path / "custom.yaml").write_text(yaml.safe_dump(definition))
    monkeypatch.setattr(presets, "USER_PRESETS_DIR", tmp_path)


def test_task_tools_outside_the_agent_whitelist_fail_when_the_run_is_built(tmp_path, monkeypatch):
    _user_preset(tmp_path, monkeypatch, {
        "name": "custom", "agents": [{"id": "a", "role": "Worker", "system_prompt": "", "tools": ["read_file"]}],
        "tasks": [{"id": "t", "agent_id": "a", "prompt_template": "Go", "tools": ["bash"]}],
    })
    with pytest.raises(ValueError, match="subset"):
        build_run_from_preset("custom", {})


def test_task_tools_narrow_the_registry_and_prompt(tmp_path, monkeypatch, _workspace):
    seen = []
    spec = SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="Use assigned input.",
                          tools=["fetch_records", "read_file", "load_skill"], skills=["data-routing"])
    task = SwarmTask(id="t", agent_id="analyst", prompt_template="Inspect", tools=["read_file"])
    result = _run(tmp_path, monkeypatch, spec, task, _call("blocked", "fetch_records"),
                  _answer("Available observations have been retained."), seen=seen)
    assert result.status == "completed"
    assert _workspace == []  # The narrowed-out tool never ran.
    assert '"fetch_records"' not in seen[0]["tools"] and '"read_file"' in seen[0]["tools"]
    assert "Available Skills" not in seen[0]["messages"]


# --- Selected handoff ------------------------------------------------------------------------------

def test_editor_sees_selected_values_without_prose_and_can_trace_sources(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    producer = _analyze(tmp_path, monkeypatch)
    task, directory = _consumer(tmp_path, {"results": METRIC_SELECTION})
    note = prepare_handoff(tmp_path, task, directory)
    supplied = selected_inputs(directory)
    assert not supplied["unavailable"], supplied["unavailable"]
    values = supplied["inputs"]["results"]
    metric = next(v for v in values if v.get("file") == "metrics.json")
    assert metric["content"] == {"measured": 19}
    assert metric["copy_to"] == "metrics.json"
    assert (directory / "metrics.json").read_bytes() == (producer / "metrics.json").read_bytes()
    assert "printf" in metric["execution"]["request"]["command"]
    assert metric["execution"]["result"]["status"] == "ok"
    assert next(v for v in values if v.get("file") == "compute.py")["content"] == "result = sum([11, 17, 23, 25]) / 4"
    observation = next(v for v in values if v.get("tool") == "fetch_records")
    assert observation["content"]["coverage"] == {"calendar_checked": False}
    assert observation["request"] == {}  # station is not a recorded request key
    assert "readings" not in observation["content"]  # rows stay in the file at path
    text = json.dumps(supplied)
    assert "negligence" not in text and "mean=19" not in text and "draft.md" not in text
    assert {v["kind"] for v in values} == {"observation", "analysis"}
    # The complete copy stays readable and hash-checked in the audit file.
    index = json.loads((directory / "upstream/index.json").read_text())
    audit_raw = (directory / index["audit_file"]["path"]).read_bytes()
    assert hashlib.sha256(audit_raw).hexdigest() == index["audit_file"]["sha256"]
    audit = json.loads(audit_raw)
    assert {e["tool"] for e in audit["observations"]} >= {"fetch_records", "bash", "quantlib_call"}
    assert {f["original_path"] for f in audit["files"]} == {"compute.py", "metrics.json", "draft.md"}
    reader = ReadFileTool(roots=FileRoots.from_config(get_env_config().api))
    for entry in audit["observations"]:
        response = json.loads(reader.execute(path=entry["path"], run_dir=str(directory)))
        assert response["status"] == "ok"
        assert hashlib.sha256(response["content"].encode()).hexdigest() == entry["sha256"]
    assert "upstream/audit.json" in note
    assert prepare_handoff(tmp_path, task, directory) == note


def test_missing_selected_file_is_an_explicit_gap_not_a_prose_fallback(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    _analyze(tmp_path, monkeypatch)
    task, directory = _consumer(tmp_path, {"results": {"task": "analyze", "files": ["metrics.json", "missing.json"]}})
    prepare_handoff(tmp_path, task, directory)
    supplied = selected_inputs(directory)
    assert any("missing.json unavailable" in error for error in supplied["unavailable"])
    assert [v["file"] for v in supplied["inputs"]["results"]] == ["metrics.json"]
    assert "negligence" not in json.dumps(supplied)


def test_copied_output_does_not_overwrite_a_consumers_changed_file(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    _analyze(tmp_path, monkeypatch)
    task, directory = _consumer(tmp_path, {"results": METRIC_SELECTION})
    note = prepare_handoff(tmp_path, task, directory)
    assert prepare_handoff(tmp_path, task, directory) == note
    (directory / "metrics.json").write_text('{"consumer_edit":true}')
    with pytest.raises(ValueError, match="modified"):
        prepare_handoff(tmp_path, task, directory)
    assert json.loads((directory / "metrics.json").read_text()) == {"consumer_edit": True}


def test_edited_metrics_cannot_inherit_an_old_execution_claim(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    producer = _analyze(tmp_path, monkeypatch)
    (producer / "metrics.json").write_text('{"measured": 999}')
    task, directory = _consumer(tmp_path, {"results": METRIC_SELECTION})
    prepare_handoff(tmp_path, task, directory)
    supplied = selected_inputs(directory)
    assert any("no successful execution recorded for metrics.json" in e for e in supplied["unavailable"])
    metric = next(v for v in supplied["inputs"]["results"] if v.get("file") == "metrics.json")
    assert metric["content"] == {"measured": 999} and "execution" not in metric


def test_oversized_selection_keeps_a_readable_file_reference(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    producer = _analyze(tmp_path, monkeypatch)
    (producer / "metrics.json").write_text(json.dumps({"items": list(range(10000))}))
    task, directory = _consumer(tmp_path, {"results": {"task": "analyze", "files": ["metrics.json"]}})
    prepare_handoff(tmp_path, task, directory)
    value = selected_inputs(directory)["inputs"]["results"][0]
    assert "content" not in value and "content_omitted" in value
    assert json.loads((directory / value["path"]).read_text()) == {"items": list(range(10000))}


@pytest.mark.parametrize("which", ["selected", "audit"])
def test_changed_evidence_is_refused_on_continuation(tmp_path, monkeypatch, which):
    _collect(tmp_path, monkeypatch)
    _analyze(tmp_path, monkeypatch)
    task, directory = _consumer(tmp_path, {"results": METRIC_SELECTION})
    prepare_handoff(tmp_path, task, directory)
    index = json.loads((directory / "upstream/index.json").read_text())
    target = {"selected": index["files"][0]["path"], "audit": index["audit_file"]["path"]}[which]
    (directory / target).write_text("{}")
    with pytest.raises(ValueError):
        prepare_handoff(tmp_path, task, directory)
    with pytest.raises(ValueError):
        selected_inputs(directory)


def test_aliases_do_not_mix_sources_from_different_dependencies(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    _analyze(tmp_path, monkeypatch, "one", 19)
    _analyze(tmp_path, monkeypatch, "two", 31)
    task, directory = _consumer(tmp_path, {name: {"task": name, "kinds": ["observation"], "files": ["metrics.json"]}
                                           for name in ["one", "two"]})
    prepare_handoff(tmp_path, task, directory)
    supplied = selected_inputs(directory)
    for name, expected in [("one", 19), ("two", 31)]:
        values = supplied["inputs"][name]
        assert {v["source_task"] for v in values} == {name}
        assert next(v["content"] for v in values if v.get("file") == "metrics.json") == {"measured": expected}


def test_incomplete_producer_is_named_and_its_files_are_not_transferred(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    _analyze(tmp_path, monkeypatch)
    TaskStore(tmp_path).update_status("analyze", TaskStatus.failed)
    task, directory = _consumer(tmp_path, {"results": METRIC_SELECTION})
    prepare_handoff(tmp_path, task, directory)
    supplied = selected_inputs(directory)
    assert any("producer is failed" in error for error in supplied["unavailable"])
    metric = next(v for v in supplied["inputs"]["results"] if v.get("file") == "metrics.json")
    assert metric["content"] == {"measured": 19} and "copy_to" not in metric
    assert not (directory / "metrics.json").exists()


def test_transitive_selection_keeps_values_and_the_original_audit(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    _analyze(tmp_path, monkeypatch)
    editor_spec = SwarmAgentSpec(id="editor", role="Editor", system_prompt="Present.", tools=["write_file"])
    editor = SwarmTask(id="publish", agent_id="editor", prompt_template="Present", depends_on=["analyze"],
                       input_from={"results": METRIC_SELECTION})
    result = _run(tmp_path, monkeypatch, editor_spec, editor,
                  _call("w", "write_file", path="result.json", content='{"answer": 19}'),
                  _answer("Report written to result.json."))
    assert result.status == "completed", result
    final, final_dir = _consumer(tmp_path, {"answer": {"task": "publish", "kinds": ["observation"],
                                                       "files": ["result.json", "metrics.json"]}}, "final", "final")
    prepare_handoff(tmp_path, final, final_dir)
    supplied = selected_inputs(final_dir)
    values = supplied["inputs"]["answer"]
    assert next(v["content"] for v in values if v.get("file") == "result.json") == {"answer": 19}
    # The copy_to transfer is the editor's own deliverable now; the original observation travels too.
    assert next(v["content"] for v in values if v.get("file") == "metrics.json") == {"measured": 19}
    assert [v["tool"] for v in values if v["kind"] == "observation"] == ["fetch_records"]
    assert not supplied["unavailable"]
    audit = json.loads((final_dir / "upstream/audit.json").read_text())
    assert {e["source_task"] for e in audit["observations"]} >= {"analyze"}
    assert any(e["tool"] == "quantlib_call" for e in audit["observations"])


def test_rehomed_inputs_are_identical(tmp_path, monkeypatch):
    old = tmp_path / "old"
    _collect(old, monkeypatch)
    _analyze(old, monkeypatch)
    task, directory = _consumer(old, {"results": METRIC_SELECTION})
    before = prepare_handoff(old, task, directory)
    values = selected_inputs(directory)
    new = tmp_path / "new"
    shutil.copytree(old, new)
    moved = node.agent_artifact_dir(new, task.agent_id, task.id)
    assert prepare_handoff(new, task, moved) == before
    assert selected_inputs(moved) == values


def test_node_receives_selected_values_and_never_the_selected_prose(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    _analyze(tmp_path, monkeypatch)
    seen = []
    spec = SwarmAgentSpec(id="editor", role="Editor", system_prompt="Present {upstream_context}.",
                          tools=["read_file", "write_file"])
    task = SwarmTask(id="publish", agent_id="editor", prompt_template="Present", depends_on=["analyze"],
                     input_from={"results": METRIC_SELECTION})
    summary = TaskStore(tmp_path).load_task("analyze").summary
    result = _run(tmp_path, monkeypatch, spec, task, _answer("The measured mean is 19."),
                  upstream={"results": summary}, seen=seen)
    assert result.status == "completed"
    text = seen[0]["messages"]
    assert "negligence" not in text and "mean=19" not in text
    assert '\\"measured\\": 19' in text and "sum([11, 17, 23, 25])" in text
    assert "the supplied upstream task results" in text


@pytest.mark.parametrize("binding", ["analyze", METRIC_SELECTION], ids=["report", "selection"])
def test_task_prompt_alias_points_to_upstream_data(tmp_path, monkeypatch, binding):
    """Resolve an alias to its data section in both handoff modes.

    Args:
        tmp_path: Isolated preset directory and node workspaces.
        monkeypatch: Fixture for the custom preset and scripted provider.
        binding: Plain producer ID or selection binding for the same producer.
    """
    _collect(tmp_path, monkeypatch)
    _analyze(tmp_path, monkeypatch)
    _user_preset(tmp_path, monkeypatch, {
        "name": "custom", "agents": [{"id": "editor", "role": "Editor"}],
        "tasks": [
            {"id": "analyze", "agent_id": "editor", "prompt_template": "Analyze"},
            {"id": "publish", "agent_id": "editor", "prompt_template": "Present {results}.",
             "depends_on": ["analyze"], "input_from": {"results": binding}},
        ],
    })
    built = build_run_from_preset("custom", {"results": "wrong same-named variable"}, validate_variables=True)
    seen = []
    result = _run(tmp_path, monkeypatch, built.agents[0], built.tasks[1], _answer("Delivered."),
                  upstream={"results": PROSE}, seen=seen, user_vars=built.user_vars)

    assert result.status == "completed"
    messages = json.loads(seen[0]["messages"])
    assert messages[-1]["content"] == 'Present upstream input "results" in the supplied data message.'
    assert "### results" in messages[-2]["content"]
    assert (PROSE in messages[-2]["content"]) == isinstance(binding, str)
    assert not presets.inspect_preset("custom")["warnings"]


def test_selected_handoff_failure_cannot_fall_back_to_the_report(tmp_path, monkeypatch):
    _collect(tmp_path, monkeypatch)
    calls = []

    def fail(*args):
        raise ValueError("Changed evidence index")

    monkeypatch.setattr(node, "prepare_handoff", fail)
    monkeypatch.setattr(node, "ChatLLM", lambda **kw: calls.append(kw) or _Script())
    task = SwarmTask(id="analyze", agent_id="analyst", prompt_template="Inspect", depends_on=["collect"],
                     input_from={"data": {"task": "collect", "kinds": ["observation"]}})
    result = node.run_node(SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="Use input."),
                           task, {"data": PROSE}, {}, tmp_path, policy=_policy())
    assert result.status == "failed" and result.summary == "" and not calls


# --- Preset plumbing ------------------------------------------------------------------------------

def test_required_preset_variables_fail_before_dispatch(tmp_path, monkeypatch):
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore
    from src.tools.swarm_variables import build_variables, merge_variables

    assert build_variables("research", "Collect readings, compute statistics, write a report") == {}
    runtime = SwarmRuntime(SwarmStore(tmp_path / "runs"), policy=_policy())
    monkeypatch.setattr(runtime, "_execute_run", lambda *a, **k: pytest.fail("must not dispatch"))
    with pytest.raises(ValueError, match="pass them in `variables`: data_request .*analysis_request .*report_request") as missing:
        runtime.start_run("research", {})
    assert "Requested calculations and their definitions" in str(missing.value), "each missing variable says what it is"
    with pytest.raises(ValueError, match="report_request"):
        runtime.start_run("research", {"data_request": "Get readings", "analysis_request": "Sum", "report_request": " "})
    assert not list((tmp_path / "runs").glob("*/run.json"))
    variables, error = merge_variables({}, {"data_request": "Get readings", "analysis_request": "Sum values",
                                            "report_request": "Write a summary"})
    assert error is None
    run = build_run_from_preset("research", variables, validate_variables=True)
    assert run.user_vars == variables


def test_research_preset_and_existing_editors_have_executable_boundaries():
    run = build_run_from_preset("research", {})
    report = inspect_preset("research")
    assert report["valid"] and not report["warnings"] and len(report["layers"]) == 3
    assert report["prefetch_grounding"] is False and run.prefetch_grounding is False
    assert build_run_from_preset("investment_committee", {}).prefetch_grounding is True
    agents = {a.id: a for a in run.agents}
    collect, analyze, editor = run.tasks
    assert "bash" not in collect.effective_tools(agents[collect.agent_id])
    assert "write_file" not in collect.effective_tools(agents[collect.agent_id])
    assert "bash" in analyze.effective_tools(agents[analyze.agent_id])
    assert editor.effective_tools(agents[editor.agent_id]) == ["read_file", "write_file"]
    assert analyze.input_from["data"]["kinds"] == ["observation"]
    assert editor.input_from["results"]["files"][0] == {"path": "metrics.json", "copy_to": "metrics.json", "execution": True}
    assert {t["id"]: t["tools"] for t in report["tasks"]}["publish"] == ["read_file", "write_file"]
    for preset in ["equity_research_team", "quant_strategy_desk"]:
        existing = build_run_from_preset(preset, {})
        agent = next(a for a in existing.agents if a.id == existing.tasks[-1].agent_id)
        assert "bash" not in existing.tasks[-1].effective_tools(agent)
        assert "read_file" in existing.tasks[-1].effective_tools(agent)


def test_research_preset_skips_the_price_prefetch(tmp_path, monkeypatch):
    import threading
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore

    store = SwarmStore(tmp_path / "runs")
    runtime = SwarmRuntime(store, policy=_policy())
    monkeypatch.setattr(runtime, "_prefetch_grounding_data", lambda run: pytest.fail("no unrequested prices"))
    monkeypatch.setattr(runtime, "_execute_layer", lambda **kwargs: {})
    run = build_run_from_preset("research", {"data_request": "AAPL closes", "analysis_request": "Mean",
                                             "report_request": "Brief"})
    store.create_run(run)
    runtime._execute_run(run, threading.Event())
    assert store.load_run(run.id).grounding_data is None


def test_changed_tools_inputs_or_prefetch_invalidate_resume():
    run = build_run_from_preset("research", {})
    agents = {a.id: a for a in run.agents}
    old = run.tasks[1]
    for changes in [{"tools": []}, {"input_from": {"data": "collect"}}]:
        assert _task_definition_changed(old, old.model_copy(update=changes), agents, agents, run, run)
    assert not _task_definition_changed(old, old.model_copy(), agents, agents, run, run)
    assert _task_definition_changed(old, old.model_copy(), agents, agents, run,
                                    run.model_copy(update={"prefetch_grounding": True}))


def test_selected_fields_survive_serialization_and_inspection():
    task = build_run_from_preset("research", {}).tasks[-1]
    assert SwarmTask.model_validate(task.model_dump(mode="json")).input_from == task.input_from
    public = serialize_task(task)
    assert public["input_from"] == task.input_from and public["tools"] == ["read_file", "write_file"]
    assert inspect_preset("research")["valid"]


def test_inspect_cli_shows_task_tools_inputs_and_prefetch(capsys):
    from cli.commands import common
    from cli.commands.swarm_runtime import cmd_swarm_inspect

    assert cmd_swarm_inspect("research") == common.EXIT_SUCCESS
    out = capsys.readouterr().out
    assert "Recent-price prefetch" in out and "False" in out
    assert "read_file, write_file" in out and "metrics.json" in out and "inherit" in out


class _MarketData(_Records):
    name = "get_market_data"


def test_research_preset_runs_end_to_end_and_resumes_without_replay(tmp_path, monkeypatch):
    """The scheduler hands selected values to the editor, and a continuation reuses finished stages."""
    import threading
    from src.swarm.models import RunStatus
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore

    fetched = []
    original = node.build_swarm_registry

    def registry(names, **kwargs):
        built = original([name for name in names if name != "get_market_data"], **kwargs)
        if "get_market_data" in names:
            built.register(_MarketData(fetched))
        return built

    monkeypatch.setattr(node, "build_swarm_registry", registry)
    variables = {"data_request": "Collect instrument readings", "analysis_request": "Average the readings",
                 "report_request": "Report the mean"}
    run = build_run_from_preset("research", variables, validate_variables=True)
    run.id = "first"
    for agent in run.agents:
        agent.model_name, agent.max_retries = agent.id, 0
    command = ("printf 'mean = sum([11, 17, 23, 25]) / 4' > compute.py; "
               "printf '{\"mean\": 19}' > metrics.json")
    editor_seen, analyst_runs = [], []
    state = {"resumed": False}

    def model(model_name=None, **kwargs):
        if model_name == "data":
            return _Script(_call("fetch", "get_market_data"), _answer(f"Collected readings. {PROSE}"))
        if model_name == "analyst":
            analyst_runs.append(1)
            return _Script(_call("calc", "bash", command=command), _answer(f"metrics.json delivered. {PROSE}"))
        if not state["resumed"]:
            return _Script(_answer(""), seen=editor_seen)  # an empty delivery fails the editor
        return _Script(_call("report", "write_file", path="research.md", content="The mean is 19."),
                       _answer("Report saved in research.md."), seen=editor_seen)

    monkeypatch.setattr(node, "ChatLLM", model)
    store = SwarmStore(tmp_path / "runs")
    runtime = SwarmRuntime(store, policy=_policy())
    runtime._max_workers = 1
    monkeypatch.setattr(runtime, "_prefetch_grounding_data", lambda run: pytest.fail("no unrequested prices"))
    store.create_run(run)
    runtime._execute_run(run, threading.Event(), include_shell_tools=True)
    prior = store.load_run("first")
    assert prior.status == RunStatus.failed
    assert {t.id: t.status for t in prior.tasks}["analyze"] == TaskStatus.completed
    assert len(fetched) == 1 and len(analyst_runs) == 1

    state["resumed"] = True
    continued = run.model_copy(deep=True, update={"id": "continued", "status": RunStatus.pending})
    store.create_run(continued)
    runtime._execute_run(continued, threading.Event(), include_shell_tools=True, resume_from=prior)
    final = store.load_run("continued")
    assert final.status == RunStatus.completed, [(t.id, t.status, t.error) for t in final.tasks]
    assert len(fetched) == 1 and len(analyst_runs) == 1  # finished stages are not replayed
    text = editor_seen[-1]["messages"]
    assert '\\"mean\\": 19' in text and "sum([11, 17, 23, 25])" in text and "fetch_records" not in text
    assert "negligence" not in text
    assert '"bash"' not in editor_seen[-1]["tools"] and '"read_file"' in editor_seen[-1]["tools"]
    folder = store.run_dir("continued") / "artifacts/editor/publish"
    index = json.loads((folder / "upstream/index.json").read_text())
    assert not index["unavailable"], index["unavailable"]
    assert json.loads((folder / "metrics.json").read_text()) == {"mean": 19}
    assert any(e["tool"] == "get_market_data" for e in index["observations"])
