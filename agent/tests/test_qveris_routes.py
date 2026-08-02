from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import qveris_routes
from src.tools import qveris_tool as qt


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(qt, "QVERIS_CONFIG_PATH", tmp_path / "qveris.json")
    monkeypatch.delenv("QVERIS_API_KEY", raising=False)
    monkeypatch.delenv("QVERIS_BASE_URL", raising=False)
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    monkeypatch.setattr(api_server, "_API_KEY", "")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_get_config_returns_redacted_unconfigured_shape(client: TestClient):
    response = client.get("/qveris/config")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "enabled": False,
        "base_url": qt.DEFAULT_BASE_URL,
        "api_key_masked": "",
        "mode": "free",
        "budget_credits_per_session": 50.0,
        "configured": False,
        "signup_url": qt.SIGNUP_URL,
        "invite_code": qt.INVITE_CODE,
    }


def test_put_config_persists_and_never_returns_plain_key(client: TestClient):
    response = client.put(
        "/qveris/config",
        json={
            "enabled": True,
            "base_url": "https://qveris.example/api",
            "api_key": "sk-secret-8TI",
            "mode": "paid",
            "budget_credits_per_session": 7.5,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["configured"] is True
    assert body["api_key_masked"] == "sk-s…8TI"
    assert "sk-secret-8TI" not in response.text
    assert qt.load_qveris_config().api_key == "sk-secret-8TI"


def test_put_config_rejects_bad_mode_and_bad_url(client: TestClient):
    bad_mode = client.put("/qveris/config", json={"mode": "live"})
    bad_url = client.put("/qveris/config", json={"base_url": "ftp://qveris.test"})

    assert bad_mode.status_code == 422
    assert bad_url.status_code == 422


def test_put_config_empty_key_preserves_existing_key(client: TestClient):
    qt.save_qveris_config(qt.QVerisConfig(enabled=True, api_key="sk-existing-abc"))

    response = client.put("/qveris/config", json={"api_key": "", "mode": "paid"})

    assert response.status_code == 200
    assert qt.load_qveris_config().api_key == "sk-existing-abc"
    assert response.json()["mode"] == "paid"


def test_status_unconfigured_is_fail_closed(client: TestClient):
    response = client.get("/qveris/status")

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["ok"] is False
    assert body["remaining_credits"] is None
    assert body["recent"] == []


def test_status_paid_mode_uses_qveris_search_and_usage_history(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    qt.save_qveris_config(qt.QVerisConfig(enabled=True, api_key="sk-live", mode="paid"))

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def search(self, query, *, limit):
            assert query == "status"
            assert limit == 1
            return {"remaining_credits": 88.0}

        def usage_history(self, **params):
            return {
                "events": [
                    {
                        "ts": "2026-07-07T00:00:00Z",
                        "tool_id": "tool_1",
                        "cost": 1.5,
                        "charge_outcome": "charged",
                    }
                ]
            }

    monkeypatch.setattr(qveris_routes, "QVerisClient", FakeClient)

    response = client.get("/qveris/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["remaining_credits"] == 88.0
    assert body["recent"] == [
        {
            "ts": "2026-07-07T00:00:00Z",
            "tool_id": "tool_1",
            "cost": 1.5,
            "charge_outcome": "charged",
        }
    ]


def test_status_free_mode_keeps_public_data_route_and_skips_qveris_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    qt.save_qveris_config(qt.QVerisConfig(enabled=True, api_key="sk-live", mode="free"))

    class FakeClient:
        def __init__(self, config):  # pragma: no cover - must not instantiate
            raise AssertionError("free mode must not contact QVeris")

    monkeypatch.setattr(qveris_routes, "QVerisClient", FakeClient)

    response = client.get("/qveris/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["remaining_credits"] is None
    assert body["recent"] == []
