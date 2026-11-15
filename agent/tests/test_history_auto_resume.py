"""Durable retry dispatch, user intent and recovery without client resume loops."""

from contextlib import contextmanager
import hashlib
import os
import threading
import time

import pytest

from src.data_gateway.history_store import HistoryCapacityError, HistoryStore
from src.data_gateway.history_router import HistoryRouteError


def wait_for(store, job, predicate, seconds=12):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        state = store.status(job)
        if predicate(state):
            return state
        time.sleep(0.02)
    raise AssertionError(store.status(job))


def rows(symbol, start, end, interval):
    return [{"symbol": symbol, "time": start, "close": 1}], {"source": "fixture", "coverage_verified": True}


def create(store):
    return store.create(codes=["AAPL.US", "MSFT.US"], start_date="2026-11-12", end_date="2026-11-12", interval="1D")[
        "id"
    ]


@pytest.fixture
def store(tmp_path):
    value = HistoryStore(tmp_path, fetcher=rows)
    value.retry_base = 0.2
    value.retry_max = 1
    yield value
    value.close()


def test_transient_failure_resumes_without_another_start_and_keeps_good_chunks(store):
    restored = threading.Event()
    calls = []

    def fetch(*args):
        calls.append(args[0])
        if args[0] == "MSFT.US" and not restored.is_set():
            raise ConnectionError("offline")
        return rows(*args)

    store.fetcher = fetch
    job = create(store)
    store.start(job)  # The only client start.
    waiting = wait_for(store, job, lambda s: s["retry_at"] > 0)
    assert waiting["state"] == "failed" and waiting["completed_chunks"] == 1
    assert waiting["reserved"] == 0 and waiting["retry_count"] == 1
    digest = hashlib.sha256(store._path(job, 0).read_bytes()).hexdigest()
    restored.set()
    done = wait_for(store, job, lambda s: s["state"] == "complete")
    assert done["rows"] == 2 and not done["retry_at"] and not done["auto_resume"]
    assert calls.count("AAPL.US") == 1
    assert hashlib.sha256(store._path(job, 0).read_bytes()).hexdigest() == digest
    assert store.status()[0]["retry_count"] == 0


def test_pause_wins_over_due_retry_and_catalog_restart(store):
    job = create(store)
    with store.transaction() as db:
        db.execute("UPDATE jobs SET state='failed',auto_resume=1,retry_at=? WHERE id=?", (time.time() + 60, job))
    store.cancel(job)
    calls = []
    store.fetcher = lambda *a: calls.append(a) or rows(*a)
    store._resume_due()
    store.start(job, _automatic=True)  # Simulate a dispatcher that selected before pause.
    other = HistoryStore(store.directory, fetcher=store.fetcher)
    try:
        other._resume_due()
        assert other.status(job)["state"] == "paused"
        assert not other.status(job)["auto_resume"] and not calls
    finally:
        other.close()


def test_retry_schedule_survives_restart_and_two_dispatchers_claim_once(store):
    job = create(store)
    with store.transaction() as db:
        db.execute(
            "UPDATE jobs SET state='failed',auto_resume=1,retry_at=?,retry_count=2 WHERE id=?", (time.time() + 60, job)
        )
    store.close()
    calls, entered, release = [], threading.Event(), threading.Event()

    def fetch(*args):
        calls.append(args[0])
        entered.set()
        release.wait(3)
        return rows(*args)

    a = HistoryStore(store.directory, fetcher=fetch)
    b = HistoryStore(store.directory, fetcher=fetch)
    try:
        with a.transaction() as db:
            db.execute("UPDATE jobs SET retry_at=? WHERE id=?", (time.time() - 1, job))
        a._resume_due()
        assert entered.wait(2)
        b._resume_due()
        assert len(calls) == 1
        release.set()
        wait_for(a, job, lambda s: s["state"] == "complete")
        assert calls == ["AAPL.US", "MSFT.US"]
    finally:
        release.set()
        a.close()
        b.close()


