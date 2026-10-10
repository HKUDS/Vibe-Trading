"""Contracts for the user-visible notice when a hot apply degrades (F3, #1625).

A PUT whose ``reload_channel`` fails degrades to a full runtime reset: every
connection drops. The route now explains the disruption — the response carries
a sanitized ``reset_reason`` and the changed channel's last chat receives one
best-effort ``OutboundMessage`` (``_config_notice``) published on the FRESH
runtime's bus after the restart.

Duplicate-suppression interaction (verified against manager.py):
``ChannelManager._should_suppress_outbound`` builds its fingerprint key from
``metadata["message_id"]`` and returns ``False`` early when that key is
absent — a reset notice carries only ``_config_notice``, so it can never be
suppressed as a duplicate reply.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api_server
import src.channels.manager as manager_module
from src.api import channels_config_routes as routes
from src.channels.base import BaseChannel
from src.channels.bus.events import OutboundMessage
from src.channels.bus.queue import MessageBus
from src.channels.manager import ChannelManager

CLIENT_ID = "ding-client-id-1234567890"
STORED_SECRET = "stored-secret-abcdefghij"
LAST_CHAT = "chat-42"


class _FakeAdapter(BaseChannel):
    """Concrete adapter stand-in; sends are no-ops, no platform SDK is touched."""

    name = "dingtalk"
    display_name = "DingTalk"

    def __init__(self, config: Any, bus: MessageBus, **kwargs: Any) -> None:
        del kwargs
        super().__init__(config, bus)

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: Any) -> None:
        del msg


def _fake_inspect_channels(config: Any) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    if not isinstance(config, dict):
        return statuses
    for name, section in config.items():
        if not isinstance(section, dict):
            continue
        statuses[name] = {
            "name": name,
            "available": True,
            "display_name": name.title(),
            "install_hint": "",
            "error": "",
            "configured": True,
            "enabled": bool(section.get("enabled")),
            "loaded": False,
            "running": False,
        }
    return statuses


def _seeded_manager(
    monkeypatch: pytest.MonkeyPatch, *, last_chat: str | None
) -> ChannelManager:
    """Build a real manager and record a last chat through the real dispatcher.

    Driving an actual outbound message through ``_dispatch_outbound`` is what
    populates ``_last_chat_ids`` in production, so the seeding doubles as
    coverage of the dispatch hook. The dispatcher is stopped before return;
    only the recorded state is consumed by the route.
    """
    monkeypatch.setattr(manager_module, "discover_channel_names", lambda: ["dingtalk"])
    monkeypatch.setattr(manager_module, "load_channel_class", lambda name: _FakeAdapter)
    monkeypatch.setattr(manager_module, "inspect_channels", _fake_inspect_channels)

    async def setup() -> ChannelManager:
        manager = ChannelManager({"dingtalk": {"enabled": True}}, MessageBus())
        await manager.start_all()
        if last_chat is not None:
            await manager.bus.publish_outbound(
                OutboundMessage(
                    channel="dingtalk", chat_id=last_chat, content="earlier reply"
                )
            )
            for _ in range(200):
                if manager.last_chat_id("dingtalk") is not None:
                    break
                await asyncio.sleep(0.01)
        await manager.stop_all()
        return manager

    return asyncio.run(setup())


class _FakeRuntime:
    """Stands in for ChannelRuntime: running flag + manager + bus."""

    def __init__(self, *, running: bool, manager: Any = None) -> None:
        self._running = running
        self.manager = manager
        self.bus = MessageBus()
        self.start_calls: list[bool] = []
        self.stop_calls: list[bool] = []

    def status(self) -> dict[str, Any]:
        return {"running": self._running, "channels": {}}

    async def start(self, *, start_manager: bool = True) -> None:
        self.start_calls.append(start_manager)

    async def stop(self) -> None:
        self.stop_calls.append(True)
        self._running = False


def _dingtalk_section() -> dict[str, Any]:
    return {
        "enabled": True,
        "client_id": CLIENT_ID,
        "client_secret": STORED_SECRET,
        "allow_from": ["*"],
    }


def _arrange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    last_chat: str | None,
    fail_reload: bool,
) -> tuple[TestClient, _FakeRuntime, _FakeRuntime]:
    """Wire a seeded old runtime + a fresh rebuild target into the test app."""
    manager = _seeded_manager(monkeypatch, last_chat=last_chat)
    if fail_reload:
        async def boom(name: str, section: dict | None) -> dict[str, Any]:
            raise RuntimeError("reload boom via https://user:pw@ding.example.com")

        manager.reload_channel = boom  # type: ignore[method-assign]
    old_runtime = _FakeRuntime(running=True, manager=manager)
    new_runtime = _FakeRuntime(running=False)

    (tmp_path / "agent.json").write_text(
        json.dumps({"channels": {"dingtalk": _dingtalk_section()}}), encoding="utf-8"
    )
    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.setattr(api_server, "_channel_runtime", old_runtime)
    monkeypatch.setattr(api_server, "_channel_bus", None)
    monkeypatch.setattr(api_server, "_channel_manager", None)
    monkeypatch.setattr(api_server, "_get_session_service", lambda: object())

    def _stub_get_channel_runtime() -> _FakeRuntime:
        # Mirror the real accessor's caching contract: the rebuilt singleton
        # becomes observable on the host module.
        monkeypatch.setattr(api_server, "_channel_runtime", new_runtime)
        return new_runtime

    monkeypatch.setattr(api_server, "_get_channel_runtime", _stub_get_channel_runtime)
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    return client, old_runtime, new_runtime


@pytest.fixture(autouse=True)
def _fresh_locks():
    """Give every test unbound locks (asyncio.Lock binds to a loop on contention)."""
    routes._channel_locks.clear()
    routes._runtime_lock = asyncio.Lock()
    yield
    routes._channel_locks.clear()
    routes._runtime_lock = asyncio.Lock()


def _put_rotated_id(client: TestClient) -> dict[str, Any]:
    """PUT a connection-key edit (never noop) and return the JSON response."""
    response = client.put(
        "/channels/config/dingtalk", json={"config": {"client_id": "rotated-id"}}
    )
    assert response.status_code == 200
    return response.json()


def test_degraded_reset_publishes_one_notice_to_last_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planbook test 1: reload failure → reset + reason + exactly one notice.

    The notice is exempt from duplicate suppression: it carries no inbound
    ``message_id``, so ``_should_suppress_outbound`` returns False early.
    """
    client, old_runtime, new_runtime = _arrange(
        tmp_path, monkeypatch, last_chat=LAST_CHAT, fail_reload=True
    )

    body = _put_rotated_id(client)

    assert body["applied"] == "reset"
    assert "RuntimeError" in body["reset_reason"]
    assert old_runtime.stop_calls == [True]
    assert new_runtime.start_calls == [True]
    assert new_runtime.bus.outbound.qsize() == 1
    notice = new_runtime.bus.outbound.get_nowait()
    assert (notice.channel, notice.chat_id) == ("dingtalk", LAST_CHAT)
    assert notice.content == routes.format_reset_notice()
    assert notice.metadata == {"_config_notice": True}


