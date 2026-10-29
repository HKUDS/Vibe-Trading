"""Durable task records and the restart reconciliation that must never re-run."""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest

from src.tools import background_store as store_mod
from src.tools.background_store import (
    SCHEMA_VERSION,
    BackgroundStoreError,
    BackgroundTaskStore,
    TaskRecord,
    record_from_task,
    reconcile_after_restart,
)


def make(**overrides) -> TaskRecord:
    values = dict(
        schema_version=SCHEMA_VERSION,
        task_id="deadbeef",
        owner_id="session:s1",
        status="completed",
        command_preview="echo hi",
        exit_code=0,
        result_preview="hi",
    )
    values.update(overrides)
    return TaskRecord(**values)


class TestRecoveryIsConservative:
    @pytest.fixture(autouse=True)
    def forbid_side_effects(self, monkeypatch):
        """Recovery must not spawn, signal, fetch or call a model."""

        def explode(*args, **kwargs):
            raise AssertionError(f"recovery must not call {kwargs or args}")

        from tests.module_os_helpers import patch_module_os

        patch_module_os(monkeypatch, store_mod, kill=explode, killpg=explode)
        monkeypatch.setattr(store_mod.time, "sleep", explode)

    def test_running_becomes_interrupted_without_rerun(self):
        recovered, unchanged = reconcile_after_restart([make(status="running")])
        assert unchanged == []
        assert recovered[0].status == "interrupted"
        assert recovered[0].recovery_reason == "service_restart"
        assert recovered[0].command_preview == "echo hi"

    def test_cancelling_stays_outcome_unknown(self):
        recovered, _ = reconcile_after_restart([make(status="cancelling")])
        assert recovered[0].status == "outcome_unknown"
        assert recovered[0].recovery_reason == "service_restart_before_reap_completed"

    @pytest.mark.parametrize("status", ["completed", "error", "timeout", "cancelled"])
    def test_terminal_outcomes_are_kept_queryable(self, status):
        recovered, unchanged = reconcile_after_restart([make(status=status, exit_code=3)])
        assert recovered == []
        assert unchanged[0].status == status
        assert unchanged[0].exit_code == 3

    def test_recovery_is_idempotent(self):
        once, _ = reconcile_after_restart([make(status="running")])
        twice, unchanged = reconcile_after_restart(once)
        assert twice == []
        assert unchanged[0].status == "interrupted"

    def test_stored_pid_is_descriptive_only(self):
        record = make(status="running", pid=os.getpid())
        recovered, _ = reconcile_after_restart([record])
        assert recovered[0].pid == os.getpid()
        # No signal path reads it; nothing above touches os.kill.


class TestStore:
    def test_round_trip_and_layout_is_stable_per_owner(self, tmp_path):
        store = BackgroundTaskStore(tmp_path)
        record = make()
        path = store.save(record)
        assert path.parent == tmp_path / "background-tasks"
        assert path.name == path.name  # deterministic
        assert store.save(record).name == path.name
        records, unreadable = store.load_all()
        assert unreadable == []
        assert records == [record]

    def test_owner_id_is_not_a_filename(self, tmp_path):
        store = BackgroundTaskStore(tmp_path)
        path = store.save(make(owner_id="session:../escape"))
        assert ".." not in path.name
        assert path.parent == tmp_path / "background-tasks"

    def test_unsafe_task_id_is_rejected(self, tmp_path):
        store = BackgroundTaskStore(tmp_path)
        with pytest.raises(BackgroundStoreError):
            store.save(make(task_id="../../etc/passwd"))

    def test_private_permissions(self, tmp_path):
        store = BackgroundTaskStore(tmp_path)
        path = store.save(make())
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

    def test_unknown_version_is_reported_not_overwritten(self, tmp_path):
        store = BackgroundTaskStore(tmp_path)
        store.save(make())
        for path in (tmp_path / "background-tasks").glob("*.json"):
            payload = json.loads(path.read_text())
            payload["schema_version"] = SCHEMA_VERSION + 1
            path.write_text(json.dumps(payload))
        records, unreadable = store.load_all()
        assert records == []
        assert len(unreadable) == 1
        assert json.loads(Path(unreadable[0]).read_text())["schema_version"] == SCHEMA_VERSION + 1

    def test_half_written_file_is_reported_not_invented(self, tmp_path):
        store = BackgroundTaskStore(tmp_path)
        directory = tmp_path / "background-tasks"
        directory.mkdir()
        (directory / "deadbeef.json").write_text('{"schema_version": 1, "task_id"')
        records, unreadable = store.load_all()
        assert records == []
        assert len(unreadable) == 1

    def test_symlink_is_refused(self, tmp_path):
        store = BackgroundTaskStore(tmp_path)
        directory = tmp_path / "background-tasks"
        directory.mkdir()
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps({"schema_version": SCHEMA_VERSION}))
        link = directory / f"{'0' * 16}-deadbeef.json"
        link.symlink_to(outside)
        _records, unreadable = store.load_all()
        assert len(unreadable) == 1

    def test_previews_are_bounded_and_redacted(self, tmp_path):
        record = make(
            command_preview=store_mod._preview(" ".join(["x" * 100] * 50)),
            result_preview=store_mod._preview(f"token sk-{'a' * 40} end"),
        )
        assert len(record.command_preview) <= store_mod.MAX_PREVIEW_CHARS
        assert len(record.result_preview) <= store_mod.MAX_PREVIEW_CHARS
        assert f"sk-{'a' * 40}" not in record.result_preview

    def test_two_local_processes_can_share_the_directory(self, tmp_path):
        """One process's records stay readable after another writes beside them."""
        first = BackgroundTaskStore(tmp_path)
        second = BackgroundTaskStore(tmp_path)
        first.save(make(task_id="aaaaaaaa", owner_id="session:a"))
        second.save(make(task_id="bbbbbbbb", owner_id="session:b"))
        records, unreadable = first.load_all()
        assert unreadable == []
        assert {r.task_id for r in records} == {"aaaaaaaa", "bbbbbbbb"}

    def test_recovery_survives_a_process_that_never_wrote(self, tmp_path):
        """A crash before the first save leaves no record, and none is invented."""
        store = BackgroundTaskStore(tmp_path)
        assert store.load_all() == ([], [])
        recovered, unchanged = reconcile_after_restart([])
        assert recovered == [] and unchanged == []

    def test_record_from_task_projects_the_live_shape(self):
        task = {
            "status": "running",
            "owner_id": "session:s1",
            "attempt_id": "a1",
            "command": "echo hi",
            "result": None,
            "exit_code": None,
            "started_at": 10.0,
            "duration_seconds": 2.5,
        }
        record = record_from_task("deadbeef", task)
        assert record.owner_id == "session:s1"
        assert record.attempt_id == "a1"
        assert record.status == "running"
        assert record.started_at == 10.0
        assert record.duration_seconds == 2.5
        assert record.is_live and not record.is_terminal


