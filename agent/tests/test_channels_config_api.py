"""API contracts for the web IM channel-config surface (Task 5).

Covers the contract from https://github.com/HKUDS/Vibe-Trading/issues/1519:
``GET /channels/config``, ``PUT /channels/config/{name}`` and
``POST /channels/{name}/test`` — secret masking, the 422-before-write ordering
(bad credentials never reach disk), hot-apply modes (hot_swapped / reset /
deferred), per-channel lock serialization, and the never-persist guarantee of
the test endpoint. No secret value may appear in any response body.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

import api_server
from src.api import channels_config_routes as routes
from src.api import state as api_state
from src.channels.dingtalk import DINGTALK_AVAILABLE, DingTalkChannel

CLIENT_ID = "ding-client-id-1234567890"
STORED_SECRET = "stored-secret-abcdefghij"
UNSAVED_SECRET = "unsaved-secret-xyz987654321"

# Captured before any test monkeypatches httpx, so repeated injections in a
# single test still wrap the real client (test_dingtalk_connection_test idiom).
_REAL_ASYNC_CLIENT = httpx.AsyncClient


class FakeSessionService:
    """SessionService placeholder so a runtime build never touches real state."""


class FakeManager:
    """Records ``reload_channel`` calls; optional delay exposes lock overlap."""

    def __init__(self, *, delay: float = 0.0, fail: bool = False) -> None:
        self.reload_calls: list[tuple[str, dict | None]] = []
        self.active = 0
        self.max_active = 0
        self._delay = delay
        self._fail = fail

    async def reload_channel(self, name: str, section: dict | None) -> dict[str, Any]:
        if self._fail:
            raise RuntimeError("reload boom")
        self.reload_calls.append((name, section))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self._delay:
                await asyncio.sleep(self._delay)
        finally:
            self.active -= 1
        return {"loaded": bool(section and section.get("enabled"))}


class FakeRuntime:
    """Stands in for ChannelRuntime: an authoritative running flag + manager."""

    def __init__(self, *, running: bool, manager: FakeManager | None = None) -> None:
        self._running = running
        self.manager = manager if manager is not None else FakeManager()
        self.start_calls: list[bool] = []
        self.stop_calls: list[bool] = []

    def status(self) -> dict[str, Any]:
        return {"running": self._running, "channels": {}}

    async def start(self, *, start_manager: bool = True) -> None:
        self.start_calls.append(start_manager)

    async def stop(self) -> None:
        self.stop_calls.append(True)
        self._running = False


def _write_agent_config(
    tmp_path: Path, channels: dict[str, Any], *, suffix: str = ".json"
) -> Path:
    path = tmp_path / f"agent{suffix}"
    payload = {"channels": channels}
    if suffix == ".json":
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    channels: dict[str, Any] | None = None,
    runtime: Any = None,
    suffix: str = ".json",
) -> tuple[TestClient, Path]:
    """Point the config root at *tmp_path* and mount the app test client."""
    config_path = _write_agent_config(tmp_path, channels or {}, suffix=suffix)
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.setattr(api_server, "_channel_runtime", runtime)
    monkeypatch.setattr(api_server, "_channel_bus", None)
    monkeypatch.setattr(api_server, "_channel_manager", None)
    monkeypatch.setattr(api_server, "_get_session_service", lambda: FakeSessionService())
    return TestClient(api_server.app, client=("127.0.0.1", 50000)), config_path


@pytest.fixture(autouse=True)
def _fresh_locks():
    """Give every test unbound locks (asyncio.Lock binds to a loop on contention)."""
    routes._channel_locks.clear()
    routes._runtime_lock = asyncio.Lock()
    yield
    routes._channel_locks.clear()
    routes._runtime_lock = asyncio.Lock()


def _dingtalk_section(**overrides: Any) -> dict[str, Any]:
    section: dict[str, Any] = {
        "enabled": False,
        "client_id": CLIENT_ID,
        "client_secret": STORED_SECRET,
        "allow_from": ["*"],
    }
    section.update(overrides)
    return section


def _inject_mock_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Any
) -> list[httpx.Request]:
    """Route the probe's fresh ``httpx.AsyncClient`` through a MockTransport."""
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(recording_handler)
    real_client_cls = _REAL_ASYNC_CLIENT

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return requests


