"""API contracts for IM channel runtime controls."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import api_server


class FakeSessionService:
    """SessionService placeholder for channel status tests."""


def _client(
    tmp_path: Path,
    monkeypatch,
    *,
    channels_config: dict[str, object] | None = None,
) -> TestClient:
    import src.channels.config as channel_config
    import src.channels.pairing.store as pairing_store

    config_path = tmp_path / "agent.json"
    config_path.write_text(
        json.dumps({"channels": channels_config or {}}),
        encoding="utf-8",
    )
    config = channel_config.load_channels_config(config_path)
    config.update(
        {
            "websocket": {"enabled": False, "allow_from": ["*"]},
            "telegram": {"enabled": False},
            "slack": {"enabled": True},
        }
    )

    monkeypatch.setattr(api_server, "_channel_runtime", None)
    monkeypatch.setattr(api_server, "_channel_bus", None)
    monkeypatch.setattr(api_server, "_channel_manager", None)
    monkeypatch.setattr(api_server, "_get_session_service", lambda: FakeSessionService())
    monkeypatch.setattr(channel_config, "load_channels_config", lambda: dict(config))
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
    assert "reply_timeout_s" not in payload["channels"]
    assert "send_max_retries" not in payload["channels"]
    assert api_server._channel_runtime is not None
    assert api_server._channel_runtime.config.reply_timeout_s == 600.0


def test_channels_runtime_uses_configured_reply_timeout(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, channels_config={"reply_timeout_s": 42})

    response = client.get("/channels/status")

    assert response.status_code == 200
    assert api_server._channel_runtime is not None
    assert api_server._channel_runtime.config.reply_timeout_s == 42


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


def test_weixin_qr_login_never_returns_credentials(tmp_path: Path, monkeypatch) -> None:
    from src.channels.weixin import WeixinChannel

    async def begin_qr_login(self):
        return {"status": "waiting", "qr_content": "https://weixin.example/scan"}

    async def poll_qr_login(self):
        self._token = "server-only-token"
        return {"status": "authenticated"}

    async def cancel_qr_login(self):
        return None

    monkeypatch.setattr(WeixinChannel, "begin_qr_login", begin_qr_login)
    monkeypatch.setattr(WeixinChannel, "poll_qr_login", poll_qr_login)
    monkeypatch.setattr(WeixinChannel, "cancel_qr_login", cancel_qr_login)
    client = _client(tmp_path, monkeypatch, channels_config={"weixin": {"enabled": True}})

    started = client.post("/channels/weixin/qr-login")

    assert started.status_code == 200
    start_payload = started.json()
    assert start_payload["status"] == "waiting"
    assert start_payload["qr_content"] == "https://weixin.example/scan"
    assert "token" not in json.dumps(start_payload).lower()

    completed = client.get(f"/channels/qr-login/{start_payload['session_id']}")

    assert completed.status_code == 200
    assert completed.json() == {"channel": "weixin", "status": "authenticated"}
    assert "token" not in completed.text.lower()


def test_qr_login_rejects_adapters_without_browser_qr_support(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, channels_config={"email": {"enabled": True}})

    response = client.post("/channels/email/qr-login")

    assert response.status_code == 400
    assert response.json()["detail"] == "Channel 'email' does not support QR login"
