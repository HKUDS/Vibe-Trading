"""Owner liveness checks behave the same on POSIX and Windows."""

import json
import subprocess
import sys

from src.utils.process import pid_is_running


def exited_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_running_and_exited_processes_are_told_apart():
    with subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read(); sys.exit(17)"],
        stdin=subprocess.PIPE,
    ) as child:
        assert child.stdin is not None
        try:
            assert pid_is_running(child.pid)
            assert child.poll() is None
        finally:
            child.stdin.close()
            returncode = child.wait(timeout=10)
        assert returncode == 17
        assert not pid_is_running(child.pid)


def test_research_job_whose_owner_exited_is_reported_interrupted(tmp_path, monkeypatch):
    from src.research_lab import service

    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setattr(service, "get_runs_dir", lambda: tmp_path)
    state = service.create_job("factor_audit", {})
    path = service.job_root(state["id"]) / "study.json"
    path.write_text(json.dumps({**state, "owner_pid": exited_pid()}), encoding="utf-8")
    result = service.get_job(state["id"])
    assert result["status"] == "failed"
    assert "interrupted" in result["error"]


def test_history_recovery_releases_a_queued_job_whose_owner_exited(tmp_path):
    from src.data_gateway.history_store import HistoryStore

    from .test_history_auto_resume import create, rows

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