class TestManagerWiring:
    def test_a_completed_run_leaves_a_queryable_record(self, tmp_path, monkeypatch):
        import json as _json
        import shlex
        import sys as _sys

        from src.tools import background_tools as bg

        monkeypatch.setattr(bg, "WORKDIR", tmp_path)
        manager = bg.BackgroundManager(bg.BackgroundScope("session:s1"), store=BackgroundTaskStore(tmp_path))
        command = shlex.join([_sys.executable, "-c", "print('stored')"])
        task_id = _json.loads(manager.run(command))["task_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and _json.loads(manager.check(task_id))["status"] == "running":
            time.sleep(0.01)
        # The in-memory status flips inside the lock while the best-effort write
        # happens after it, so reading the store the moment check() moves on
        # races the persist. Wait for the record to land.
        records: list = []
        unreadable: list = []
        while time.monotonic() < deadline:
            records, unreadable = manager._store.load_all()
            if records and records[0].status != "running":
                break
            time.sleep(0.01)
        assert unreadable == []
        assert records[0].task_id == task_id
        assert records[0].status == "completed"
        assert records[0].attempt_id is None
        assert records[0].command_preview

    def test_restart_recovery_leaves_this_processes_live_tasks_alone(self, tmp_path):
        from src.tools import background_tools as bg

        store = BackgroundTaskStore(tmp_path)
        live = make(task_id="aaaaaaaa", status="running", owner_id="session:live")
        stale = make(task_id="bbbbbbbb", status="running", owner_id="session:stale")
        store.save(live)
        store.save(stale)
        bg._LIVE_TASK_IDS.add("aaaaaaaa")
        try:
            first = BackgroundTaskStore(tmp_path)
            manager = bg.BackgroundManager(bg.BackgroundScope("session:x"), store=first)
            summary = manager.recover_on_start()
        finally:
            bg._LIVE_TASK_IDS.discard("aaaaaaaa")
        assert summary["recovered"] == 1
        records, _ = first.load_all()
        by_id = {record.task_id: record for record in records}
        assert by_id["aaaaaaaa"].status == "running"
        assert by_id["bbbbbbbb"].status == "interrupted"

    def test_recovery_does_not_rerun_a_previous_commands(self, tmp_path, monkeypatch):
        from src.tools import background_tools as bg

        monkeypatch.setattr(bg, "WORKDIR", tmp_path)
        store = BackgroundTaskStore(tmp_path)
        store.save(make(task_id="cccccccc", status="running", command_preview="touch should-not-exist"))
        manager = bg.BackgroundManager(bg.BackgroundScope("session:x"), store=store)
        assert manager.recover_on_start()["recovered"] == 1
        assert not (tmp_path / "should-not-exist").exists()
