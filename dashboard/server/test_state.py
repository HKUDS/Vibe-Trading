"""Tests for state.py and promote/demote endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from state import demote, is_promoted, load_state, promote


STRATEGY_PAYLOAD = {
    "schema_version": 1,
    "strategy_id": "strat_btc_001",
    "symbol": "BTC",
    "generated_at": "2024-01-01T00:00:00Z",
    "pipeline_stage": 2,
    "spec": {
        "strategy_id": "strat_btc_001",
        "symbol": "BTC",
        "spec_yaml": "research/strategies/strat_btc_001.yaml",
    },
}

STRATEGY_GATE_PASS = {
    **STRATEGY_PAYLOAD,
    "pipeline_stage": 4,
    "gate": {
        "thresholds": [
            {"name": "min_sharpe", "threshold": 1.5, "actual": 2.0, "passed": True, "fatal": False},
        ],
        "overall_pass": True,
        "fatal_fail": False,
        "red_flags": [],
    },
}

STRATEGY_GATE_FATAL = {
    **STRATEGY_PAYLOAD,
    "pipeline_stage": 4,
    "gate": {
        "thresholds": [
            {"name": "oos_sharpe_positive", "threshold": 0.0, "actual": -0.5, "passed": False, "fatal": True},
        ],
        "overall_pass": False,
        "fatal_fail": True,
        "red_flags": [],
    },
}

STRATEGY_GATE_SOFT_FAIL = {
    **STRATEGY_PAYLOAD,
    "pipeline_stage": 4,
    "gate": {
        "thresholds": [
            {"name": "min_sharpe", "threshold": 1.5, "actual": 1.2, "passed": False, "fatal": False},
        ],
        "overall_pass": False,
        "fatal_fail": False,
        "red_flags": [],
    },
}


# ---------------------------------------------------------------------------
# state.py unit tests
# ---------------------------------------------------------------------------

def test_load_state_missing(tmp_path):
    assert load_state(tmp_path) == {"promoted": {}}


def test_promote_and_is_promoted(tmp_path):
    (tmp_path / "research").mkdir()
    yaml = tmp_path / "research" / "s.yaml"
    yaml.write_text("name: test", encoding="utf-8")
    promote(tmp_path, tmp_path, "strat_001", "research/s.yaml")
    assert is_promoted(tmp_path, "strat_001") is True


def test_demote(tmp_path):
    (tmp_path / "research").mkdir()
    (tmp_path / "research" / "s.yaml").write_text("name: test", encoding="utf-8")
    promote(tmp_path, tmp_path, "strat_001", "research/s.yaml")
    assert demote(tmp_path, "strat_001") is True
    assert is_promoted(tmp_path, "strat_001") is False


def test_demote_not_promoted(tmp_path):
    assert demote(tmp_path, "strat_001") is False


def test_promote_exports_yaml(tmp_path):
    (tmp_path / "research").mkdir()
    yaml = tmp_path / "research" / "s.yaml"
    yaml.write_text("name: test", encoding="utf-8")
    promote(tmp_path, tmp_path, "strat_001", "research/s.yaml")
    assert (tmp_path / "data" / "exports" / "s.yaml").exists()


def test_promote_with_override_reason(tmp_path):
    record = promote(tmp_path, tmp_path, "strat_001", "research/nope.yaml", override_reason="known risk")
    assert record["override"]["reason"] == "known risk"


# ---------------------------------------------------------------------------
# FastAPI endpoint tests
# ---------------------------------------------------------------------------

def _make_client(tmp_path: Path, payload: dict) -> TestClient:
    manifests = tmp_path / "research" / "manifests" / "strat_btc_001"
    manifests.mkdir(parents=True)
    (manifests / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    os.environ["REPO_ROOT"] = str(tmp_path)
    import importlib, main as main_module
    importlib.reload(main_module)
    from main import app, DASHBOARD_DIR
    # Point DASHBOARD_DIR to tmp_path/dashboard for isolation
    main_module.DASHBOARD_DIR = tmp_path / "dashboard"
    (tmp_path / "dashboard").mkdir(exist_ok=True)
    return TestClient(app)


def test_promote_no_gate(tmp_path):
    client = _make_client(tmp_path, STRATEGY_PAYLOAD)
    r = client.post("/api/strategies/strat_btc_001/promote")
    assert r.status_code == 201
    assert r.json()["strategy_id"] == "strat_btc_001"


def test_promote_gate_pass(tmp_path):
    client = _make_client(tmp_path, STRATEGY_GATE_PASS)
    r = client.post("/api/strategies/strat_btc_001/promote")
    assert r.status_code == 201


def test_promote_fatal_gate_blocked(tmp_path):
    client = _make_client(tmp_path, STRATEGY_GATE_FATAL)
    r = client.post("/api/strategies/strat_btc_001/promote")
    assert r.status_code == 422
    assert "fatal" in r.json()["detail"].lower()


def test_promote_soft_fail_no_reason(tmp_path):
    client = _make_client(tmp_path, STRATEGY_GATE_SOFT_FAIL)
    r = client.post("/api/strategies/strat_btc_001/promote")
    assert r.status_code == 422


def test_promote_soft_fail_with_reason(tmp_path):
    client = _make_client(tmp_path, STRATEGY_GATE_SOFT_FAIL)
    r = client.post(
        "/api/strategies/strat_btc_001/promote",
        json={"override_reason": "acceptable risk"},
    )
    assert r.status_code == 201


def test_promote_404(tmp_path):
    client = _make_client(tmp_path, STRATEGY_PAYLOAD)
    r = client.post("/api/strategies/ghost/promote")
    assert r.status_code == 404


def test_demote_endpoint(tmp_path):
    client = _make_client(tmp_path, STRATEGY_PAYLOAD)
    client.post("/api/strategies/strat_btc_001/promote")
    r = client.delete("/api/strategies/strat_btc_001/promote")
    assert r.status_code == 200
    assert r.json()["demoted"] is True


def test_demote_not_promoted_endpoint(tmp_path):
    client = _make_client(tmp_path, STRATEGY_PAYLOAD)
    r = client.delete("/api/strategies/strat_btc_001/promote")
    assert r.status_code == 404
