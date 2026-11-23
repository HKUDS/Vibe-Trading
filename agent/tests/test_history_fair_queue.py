"""Durable admission and per-chunk turns without increasing worker budgets."""

import threading
import time

from src.data_gateway.history_store import HistoryStore
from .test_history_auto_resume import wait_for


def test_ten_starts_fit_existing_catalog_and_take_fair_chunk_turns(tmp_path):
    release = threading.Event()
    calls = []
    counts = {"active": 0, "peak": 0}

    def fetch(symbol, start, *args):
        counts["active"] += 1
        counts["peak"] = max(counts["peak"], counts["active"])
        calls.append(symbol)
        assert release.wait(5)
        counts["active"] -= 1
        return [{"symbol": symbol, "time": start, "close": 1}], {"coverage_verified": True}

    store = HistoryStore(tmp_path, fetcher=fetch)
    jobs = []
    symbols = [f"60000{i}.SH" for i in range(10)]
    try:
        for symbol in symbols:
            job = store.create(codes=[symbol], start_date="2026-09-01", end_date="2026-10-30", interval="5m")["id"]
            jobs.append(job)
            assert store.start(job)["state"] in {"queued", "running", "waiting"}
            assert len(store.futures) <= 4
        assert sum(s["state"] == "waiting" for s in store.status()) == 6
        store.cancel(jobs[2])  # Executor queue.
        store.cancel(jobs[7])  # Durable waiting queue.
        release.set()
        active = [s for i, s in enumerate(symbols) if i not in {2, 7}]
        for i, job in enumerate(jobs):
            if i not in {2, 7}:
                wait_for(store, job, lambda s: s["state"] == "complete", 15)
            else:
                assert store.status(job)["state"] == "paused"
        assert counts["peak"] == 1
        assert len(calls) == 16 and set(calls[:8]) == set(active)
        assert symbols[2] not in calls and symbols[7] not in calls
        assert store.settings()["reserved_bytes"] == 0
    finally:
        release.set()
        store.close()


def test_waiting_intent_reopens_but_pause_and_expiry_win(tmp_path):
    def fetch(symbol, start, *args):
        return [{"symbol": symbol, "time": start, "close": 1}], {"coverage_verified": True}

    store = HistoryStore(tmp_path, fetcher=fetch)
    jobs = [
        store.create(codes=["601398.SH"], start_date="2026-11-12", end_date="2026-11-12", interval="5m")["id"]
        for _ in range(3)
    ]
    with store.transaction() as db:
        for job in jobs:
            db.execute("UPDATE jobs SET state='waiting',auto_resume=1 WHERE id=?", (job,))
        db.execute("UPDATE jobs SET accessed=? WHERE id=?", (time.time() - 31 * 86400, jobs[2]))
    store.cancel(jobs[1])
    store.prune()
    store.close()
    reopened = HistoryStore(tmp_path, fetcher=fetch)
    try:
        wait_for(reopened, jobs[0], lambda s: s["state"] == "complete")
        assert reopened.status(jobs[1])["state"] == "paused"
        assert len(reopened.status()) == 2
    finally:
        reopened.close()
