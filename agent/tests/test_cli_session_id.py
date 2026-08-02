"""Regression tests for host session-id injection in non-interactive CLI runs.

Issue #885: ``cmd_run`` registered the research-goal tools but never gave them a
session, so every goal call failed validation with ``session_id is required``
while the run still reported success. The same omission affected
``cmd_continue``, ``cmd_interactive`` and ``cmd_session_chat``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli import _legacy
from src.agent.trace import TraceWriter
from src.goal import GoalStore
from src.tools.goal_tool import StartResearchGoalTool


@pytest.fixture()
def sessions_dir(tmp_path, monkeypatch) -> Path:
    """Point the session store at a temp dir so tests never touch agent/sessions."""
    path = tmp_path / "sessions"
    path.mkdir()
    monkeypatch.setattr(_legacy, "SESSIONS_DIR", path)
    monkeypatch.setattr(_legacy, "RUNS_DIR", tmp_path / "runs")
    return path


def _capture_session_ids(monkeypatch) -> list:
    """Replace ``_run_agent`` with a spy recording the session id it receives."""
    seen: list = []

    def fake_run_agent(prompt, history=None, run_dir_override=None, **kwargs):
        seen.append(kwargs.get("session_id"))
        return {"status": "success", "run_id": "r1", "run_dir": run_dir_override or "d"}

    monkeypatch.setattr(_legacy, "_run_agent", fake_run_agent)
    monkeypatch.setattr(_legacy, "_print_json_result", lambda result: None)
    return seen


# ---------------------------------------------------------------------------
# The defect itself
# ---------------------------------------------------------------------------


def test_goal_tool_fails_without_a_session_id() -> None:
    """Pin the reported symptom: no host session means every goal call errors."""
    result = StartResearchGoalTool(default_session_id=None).execute(objective="x")
    assert '"session_id is required"' in result


def test_cmd_run_injects_a_nonempty_session_id(sessions_dir, monkeypatch) -> None:
    seen = _capture_session_ids(monkeypatch)
    monkeypatch.setattr(_legacy, "run_preflight", lambda console: [], raising=False)

    assert _legacy.cmd_run("backtest SPY", 5, json_mode=True) == _legacy.EXIT_SUCCESS

    assert len(seen) == 1
    assert seen[0]


def test_injected_session_id_makes_the_goal_tool_work(sessions_dir, tmp_path) -> None:
    """The end-to-end point of the fix: goals resolve instead of erroring."""
    session_id = _legacy._ensure_session_id("backtest SPY")
    store = GoalStore(db_path=tmp_path / "goals.db")

    result = StartResearchGoalTool(default_session_id=session_id, store=store).execute(
        objective="Backtest a 20/50-day moving average crossover on SPY"
    )

    assert '"status": "ok"' in result
    assert "session_id is required" not in result


# ---------------------------------------------------------------------------
# _ensure_session_id contract
# ---------------------------------------------------------------------------


def test_ensure_session_id_persists_a_session_record(sessions_dir) -> None:
    session_id = _legacy._ensure_session_id("a prompt used as the title")

    assert (sessions_dir / session_id / "session.json").exists()


def test_ensure_session_id_survives_an_unwritable_store(sessions_dir, monkeypatch) -> None:
    """Persistence is best effort — a store failure must not restore the bug."""

    class _Boom:
        def __init__(self, *a, **kw) -> None:
            raise OSError("disk gone")

    monkeypatch.setattr("src.session.store.SessionStore", _Boom)

    assert _legacy._ensure_session_id("prompt")


def test_ensure_session_id_honours_an_explicit_id(sessions_dir) -> None:
    assert _legacy._ensure_session_id("t", session_id="run-abc") == "run-abc"


def test_ensure_session_id_is_idempotent_for_a_known_id(sessions_dir) -> None:
    """Re-registering an existing session returns the id rather than raising."""
    first = _legacy._ensure_session_id("t", session_id="run-abc")
    second = _legacy._ensure_session_id("t", session_id="run-abc")

    assert first == second == "run-abc"


# ---------------------------------------------------------------------------
# The other three entry points
# ---------------------------------------------------------------------------


def test_cmd_continue_reuses_one_session_across_continuations(sessions_dir, monkeypatch) -> None:
    """Goals must accumulate across continuations, so the id has to be stable."""
    trace_dir = sessions_dir / "session-1"
    writer = TraceWriter(trace_dir)
    writer.write({"type": "start", "prompt": "q"})
    writer.write({"type": "answer", "content": "a"})
    writer.close()

    seen = _capture_session_ids(monkeypatch)

    _legacy.cmd_continue("session-1", "first", 5, json_mode=True)
    _legacy.cmd_continue("session-1", "second", 5, json_mode=True)

    assert seen[0]
    assert seen[0] == seen[1]
    # A session-backed run_id already *is* a session id, so it is used directly.
    assert seen[0] == "session-1"


def test_cmd_continue_derives_an_id_for_a_plain_run(sessions_dir, tmp_path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    trace_dir = runs_dir / "run-x"
    writer = TraceWriter(trace_dir)
    writer.write({"type": "start", "prompt": "q"})
    writer.close()

    seen = _capture_session_ids(monkeypatch)

    _legacy.cmd_continue("run-x", "follow up", 5, json_mode=True)

    assert seen == ["run-run-x"]


def test_cmd_session_chat_passes_the_session_it_was_given(sessions_dir, monkeypatch) -> None:
    """The id was already in scope as a parameter and simply was not forwarded."""
    from src.session.models import Session
    from src.session.store import SessionStore

    store = SessionStore(base_dir=sessions_dir)
    session = Session(title="existing")
    store.create_session(session)

    seen = _capture_session_ids(monkeypatch)
    replies = iter(["analyse AAPL", "q"])
    monkeypatch.setattr(_legacy, "_read_input", lambda _s: next(replies))
    monkeypatch.setattr(_legacy, "_create_prompt_session", lambda _stats: None)
    monkeypatch.setattr(_legacy, "_print_status_bar", lambda _stats: None)
    monkeypatch.setattr(_legacy, "_print_result", lambda *a, **kw: None)

    _legacy.cmd_session_chat(session.session_id, 5)

    assert seen == [session.session_id]
