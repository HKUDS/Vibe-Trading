"""Entry points share validation, persistence, authentication and failure semantics."""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from src.research_lab import service
from src.api.research_lab_routes import register_research_lab_routes
from src.tools.research_lab_tool import ResearchLabTool


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
    monkeypatch.setattr(service, "pid_is_running", lambda pid: False)
    assert service.get_job(state["id"])["status"] == "failed"
    assert "interrupted" in service.get_job(state["id"])["error"]


def test_poll_does_not_overwrite_completion_when_worker_exits(isolated, monkeypatch):
    state = service.create_job("factor_audit", {})
    path = service.job_root(state["id"]) / "study.json"
    completed = {**state, "status": "completed", "result": {"kind": "factor_audit", "count": 0}}

    def finish_before_exit(pid):
        service._write(path, completed)
        return False

    monkeypatch.setattr(service, "pid_is_running", finish_before_exit)
    assert service.get_job(state["id"]) == completed
    assert json.loads(path.read_text()) == completed


def test_report_survives_interruption_before_final_status(isolated, monkeypatch):
    import src.factors.audit

    report = {"kind": "factor_audit", "count": 0, "rows": [], "finding_count": 0}
    monkeypatch.setattr(src.factors.audit, "audit_factors", lambda ids: report)
    state = service.create_job("factor_audit", {})
    identifier = state["id"]
    write = service._write

    def interrupt_final_status(path, payload):
        if path.name == "study.json" and payload["status"] == "completed":
            raise SystemExit()
        write(path, payload)

    with monkeypatch.context() as worker:
        worker.setattr(service, "_write", interrupt_final_status)
        with pytest.raises(SystemExit):
            service.execute_job(identifier)

    root = service.job_root(identifier)
    assert json.loads((root / "report.json").read_text()) == report
    assert service.get_job(identifier)["status"] == "running"

    monkeypatch.setattr(service, "pid_is_running", lambda pid: False)
    app = FastAPI()
    register_research_lab_routes(app, lambda: None, lambda: None)
    with TestClient(app) as client:
        response = client.get(f"/api/research-lab/jobs/{identifier}/report")
        assert response.status_code == 200
        assert response.json() == report
    assert service.get_job(identifier)["status"] == "completed"


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


@pytest.mark.parametrize(
    "malformed",
    [None, [{"codes": ["AAPL.US"]}], {"codes": "AAPL.US"}, {"codes": [42]}, {"signal_parameters": ["fast", 8]}],
)
def test_catalog_http_keeps_valid_runs_beside_malformed_metadata(isolated, malformed):
    broken = isolated / "zz-broken-run"
    broken.mkdir()
    broken_config = broken / "config.json"
    broken_config.write_text(json.dumps(malformed), encoding="utf-8")
    (broken / "req.json").write_text('{"prompt":"another task"}', encoding="utf-8")
    valid = isolated / "backtest-run"
    valid.mkdir()
    (valid / "config.json").write_text(
        '{"codes":["AAPL.US"],"start_date":"2026-10-01","signal_parameters":{"fast":8}}', encoding="utf-8"
    )
    replay = isolated / "replay-run"
    replay.mkdir()
    (replay / "req.json").write_text('{"prompt":"saved task"}', encoding="utf-8")
    (replay / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    before = broken_config.read_bytes()

    app = FastAPI()
    register_research_lab_routes(app, lambda: None, lambda: None)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/research-lab/catalog")

    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()["runs"]}
    assert set(rows) == {"backtest-run", "replay-run"}
    assert rows["backtest-run"]["codes"] == ["AAPL.US"]
    assert rows["backtest-run"]["parameters"] == {"fast": 8}
    assert rows["replay-run"]["has_trace"] and not rows["replay-run"]["has_prices"]
    assert broken_config.read_bytes() == before


def test_catalog_checks_parameters_after_applying_saved_overrides(isolated, monkeypatch):
    monkeypatch.setattr(service, "constructor_defaults", lambda _source: {"threshold": float("nan")})

    paths = {}
    for name, parameters in (("default-only", {}), ("saved-override", {"threshold": 0.5})):
        root = isolated / name
        (root / "code").mkdir(parents=True)
        (root / "code/signal_engine.py").write_text("# synthetic strategy\n", encoding="utf-8")
        config = root / "config.json"
        config.write_text(json.dumps({"codes": ["AAPL.US"], "signal_parameters": parameters}), encoding="utf-8")
        paths[config] = config.read_bytes()
    replay = isolated / "replay"
    replay.mkdir()
    (replay / "req.json").write_text('{"prompt":"saved task"}', encoding="utf-8")

    rows = {row["id"]: row for row in service.catalog()["runs"]}
    assert set(rows) == {"saved-override", "replay"}
    assert rows["saved-override"]["parameters"] == {"threshold": 0.5}
    assert rows["replay"]["parameters"] == {}
    assert all(path.read_bytes() == content for path, content in paths.items())


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


@pytest.mark.parametrize(
    ("raw_content", "expected_fragment"),
    [
        (json.dumps([{"case_id": "research.example"}]), "binding[0].run_dir"),
        (json.dumps([{"case_id": "research.example", "run_dir": "/tmp/run"}, None]), "binding[1]"),
        (json.dumps({"case_id": "research.example", "run_dir": "/tmp/run"}), "JSON array"),
        ("{not valid json", ""),
    ],
)
def test_cli_replay_bindings_malformed_input_emits_json_error(tmp_path, capsys, raw_content, expected_fragment):
    from src.research_lab.cli import dispatch
    import argparse

    bindings_file = tmp_path / "bindings.json"
    bindings_file.write_text(raw_content, encoding="utf-8")
    code = dispatch(
        argparse.Namespace(
            lab_command="replay",
            bindings=bindings_file,
            run_dir=None,
            case_ids=None,
            trace_dir=None,
            json=True,
        )
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert isinstance(payload["error"], str) and payload["error"]
    if expected_fragment:
        assert expected_fragment in payload["error"]


def test_catalog_does_not_read_an_escaping_strategy(isolated):
    outside = isolated / "outside.py"
    outside.write_text("class SignalEngine:\n    def __init__(self, secret=123):pass\n")
    root = isolated / "run"
    (root / "code").mkdir(parents=True)
    (root / "config.json").write_text('{"codes":["AAPL.US"]}')
    (root / "code/signal_engine.py").symlink_to(outside)
    assert service.catalog()["runs"] == []
