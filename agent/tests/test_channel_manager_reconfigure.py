"""Contracts for ChannelManager.reconfigure_channel single-channel hot apply."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import src.channels.config as channels_config
import src.channels.manager as manager_module
from src.channels.bus.queue import MessageBus
from src.channels.manager import ChannelManager
from src.channels.registry import ChannelAvailability


class FakeChannel:
    """Duck-typed channel stand-in; manager never touches BaseChannel internals."""

    name = "fakechan"
    display_name = "FakeChan"

    def __init__(self, config: Any, bus: MessageBus, **kwargs: Any) -> None:
        self.config = config
        self.bus = bus
        self._running = False
        self.started = 0
        self.stopped = 0
        self.send_progress = True
        self.send_tool_hints = False
        self.show_reasoning = True

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        self.started += 1
        self._running = True

    async def stop(self) -> None:
        self.stopped += 1
        self._running = False

    async def send(self, msg: Any) -> None:
        del msg


@pytest.fixture()
def fake_channel_wiring(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Point the manager's discovery/construction hooks at FakeChannel."""
    state: dict[str, Any] = {"config": {"fakechan": {"enabled": True}}}
    monkeypatch.setattr(
        channels_config, "load_channels_config", lambda: dict(state["config"])
    )
    monkeypatch.setattr(
        manager_module,
        "inspect_channel",
        lambda name: ChannelAvailability(name=name, available=True, display_name="FakeChan"),
    )
    monkeypatch.setattr(manager_module, "load_channel_class", lambda name: FakeChannel)
    monkeypatch.setattr(manager_module, "discover_channel_names", lambda: ["fakechan"])
    return state


def test_reconfigure_builds_and_starts_channel_when_manager_started(
    fake_channel_wiring,
) -> None:
    async def scenario() -> None:
        manager = ChannelManager({}, MessageBus())
        manager._dispatch_task = asyncio.create_task(asyncio.sleep(60))
        try:
            status = await manager.reconfigure_channel("fakechan")
            await asyncio.gather(*manager._start_tasks)
        finally:
            manager._dispatch_task.cancel()

        assert status["enabled"] is True
        assert status["loaded"] is True
        assert status["running"] is True
        channel = manager.channels["fakechan"]
        assert isinstance(channel, FakeChannel)
        assert channel.started == 1

    asyncio.run(scenario())


def test_reconfigure_replaces_old_instance_without_starting_when_stopped(
    fake_channel_wiring,
) -> None:
    async def scenario() -> None:
        manager = ChannelManager({}, MessageBus())
        old = FakeChannel({"enabled": True}, manager.bus)
        old._running = True
        manager.channels["fakechan"] = old

        status = await manager.reconfigure_channel("fakechan")

        assert old.stopped == 1
        assert manager.channels["fakechan"] is not old
        assert status["loaded"] is True
        assert status["running"] is False  # dispatcher not alive -> built but not started

    asyncio.run(scenario())


def test_reconfigure_disable_removes_instance_and_keeps_status_honest(
    fake_channel_wiring,
) -> None:
    fake_channel_wiring["config"] = {"fakechan": {"enabled": False}}

    async def scenario() -> None:
        manager = ChannelManager({}, MessageBus())
        old = FakeChannel({"enabled": True}, manager.bus)
        old._running = True
        manager.channels["fakechan"] = old

        status = await manager.reconfigure_channel("fakechan")

        assert old.stopped == 1
        assert "fakechan" not in manager.channels
        assert status["enabled"] is False
        assert status["loaded"] is False
        assert status["running"] is False

    asyncio.run(scenario())


def test_reconfigure_leaves_other_channels_untouched(fake_channel_wiring) -> None:
    async def scenario() -> None:
        manager = ChannelManager({}, MessageBus())
        other = FakeChannel({"enabled": True}, manager.bus)
        other._running = True
        manager.channels["otherchan"] = other
        manager._status["otherchan"] = {"enabled": True, "running": True}

        await manager.reconfigure_channel("fakechan")

        assert other.stopped == 0
        assert other._running is True
        assert manager.channels["otherchan"] is other
        assert manager._status["otherchan"] == {"enabled": True, "running": True}

    asyncio.run(scenario())


def test_reconfigure_reports_unavailable_adapter_without_building(
    fake_channel_wiring, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        manager_module,
        "inspect_channel",
        lambda name: ChannelAvailability(
            name=name,
            available=False,
            display_name="FakeChan",
            error="missing optional dependency for fakechan",
        ),
    )

    async def scenario() -> None:
        manager = ChannelManager({}, MessageBus())

        status = await manager.reconfigure_channel("fakechan")

        assert "fakechan" not in manager.channels
        assert status["available"] is False
        assert status["loaded"] is False
        assert "missing optional dependency" in status["error"]

    asyncio.run(scenario())


def test_reconfigure_hot_enables_first_channel_when_started_with_zero(
    fake_channel_wiring,
) -> None:
    """start_all() with zero channels builds no dispatcher; hot-enabling the
    first channel via reconfigure must bring the dispatcher up too, else the
    instance is built but never started (the old apply-on-next-restart gap)."""

    async def scenario() -> None:
        manager = ChannelManager({}, MessageBus())
        await manager.start_all()  # zero channels: early return, no dispatcher
        assert manager._dispatch_task is None
        try:
            status = await manager.reconfigure_channel("fakechan")
            await asyncio.gather(*manager._start_tasks, return_exceptions=True)
            assert status["running"] is True
            assert manager._dispatch_task is not None and not manager._dispatch_task.done()
            channel = manager.channels["fakechan"]
            assert channel.started == 1
        finally:
            await manager.stop_all()

    asyncio.run(scenario())
