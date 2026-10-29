"""Background tasks must stay inside the session or worker that started them.

A background task's result and its completion notification are runtime state
belonging to one conversation. They live in process-wide tables, so a second
session that reaches its next iteration first drains the first one's
notification and can list, read or cancel its tasks. These tests pin the
ownership boundary rather than any particular storage layout.
"""

from __future__ import annotations

import json
import sys
import time

import pytest

from src.tools import build_registry
from src.tools.background_tools import BackgroundManager, get_background_manager


def _echo_command(text: str) -> str:
    return f'"{sys.executable}" -c "print(\'{text}\')"'


def _run_to_completion(
    manager: BackgroundManager, command: str, *, timeout: float = 15.0
) -> str:
    payload = json.loads(manager.run(command))
    assert payload["status"] == "ok", payload
    task_id = payload["task_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = json.loads(manager.check(task_id))["status"]
        if status not in {"running", "cancelling"}:
            return task_id
        time.sleep(0.01)
    raise AssertionError(f"background task {task_id} did not reach a terminal state")


def _listed_task_ids(manager: BackgroundManager) -> list[str]:
    listing = manager.check()
    if listing == "No background tasks.":
        return []
    return [line.split(":", 1)[0] for line in listing.splitlines() if line]


class TestTwoConcurrentSessions:
    """The bug itself, expressed with the handle a host is given today."""

    def test_second_session_cannot_drain_the_first_ones_notification(self) -> None:
        session_a = get_background_manager()
        session_b = get_background_manager()

        _run_to_completion(session_a, _echo_command("belongs-to-a"))

        assert session_b.drain_notifications() == []
        assert [n["result"] for n in session_a.drain_notifications()] == [
            "belongs-to-a"
        ]

    def test_second_session_cannot_list_the_first_ones_tasks(self) -> None:
        session_a = get_background_manager()
        session_b = get_background_manager()

        task_id = _run_to_completion(session_a, _echo_command("private"))

        assert task_id not in _listed_task_ids(session_b)

    def test_second_session_cannot_cancel_the_first_ones_task(self) -> None:
        session_a = get_background_manager()
        session_b = get_background_manager()
        task_id = "still-running"

        session_a.tasks[task_id] = {
            "status": "running",
            "result": None,
            "command": "python slow.py",
            "exit_code": None,
            "process": None,
            "cancel_requested": False,
            "started_at": time.monotonic(),
            "owner_id": session_a.scope.owner_id,
            "attempt_id": session_a.scope.attempt_id,
        }

        result = json.loads(session_b.cancel(task_id))
        assert result == {"status": "error", "error": f"Unknown task {task_id}"}
        assert session_a.tasks[task_id]["status"] == "running"
        assert session_a.tasks[task_id]["cancel_requested"] is False

    def test_second_session_cannot_read_the_first_ones_result(self) -> None:
        session_a = get_background_manager()
        session_b = get_background_manager()

        task_id = _run_to_completion(session_a, _echo_command("private-result"))

        foreign = json.loads(session_b.check(task_id))
        assert foreign == {"status": "error", "error": f"Unknown task {task_id}"}
        assert "private-result" not in json.dumps(foreign)


class TestOwnerIsolation:
    def test_draining_preserves_shared_queue_identity_and_future_delivery(self) -> None:
        from src.tools.background_tools import BackgroundScope

        root = BackgroundManager(scope=BackgroundScope(owner_id="a"))
        later_attempt = root.for_scope(BackgroundScope(owner_id="a", attempt_id="later"))
        other = root.for_scope(BackgroundScope(owner_id="b"))
        _run_to_completion(root, _echo_command("a-first"))
        assert [n["result"] for n in root.drain_notifications()] == ["a-first"]
        assert later_attempt.drain_notifications() == []
        _run_to_completion(later_attempt, _echo_command("a-next"))
        _run_to_completion(other, _echo_command("b-next"))
        assert [n["result"] for n in root.drain_notifications()] == ["a-next"]
        assert [n["result"] for n in other.drain_notifications()] == ["b-next"]
        assert later_attempt.drain_notifications() == []

    def test_completion_notification_reaches_only_its_own_owner(self) -> None:
        from src.tools.background_tools import BackgroundScope

        root = BackgroundManager(scope=BackgroundScope(owner_id="session-a"))
        other = root.for_scope(BackgroundScope(owner_id="session-b"))

        _run_to_completion(root, _echo_command("alice-output"))

        assert [n["result"] for n in root.drain_notifications()] == ["alice-output"]
        assert other.drain_notifications() == []

    def test_owner_does_not_see_another_owners_task_listing(self) -> None:
        from src.tools.background_tools import BackgroundScope

        root = BackgroundManager(scope=BackgroundScope(owner_id="session-a"))
        other = root.for_scope(BackgroundScope(owner_id="session-b"))

        mine = _run_to_completion(root, _echo_command("a"))
        theirs = _run_to_completion(other, _echo_command("b"))

        assert mine != theirs
        assert set(_listed_task_ids(root)) == {mine}
        assert set(_listed_task_ids(other)) == {theirs}

    def test_later_attempt_of_same_owner_reads_the_earlier_task(self) -> None:
        from src.tools.background_tools import BackgroundScope

        first = BackgroundScope(owner_id="session-a", attempt_id="attempt-1")
        second = BackgroundScope(owner_id="session-a", attempt_id="attempt-2")
        root = BackgroundManager(scope=first)
        later = root.for_scope(second)

        task_id = _run_to_completion(root, _echo_command("carried-over"))

        record = json.loads(later.check(task_id))
        assert record["status"] == "completed"
        assert record["attempt_id"] == "attempt-1"
        assert len(later.drain_notifications()) == 1

    def test_shared_handles_keep_one_notification_queue_after_a_drain(self) -> None:
        from src.tools.background_tools import BackgroundScope

        root = BackgroundManager(scope=BackgroundScope(owner_id="session-a"))
        later = root.for_scope(BackgroundScope(owner_id="session-a", attempt_id="2"))
        sibling = root.for_scope(BackgroundScope(owner_id="session-b"))
        _run_to_completion(root, _echo_command("first"))
        assert [n["result"] for n in later.drain_notifications()] == ["first"]
        assert root.drain_notifications() == []
        _run_to_completion(root, _echo_command("second"))
        _run_to_completion(sibling, _echo_command("sibling"))
        assert [n["result"] for n in later.drain_notifications()] == ["second"]
        assert [n["result"] for n in sibling.drain_notifications()] == ["sibling"]

    def test_notification_is_delivered_once_across_repeated_drains(self) -> None:
        from src.tools.background_tools import BackgroundScope

        manager = BackgroundManager(scope=BackgroundScope(owner_id="session-a"))

        _run_to_completion(manager, _echo_command("once"))

        assert len(manager.drain_notifications()) == 1
        assert manager.drain_notifications() == []


class TestRegistryBinding:
    def test_filtered_registry_and_loop_keep_the_bound_handle(self) -> None:
        from types import SimpleNamespace
        from src.agent.loop import AgentLoop
        from src.tools import build_filtered_registry
        from src.tools.background_tools import BackgroundScope

        handle = BackgroundManager(scope=BackgroundScope(owner_id="filtered-owner"))
        registry = build_filtered_registry(["background_run", "check_background"],
                                           include_shell_tools=True, background_manager=handle)
        assert registry.background.scope == handle.scope
        assert registry.background is registry.get("check_background").background
        loop = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=1)
        assert loop._background_manager is registry.background

    def test_scope_is_absent_from_the_model_visible_tool_schema(self) -> None:
        registry = build_registry(include_shell_tools=True)

        for name in ("background_run", "check_background", "cancel_background"):
            tool = registry.get(name)
            assert tool is not None, name
            allowed = set(tool.parameters.get("properties", {}))
            assert allowed <= {"command", "task_id"}, (name, allowed)
            required = set(tool.parameters.get("required", []))
            assert not (required & {"owner_id", "session_id", "attempt_id"}), name

    def test_registry_tools_bind_the_scoped_handle_the_host_supplied(self) -> None:
        from src.tools.background_tools import BackgroundScope

        scope = BackgroundScope(owner_id="session-wired", attempt_id="attempt-1")
        host_handle = BackgroundManager(scope=scope)

        registry = build_registry(
            include_shell_tools=True,
            background_manager=host_handle,
            background_scope=scope,
        )

        run_tool = registry.get("background_run")
        assert run_tool is not None
        assert run_tool.background.scope == scope
        assert run_tool.background is registry.get("check_background").background

    def test_registry_without_an_explicit_scope_is_still_owner_scoped(self) -> None:
        first = build_registry(include_shell_tools=True)
        second = build_registry(include_shell_tools=True)

        first_scope = first.get("background_run").background.scope
        second_scope = second.get("background_run").background.scope

        assert first_scope != second_scope
        assert first_scope.owner_id.startswith("isolated:")

    def test_session_id_becomes_the_owner_when_no_scope_is_given(self) -> None:
        registry = build_registry(session_id="session-xyz", include_shell_tools=True)

        scope = registry.get("background_run").background.scope
        assert scope.owner_id == "session:session-xyz"

    def test_agent_loop_drains_the_same_handle_the_tools_write_to(self) -> None:
        from types import SimpleNamespace

        from src.agent.loop import AgentLoop
        from src.tools.background_tools import BackgroundScope

        scope = BackgroundScope(owner_id="session-wired", attempt_id="attempt-1")
        handle = BackgroundManager(scope=scope)
        registry = build_registry(
            include_shell_tools=True,
            background_manager=handle,
            background_scope=scope,
        )

        task_id = _run_to_completion(
            registry.get("background_run").background, _echo_command("wired")
        )

        loop = AgentLoop(registry=registry, llm=SimpleNamespace(), max_iterations=1)

        # The loop drains exactly the handle the tool wrote to, so the result
        # reaches this conversation and not another one.
        assert loop._background_manager is registry.background
        assert (
            json.loads(loop._background_manager.check(task_id))["status"] == "completed"
        )
        assert [
            n["result"] for n in loop._background_manager.drain_notifications()
        ] == ["wired"]
        stranger = BackgroundManager().for_scope(BackgroundScope(owner_id="stranger"))
        assert stranger.drain_notifications() == []

    def test_shell_tool_policy_is_unchanged_by_scoping(self) -> None:
        registry = build_registry()

        # Only the two process-control tools sit behind the shell opt-in.
        assert registry.get("background_run") is None
        assert registry.get("cancel_background") is None
        assert registry.get("check_background") is not None

        enabled = build_registry(include_shell_tools=True)
        for name in ("background_run", "check_background", "cancel_background"):
            assert enabled.get(name) is not None, name


class TestScopeContract:
    def test_scope_rejects_an_empty_owner(self) -> None:
        from src.tools.background_tools import BackgroundScope

        with pytest.raises(ValueError):
            BackgroundScope(owner_id="   ")

    def test_unowned_handles_are_not_a_shared_catch_all(self) -> None:
        from src.tools.background_tools import BackgroundScope

        first = get_background_manager()
        second = get_background_manager()

        assert first.scope != second.scope
        assert first.scope.owner_id.startswith("isolated:")
        assert second.scope.owner_id.startswith("isolated:")
        assert BackgroundScope(owner_id="explicit") != first.scope