# --------------------------------------------------------------------------- #
# GET /channels/config
# --------------------------------------------------------------------------- #


def test_get_masks_secrets_and_reports_writable(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )

    response = client.get("/channels/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["config_path"] == path.name
    assert payload["writable"] is True
    assert payload["runtime_running"] is False

    entry = payload["channels"]["dingtalk"]
    assert entry["display_name"] == "DingTalk"
    assert entry["supports_test"] is True
    assert entry["sdk_available"] is DINGTALK_AVAILABLE
    assert entry["values"]["client_id"] == CLIENT_ID
    assert entry["values"]["enabled"] is False
    assert "client_secret" not in entry["values"]
    assert entry["secrets"]["client_secret"] == {"set": True, "masked": "****ghij"}
    keys = {field["key"] for field in entry["fields"]}
    assert keys >= {"client_id", "client_secret", "allow_from"}
    assert "enabled" not in keys
    client_id_hint = next(f for f in entry["fields"] if f["key"] == "client_id")
    assert client_id_hint["help_key"] == "settings.channels.fields.dingtalk.client_id"
    assert client_id_hint["secret"] is False

    assert STORED_SECRET not in response.text
    # GET is read-only: it must not build the runtime singleton.
    assert api_server._channel_runtime is None


def test_get_excludes_non_channel_helper_modules(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch)

    payload = client.get("/channels/config").json()

    assert "targets" not in payload["channels"]
    assert "config_meta" not in payload["channels"]
    assert "dingtalk" in payload["channels"]


def test_get_reports_not_writable_for_yaml_config(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path,
        monkeypatch,
        channels={"dingtalk": _dingtalk_section()},
        suffix=".yaml",
    )

    response = client.get("/channels/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["writable"] is False
    assert payload["config_path"] == path.name
    assert payload["channels"]["dingtalk"]["values"]["client_id"] == CLIENT_ID
    assert STORED_SECRET not in response.text


def test_get_reports_runtime_running_from_live_status(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(
        tmp_path,
        monkeypatch,
        channels={"dingtalk": _dingtalk_section()},
        runtime=FakeRuntime(running=True),
    )

    payload = client.get("/channels/config").json()

    assert payload["runtime_running"] is True


def test_get_backfills_adapter_defaults_for_unconfigured_channel(
    tmp_path: Path, monkeypatch
) -> None:
    """An empty on-disk section still yields the adapter's default values.

    Regression (found by live QQ E2E): a never-configured channel returned
    empty ``values``, so the generic form seeded "" into typed fields
    (``msg_format`` Literal, ``download_chunk_size`` int) and any Test/Save
    died on validation_error before the fix.
    """
    client, _ = _client(tmp_path, monkeypatch, channels={})

    qq = client.get("/channels/config").json()["channels"]["qq"]

    assert qq["values"]["msg_format"] == "plain"
    assert qq["values"]["download_chunk_size"] == 262144
    assert qq["values"]["download_max_bytes"] == 209715200
    assert qq["values"]["app_id"] == ""
    assert qq["values"]["enabled"] is False
    # Secret masking still reflects stored state only: nothing is configured.
    assert qq["secrets"]["secret"] == {"set": False, "masked": ""}


def test_pristine_form_roundtrip_validates_for_typed_fields(
    tmp_path: Path, monkeypatch
) -> None:
    """GET values echoed back as a form patch must pass Test validation.

    Mirrors the frontend's ``buildPatch`` for a pristine (never-configured)
    QQ form: every non-secret field is sent back as the string/list/bool the
    generic widgets hold. Before the defaults backfill this produced
    ``validation_error: msg_format, download_chunk_size, download_max_bytes``.
    """
    client, _ = _client(tmp_path, monkeypatch, channels={})
    entry = client.get("/channels/config").json()["channels"]["qq"]

    patch: dict[str, Any] = {}
    for field in entry["fields"]:
        if field["secret"]:
            continue
        value = entry["values"].get(field["key"])
        if field["type"] == "list":
            patch[field["key"]] = value if isinstance(value, list) else []
        elif field["type"] == "bool":
            patch[field["key"]] = bool(value)
        else:
            patch[field["key"]] = "" if value is None else str(value)
    patch["app_id"] = "1905653354"
    patch["secret"] = "form-typed-secret-xyz987654321"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "probe-token-do-not-leak"})

    requests = _inject_mock_transport(monkeypatch, handler)

    response = client.post("/channels/qq/test", json={"config": patch})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True, body
    assert body["code"] == "ok"
    assert len(requests) == 1
    assert "form-typed-secret-xyz987654321" not in response.text


def test_display_config_path_relativizes_home() -> None:
    home = Path.home()

    assert routes._display_config_path(home / "sub" / "agent.json") == "~/sub/agent.json"
    assert routes._display_config_path(Path("/not-under-home/agent.json")) == "agent.json"


# --------------------------------------------------------------------------- #
# PUT /channels/config/{name}
# --------------------------------------------------------------------------- #


def test_put_writes_file_and_hot_swaps_running_runtime(tmp_path: Path, monkeypatch) -> None:
    runtime = FakeRuntime(running=True)
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}, runtime=runtime
    )

    response = client.put(
        "/channels/config/dingtalk", json={"config": {"client_id": "new-client-id"}}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == "hot_swapped"
    assert body["channel"]["values"]["client_id"] == "new-client-id"
    assert body["channel"]["secrets"]["client_secret"]["set"] is True

    on_disk = json.loads(path.read_text(encoding="utf-8"))["channels"]["dingtalk"]
    assert on_disk["client_id"] == "new-client-id"
    # A secret absent from the patch keeps its stored value.
    assert on_disk["client_secret"] == STORED_SECRET

    assert runtime.manager.reload_calls == [
        ("dingtalk", {**on_disk}),
    ]
    assert STORED_SECRET not in response.text


def test_put_empty_secret_string_keeps_stored_value(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )

    response = client.put(
        "/channels/config/dingtalk", json={"config": {"client_secret": ""}}
    )

    assert response.status_code == 200
    on_disk = json.loads(path.read_text(encoding="utf-8"))["channels"]["dingtalk"]
    assert on_disk["client_secret"] == STORED_SECRET
    assert STORED_SECRET not in response.text


def test_put_enable_with_bad_credentials_is_blocked_before_write(
    tmp_path: Path, monkeypatch
) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid appKey/appSecret"})

    requests = _inject_mock_transport(monkeypatch, handler)

    response = client.put("/channels/config/dingtalk", json={"config": {"enabled": True}})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_credentials"
    assert detail["fields"] == []
    assert len(requests) == 1
    # The security property: bad credentials never reach disk.
    assert path.read_bytes() == before
    assert api_server._channel_runtime is None
    assert STORED_SECRET not in response.text


def test_put_enable_rejection_carries_scrubbed_message(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"appSecret {STORED_SECRET} is invalid")

    requests = _inject_mock_transport(monkeypatch, handler)

    response = client.put("/channels/config/dingtalk", json={"config": {"enabled": True}})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_credentials"
    assert isinstance(detail["message"], str)
    assert detail["message"]
    assert len(requests) == 1
    assert path.read_bytes() == before
    assert STORED_SECRET not in response.text


def test_put_enable_probe_exception_becomes_422_network(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    async def raising_probe(self) -> dict[str, Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr(DingTalkChannel, "test_connection", raising_probe)

    response = client.put("/channels/config/dingtalk", json={"config": {"enabled": True}})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "network"
    assert "boom" in detail["message"]
    assert path.read_bytes() == before


def test_put_enable_skip_verify_writes_without_probe(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("probe must not run with skip_verify")

    _inject_mock_transport(monkeypatch, handler)

    response = client.put(
        "/channels/config/dingtalk",
        json={"config": {"enabled": True}, "skip_verify": True},
    )

    assert response.status_code == 200
    assert response.json()["applied"] == "deferred"
    on_disk = json.loads(path.read_text(encoding="utf-8"))["channels"]["dingtalk"]
    assert on_disk["enabled"] is True


def test_put_validation_error_blocks_write(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    response = client.put(
        "/channels/config/dingtalk", json={"config": {"allow_from": "not-a-list"}}
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert "allow_from" in detail["fields"]
    assert path.read_bytes() == before
    assert STORED_SECRET not in response.text


def test_put_clear_flag_removes_stored_secret(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )

    response = client.put(
        "/channels/config/dingtalk", json={"config": {}, "clear_client_secret": True}
    )

    assert response.status_code == 200
    on_disk = json.loads(path.read_text(encoding="utf-8"))["channels"]["dingtalk"]
    assert "client_secret" not in on_disk
    assert on_disk["client_id"] == CLIENT_ID
    entry = response.json()["channel"]
    assert entry["secrets"].get("client_secret", {"set": False})["set"] is False
    assert STORED_SECRET not in response.text


def test_put_rejects_unknown_config_keys(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    response = client.put(
        "/channels/config/dingtalk",
        json={"config": {"definitely_unknown_key": 1, "__proto__": 1}},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert {"definitely_unknown_key", "__proto__"} <= set(detail["fields"])
    assert path.read_bytes() == before


def test_put_accepts_manager_override_keys(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )

    response = client.put(
        "/channels/config/dingtalk", json={"config": {"send_progress": True}}
    )

    assert response.status_code == 200
    on_disk = json.loads(path.read_text(encoding="utf-8"))["channels"]["dingtalk"]
    assert on_disk["send_progress"] is True


def test_put_yaml_config_returns_config_not_writable(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path,
        monkeypatch,
        channels={"dingtalk": _dingtalk_section()},
        suffix=".yaml",
    )
    before = path.read_bytes()

    response = client.put(
        "/channels/config/dingtalk", json={"config": {"client_id": "x"}}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "config_not_writable"}
    assert path.read_bytes() == before


def test_put_with_stopped_runtime_resets_singleton(tmp_path: Path, monkeypatch) -> None:
    runtime = FakeRuntime(running=False)
    client, _ = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}, runtime=runtime
    )
    resets: list[bool] = []
    monkeypatch.setattr(api_state, "reset_channel_runtime", lambda: resets.append(True))

    response = client.put(
        "/channels/config/dingtalk", json={"config": {"client_id": "stopped-id"}}
    )

    assert response.status_code == 200
    assert response.json()["applied"] == "reset"
    assert resets == [True]
    assert runtime.manager.reload_calls == []


def test_put_without_runtime_defers(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()})
    resets: list[bool] = []
    monkeypatch.setattr(api_state, "reset_channel_runtime", lambda: resets.append(True))

    response = client.put(
        "/channels/config/dingtalk", json={"config": {"client_id": "deferred-id"}}
    )

    assert response.status_code == 200
    assert response.json()["applied"] == "deferred"
    assert resets == []
    assert api_server._channel_runtime is None


def test_put_reload_failure_falls_back_to_reset_and_restart(
    tmp_path: Path, monkeypatch
) -> None:
    runtime = FakeRuntime(running=True, manager=FakeManager(fail=True))
    client, _ = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}, runtime=runtime
    )
    new_runtime = FakeRuntime(running=False)

    def _stub_get_channel_runtime() -> FakeRuntime:
        # Mirror the real accessor's caching contract: the rebuilt singleton is
        # observable on the host module, which is what `_hot_apply` leaves behind.
        monkeypatch.setattr(api_server, "_channel_runtime", new_runtime)
        return new_runtime

    monkeypatch.setattr(api_server, "_get_channel_runtime", _stub_get_channel_runtime)

    response = client.put(
        "/channels/config/dingtalk", json={"config": {"client_id": "fallback-id"}}
    )

    assert response.status_code == 200
    assert response.json()["applied"] == "reset"
    # The orphaned runtime is stopped before the reset + restart...
    assert runtime.stop_calls == [True]
    # ...and the old runtime is never restarted in its orphaned state.
    assert runtime.start_calls == []
    assert new_runtime.start_calls == [True]
    assert api_server._channel_runtime is new_runtime


def test_put_reload_failure_survives_a_wedged_stop(tmp_path: Path, monkeypatch) -> None:
    class WedgedStopRuntime(FakeRuntime):
        """A runtime whose stop() fails, standing in for a wedged adapter."""

        async def stop(self) -> None:
            raise RuntimeError("wedged")

    runtime = WedgedStopRuntime(running=True, manager=FakeManager(fail=True))
    client, _ = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}, runtime=runtime
    )
    new_runtime = FakeRuntime(running=False)
    monkeypatch.setattr(api_server, "_get_channel_runtime", lambda: new_runtime)

    response = client.put(
        "/channels/config/dingtalk", json={"config": {"client_id": "fallback-id"}}
    )

    assert response.status_code == 200
    assert response.json()["applied"] == "reset"
    # A failed stop must not block the rebuild.
    assert new_runtime.start_calls == [True]


def test_concurrent_puts_serialize_per_channel(tmp_path: Path, monkeypatch) -> None:
    runtime = FakeRuntime(running=True, manager=FakeManager(delay=0.05))
    _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}, runtime=runtime
    )

    async def scenario() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=api_server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return list(
                await asyncio.gather(
                    ac.put("/channels/config/dingtalk", json={"config": {"client_id": "a"}}),
                    ac.put("/channels/config/dingtalk", json={"config": {"client_id": "b"}}),
                )
            )

    responses = asyncio.run(scenario())

    assert [r.status_code for r in responses] == [200, 200]
    assert len(runtime.manager.reload_calls) == 2
    # The per-channel lock kept the two hot swaps from overlapping.
    assert runtime.manager.max_active == 1


