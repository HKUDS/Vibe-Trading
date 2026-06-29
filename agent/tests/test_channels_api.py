"""API contracts for IM channel runtime controls."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import api_server


class FakeSessionService:
    """SessionService placeholder for channel status tests."""


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    import src.channels.config as channel_config
    import src.channels.pairing.store as pairing_store

    monkeypatch.setattr(api_server, "_channel_runtime", None)
    monkeypatch.setattr(api_server, "_channel_bus", None)
    monkeypatch.setattr(api_server, "_channel_manager", None)
    monkeypatch.setattr(api_server, "_get_session_service", lambda: FakeSessionService())
    monkeypatch.setattr(
        channel_config,
        "load_channels_config",
        lambda: {
            "send_max_retries": 1,
            "websocket": {"enabled": False, "allow_from": ["*"]},
            "telegram": {"enabled": False},
            "slack": {"enabled": True},
        },
    )
    monkeypatch.setattr(pairing_store, "_store_path", lambda: tmp_path / "pairing.json")
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def test_channels_status_reports_all_configured_adapters(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/channels/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is False
    assert payload["channels"]["websocket"]["configured"] is True
    assert payload["channels"]["telegram"]["enabled"] is False
    assert payload["channels"]["slack"]["enabled"] is True
    assert "available" in payload["channels"]["slack"]


def test_channels_start_stop_are_controlled_runtime_actions(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    start = client.post("/channels/start")
    stop = client.post("/channels/stop")

    assert start.status_code == 200
    assert start.json()["status"] == "started"
    assert start.json()["running"] is True
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopped"
    assert stop.json()["running"] is False


def test_channels_pairing_command_uses_shared_store(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/channels/pairing/command",
        json={"channel": "telegram", "command": "list"},
    )

    assert response.status_code == 200
    assert response.json()["channel"] == "telegram"
    assert "No pending pairing requests" in response.json()["reply"]
