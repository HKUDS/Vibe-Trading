"""App lifecycle recovery preserves intent, leases, reservations and good chunks."""

import hashlib
import os
import threading

import pytest

from src.data_gateway.history_store import HistoryStore
from .test_history_auto_resume import create, rows, wait_for


@pytest.mark.parametrize("fetch_fails", [False, True])
def test_shutdown_running_and_queued_jobs_continue_but_manual_pause_does_not(tmp_path, fetch_fails):
    entered, release = threading.Event(), threading.Event()

    def fetch(*args):
        if args[0] == "MSFT.US":
            entered.set()
            assert release.wait(5)
            if fetch_fails:
                raise ConnectionError("shutdown interrupted transport")
        return rows(*args)

    first = HistoryStore(tmp_path, fetcher=fetch)
    active = first.create(
        codes=["AAPL.US", "MSFT.US", "TSLA.US"], start_date="2026-11-12", end_date="2026-11-12", interval="1D"
    )["id"]
    queued, paused, untouched = create(first), create(first), create(first)
    first.start(active)
    assert entered.wait(3)
    prefix = hashlib.sha256(first._path(active, 0).read_bytes()).hexdigest()
    first.start(queued)
    first.start(paused)
    first.cancel(paused)
    first.close()
    release.set()
    wait_for(first, active, lambda s: s["state"] == "failed")
    assert first.status(queued)["retry_at"] > 0
    assert first.status(paused)["state"] == "paused" and not first.status(paused)["auto_resume"]
    assert first.settings()["reserved_bytes"] == 0
    calls = []
    second = HistoryStore(tmp_path, fetcher=lambda *a: calls.append(a[0]) or rows(*a))
    try:
        wait_for(second, active, lambda s: s["state"] == "complete")
        wait_for(second, queued, lambda s: s["state"] == "complete")
        assert second.status(paused)["state"] == "paused"
        assert second.status(untouched)["state"] == "paused"
        assert calls.count("AAPL.US") == 1  # Queued job only, not the completed prefix.
        assert hashlib.sha256(second._path(active, 0).read_bytes()).hexdigest() == prefix
    finally:
        release.set()
        first.close()
        second.close()


def test_manual_pause_running_at_shutdown_wins(tmp_path):
    entered, release = threading.Event(), threading.Event()

    def fetch(*args):
        entered.set()
        assert release.wait(5)
        raise ConnectionError("interrupted")

    store = HistoryStore(tmp_path, fetcher=fetch)
    job = create(store)
    store.start(job)
    assert entered.wait(3)
    store.cancel(job)
    store.close()
    release.set()
    wait_for(store, job, lambda s: s["state"] == "paused")
    other = HistoryStore(tmp_path, fetcher=rows)
    try:
        other._resume_due()
        state = other.status(job)
        assert state["state"] == "paused" and state["rows"] == 0
        assert not state["retry_at"] and not state["auto_resume"]
    finally:
        other.close()


def test_app_startup_recovers_without_a_history_request(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.data_gateway import history_store as module
    from src.data_gateway.api import register_gateway_routes

    seed = HistoryStore(tmp_path, fetcher=rows)
    active, paused, permanent = create(seed), create(seed), create(seed)
    with seed.transaction() as db:
        db.execute("UPDATE jobs SET state='running',auto_resume=1,reserved=1234 WHERE id=?", (active,))
        db.execute("UPDATE jobs SET state='failed',auto_resume=0,error='invalid coverage' WHERE id=?", (permanent,))
    seed.close()
    monkeypatch.setattr(module, "_instance", None)
    monkeypatch.setattr(module, "history_directory", lambda: tmp_path)
    monkeypatch.setattr(module, "HistoryStore", lambda p: HistoryStore(p, fetcher=rows))
    app = FastAPI()
    register_gateway_routes(app, lambda: None)
    with TestClient(app):
        recovered = module._instance
        assert recovered is not None  # No history HTTP endpoint has been visited.
        wait_for(recovered, active, lambda s: s["state"] == "complete")
        assert recovered.status(paused)["state"] == "paused"
        assert recovered.status(permanent)["state"] == "failed"
    assert module._instance is None and recovered.stop.is_set()


def test_startup_without_catalog_does_not_create_storage(tmp_path, monkeypatch):
    from src.data_gateway import history_store as module

    monkeypatch.setattr(module, "history_directory", lambda: tmp_path / "absent")
    monkeypatch.setattr(module, "get_history_store", lambda: pytest.fail("must stay lazy without existing data"))
    module.start_history_recovery()
    assert not (tmp_path / "absent").exists()


def test_recovery_does_not_steal_a_live_queued_job(tmp_path):
    store = HistoryStore(tmp_path, fetcher=rows)
    job = create(store)
    with store.transaction() as db:
        db.execute("UPDATE jobs SET state='queued',owner=?,auto_resume=1 WHERE id=?", (os.getpid(), job))
    other = HistoryStore(tmp_path, fetcher=rows)
    try:
        assert other.status(job)["state"] == "queued"
        assert not other.status(job)["retry_at"]
    finally:
        store.cancel(job)
        store.close()
        other.close()


def test_close_waits_for_cooperative_checkpoint_within_existing_budget(tmp_path):
    from src.data_gateway.history_router import HistoryPaused

    entered = threading.Event()

    def fetch(*args):
        entered.set()
        store.stop.wait(3)
        # A real callback needs a brief scheduling turn after the stop signal.
        threading.Event().wait(0.1)
        raise HistoryPaused()

    store = HistoryStore(tmp_path, fetcher=fetch)
    job = create(store)
    store.start(job)
    assert entered.wait(3)
    store.close()
    state = store.status(job)
    assert state["state"] == "failed" and state["retry_at"] > 0
    assert state["reserved"] == 0
    assert all(future.done() for future in store.futures.values())
