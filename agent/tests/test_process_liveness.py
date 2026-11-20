"""Owner liveness checks behave the same on POSIX and Windows."""

import json
import os
import subprocess
import sys

from src.data_gateway.history_store import HistoryStore
from src.research_lab import service
from src.utils.process import pid_is_running
from .test_history_auto_resume import create, rows


def exited_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_running_and_exited_processes_are_told_apart():
    assert pid_is_running(os.getpid())
    assert not pid_is_running(exited_pid())


def test_research_job_whose_owner_exited_is_reported_interrupted(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setattr(service, "get_runs_dir", lambda: tmp_path)
    state = service.create_job("factor_audit", {})
    path = service.job_root(state["id"]) / "study.json"
    path.write_text(json.dumps({**state, "owner_pid": exited_pid()}), encoding="utf-8")
    result = service.get_job(state["id"])
    assert result["status"] == "failed"
    assert "interrupted" in result["error"]


def test_history_recovery_releases_a_queued_job_whose_owner_exited(tmp_path):
    store = HistoryStore(tmp_path, fetcher=rows)
    job = create(store)
    with store.transaction() as db:
        db.execute("UPDATE jobs SET state='queued',owner=?,auto_resume=0 WHERE id=?", (exited_pid(), job))
    store.close()
    reopened = HistoryStore(tmp_path, fetcher=rows)
    try:
        assert reopened.status(job)["state"] == "paused"
    finally:
        reopened.close()
