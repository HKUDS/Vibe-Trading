"""Entry points share validation, persistence, authentication and failure semantics."""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from src.research_lab import service
from src.api.research_lab_routes import register_research_lab_routes
from src.tools.research_lab_tool import ResearchLabTool
from tests.module_os_helpers import patch_module_os


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    monkeypatch.setattr(service, "get_runs_dir", lambda: tmp_path)
    return tmp_path


def test_audit_job_and_tool_keep_full_report_and_bounded_response(isolated, monkeypatch):
    import src.factors.audit

    rows = [{"id": f"factor_{i}", "valid": True, "notes": "x" * 100} for i in range(100)]
    monkeypatch.setattr(
        src.factors.audit,
        "audit_factors",
        lambda ids: {"kind": "factor_audit", "count": 100, "rows": rows, "finding_count": 0},
    )
    state = service.run("factor_audit", {})
    assert state["status"] == "completed"
    assert service.get_job(state["id"])["result"]["rows"] == rows
    reply = ResearchLabTool().execute(action="show", request={"job_id": state["id"]})
    assert len(reply) <= 9000
    assert json.loads(reply)["summary"]["count"] == 100
    assert Path(json.loads(reply)["report_path"]).is_file()


def test_interrupted_worker_does_not_remain_running(isolated, monkeypatch):
    state = service.create_job("factor_audit", {})

    def missing(pid, signal):
        raise ProcessLookupError()

    patch_module_os(monkeypatch, service, kill=missing)
    assert service.get_job(state["id"])["status"] == "failed"
    assert "interrupted" in service.get_job(state["id"])["error"]


def test_running_job_is_not_executed_twice(isolated, monkeypatch):
    state = service.create_job("factor_audit", {})
    root = service.job_root(state["id"])
    (root / "execution.lock").touch()
    assert service.execute_job(state["id"])["status"] == "pending"


def test_catalog_includes_research_runs_without_backtest_config(isolated):
    root = isolated / "research-run"
    root.mkdir()
    (root / "req.json").write_text('{"prompt":"task"}')
    (root / "trace.jsonl").write_text("{}\n")
    row = service.catalog()["runs"][0]
    assert row["id"] == "research-run"
    assert row["has_trace"] and not row["has_prices"]


def test_http_authentication_submission_and_report_recovery(isolated, monkeypatch):
    import src.factors.audit

    monkeypatch.setattr(
        src.factors.audit,
        "audit_factors",
        lambda ids: {"kind": "factor_audit", "count": 0, "rows": [], "finding_count": 0},
    )
    app = FastAPI()

    def auth():
        raise HTTPException(401, "not authenticated")

    def write_auth():
        raise HTTPException(403, "write denied")

    register_research_lab_routes(app, auth, write_auth)
    with TestClient(app) as client:
        assert client.get("/api/research-lab/catalog").status_code == 401
        assert client.post("/api/research-lab/jobs", json={"action": "factor_audit", "request": {}}).status_code == 403
        app.dependency_overrides[auth] = lambda: None
        app.dependency_overrides[write_auth] = lambda: None
        assert client.post("/api/research-lab/jobs", json={"action": "bad", "request": {}}).status_code == 422
        response = client.post("/api/research-lab/jobs", json={"action": "factor_audit", "request": {}})
        assert response.status_code == 202
        identifier = response.json()["id"]
        # TestClient drains the thread task as the context closes; polling is
        # read-only and recovers the same durable service result.
    state = service.get_job(identifier)
    if state["status"] == "pending":
        state = service.execute_job(identifier)
    assert state["status"] == "completed"
    with TestClient(app) as client:
        assert client.get(f"/api/research-lab/jobs/{identifier}/report").json()["kind"] == "factor_audit"
        assert client.get("/api/research-lab/jobs/../other").status_code == 404


def test_cli_parameter_grid_and_replay_case_listing(capsys):
    from src.research_lab.cli import parameter_candidates, dispatch
    import argparse

    assert len(parameter_candidates(["fast=10,20", "slow=40,60"])) == 4
    with pytest.raises(ValueError):
        parameter_candidates(["x=1,2,3,4", "y=1,2,3,4"])
    assert dispatch(argparse.Namespace(lab_command="cases")) == 0
    assert len(json.loads(capsys.readouterr().out)["cases"]) >= 21


def test_catalog_does_not_read_an_escaping_strategy(isolated):
    outside = isolated / "outside.py"
    outside.write_text("class SignalEngine:\n    def __init__(self, secret=123):pass\n")
    root = isolated / "run"
    (root / "code").mkdir(parents=True)
    (root / "config.json").write_text('{"codes":["AAPL.US"]}')
    (root / "code/signal_engine.py").symlink_to(outside)
    assert service.catalog()["runs"] == []
