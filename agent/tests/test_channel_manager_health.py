"""Contracts for the channel runtime health surface (``_record_error``)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest

import src.channels.manager as manager_module
from src.channels.bus.events import OutboundMessage
from src.channels.bus.queue import MessageBus
from src.channels.manager import ChannelManager


class FakeChannel:
    """Adapter stand-in whose failures are config-driven; no platform SDK is touched."""

    display_name = "Fake"
    send_progress = True
    send_tool_hints = False
    show_reasoning = True

    instances: list["FakeChannel"] = []

    def __init__(self, config: dict[str, Any], bus: MessageBus, **kwargs: Any) -> None:
        del kwargs
        if config.get("bad_config"):
            raise ValueError("bad channel config")
        self.config = config
        self.bus = bus
        self.tag = str(config.get("tag", len(FakeChannel.instances)))
        self._running = False
        FakeChannel.instances.append(self)

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self.config.get("fail_start"):
            raise RuntimeError("start failed")
        self._running = True

    async def stop(self) -> None:
        if self.config.get("raise_stop"):
            raise TimeoutError("stop timed out")
        if self.config.get("hang_stop"):
            await asyncio.sleep(60)
        self._running = False

    async def send(self, message: Any) -> None:
        del message
        if self.config.get("fail_send"):
            raise ConnectionError("send failed")


@pytest.fixture(autouse=True)
def _reset_fake_channel() -> Iterator[None]:
    """Give every test a clean instance ledger."""
    FakeChannel.instances = []
    yield


def _fake_inspect_channels(config: Any) -> dict[str, dict[str, Any]]:
    """``inspect_channels`` stand-in covering the fake names under test."""
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


def _build_manager(
    monkeypatch: pytest.MonkeyPatch,
    config: dict[str, Any],
    *,
    names: tuple[str, ...] = ("fakea",),
) -> ChannelManager:
    """Construct a manager whose adapters are :class:`FakeChannel`."""
    monkeypatch.setattr(manager_module, "discover_channel_names", lambda: list(names))
    monkeypatch.setattr(manager_module, "load_channel_class", lambda name: FakeChannel)
    monkeypatch.setattr(manager_module, "inspect_channels", _fake_inspect_channels)
    return ChannelManager(config, MessageBus())


def test_start_failure_records_error_into_status(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch, {"fakea": {"enabled": True, "fail_start": True}}
        )
        await manager.start_all()
        try:
            status = manager.get_status()["fakea"]
            assert status["running"] is False
            assert "RuntimeError" in status["error"]
            assert "start failed" in status["error"]
            assert status["error_context"] == "start"
            assert datetime.fromisoformat(status["error_at"]).tzinfo is not None
        finally:
            await manager.stop_all()

    asyncio.run(scenario())


def test_send_final_failure_records_send_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch,
            {"send_max_retries": 1, "fakea": {"enabled": True, "fail_send": True}},
        )
        msg = OutboundMessage(channel="fakea", chat_id="chat-1", content="hello")

        await manager._send_with_retry(manager.channels["fakea"], msg)

        status = manager.get_status()["fakea"]
        assert status["error_context"] == "send"
        assert "ConnectionError" in status["error"]
        assert datetime.fromisoformat(status["error_at"]).tzinfo is not None

    asyncio.run(scenario())


@pytest.mark.parametrize("old_extra", [{"hang_stop": True}, {"raise_stop": True}])
def test_reload_stop_failure_records_reload_stop_and_reload_completes(
    monkeypatch: pytest.MonkeyPatch, old_extra: dict[str, Any],
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(manager_module, "_RELOAD_STOP_TIMEOUT_S", 0.05)
        manager = _build_manager(
            monkeypatch, {"fakea": {"enabled": True, "tag": "old", **old_extra}}
        )

        status = dict(
            await manager.reload_channel("fakea", {"enabled": True, "tag": "new"})
        )

        assert manager.channels["fakea"].tag == "new"  # the reload still completed
        assert status["loaded"] is True
        assert status["error_context"] == "reload_stop"
        assert status["error"].startswith("TimeoutError")
        assert datetime.fromisoformat(status["error_at"]).tzinfo is not None

    asyncio.run(scenario())


def test_successful_rebuild_clears_stale_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        manager = _build_manager(monkeypatch, {"fakea": {"enabled": True, "tag": "old"}})
        manager._record_error("fakea", "start", RuntimeError("earlier crash"))
        assert manager.get_status()["fakea"]["error_context"] == "start"

        status = dict(
            await manager.reload_channel("fakea", {"enabled": True, "tag": "new"})
        )

        assert status["error"] == ""
        assert status["error_context"] == ""
        assert status["error_at"] == ""

    asyncio.run(scenario())


def test_record_error_scrubs_credentials_and_bounds_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _build_manager(monkeypatch, {"fakea": {"enabled": True}})

    manager._record_error(
        "fakea",
        "start",
        ConnectionError("cannot reach https://bot:sup3rsecret@chat.example.com:443/api"),
    )
    error = manager.get_status()["fakea"]["error"]
    assert "sup3rsecret" not in error
    assert "bot" not in error
    assert "https://chat.example.com:443/api" in error

    manager._record_error(
        "fakea",
        "start",
        ValueError("bad url https://user:pass@host:notaport/x"),
    )
    error = manager.get_status()["fakea"]["error"]
    # A malformed port must not exempt the URL from redaction.
    assert "user:pass" not in error
    assert "https://host:notaport/x" in error

    # An out-of-range port is the same fail-open path (a plausible typo).
    manager._record_error(
        "fakea",
        "start",
        ConnectionError("cannot reach https://bot:sup3rsecret@chat.example.com:99999/api"),
    )
    error = manager.get_status()["fakea"]["error"]
    assert "sup3rsecret" not in error
    assert "https://chat.example.com:99999/api" in error

    manager._record_error("fakea", "send", RuntimeError("x" * 500))
    error = manager.get_status()["fakea"]["error"]
    assert error.startswith("RuntimeError: ")
    assert len(error) <= 200
