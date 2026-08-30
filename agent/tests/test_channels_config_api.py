"""Tests for the IM channel configuration API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api_server
from src.api import channels_routes


@pytest.fixture()
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "agent.json"
    monkeypatch.setattr("src.config.paths.get_config_path", lambda config_path=None: path)
    return path


@pytest.fixture()
def client() -> TestClient:
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_get_channels_config_redacts_secrets(client: TestClient, config_path: Path) -> None:
    config_path.write_text(
        json.dumps({
            "channels": {
                "telegram": {"enabled": True, "token": "secret-token", "allowFrom": ["123", "456"]}
            }
        }),
        encoding="utf-8",
    )

    response = client.get("/channels/config")

    assert response.status_code == 200
    body = response.json()
    telegram = next(item for item in body["channels"] if item["channel"] == "telegram")
    assert telegram["configured"] is True
    assert telegram["enabled"] is True
    assert telegram["token_configured"] is True
    assert telegram["allowlist"] == ["123", "456"]
    assert "secret-token" not in response.text


def test_get_channels_config_marks_unconfigured_channels(client: TestClient, config_path: Path) -> None:
    config_path.write_text("{}", encoding="utf-8")

    response = client.get("/channels/config")

    assert response.status_code == 200
    body = response.json()
    assert body["channels"]
    assert all(item["configured"] is False for item in body["channels"])
    assert all(item["enabled"] is False for item in body["channels"])


def test_put_channels_config_writes_enabled_token_allowlist(client: TestClient, config_path: Path) -> None:
    response = client.put(
        "/channels/config",
        json={"channel": "telegram", "enabled": True, "token": "new-token", "allowlist": "111, 222"},
    )

    assert response.status_code == 200
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    section = payload["channels"]["telegram"]
    assert section["enabled"] is True
    assert section["token"] == "new-token"
    assert section["allowFrom"] == ["111", "222"]
    assert "new-token" not in response.text


def test_put_channels_config_rejects_invalid_channel_id(client: TestClient, config_path: Path) -> None:
    response = client.put("/channels/config", json={"channel": "../evil", "enabled": True})

    assert response.status_code == 400
    assert not config_path.exists()


def test_put_channels_config_requires_json_agent_config(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("src.config.paths.get_config_path", lambda config_path=None: tmp_path / "agent.yaml")

    response = client.put(
        "/channels/config",
        json={"channel": "telegram", "enabled": True, "token": "x"},
    )

    assert response.status_code == 400


def test_channel_test_endpoint_validates_channel_id(client: TestClient, config_path: Path) -> None:
    response = client.post("/channels/config/test", json={"channel": "bad id!"})

    assert response.status_code == 400


def test_channel_test_endpoint_uses_stored_token(
    client: TestClient, config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path.write_text(
        json.dumps({"channels": {"telegram": {"enabled": True, "token": "stored-token"}}}),
        encoding="utf-8",
    )

    async def fake_probe(channel: str, token: str | None) -> dict:
        assert token == "stored-token"
        return {
            "status": "ok",
            "channel": channel,
            "checks": {"adapter_available": True, "token_present": True, "live_probe": "telegram_getme"},
        }

    monkeypatch.setattr(channels_routes, "_probe_channel", fake_probe)

    response = client.post("/channels/config/test", json={"channel": "telegram"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