def test_stale_dispatcher_does_not_take_queued_workers_lease(store, monkeypatch):
    job = create(store)
    with store.transaction() as db:
        db.execute(
            "UPDATE jobs SET state='queued',auto_resume=1,owner=? WHERE id=?",
            (os.getpid(), job),
        )
    other = HistoryStore(store.directory, fetcher=rows)
    original_lease = other.lease
    worker_errors = []

    @contextmanager
    def race_worker(job_id, timeout=0):
        with original_lease(job_id, timeout):
            # Force the queued worker to enter while a stale dispatcher is
            # checking the same job. That check must not hold its worker lease.
            try:
                store.run(job_id)
            except ValueError as exc:
                worker_errors.append(exc)
            yield

    monkeypatch.setattr(other, "lease", race_worker)
    try:
        assert other.start(job, _automatic=True)["state"] == "queued"
        assert not worker_errors
        assert store.run(job)["state"] == "complete"
    finally:
        other.close()


@pytest.mark.parametrize(
    "error",
    [
        ValueError("bad calendar"),
        HistoryRouteError([{"source": "x", "status": "unavailable", "reason": "bad currency"}]),
    ],
)
def test_invalid_data_never_schedules_automatic_retry(store, error):
    def fetch(*args):
        raise error

    store.fetcher = fetch
    job = create(store)
    store.start(job)
    state = wait_for(store, job, lambda s: s["state"] == "failed")
    assert state["retry_at"] == 0
    assert state["retry_count"] == 0


def test_backoff_is_capped_and_waiting_job_does_not_block_healthy_job(store):
    store.retry_base = 2
    store.retry_max = 3

    def fetch(*args):
        if args[0] == "AAPL.US":
            raise ConnectionError("offline")
        return rows(*args)

    store.fetcher = fetch
    job = create(store)
    with store.transaction() as db:
        db.execute("UPDATE jobs SET auto_resume=1,retry_count=9 WHERE id=?", (job,))
    state = store.run(job)
    assert state["retry_count"] == 10 and 2 < state["retry_at"] - time.time() <= 3
    healthy = store.create(codes=["MSFT.US"], start_date="2026-11-12", end_date="2026-11-12", interval="1D")["id"]
    store.start(healthy)
    assert wait_for(store, healthy, lambda s: s["state"] == "complete", 2)["rows"] == 1
    store.cancel(job)


def test_waiting_prefix_is_not_evicted_for_quota_and_delete_cancels_schedule(store):
    job = create(store)
    store.run(job)
    prefix = store._path(job, 0).read_bytes()
    with store.transaction() as db:
        db.execute("UPDATE jobs SET state='failed',auto_resume=1,retry_at=? WHERE id=?", (time.time() + 60, job))
    with pytest.raises(HistoryCapacityError), store.transaction() as db:
        store._prune(db, required=store.settings()["quota_bytes"])
    assert store.status(job)["retry_at"] > 0
    assert store._path(job, 0).read_bytes() == prefix
    store.delete(job)
    store._resume_due()
    assert store.status() == []


def test_waiting_retry_still_expires_after_retention(store):
    job = create(store)
    with store.transaction() as db:
        db.execute(
            "UPDATE jobs SET state='failed',auto_resume=1,retry_at=?,accessed=? WHERE id=?",
            (time.time() + 60, time.time() - 31 * 86400, job),
        )
    store.prune()
    assert store.status() == []


@pytest.mark.parametrize(
    "reason,retryable",
    [
        ("network_failure", True),
        ("network_cooldown", True),
        ("source_busy", True),
        ("timeout", True),
        ("no_data", False),
    ],
)
def test_router_distinguishes_recoverable_acquisition_from_missing_history(monkeypatch, reason, retryable):
    from types import SimpleNamespace
    from src.data_gateway import history_router
    from src.data_gateway.routing import NetworkRouter

    gateway = SimpleNamespace(
        router=NetworkRouter(),
        bars=lambda **kw: {
            "ok": False,
            "error": reason,
            "data": {"_diagnostics": {"AAPL.US": [{"reason": reason}]}},
        },
    )
    monkeypatch.setattr("src.data_gateway.get_gateway", lambda: gateway)
    monkeypatch.setattr(history_router, "candidates", lambda *a: ["yahoo"])
    with pytest.raises(HistoryRouteError) as caught:
        history_router.fetch_chunk("AAPL.US", "2026-11-12", "2026-11-12", "1D")
    assert caught.value.retryable is retryable
