"""Integration tests for FastAPI endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


STRATEGY_PAYLOAD = {
    "schema_version": 1,
    "strategy_id": "strat_btc_001",
    "symbol": "BTC",
    "generated_at": "2024-01-01T00:00:00Z",
    "pipeline_stage": 2,
    "spec": {
        "strategy_id": "strat_btc_001",
        "symbol": "BTC",
        "spec_yaml": "runs/strat_btc_001/config.yaml",
    },
}


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    manifests = tmp_path / "research" / "manifests" / "strat_btc_001"
    manifests.mkdir(parents=True)
    (manifests / "manifest.json").write_text(
        json.dumps(STRATEGY_PAYLOAD), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def client(repo_root: Path):
    os.environ["REPO_ROOT"] = str(repo_root)
    import importlib
    import main as main_module
    importlib.reload(main_module)
    from main import app
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /api/strategies
# ---------------------------------------------------------------------------

def test_list_strategies(client):
    r = client.get("/api/strategies")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["strategy_id"] == "strat_btc_001"
    assert data[0]["symbol"] == "BTC"
    assert data[0]["pipeline_stage"] == 2
    assert data[0]["gate_pass"] is None  # no gate block yet


def test_list_strategies_empty(tmp_path):
    os.environ["REPO_ROOT"] = str(tmp_path)
    import importlib, main as main_module
    importlib.reload(main_module)
    from main import app
    with TestClient(app) as c:
        r = c.get("/api/strategies")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /api/strategies/{id}
# ---------------------------------------------------------------------------

def test_get_strategy(client):
    r = client.get("/api/strategies/strat_btc_001")
    assert r.status_code == 200
    data = r.json()
    assert data["strategy_id"] == "strat_btc_001"
    assert data["spec"]["symbol"] == "BTC"


def test_get_strategy_404(client):
    r = client.get("/api/strategies/nonexistent")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()
