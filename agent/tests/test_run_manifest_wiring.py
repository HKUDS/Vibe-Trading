"""The run manifest must actually be produced by a run.

`build_run_manifest` existed with no caller, so nothing in the system could
answer "what methodology produced that number". These tests pin the wiring, and
pin the two properties that make the record safe to keep: it stores no prompt
text, and it can never break a run.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from src.agent.loop import AgentLoop


class _Registry:
    tool_names = ["get_market_data", "backtest", "quantlib_call"]


def _loop() -> AgentLoop:
    """An AgentLoop shell built without running __init__ (we only need the helper)."""
    loop = AgentLoop.__new__(AgentLoop)
    loop.registry = _Registry()
    loop._run_iteration = 0
    return loop


@pytest.fixture
def trace_dir():
    return pathlib.Path(tempfile.mkdtemp()) / "run"


_MESSAGES = [
    {"role": "system", "content": "You are a finance agent. <skill>tushare body</skill>"},
    {"role": "user", "content": "what is nvda worth"},
]


def test_a_run_writes_a_manifest_next_to_its_trace(trace_dir):
    _loop()._write_run_manifest(trace_dir, _MESSAGES)

    path = trace_dir / "run_manifest.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["system_prompt_hash"]
    assert data["manifest_hash"]


def test_the_manifest_records_the_tool_registry(trace_dir):
    _loop()._write_run_manifest(trace_dir, _MESSAGES)
    data = json.loads((trace_dir / "run_manifest.json").read_text())

    assert set(data["tools"]["tool_names"]) == set(_Registry.tool_names)
    assert data["tools"]["tools_hash"]


def test_the_prompt_text_itself_is_never_stored(trace_dir):
    # The prompt can carry user memory and workspace content. This file is a
    # provenance record, not a second copy of the conversation.
    _loop()._write_run_manifest(trace_dir, _MESSAGES)
    raw = (trace_dir / "run_manifest.json").read_text()

    assert "You are a finance agent" not in raw
    assert "tushare body" not in raw
    assert "what is nvda worth" not in raw


def test_a_changed_system_prompt_changes_the_hash(trace_dir):
    _loop()._write_run_manifest(trace_dir, _MESSAGES)
    first = json.loads((trace_dir / "run_manifest.json").read_text())

    changed = [dict(_MESSAGES[0], content="You are a finance agent. <skill>EDITED</skill>"), _MESSAGES[1]]
    _loop()._write_run_manifest(trace_dir, changed)
    second = json.loads((trace_dir / "run_manifest.json").read_text())

    assert first["system_prompt_hash"] != second["system_prompt_hash"]
    assert first["manifest_hash"] != second["manifest_hash"]


def test_an_identical_run_reproduces_the_same_manifest_hash(trace_dir):
    # manifest_hash deliberately excludes run_id and timestamp, so the same
    # methodology on a different day hashes identically.
    a = pathlib.Path(tempfile.mkdtemp()) / "a"
    b = pathlib.Path(tempfile.mkdtemp()) / "b"
    _loop()._write_run_manifest(a, _MESSAGES)
    _loop()._write_run_manifest(b, _MESSAGES)

    assert (
        json.loads((a / "run_manifest.json").read_text())["manifest_hash"]
        == json.loads((b / "run_manifest.json").read_text())["manifest_hash"]
    )


def test_a_changed_tool_registry_changes_the_hash(trace_dir):
    _loop()._write_run_manifest(trace_dir, _MESSAGES)
    before = json.loads((trace_dir / "run_manifest.json").read_text())["manifest_hash"]

    loop = _loop()
    loop.registry = type("R", (), {"tool_names": ["get_market_data"]})()
    loop._write_run_manifest(trace_dir, _MESSAGES)
    after = json.loads((trace_dir / "run_manifest.json").read_text())["manifest_hash"]

    assert before != after


def test_the_skill_coverage_limit_is_stated_not_implied(trace_dir):
    # Mid-run load_skill content is NOT in the hashed prompt. Saying so beats
    # implying a coverage the record does not have.
    _loop()._write_run_manifest(trace_dir, _MESSAGES)
    data = json.loads((trace_dir / "run_manifest.json").read_text())
    assert "load_skill" in data["extra"]["skill_coverage"]


def test_a_manifest_failure_never_breaks_the_run(trace_dir, monkeypatch):
    # A provenance record that can kill a run is worse than a missing one.
    import src.governance.manifest as manifest_mod

    def boom(**kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(manifest_mod, "build_run_manifest", boom)
    _loop()._write_run_manifest(trace_dir, _MESSAGES)  # must not raise
    assert not (trace_dir / "run_manifest.json").exists()


def test_a_run_with_no_system_message_still_writes_a_manifest(trace_dir):
    _loop()._write_run_manifest(trace_dir, [{"role": "user", "content": "hi"}])
    assert (trace_dir / "run_manifest.json").exists()
