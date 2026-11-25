"""Conversation fork snapshots are complete, independent, and secret-free."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.sessions_routes import register_sessions_routes
from src.goal import EvidenceInput, GoalStatus, GoalStore
from src.session.events import EventBus
from src.session.fork import ForkAuthorizationError, ForkSelectionError, ForkSourceNotFound
from src.session.models import Attempt, AttemptStatus, AuthMethod, Message, Principal
from src.session.search import SessionSearchIndex
from src.session.service import SessionService
from src.session.store import SessionStore


ALICE = Principal(subject="alice@example.com", auth_method=AuthMethod.FEDERATED_IDENTITY, tenant="desk-a")
BOB = Principal(subject="bob@example.com", auth_method=AuthMethod.FEDERATED_IDENTITY, tenant="desk-a")


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    index = SessionSearchIndex(tmp_path / "search.db")
    monkeypatch.setattr("src.session.service.get_shared_index", lambda: index)
    service = SessionService(
        store=SessionStore(tmp_path / "sessions"),
        event_bus=EventBus(),
        runs_dir=tmp_path / "runs",
    )
    goals = GoalStore(tmp_path / "goals.db")
    try:
        yield service, goals, index
    finally:
        index.close()


def _run_files(service: SessionService, run_id: str, *, session_id: str) -> Path:
    run_dir = service.runs_dir / run_id
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "logs").mkdir()
    (run_dir / "artifacts").mkdir()
    (run_dir / "req.json").write_text(json.dumps({"prompt": "research", "context": {"session_id": session_id}, "api_key": "do-not-copy"}))
    (run_dir / "state.json").write_text(json.dumps({"status": "success"}))
    (run_dir / "planner_output.json").write_text(json.dumps({"run_id": run_id, "session_id": session_id}))
    (run_dir / "run_card.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "run_dir": str(run_dir),
                "metrics": {"sharpe": 1.5},
                "artifacts": [
                    {"path": "artifacts/metrics.csv", "size_bytes": 0, "sha256": "stale"},
                    {"path": "logs/runner_stdout.txt", "size_bytes": 0, "sha256": "secret-log"},
                ],
                "tool_traces": [
                    {
                        "tool": "backtest", "status": "completed",
                        "started_at": "2026-01-01T00:00:00+00:00", "ended_at": "2026-01-01T00:00:01+00:00",
                        "args_hash": "a" * 64, "result_hash": "b" * 64,
                        "arguments": {"api_key": "do-not-copy"},
                    }
                ],
            }
        )
    )
    (run_dir / "run_card.md").write_text(f"Run directory: `{run_dir}`\n")
    (run_dir / "code" / "signal_engine.py").write_text(f"RUN_ID = {run_id!r}\nSESSION_ID = {session_id!r}\n")
    (run_dir / "logs" / "runner_stdout.txt").write_text("API_KEY=do-not-copy\n")
    (run_dir / "config.json").write_text('{"api_key":"do-not-copy"}')
    outside = run_dir.parent.parent / f"{run_id}-outside-secret.csv"
    outside.write_text("do-not-copy\n")
    (run_dir / "artifacts" / "linked.csv").symlink_to(outside)
    (run_dir / "artifacts" / "metrics.csv").write_text("metric,value\nsharpe,1.5\n")
    (run_dir / "artifacts" / "equity.csv").write_text("date,equity\n2026-01-01,100\n")
    (run_dir / "artifacts" / "price_series.csv").write_text("date,close\n2026-01-01,101\n")
    (run_dir / "artifacts" / "strategy.pine").write_text(f"// {run_id}\n")
    (run_dir / "artifacts" / "agent_trace.json").write_text('{"secret":"do-not-copy"}')
    (run_dir / "artifacts" / "credentials.json").write_text('{"api_key":"do-not-copy"}')
    return run_dir


def _turn(
    service: SessionService,
    session_id: str,
    label: str,
    *,
    run_id: str | None = None,
    parent_attempt_id: str | None = None,
    status: AttemptStatus = AttemptStatus.COMPLETED,
    metadata_status: str | None = "completed",
    linked: bool = True,
) -> tuple[Message, Message, Attempt | None]:
    user = Message(
        session_id=session_id,
        role="user",
        content=f"user {label}",
        created_at="2026-01-01T00:00:00+00:00",
    )
    attempt = None
    metadata = {"status": metadata_status, "elapsed_ms": 123, "metrics": {"sharpe": 1.5}}
    if run_id:
        metadata["run_id"] = run_id
        metadata["render"] = {"run_id": run_id, run_id: {"path": f"runs/{run_id}"}}
        _run_files(service, run_id, session_id=session_id)
    if linked:
        attempt = Attempt(
            session_id=session_id,
            parent_attempt_id=parent_attempt_id,
            prompt=user.content,
            run_dir=str(service.runs_dir / run_id) if run_id else None,
            created_at="2026-01-01T00:00:01+00:00",
            started_at=1.0,
            metrics={"sharpe": 1.5},
            react_trace=[{"secret": "raw trace must not be copied"}],
        )
        if status is AttemptStatus.COMPLETED:
            attempt.mark_completed(summary=f"assistant {label}")
        else:
            attempt.status = status
        attempt = replace(attempt, completed_at="2026-01-01T00:00:02+00:00")
        service.store.create_attempt(attempt)
    assistant = Message(
        session_id=session_id,
        role="assistant",
        content=f"assistant {label}",
        created_at="2026-01-01T00:00:02+00:00",
        linked_attempt_id=attempt.attempt_id if attempt else None,
        metadata=metadata,
        tool_trail=[{"tool": "backtest", "attempt_id": attempt.attempt_id if attempt else None, "run_id": run_id}],
    )
    service.store.append_message(user)
    service._search_index.index_message(session_id, "user", user.content)
    service.store.append_message(assistant)
    service._search_index.index_message(session_id, "assistant", assistant.content)
    return user, assistant, attempt


def _source(runtime, *, owner=ALICE, config=None):
    service, goals, index = runtime
    session = service.create_session(
        title="Exact source title",
        owner=owner,
        config=config
        or {
            "model": "research-model",
            "max_tokens": 2048,
            "strategy": {"engine": "daily", "token_budget": 5000},
            "api_key": "do-not-copy",
            "api_token": "do-not-copy",
            "nested": {"authorization": "Bearer do-not-copy", "clientSecret": "do-not-copy", "safe": 3},
            "mcp_servers": {"private": {"env": {"TOKEN": "do-not-copy"}}},
            "channels": {"telegram": {"token": "do-not-copy"}},
            "compaction_summary": "temporary summary",
            "compactionSummary": "temporary camel-case summary",
            "active_task": "live handle",
            "liveLoops": {"source": "live handle"},
        },
    )
    return service, goals, index, session


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_fork_copies_exact_prefix_and_remaps_all_ids(runtime):
    service, goals, _, source = _source(runtime)
    _, first, first_attempt = _turn(service, source.session_id, "first", run_id="run-first")
    _, selected, selected_attempt = _turn(
        service, source.session_id, "selected", run_id="run-selected", parent_attempt_id=first_attempt.attempt_id
    )
    _turn(service, source.session_id, "after", run_id="run-after", parent_attempt_id=selected_attempt.attempt_id)
    # Some legacy completed attempts rely on reply metadata for their run path.
    selected_attempt.run_dir = None
    service.store.update_attempt(selected_attempt)

    child = service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)

    copied = service.store.get_messages(child.session_id, limit=None)
    assert [item.content for item in copied] == ["user first", "assistant first", "user selected", "assistant selected"]
    assert [item.created_at for item in copied] == [item.created_at for item in service.store.get_messages(source.session_id)[:4]]
    assert len({item.message_id for item in copied}) == 4
    assert all(item.message_id not in {old.message_id for old in service.store.get_messages(source.session_id)} for item in copied)
    assert all(item.session_id == child.session_id for item in copied)
    assert copied[-1].tool_trail[0]["run_id"] != "run-selected"
    assert copied[-1].metadata["render"]["run_id"] == copied[-1].metadata["run_id"]
    assert copied[-1].metadata["render"][copied[-1].metadata["run_id"]] == {"path": f"runs/{copied[-1].metadata['run_id']}"}
    assert copied[-1].tool_trail[0]["attempt_id"] == child.last_attempt_id
    assert copied[-1].metadata["metrics"] == {"sharpe": 1.5}
    child_attempt = service.store.get_attempt(child.session_id, child.last_attempt_id)
    assert child_attempt.status is AttemptStatus.COMPLETED
    assert child_attempt.attempt_id != selected_attempt.attempt_id
    assert child_attempt.parent_attempt_id != first_attempt.attempt_id
    assert child_attempt.parent_attempt_id is not None
    assert Path(child_attempt.run_dir).name == copied[-1].metadata["run_id"]
    assert child_attempt.react_trace == []
    assert child_attempt.created_at == selected_attempt.created_at
    assert child_attempt.completed_at == selected_attempt.completed_at
    assert child_attempt.metrics == selected_attempt.metrics
    assert not (service.store._attempt_dir(child.session_id, child.last_attempt_id) / "partial_response.json").exists()
    assert child.forked_from_session_id == source.session_id
    assert child.forked_from_message_id == selected.message_id
    assert first.message_id not in {item.message_id for item in copied}


def test_message_content_is_preserved_except_internal_run_references(runtime):
    service, goals, _, source = _source(runtime)
    content = f"Refer to session {source.session_id}; keep this prose exactly."
    message = Message(
        session_id=source.session_id,
        role="assistant",
        content=content,
        metadata={"status": "completed"},
    )
    service.store.append_message(message)
    child = service.fork_session(source.session_id, message.message_id, owner=ALICE, goal_store=goals)
    assert service.store.get_messages(child.session_id)[0].content == content


def test_busy_source_is_unchanged_and_only_committed_prefix_is_snapshotted(runtime, monkeypatch):
    service, goals, index, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "selected", run_id="run-selected")

    async def scenario():
        gate = asyncio.Event()

        async def fake_agent(attempt, messages=None, **kwargs):
            del attempt, messages, kwargs
            await gate.wait()
            return {"status": "success", "content": "still running"}

        monkeypatch.setattr(service, "_run_with_agent", fake_agent)
        await service.send_message(source.session_id, "uncommitted follow-up")
        task = service._active_tasks[source.session_id]
        before = _files(service.store.base_dir / source.session_id)
        source_messages_before = index._get_conn().execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (source.session_id,)
        ).fetchone()[0]
        child = service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)
        assert service.store.get_session(source.session_id).last_attempt_id != child.last_attempt_id
        assert source.session_id in service._inflight
        assert service._active_tasks[source.session_id] is task and not task.done()
        assert _files(service.store.base_dir / source.session_id) == before
        assert [item.content for item in service.store.get_messages(child.session_id)] == ["user selected", "assistant selected"]
        assert index._get_conn().execute(
            "SELECT COUNT(*) FROM messages WHERE session_id = ?", (source.session_id,)
        ).fetchone()[0] == source_messages_before
        gate.set()
        await task

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "kind",
    ["user", "unknown", "streaming", "partial", "failed", "cancelled", "interrupted", "attempt_failed", "run_without_attempt"],
)
def test_ineligible_cutoffs_are_rejected(runtime, kind):
    service, goals, _, source = _source(runtime)
    if kind == "user":
        message = Message(session_id=source.session_id, role="user", content="not an assistant")
        service.store.append_message(message)
    elif kind == "run_without_attempt":
        message = Message(
            session_id=source.session_id,
            role="assistant",
            content="legacy run without attempt",
            metadata={"status": "completed", "run_id": "orphan-run"},
        )
        service.store.append_message(message)
    else:
        kwargs = {}
        if kind == "attempt_failed":
            kwargs["status"] = AttemptStatus.FAILED
        elif kind in {"streaming", "partial", "failed", "cancelled", "interrupted"}:
            kwargs["metadata_status"] = kind
        _, message, _ = _turn(service, source.session_id, kind, **kwargs)
        if kind in {"streaming", "partial"}:
            message.metadata[kind] = True
            service.store.append_message(message)
    selected_id = "does-not-exist" if kind == "unknown" else message.message_id
    with pytest.raises(ForkSelectionError):
        service.fork_session(source.session_id, selected_id, owner=ALICE, goal_store=goals)
    assert service.store.list_sessions(limit=10) == [source]
    assert not list(service.runs_dir.glob(".*.fork-*"))


def test_legacy_terminal_assistant_without_run_is_allowed(runtime):
    service, goals, _, source = _source(runtime)
    message = Message(
        session_id=source.session_id,
        role="assistant",
        content="legacy completed answer",
        created_at="2025-01-01T00:00:00+00:00",
        metadata={"status": "completed"},
    )
    service.store.append_message(message)
    child = service.fork_session(source.session_id, message.message_id, owner=ALICE, goal_store=goals)
    assert child.last_attempt_id is None
    assert service.store.get_messages(child.session_id)[0].content == message.content


def test_legacy_tool_trail_run_reference_is_cloned_and_remapped(runtime):
    service, goals, _, source = _source(runtime)
    _run_files(service, "legacy-tool-run", session_id=source.session_id)
    message = Message(
        session_id=source.session_id,
        role="assistant",
        content="legacy answer with a run card",
        metadata={"status": "completed"},
        tool_trail=[{"tool": "backtest", "run_id": "legacy-tool-run"}],
    )
    service.store.append_message(message)
    child = service.fork_session(source.session_id, message.message_id, owner=ALICE, goal_store=goals)
    copied = service.store.get_messages(child.session_id)[0]
    new_run_id = copied.tool_trail[0]["run_id"]
    assert new_run_id != "legacy-tool-run"
    assert (service.runs_dir / new_run_id / "artifacts" / "metrics.csv").is_file()
    assert child.last_attempt_id is None


def test_artifacts_survive_source_deletion_and_sensitive_files_are_not_copied(runtime):
    service, goals, _, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "selected", run_id="render-run")
    child = service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)
    copied_run_id = service.store.get_messages(child.session_id)[-1].metadata["run_id"]
    copied_run = service.runs_dir / copied_run_id
    assert (copied_run / "artifacts" / "metrics.csv").read_text() == "metric,value\nsharpe,1.5\n"
    assert (copied_run / "artifacts" / "equity.csv").is_file()
    assert (copied_run / "artifacts" / "price_series.csv").is_file()
    assert (copied_run / "artifacts" / "strategy.pine").is_file()
    assert copied_run_id in (copied_run / "code" / "signal_engine.py").read_text()
    assert json.loads((copied_run / "req.json").read_text())["context"]["session_id"] == child.session_id
    assert "api_key" not in json.loads((copied_run / "req.json").read_text())
    assert "do-not-copy" not in (copied_run / "req.json").read_text()
    card = json.loads((copied_run / "run_card.json").read_text())
    assert card["run_dir"] == str(copied_run)
    assert [item["path"] for item in card["artifacts"]] == ["artifacts/metrics.csv"]
    assert card["tool_traces"][0]["args_hash"] == "a" * 64
    assert "arguments" not in card["tool_traces"][0]
    for forbidden in ("logs", "config.json", "artifacts/agent_trace.json", "artifacts/credentials.json", "artifacts/linked.csv"):
        assert not (copied_run / forbidden).exists()
    assert "do-not-copy" not in json.dumps(card)
    assert service.store.delete_session(source.session_id)
    assert (copied_run / "artifacts" / "metrics.csv").is_file()
    assert service.store.get_session(child.session_id) is not None


def test_title_config_lineage_and_requesting_owner_are_copied(runtime):
    service, goals, _, source = _source(runtime)
    source.config["session_id"] = source.session_id
    service.store.update_session(source)
    _, selected, _ = _turn(service, source.session_id, "selected")
    child = service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)
    stored = SessionStore(service.store.base_dir).get_session(child.session_id)
    assert stored.title == source.title
    assert stored.owner == ALICE
    assert stored.config == {
        "model": "research-model",
        "max_tokens": 2048,
        "strategy": {"engine": "daily", "token_budget": 5000},
        "nested": {"safe": 3},
        "session_id": child.session_id,
    }
    assert stored.forked_from_session_id == source.session_id
    assert stored.forked_from_message_id == selected.message_id
    assert stored.status.value == "active"
    assert source.session_id not in {stored.session_id, stored.last_attempt_id}
    assert child.session_id not in service._inflight
    assert child.session_id not in service._active_tasks
    assert child.session_id not in service._active_loops
    assert child.session_id not in service._background_handles


def test_current_goal_snapshot_has_new_ids_and_cannot_auto_continue(runtime):
    service, goals, _, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "selected", run_id="goal-run")
    # The ledger intentionally reflects fork time, including a run after the
    # historical message cutoff. Its artifacts must still be child-owned.
    _turn(service, source.session_id, "after-cutoff", run_id="later-goal-run")
    source_goal = goals.replace_goal(session_id=source.session_id, objective="Evaluate synthetic momentum.", criteria=["Check evidence"])
    for evidence_index in range(55):
        goals.append_evidence(
            session_id=source.session_id,
            goal_id=source_goal.goal_id,
            expected_goal_id=source_goal.goal_id,
            evidence=EvidenceInput(
                text=f"Synthetic evidence {evidence_index}.",
                criterion_id=goals.list_criteria(source_goal.goal_id)[0].criterion_id,
                claim_id=goals.list_claims(source_goal.goal_id)[0].claim_id,
                run_id="later-goal-run" if evidence_index == 0 else None,
                artifact_path=str(service.runs_dir / "later-goal-run" / "artifacts" / "metrics.csv") if evidence_index == 0 else None,
            ),
        )
    source_before = goals.get_goal_snapshot(source_goal.goal_id, evidence_limit=None)
    child = service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)
    child_snapshot = goals.get_current_snapshot(child.session_id)
    child_full_snapshot = goals.get_goal_snapshot(child_snapshot["goal"]["goal_id"], evidence_limit=None)
    assert child_snapshot["evidence_count"] == 55
    assert len(child_full_snapshot["evidence"]) == 55
    assert child_snapshot["goal"]["status"] == GoalStatus.PAUSED.value
    from src.goal.context import goal_needs_continuation

    assert goal_needs_continuation(child_snapshot) is False
    assert child_snapshot["goal"]["objective"] == source_before["goal"]["objective"]
    assert child_snapshot["goal"]["tokens_used"] == source_before["goal"]["tokens_used"]
    assert child_snapshot["goal"]["goal_id"] != source_goal.goal_id
    assert child_snapshot["claims"][0]["claim_id"] != source_before["claims"][0]["claim_id"]
    assert child_snapshot["criteria"][0]["criterion_id"] != source_before["criteria"][0]["criterion_id"]
    evidence = child_full_snapshot["evidence"][0]
    assert evidence["evidence_id"] != source_before["evidence"][0]["evidence_id"]
    assert evidence["goal_id"] == child_snapshot["goal"]["goal_id"]
    assert evidence["session_id"] == child.session_id
    assert evidence["criterion_id"] == child_snapshot["criteria"][0]["criterion_id"]
    assert evidence["claim_id"] == child_snapshot["claims"][0]["claim_id"]
    assert evidence["run_id"] != "later-goal-run"
    assert evidence["artifact_path"] == str(service.runs_dir / evidence["run_id"] / "artifacts" / "metrics.csv")
    assert (service.runs_dir / evidence["run_id"] / "artifacts" / "metrics.csv").is_file()
    assert goals.get_goal_snapshot(source_goal.goal_id, evidence_limit=None) == source_before
    assert goals.get_current_goal(source.session_id).status is GoalStatus.ACTIVE


def test_search_index_is_rebuilt_only_for_child(runtime):
    service, goals, index, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "searchable-needle", run_id="search-run")
    _turn(service, source.session_id, "excluded-needle")
    source_before = index.search("needle")
    child = service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)
    child_matches = [match for match in index.search("needle") if match.session_id == child.session_id]
    source_after = [match for match in index.search("needle") if match.session_id == source.session_id]
    assert len(child_matches) == 1
    assert child_matches[0].message_count == 2
    assert child_matches[0].title == source.title
    assert [(item.message_count, item.snippet) for item in source_after] == [(item.message_count, item.snippet) for item in source_before]


def test_publication_failure_cleans_runs_goal_index_and_partial_session(runtime, monkeypatch):
    service, goals, index, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "selected", run_id="failure-run")
    goal = goals.replace_goal(session_id=source.session_id, objective="Preserve source goal.", criteria=["Check"])
    source_before = goals.get_goal_snapshot(goal.goal_id, evidence_limit=None)
    original_replace = __import__("os").replace
    child_id = None

    # Capture the id from the staged session record at the final publication.
    def fail_and_capture(src, dst):
        nonlocal child_id
        if Path(dst).parent == service.store.base_dir and Path(src).name.startswith(f".{Path(dst).name}.fork-"):
            child_id = Path(dst).name
            raise OSError("simulated publication failure")
        return original_replace(src, dst)

    monkeypatch.setattr("src.session.fork.os.replace", fail_and_capture)
    with pytest.raises(OSError, match="simulated publication failure"):
        service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)
    assert child_id is not None
    assert service.store.get_session(child_id) is None
    assert list(service.store.base_dir.iterdir()) == [service.store.base_dir / source.session_id]
    assert [path.name for path in service.runs_dir.iterdir()] == ["failure-run"]
    assert goals.get_current_snapshot(child_id) is None
    assert goals.get_goal_snapshot(goal.goal_id, evidence_limit=None) == source_before
    assert all(match.session_id != child_id for match in index.search("selected"))


def test_search_failure_after_publication_rolls_back_the_child(runtime, monkeypatch):
    service, goals, index, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "selected", run_id="search-failure-run")
    goals.replace_goal(session_id=source.session_id, objective="Source goal survives.", criteria=["Check"])

    def fail_index(*args, **kwargs):
        raise RuntimeError("search unavailable")

    monkeypatch.setattr(index, "index_message", fail_index)
    with pytest.raises(RuntimeError, match="search unavailable"):
        service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)
    assert [item.session_id for item in service.store.list_sessions(limit=10)] == [source.session_id]
    assert [path.name for path in service.runs_dir.iterdir()] == ["search-failure-run"]
    assert goals.get_current_snapshot(source.session_id) is not None
    assert not list(service.store.base_dir.glob(".*.fork-*"))


def test_each_fork_request_creates_an_independent_child(runtime):
    service, goals, _, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "selected", run_id="duplicate-run")
    first = service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)
    second = service.fork_session(source.session_id, selected.message_id, owner=ALICE, goal_store=goals)
    first_run_id = service.store.get_messages(first.session_id)[-1].metadata["run_id"]
    second_run_id = service.store.get_messages(second.session_id)[-1].metadata["run_id"]
    assert first.session_id != second.session_id
    assert first_run_id != second_run_id
    assert first.forked_from_session_id == second.forked_from_session_id == source.session_id
    assert first.forked_from_message_id == second.forked_from_message_id == selected.message_id
    assert len(service.store.list_sessions(limit=10)) == 3
    assert len(list(service.runs_dir.iterdir())) == 3


def test_parent_and_child_delete_independently(runtime):
    service, _, _, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "selected")
    first = service.fork_session(source.session_id, selected.message_id)
    second = service.fork_session(source.session_id, selected.message_id)

    assert service.delete_session(first.session_id) is True
    assert service.get_session(source.session_id) is not None
    assert service.get_session(second.session_id) is not None

    assert service.delete_session(source.session_id) is True
    assert service.get_session(first.session_id) is None
    assert service.get_session(second.session_id) is not None


def test_attributable_owner_mismatch_is_rejected_but_legacy_owner_is_preserved(runtime):
    service, goals, _, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "selected")
    with pytest.raises(ForkAuthorizationError):
        service.fork_session(source.session_id, selected.message_id, owner=BOB, goal_store=goals)
    legacy = service.create_session(title="legacy", owner=Principal("shared", AuthMethod.SHARED_KEY))
    _, legacy_selected, _ = _turn(service, legacy.session_id, "legacy")
    child = service.fork_session(legacy.session_id, legacy_selected.message_id, owner=ALICE, goal_store=goals)
    assert child.owner == ALICE
    with pytest.raises(ForkSourceNotFound):
        service.fork_session("missing-source", selected.message_id, owner=ALICE, goal_store=goals)


def test_fork_route_requires_auth_and_maps_selection_and_owner_errors(runtime, monkeypatch):
    service, goals, _, source = _source(runtime)
    _, selected, _ = _turn(service, source.session_id, "selected")
    user = Message(session_id=source.session_id, role="user", content="not eligible")
    service.store.append_message(user)

    def validate(value, kind):
        del kind
        if not value or "/" in value:
            raise HTTPException(status_code=400, detail="invalid id")

    host = SimpleNamespace(
        require_auth=lambda: ALICE,
        require_event_stream_auth=lambda: None,
        _get_session_service=lambda: service,
        _validate_path_param=validate,
    )
    monkeypatch.setitem(sys.modules, "api_server", host)
    monkeypatch.setattr("src.api.sessions_routes._goal_store", goals)
    app = FastAPI()
    register_sessions_routes(app)
    client = TestClient(app)
    response = client.post(f"/sessions/{source.session_id}/fork", json={"message_id": selected.message_id})
    assert response.status_code == 201
    assert response.json()["forked_from_session_id"] == source.session_id
    assert response.json()["forked_from_message_id"] == selected.message_id
    assert client.post(f"/sessions/{source.session_id}/fork", json={"message_id": user.message_id}).status_code == 422
    assert client.post(f"/sessions/{source.session_id}/fork", json={"message_id": "missing"}).status_code == 422
    assert client.post("/sessions/missing/fork", json={"message_id": selected.message_id}).status_code == 404
    assert client.post(f"/sessions/{source.session_id}/fork", json={"message_id": "../escape"}).status_code == 422
    app.dependency_overrides[host.require_auth] = lambda: BOB
    assert client.post(f"/sessions/{source.session_id}/fork", json={"message_id": selected.message_id}).status_code == 403

    def deny_auth():
        raise HTTPException(status_code=401, detail="authentication required")

    app.dependency_overrides[host.require_auth] = deny_auth
    assert client.post(f"/sessions/{source.session_id}/fork", json={"message_id": selected.message_id}).status_code == 401