def test_degraded_reset_without_prior_outbound_publishes_no_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planbook test 2: no recorded last chat → the reset still happens, silently."""
    client, _, new_runtime = _arrange(
        tmp_path, monkeypatch, last_chat=None, fail_reload=True
    )

    body = _put_rotated_id(client)

    assert body["applied"] == "reset"
    assert "reload boom" in body["reset_reason"]
    assert new_runtime.start_calls == [True]
    assert new_runtime.bus.outbound.qsize() == 0


def test_successful_hot_swap_publishes_no_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planbook test 3: a clean per-channel swap is not disruptive → no notice."""
    client, _, new_runtime = _arrange(
        tmp_path, monkeypatch, last_chat=LAST_CHAT, fail_reload=False
    )

    body = _put_rotated_id(client)

    assert body["applied"] == "hot_swapped"
    assert "reset_reason" not in body
    assert new_runtime.start_calls == []
    assert new_runtime.bus.outbound.qsize() == 0


def test_reset_reason_scrubs_userinfo_and_truncates() -> None:
    """Planbook test 4: credentials stripped, length bounded (≤200 chars)."""
    reason = routes._sanitize_reset_reason(
        RuntimeError("connect failed via https://user:secret@api.example.com:8443/v1")
    )
    assert reason.startswith("RuntimeError:")
    assert "secret" not in reason
    assert "user:" not in reason
    assert "api.example.com:8443/v1" in reason

    long = routes._sanitize_reset_reason(RuntimeError("x" * 500))
    assert len(long) <= 200


def test_notice_content_never_echoes_config_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planbook test 5: the notice is a fixed string — no config value appears."""
    client, _, new_runtime = _arrange(
        tmp_path, monkeypatch, last_chat=LAST_CHAT, fail_reload=True
    )

    body = _put_rotated_id(client)

    assert body["applied"] == "reset"
    notice = new_runtime.bus.outbound.get_nowait()
    assert notice.content == routes.format_reset_notice()
    section = dict(_dingtalk_section(), client_id="rotated-id")
    for value in section.values():
        items = value if isinstance(value, list) else [value]
        for item in items:
            if isinstance(item, str) and item:
                assert item not in notice.content


@pytest.mark.parametrize("url", [
    "https://user:pass@word@host:99999/x",
    "https://user:pass@word@[::1]:8443/x",
])
def test_reset_reason_strips_the_entire_userinfo(url: str) -> None:
    reason = routes._sanitize_reset_reason(RuntimeError(f"failed ({url})\nretry later"))
    assert "pass" not in reason
    assert "word" not in reason
    assert "\n" not in reason


def test_reset_reason_does_not_expose_a_stored_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, old_runtime, _ = _arrange(
        tmp_path, monkeypatch, last_chat=None, fail_reload=True,
    )

    async def fail(name, section):
        raise RuntimeError(f"SDK refused credential {STORED_SECRET}")

    old_runtime.manager.reload_channel = fail
    body = _put_rotated_id(client)
    assert body["applied"] == "reset"
    assert STORED_SECRET not in body["reset_reason"]
