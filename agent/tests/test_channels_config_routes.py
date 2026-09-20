"""API contracts for the IM channel configuration surface."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

import api_server
import src.api.channels_config_routes as config_routes


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.setattr(api_server, "_channel_runtime", None)
    monkeypatch.setattr(api_server, "_channel_bus", None)
    monkeypatch.setattr(api_server, "_channel_manager", None)
    return TestClient(api_server.app, client=("127.0.0.1", 50000))


def _write_agent_json(tmp_path: Path, channels: dict) -> None:
    (tmp_path / "agent.json").write_text(
        json.dumps({"channels": channels}),
        encoding="utf-8",
    )


def _read_agent_json(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "agent.json").read_text(encoding="utf-8"))


def test_schema_gives_dingtalk_full_fields_and_others_enabled_only(client) -> None:
    response = client.get("/channels/config-schema")

    assert response.status_code == 200
    entries = {entry["name"]: entry for entry in response.json()["channels"]}
    assert {"dingtalk", "telegram", "slack", "websocket"}.issubset(entries)

    dingtalk_fields = {field["key"]: field for field in entries["dingtalk"]["fields"]}
    assert set(dingtalk_fields) == {"enabled", "client_id", "client_secret"}
    assert dingtalk_fields["client_id"]["required"] is True
    assert dingtalk_fields["client_secret"]["secret"] is True
    assert dingtalk_fields["client_secret"]["required"] is True
    assert dingtalk_fields["client_id"]["description"]

    telegram_fields = {field["key"] for field in entries["telegram"]["fields"]}
    assert telegram_fields == {"enabled"}


def test_get_config_masks_secrets_and_hides_undeclared_values(client, tmp_path: Path) -> None:
    _write_agent_json(
        tmp_path,
        {
            "dingtalk": {
                "enabled": True,
                "client_id": "dingabcdef",
                "client_secret": "supersecretvalue",
            },
            "telegram": {"enabled": False, "bot_token": "123456789:abcdef"},
        },
    )

    response = client.get("/channels/config")

    assert response.status_code == 200
    channels = response.json()["channels"]
    assert channels["dingtalk"] == {
        "enabled": True,
        "client_id": "dingabcdef",
        "client_secret": "****alue",
    }
    # Unguided channels only expose the declared fields; the bot token must
    # never cross the wire.
    assert channels["telegram"] == {"enabled": False}


def test_get_config_returns_empty_string_for_unset_secret(client, tmp_path: Path) -> None:
    _write_agent_json(tmp_path, {"dingtalk": {"enabled": False}})

    response = client.get("/channels/config")

    assert response.status_code == 200
    assert response.json()["channels"]["dingtalk"]["client_secret"] == ""


def test_put_rejects_unknown_channel(client) -> None:
    response = client.put("/channels/config/nosuch", json={"values": {"enabled": True}})

    assert response.status_code == 404


def test_put_validates_field_types(client) -> None:
    bad_bool = client.put("/channels/config/dingtalk", json={"values": {"enabled": "yes"}})
    unknown_field = client.put("/channels/config/dingtalk", json={"values": {"bogus": 1}})
    bad_string = client.put(
        "/channels/config/dingtalk", json={"values": {"client_id": 42}}
    )

    assert bad_bool.status_code == 422
    assert unknown_field.status_code == 422
    assert bad_string.status_code == 422


def test_put_persists_section_and_returns_masked_config(client, tmp_path: Path) -> None:
    response = client.put(
        "/channels/config/dingtalk",
        json={
            "values": {
                "enabled": True,
                "client_id": "dingid123",
                "client_secret": "dingsecret123",
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["applied"] is False  # no runtime was ever built
    assert payload["config"]["client_secret"] == "****t123"

    stored = _read_agent_json(tmp_path)["channels"]["dingtalk"]
    assert stored == {
        "enabled": True,
        "client_id": "dingid123",
        "client_secret": "dingsecret123",
    }


def test_put_keeps_stored_secret_when_masked_value_echoed_back(
    client, tmp_path: Path
) -> None:
    _write_agent_json(
        tmp_path,
        {"dingtalk": {"enabled": False, "client_secret": "dingsecret123"}},
    )

    response = client.put(
        "/channels/config/dingtalk",
        json={"values": {"client_id": "dingid999", "client_secret": "****t123"}},
    )

    assert response.status_code == 200
    stored = _read_agent_json(tmp_path)["channels"]["dingtalk"]
    assert stored["client_id"] == "dingid999"
    assert stored["client_secret"] == "dingsecret123"


def test_put_refuses_enable_without_required_credentials(client) -> None:
    response = client.put("/channels/config/dingtalk", json={"values": {"enabled": True}})

    assert response.status_code == 422
    assert "client_id" in response.json()["detail"]


def test_put_hot_applies_to_existing_runtime(client, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeManager:
        async def reconfigure_channel(self, name: str) -> dict:
            calls.append(name)
            return {"enabled": True, "loaded": True, "running": True}

    monkeypatch.setattr(
        api_server, "_channel_runtime", SimpleNamespace(manager=FakeManager())
    )

    response = client.put(
        "/channels/config/dingtalk",
        json={
            "values": {
                "enabled": True,
                "client_id": "dingid123",
                "client_secret": "dingsecret123",
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == ["dingtalk"]
    assert payload["applied"] is True
    assert payload["status"]["running"] is True


def test_put_refuses_yaml_config(client, tmp_path: Path) -> None:
    (tmp_path / "agent.yaml").write_text("channels: {}\n", encoding="utf-8")

    response = client.put(
        "/channels/config/dingtalk", json={"values": {"enabled": False}}
    )

    assert response.status_code == 409
    assert "agent.yaml" in response.json()["detail"]


def test_toggle_flips_enabled_and_preserves_credentials(client, tmp_path: Path) -> None:
    _write_agent_json(
        tmp_path,
        {
            "dingtalk": {
                "enabled": False,
                "client_id": "dingid123",
                "client_secret": "dingsecret123",
            }
        },
    )

    turned_on = client.post("/channels/config/dingtalk/toggle", json={})
    assert turned_on.status_code == 200
    assert turned_on.json()["enabled"] is True

    stored = _read_agent_json(tmp_path)["channels"]["dingtalk"]
    assert stored["enabled"] is True
    assert stored["client_id"] == "dingid123"
    assert stored["client_secret"] == "dingsecret123"

    turned_off = client.post("/channels/config/dingtalk/toggle", json={"enabled": False})
    assert turned_off.status_code == 200
    assert turned_off.json()["enabled"] is False
    assert _read_agent_json(tmp_path)["channels"]["dingtalk"]["enabled"] is False


def test_toggle_refuses_enable_without_credentials(client, tmp_path: Path) -> None:
    _write_agent_json(tmp_path, {"dingtalk": {"enabled": False}})

    response = client.post("/channels/config/dingtalk/toggle", json={})

    assert response.status_code == 422


def test_toggle_rejects_unknown_channel(client) -> None:
    assert client.post("/channels/config/nosuch/toggle", json={}).status_code == 404


def test_test_endpoint_reports_missing_credentials(client, tmp_path: Path) -> None:
    _write_agent_json(tmp_path, {"dingtalk": {"enabled": False}})

    response = client.post("/channels/config/dingtalk/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["reason"] == "missing_credentials"


def test_test_endpoint_is_unsupported_for_other_channels(client) -> None:
    response = client.post("/channels/config/telegram/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["reason"] == "unsupported"


def test_test_endpoint_rejects_unknown_channel(client) -> None:
    assert client.post("/channels/config/nosuch/test").status_code == 404


def test_test_endpoint_ok_path(client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_agent_json(
        tmp_path,
        {"dingtalk": {"client_id": "dingid123", "client_secret": "dingsecret123"}},
    )

    async def fake_probe(client_id: str, client_secret: str):
        assert client_id == "dingid123"
        assert client_secret == "dingsecret123"
        return True, "ok", ""

    monkeypatch.setattr(config_routes, "_probe_dingtalk_credentials", fake_probe)

    response = client.post("/channels/config/dingtalk/test")

    assert response.status_code == 200
    assert response.json() == {
        "name": "dingtalk",
        "ok": True,
        "reason": "ok",
        "detail": "",
    }


def test_test_endpoint_failure_path_is_honest(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_agent_json(
        tmp_path,
        {"dingtalk": {"client_id": "dingid123", "client_secret": "wrong"}},
    )

    async def fake_probe(client_id: str, client_secret: str):
        return False, "invalid_credentials", "HTTP 400: InvalidParameter"

    monkeypatch.setattr(config_routes, "_probe_dingtalk_credentials", fake_probe)

    response = client.post("/channels/config/dingtalk/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["reason"] == "invalid_credentials"
    assert "InvalidParameter" in payload["detail"]


class _FakeResponse:
    def __init__(self, status_code: int, payload: object, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    async def post(self, url, json=None):
        if self._error is not None:
            raise self._error
        return self._response


def test_probe_dingtalk_maps_responses_to_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def run() -> None:
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda *a, **k: _FakeClient(_FakeResponse(200, {"accessToken": "t", "expireIn": 7200})),
        )
        assert await config_routes._probe_dingtalk_credentials("id", "secret") == (
            True,
            "ok",
            "",
        )

        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda *a, **k: _FakeClient(_FakeResponse(400, {}, "InvalidParameter")),
        )
        ok, reason, detail = await config_routes._probe_dingtalk_credentials("id", "bad")
        assert (ok, reason) == (False, "invalid_credentials")
        assert "400" in detail

        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            lambda *a, **k: _FakeClient(error=httpx.ConnectError("boom")),
        )
        ok, reason, detail = await config_routes._probe_dingtalk_credentials("id", "secret")
        assert (ok, reason) == (False, "network")
        assert "ConnectError" in detail

    asyncio.run(run())
