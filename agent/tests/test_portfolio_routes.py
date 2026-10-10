from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import portfolio_routes


class _Service:
    def __init__(self, **kwargs):
        self.progress_callback = kwargs.get("progress_callback")

    def latest(self):
        return {"snapshot_id": "latest"}

    def refresh(self):
        return {"snapshot_id": "new"}

    def settings(self):
        return {
            "display_currency": "USD",
            "sources": [{"connection_id": "ibkr", "enabled": True}],
        }

    def save_settings(self, payload):
        return payload

    def sources(self):
        return [{"profile_id": "ibkr-live-official-mcp-readonly"}]

    def history(self, limit):
        return [{"id": "one", "limit": limit}]

    def reconnect_target(self, source_id):
        return object(), object(), object()

    def export_csv(self):
        return "broker,symbol\nibkr,AAPL\n"

    def analysis_context(self, snapshot_id=None):
        return None if snapshot_id == "gone" else {"privacy": "sanitized", "snapshot_id": snapshot_id}


def test_portfolio_routes_are_readonly_and_return_expected_shapes(monkeypatch):
    monkeypatch.setattr(portfolio_routes, "PortfolioService", _Service)

    class _SuccessfulProcess:
        def wait(self, timeout):
            return 0

    monkeypatch.setattr(
        portfolio_routes.subprocess,
        "Popen",
        lambda *args, **kwargs: _SuccessfulProcess(),
    )
    app = FastAPI()
    portfolio_routes.register_portfolio_routes(app)
    client = TestClient(app)

    assert client.get("/api/portfolio").json()["snapshot"]["snapshot_id"] == "latest"
    assert (
        client.post("/api/portfolio/refresh").json()["snapshot"]["snapshot_id"] == "new"
    )
    refresh = client.get("/api/portfolio/refresh-status").json()["refresh"]
    assert refresh["running"] is False
    assert refresh["sources"] == refresh["brokers"]
    assert (
        client.get("/api/portfolio/history?limit=12").json()["history"][0]["limit"]
        == 12
    )
    settings = client.get("/api/portfolio/settings").json()
    assert settings["settings"]["display_currency"] == "USD"
    saved = client.put(
        "/api/portfolio/settings",
        json={
            "display_currency": "CNY",
            "sources": [
                {
                    "connection_id": "ibkr",
                    "label": "Main",
                    "enabled": True,
                    "order": 0,
                    "include_cash": True,
                }
            ],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["settings"]["display_currency"] == "CNY"
    reconnect = client.post("/api/portfolio/sources/ibkr/reconnect")
    assert reconnect.status_code == 202
    for _ in range(50):
        reconnect_status = client.get("/api/portfolio/reconnect-status").json()[
            "reconnect"
        ]
        if not reconnect_status["running"]:
            break
        time.sleep(0.01)
    assert reconnect_status["source_id"] == "ibkr"
    assert reconnect_status["status"] == "authorized"
    assert (
        client.get("/api/portfolio/analysis-context").json()["context"]["privacy"]
        == "sanitized"
    )
    exported = client.get("/api/portfolio/export.csv")
    assert exported.status_code == 200
    assert "ibkr,AAPL" in exported.text


def test_analysis_context_route_pins_snapshot_and_never_falls_back(monkeypatch):
    monkeypatch.setattr(portfolio_routes, "PortfolioService", _Service)
    app = FastAPI()
    portfolio_routes.register_portfolio_routes(app)
    client = TestClient(app)
    response = client.get("/api/portfolio/analysis-context?snapshot_id=first")
    assert response.status_code == 200
    assert response.json()["context"]["snapshot_id"] == "first"
    assert client.get("/api/portfolio/analysis-context?snapshot_id=gone").status_code == 404
    assert client.get("/api/portfolio/analysis-context?snapshot_id=").status_code == 422


def test_concurrent_portfolio_reconnect_returns_conflict(monkeypatch):
    monkeypatch.setattr(portfolio_routes, "PortfolioService", _Service)
    app = FastAPI()
    portfolio_routes.register_portfolio_routes(app)
    client = TestClient(app)

    assert portfolio_routes._RECONNECT_OPERATION_LOCK.acquire(blocking=False)
    try:
        response = client.post("/api/portfolio/sources/ibkr/reconnect")
    finally:
        portfolio_routes._RECONNECT_OPERATION_LOCK.release()

    assert response.status_code == 409
    assert response.json()["detail"] == "portfolio reconnect already running"


def test_reconnect_timeout_stops_worker_and_releases_operation_lock(monkeypatch):
    class _TimedOutProcess:
        def __init__(self):
            self.terminated = False

        def wait(self, timeout):
            if not self.terminated:
                raise portfolio_routes.subprocess.TimeoutExpired("oauth", timeout)
            return -15

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.terminated = True

        def poll(self):
            return None

    process = _TimedOutProcess()
    monkeypatch.setattr(
        portfolio_routes.subprocess, "Popen", lambda *args, **kwargs: process
    )
    assert portfolio_routes._RECONNECT_OPERATION_LOCK.acquire(blocking=False)

    portfolio_routes._run_reconnect("ibkr")

    state = portfolio_routes._reconnect_snapshot()
    assert state["running"] is False
    assert state["status"] == "timeout"
    assert process.terminated is True
    assert portfolio_routes._RECONNECT_OPERATION_LOCK.acquire(blocking=False)
    portfolio_routes._RECONNECT_OPERATION_LOCK.release()
