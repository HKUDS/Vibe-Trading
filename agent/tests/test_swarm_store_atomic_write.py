"""Regression tests for P13 — SwarmStore atomic write/read must survive the
Windows concurrent-access race (os.replace WinError 5/32) deterministically.

The behaviour tests drive the public ``SwarmStore`` API with a fake
``os.replace`` and therefore run on BOTH pre- and post-fix code:
- pre-fix ``_atomic_write`` calls replace once -> a single transient failure
  propagates and ``update_run`` raises (test FAILS).
- post-fix it retries the WinError-scoped transient -> ``update_run`` lands
  (test PASSES).

A non-transient error must still raise immediately (no masking), the budget
is bounded, and POSIX behaviour is unchanged (a plain OSError without
``winerror`` is never treated as transient).
"""

from __future__ import annotations

import os
import threading

import pytest

import src.swarm.store as store_mod
from src.swarm.models import SwarmRun
from src.swarm.store import SwarmStore
from tests.module_os_helpers import patch_module_os


def _winerr(code: int) -> PermissionError:
    e = PermissionError(f"simulated WinError {code}")
    e.winerror = code  # set even off-Windows so the test is deterministic
    return e


def _run(rid: str = "r") -> SwarmRun:
    return SwarmRun(id=rid, preset_name="demo", created_at="2026-01-01T00:00:00Z")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Keep retry tests instant + deterministic.
    monkeypatch.setattr(store_mod.time, "sleep", lambda *_a, **_k: None)


def test_replace_retries_transient_winerror_then_succeeds(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    store.create_run(_run())

    real = os.replace
    calls = {"n": 0}

    def flaky(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 3:  # fail the first 3 attempts with WinError 5
            raise _winerr(5)
        return real(src, dst, *a, **k)

    patch_module_os(monkeypatch, store_mod, replace=flaky)

    upd = _run()
    upd.final_report = "RETRIED-OK"
    store.update_run(upd)  # pre-fix: raises on first WinError; post-fix: retries

    assert calls["n"] >= 4
    assert store.load_run("r").final_report == "RETRIED-OK"


def test_non_transient_error_reraises_immediately(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    store.create_run(_run())
    calls = {"n": 0}

    def boom(src, dst, *a, **k):
        calls["n"] += 1
        raise _winerr(2)  # ERROR_FILE_NOT_FOUND — NOT in the transient set

    patch_module_os(monkeypatch, store_mod, replace=boom)
    with pytest.raises(OSError):
        store.update_run(_run())
    assert calls["n"] == 1, "non-transient must not be retried (no masking)"


def test_transient_budget_is_bounded(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    store.create_run(_run())
    calls = {"n": 0}

    def always(src, dst, *a, **k):
        calls["n"] += 1
        raise _winerr(32)  # ERROR_SHARING_VIOLATION, forever

    patch_module_os(monkeypatch, store_mod, replace=always)
    with pytest.raises(OSError):
        store.update_run(_run())
    assert calls["n"] == store_mod._REPLACE_ATTEMPTS


def test_load_run_retries_transient_read_then_parses(tmp_path, monkeypatch):
    store = SwarmStore(base_dir=tmp_path)
    store.create_run(_run())

    real_validate = SwarmRun.model_validate_json
    calls = {"n": 0}

    def flaky_validate(data, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise ValueError("simulated partial-read / parse mid-replace")
        return real_validate(data, *a, **k)

    monkeypatch.setattr(store_mod.SwarmRun, "model_validate_json", staticmethod(flaky_validate))
    got = store.load_run("r")
    assert got is not None and got.id == "r"
    assert calls["n"] >= 3


def test_load_run_missing_is_fast_none(tmp_path, monkeypatch):
    """Fast not-found path must stay immediate (guards get_run_result(bogus))."""
    store = SwarmStore(base_dir=tmp_path)

    def fail_read(*a, **k):
        raise AssertionError("read_text must not be called for a missing run")

    monkeypatch.setattr(store_mod.SwarmRun, "model_validate_json", staticmethod(lambda *a, **k: fail_read()))
    assert store.load_run("does-not-exist") is None


def test_concurrent_stores_writing_same_run_do_not_crash_or_clobber(tmp_path):
    """mcp_server._get_swarm_store() builds a fresh SwarmStore per tool call,
    so two pollers of the same run each hold their own _write_lock. A shared
    ".tmp" name let one writer's rename consume the other's unwritten temp
    file, raising FileNotFoundError for the loser (or silently discarding
    the winner's own content). Neither writer should ever raise here, and
    the surviving content must be one writer's whole payload, never a mix.
    """
    store_a = SwarmStore(base_dir=tmp_path)
    store_b = SwarmStore(base_dir=tmp_path)
    store_a.create_run(_run())

    run_a = _run()
    run_a.final_report = "FROM-A"
    run_b = _run()
    run_b.final_report = "FROM-B"

    start_gate = threading.Barrier(2)
    errors: list[Exception] = []

    def write(store: SwarmStore, run: SwarmRun) -> None:
        start_gate.wait()
        try:
            store.update_run(run)
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)

    t_a = threading.Thread(target=write, args=(store_a, run_a))
    t_b = threading.Thread(target=write, args=(store_b, run_b))
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    assert not errors, f"concurrent update_run raised: {errors!r}"
    assert store_a.load_run("r").final_report in {"FROM-A", "FROM-B"}


def test_concurrent_task_stores_saving_one_task_do_not_crash(tmp_path):
    """The TaskStore sibling of the SwarmStore race (#1536): two workers writing
    the same task file each used ``task-<id>.tmp``, so one rename could consume
    the other's temp file and raise FileNotFoundError."""
    from src.swarm.models import SwarmTask
    from src.swarm.task_store import TaskStore

    errors: list[Exception] = []

    def write(store: TaskStore, task: SwarmTask, gate: threading.Barrier) -> None:
        gate.wait()
        try:
            for _ in range(20):
                store.save_task(task)
        except Exception as exc:  # noqa: BLE001 - captured for the assertion below
            errors.append(exc)

    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="do x")
    for _ in range(10):
        gate = threading.Barrier(2)
        threads = [
            threading.Thread(target=write, args=(TaskStore(tmp_path), task, gate)) for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert not errors, f"concurrent save_task raised: {errors[:3]!r}"
    assert TaskStore(tmp_path).load_task("t1").id == "t1"
    assert not list((tmp_path / "tasks").glob("*.tmp")), "a temp file was left behind"


def test_posix_oserror_is_not_treated_transient():
    """POSIX no-op guard: a plain OSError (no winerror) is never transient,
    so off-Windows the retry loop runs exactly once — no behavior change."""
    from src.swarm.store import _is_transient_windows_error

    assert _is_transient_windows_error(OSError("posix")) is False
    assert _is_transient_windows_error(_winerr(13)) is False
    assert _is_transient_windows_error(_winerr(5)) is True