# --------------------------------------------------------------------------- #
# POST /channels/{name}/test
# --------------------------------------------------------------------------- #


def test_post_test_uses_unsaved_creds_and_never_writes(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"accessToken": "token-do-not-leak"})

    _inject_mock_transport(monkeypatch, handler)

    response = client.post(
        "/channels/dingtalk/test",
        json={"config": {"client_id": "unsaved-id", "client_secret": UNSAVED_SECRET}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["code"] == "ok"
    assert body["tested_saved_config"] is False
    assert body["sdk_available"] is DINGTALK_AVAILABLE
    assert seen == [{"appKey": "unsaved-id", "appSecret": UNSAVED_SECRET}]
    # The test endpoint never persists anything.
    assert path.read_bytes() == before
    assert UNSAVED_SECRET not in response.text
    assert STORED_SECRET not in response.text
    assert "token-do-not-leak" not in response.text


def test_post_test_without_body_uses_saved_config(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"accessToken": "token-do-not-leak"})

    _inject_mock_transport(monkeypatch, handler)

    response = client.post("/channels/dingtalk/test", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["tested_saved_config"] is True
    assert body["ok"] is True
    assert seen == [{"appKey": CLIENT_ID, "appSecret": STORED_SECRET}]
    assert path.read_bytes() == before
    assert STORED_SECRET not in response.text


def test_post_test_reports_invalid_credentials(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"appSecret {STORED_SECRET} is invalid")

    _inject_mock_transport(monkeypatch, handler)

    response = client.post("/channels/dingtalk/test", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "invalid_credentials"
    assert body["tested_saved_config"] is True
    # The echoed secret is scrubbed (adapter layer + route defense in depth).
    assert STORED_SECRET not in response.text
    assert path.read_bytes() == before


@pytest.mark.parametrize("body", [b"null", b"[1, 2]", b'"oops"'])
def test_post_test_non_object_json_200_returns_envelope_not_500(
    tmp_path: Path, monkeypatch, body: bytes
) -> None:
    """A token endpoint answering 200 with non-object JSON must not 500.

    Regression for the shared probe's ``.get`` on a non-dict body: the
    ``/test`` route does not wrap ``test_connection`` in try/except, so an
    ``AttributeError`` here surfaced as a bare 500 instead of an honest
    ``invalid_credentials`` envelope.
    """
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    requests = _inject_mock_transport(monkeypatch, handler)

    response = client.post("/channels/dingtalk/test", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["code"] == "invalid_credentials"
    assert len(requests) == 1
    assert path.read_bytes() == before
    assert STORED_SECRET not in response.text


def test_post_test_rejects_unknown_config_keys(tmp_path: Path, monkeypatch) -> None:
    """POST /test shares PUT's unknown-key rejection instead of silently
    dropping the keys through pydantic ``extra="ignore"`` into the probe."""
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("an unknown key must be rejected before any probe")

    requests = _inject_mock_transport(monkeypatch, handler)

    response = client.post(
        "/channels/dingtalk/test",
        json={"config": {"definitely_unknown_key": 1, "__proto__": 1}},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert {"definitely_unknown_key", "__proto__"} <= set(detail["fields"])
    assert requests == []
    assert path.read_bytes() == before


def test_post_test_honors_pending_secret_clear(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("a cleared credential must not reach the transport")

    requests = _inject_mock_transport(monkeypatch, handler)

    response = client.post(
        "/channels/dingtalk/test", json={"config": {}, "clear_client_secret": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "invalid_credentials"
    assert body["detail"] == "missing credentials"
    # The stored secret was excluded from the probe, so nothing was sent.
    assert requests == []
    assert path.read_bytes() == before


def test_post_test_unsupported_channel_short_circuits(tmp_path: Path, monkeypatch) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"email": {"enabled": False}}
    )
    before = path.read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no network call may happen for an unsupported channel")

    requests = _inject_mock_transport(monkeypatch, handler)

    response = client.post("/channels/email/test", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "unsupported"
    assert body["tested_saved_config"] is True
    assert isinstance(body["sdk_available"], bool)
    assert requests == []
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- #
# Unknown channels / helper modules
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["nonexistent", "targets", "config_meta"])
def test_put_and_test_404_unknown_and_helper_modules(
    tmp_path: Path, monkeypatch, name: str
) -> None:
    client, path = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}
    )
    before = path.read_bytes()

    put = client.put(f"/channels/config/{name}", json={"config": {}})
    post = client.post(f"/channels/{name}/test", json={})

    assert put.status_code == 404
    assert post.status_code == 404
    assert path.read_bytes() == before


# --------------------------------------------------------------------------- #
# Secret hygiene sweep
# --------------------------------------------------------------------------- #


def test_no_secret_value_in_any_response_body(tmp_path: Path, monkeypatch) -> None:
    runtime = FakeRuntime(running=True)
    client, _ = _client(
        tmp_path, monkeypatch, channels={"dingtalk": _dingtalk_section()}, runtime=runtime
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"bad secret {STORED_SECRET}")

    _inject_mock_transport(monkeypatch, handler)

    responses = [
        client.get("/channels/config"),
        # Enable transition with a probe that echoes the secret in its 401 body.
        client.put("/channels/config/dingtalk", json={"config": {"enabled": True}}),
        client.post("/channels/dingtalk/test", json={}),
        client.put("/channels/config/dingtalk", json={"config": {"client_id": "ok-id"}}),
    ]

    assert [r.status_code for r in responses] == [200, 422, 200, 200]
    for response in responses:
        assert STORED_SECRET not in response.text
