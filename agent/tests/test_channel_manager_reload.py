"""Contracts for per-channel hot reload in ``ChannelManager``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

import pytest

import src.channels.manager as manager_module
from src.channels.bus.queue import MessageBus
from src.channels.manager import ChannelManager


class FakeChannel:
    """Recording adapter stand-in; no platform SDK is touched."""

    display_name = "Fake"
    send_progress = True
    send_tool_hints = False
    show_reasoning = True

    instances: list["FakeChannel"] = []
    events: list[tuple[str, str]] = []

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
        if self.config.get("hang_start"):
            await asyncio.Event().wait()  # parks forever unless cancelled
        self._running = True
        FakeChannel.events.append(("start", self.tag))

    async def stop(self) -> None:
        FakeChannel.events.append(("stop", self.tag))
        if self.config.get("raise_stop"):
            raise TimeoutError("stop timed out")
        if self.config.get("hang_stop"):
            await asyncio.sleep(60)
        if self.config.get("slow_stop"):
            await asyncio.sleep(0.05)
        self._running = False

    async def send(self, message: Any) -> None:
        """No-op: reload tests never dispatch outbound traffic."""
        del message


@pytest.fixture(autouse=True)
def _reset_fake_channel() -> Iterator[None]:
    """Give every test a clean instance/event ledger."""
    FakeChannel.instances = []
    FakeChannel.events = []
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
    names: tuple[str, ...] = ("fakea", "fakeb"),
) -> ChannelManager:
    """Construct a manager whose adapters are :class:`FakeChannel`."""
    monkeypatch.setattr(manager_module, "discover_channel_names", lambda: list(names))
    monkeypatch.setattr(manager_module, "load_channel_class", lambda name: FakeChannel)
    monkeypatch.setattr(manager_module, "inspect_channels", _fake_inspect_channels)
    return ChannelManager(config, MessageBus())


def test_init_channels_builds_plugin_channels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_module, "discover_channel_names", lambda: [])
    monkeypatch.setattr(
        manager_module, "discover_plugins", lambda names: {"plugx": FakeChannel}
    )
    monkeypatch.setattr(
        manager_module,
        "load_channel_class",
        lambda name: pytest.fail("built-in path used for a plugin channel"),
    )
    monkeypatch.setattr(manager_module, "inspect_channels", _fake_inspect_channels)

    manager = ChannelManager(
        {"plugx": {"enabled": True, "tag": "plugin"}}, MessageBus()
    )

    assert manager.channels["plugx"].tag == "plugin"
    assert manager.get_status()["plugx"]["loaded"] is True


def test_reload_enabled_section_builds_but_does_not_start_when_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch,
            {"fakea": {"enabled": False}, "fakeb": {"enabled": True, "tag": "b"}},
        )
        assert "fakea" not in manager.channels

        status = await manager.reload_channel("fakea", {"enabled": True, "tag": "new"})

        channel = manager.channels["fakea"]
        assert channel.tag == "new"
        assert channel.is_running is False
        assert FakeChannel.events == []
        assert manager.config["fakea"] == {"enabled": True, "tag": "new"}
        assert status["enabled"] is True
        assert status["loaded"] is True
        assert status["running"] is False

    asyncio.run(scenario())


def test_reload_on_running_manager_stops_old_before_starting_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch, {"fakea": {"enabled": True, "tag": "old"}}
        )
        old = manager.channels["fakea"]
        await manager.start_all()
        try:
            status = dict(
                await manager.reload_channel("fakea", {"enabled": True, "tag": "new"})
            )
            new = manager.channels["fakea"]
            new_is_running = new.is_running
        finally:
            await manager.stop_all()

        assert new is not old
        assert old.is_running is False
        assert new_is_running is True
        assert FakeChannel.events == [
            ("start", "old"),
            ("stop", "old"),
            ("start", "new"),
            ("stop", "new"),
        ]
        assert status["enabled"] is True
        assert status["loaded"] is True
        assert status["running"] is True

    asyncio.run(scenario())


@pytest.mark.parametrize("section", [None, {"enabled": False}])
def test_reload_disabled_section_removes_only_that_channel(
    monkeypatch: pytest.MonkeyPatch,
    section: dict[str, Any] | None,
) -> None:
    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch,
            {
                "fakea": {"enabled": True, "tag": "a"},
                "fakeb": {"enabled": True, "tag": "b"},
            },
        )
        other = manager.channels["fakeb"]

        status = dict(await manager.reload_channel("fakea", section))

        assert "fakea" not in manager.channels
        assert manager.channels["fakeb"] is other
        assert FakeChannel.events == [("stop", "a")]
        assert status["enabled"] is False
        assert status["loaded"] is False
        assert status["running"] is False
        if section is None:
            assert status["configured"] is False
            assert "fakea" not in manager.config
        else:
            assert status["configured"] is True
            assert manager.config["fakea"] == {"enabled": False}

    asyncio.run(scenario())


def test_reload_proceeds_when_old_stop_raises_timeout(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch,
            {"fakea": {"enabled": True, "tag": "old", "raise_stop": True}},
        )
        with caplog.at_level(logging.WARNING, logger="src.channels.manager"):
            status = dict(
                await manager.reload_channel("fakea", {"enabled": True, "tag": "new"})
            )

        assert manager.channels["fakea"].tag == "new"
        assert FakeChannel.events == [("stop", "old")]
        assert status["loaded"] is True

    asyncio.run(scenario())
    assert "Stopping fakea timed out; replacing" in caplog.text


def test_reload_bounds_a_wedged_stop(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def scenario() -> None:
        monkeypatch.setattr(manager_module, "_RELOAD_STOP_TIMEOUT_S", 0.05)
        manager = _build_manager(
            monkeypatch,
            {"fakea": {"enabled": True, "tag": "old", "hang_stop": True}},
        )
        with caplog.at_level(logging.WARNING, logger="src.channels.manager"):
            status = dict(
                await manager.reload_channel("fakea", {"enabled": True, "tag": "new"})
            )

        assert manager.channels["fakea"].tag == "new"
        assert status["loaded"] is True

    asyncio.run(scenario())
    assert "Stopping fakea timed out; replacing" in caplog.text


def test_reload_build_failure_records_error_and_leaves_manager_functional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch,
            {
                "fakea": {"enabled": True, "tag": "old"},
                "fakeb": {"enabled": True, "tag": "b"},
            },
        )
        other = manager.channels["fakeb"]

        status = dict(
            await manager.reload_channel("fakea", {"enabled": True, "bad_config": True})
        )

        assert "fakea" not in manager.channels
        assert manager.channels["fakeb"] is other
        assert status["loaded"] is False
        assert status["running"] is False
        assert status["error"] == "ValueError: bad channel config"

        recovered = dict(
            await manager.reload_channel("fakea", {"enabled": True, "tag": "fixed"})
        )

        assert manager.channels["fakea"].tag == "fixed"
        assert recovered["loaded"] is True
        assert recovered["error"] == ""

    asyncio.run(scenario())


def test_reload_is_contained_when_replacement_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch, {"fakea": {"enabled": True, "tag": "old"}}
        )
        await manager.start_all()
        try:
            status = dict(
                await manager.reload_channel(
                    "fakea",
                    {"enabled": True, "tag": "new", "fail_start": True},
                )
            )
        finally:
            await manager.stop_all()

        assert manager.channels["fakea"].tag == "new"
        assert status["loaded"] is True
        assert status["running"] is False

    asyncio.run(scenario())


def test_stop_all_survives_a_concurrent_reload_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails pre-fix: the live-dict iteration raised ``RuntimeError`` when the reload popped ``fakea`` mid-await."""

    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch,
            {
                "fakea": {"enabled": True, "tag": "a", "slow_stop": True},
                "fakeb": {"enabled": True, "tag": "b", "slow_stop": True},
            },
        )
        await manager.start_all()
        stopper = asyncio.create_task(manager.stop_all())
        await asyncio.sleep(0)  # let stop_all enter fakea's slow stop
        reloader = asyncio.create_task(manager.reload_channel("fakea", None))
        await asyncio.gather(stopper, reloader)  # must not raise

        assert "fakea" not in manager.channels
        assert ("stop", "b") in FakeChannel.events

    asyncio.run(scenario())


def test_start_all_without_channels_still_creates_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails pre-fix: the empty-channels early return skipped dispatcher creation, so the reload never started the channel."""

    async def scenario() -> None:
        manager = _build_manager(monkeypatch, {})
        await manager.start_all()
        try:
            assert manager._dispatch_task is not None
            assert not manager._dispatch_task.done()

            status = await manager.reload_channel(
                "fakea", {"enabled": True, "tag": "late"}
            )
            assert manager.channels["fakea"].is_running is True
            assert status["running"] is True
        finally:
            await manager.stop_all()

    asyncio.run(scenario())


def test_reload_does_not_await_a_blocking_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fails on a revert to inline start(): the reload would park on the hanging ``start()`` and ``wait_for`` would time out."""

    async def scenario() -> None:
        manager = _build_manager(
            monkeypatch, {"fakea": {"enabled": True, "tag": "old"}}
        )
        await manager.start_all()
        try:
            status = await asyncio.wait_for(
                manager.reload_channel(
                    "fakea", {"enabled": True, "tag": "new", "hang_start": True}
                ),
                timeout=1.0,
            )
            assert status["loaded"] is True
            # The replacement's start() is still parked.
            assert status["running"] is False
            assert manager._start_tasks  # the spawned task is tracked, not leaked
        finally:
            for task in manager._start_tasks:
                task.cancel()
            await manager.stop_all()

    asyncio.run(scenario())


def test_concurrent_reloads_of_one_channel_leave_one_adapter_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two reloads racing on one channel each stopped the adapter they saw and
    started their own, so one replacement ran outside the manager."""

    async def scenario() -> None:
        manager = _build_manager(monkeypatch, {"fakea": {"enabled": True, "tag": "old", "slow_stop": True}})
        await manager.start_all()
        try:
            await asyncio.gather(
                manager.reload_channel("fakea", {"enabled": True, "tag": "a", "slow_stop": True}),
                manager.reload_channel("fakea", {"enabled": True, "tag": "b", "slow_stop": True}),
            )
            await asyncio.sleep(0)
            running = [c.tag for c in FakeChannel.instances if c.is_running]
            assert running == [manager.channels["fakea"].tag]
        finally:
            await manager.stop_all()

    asyncio.run(scenario())


def test_stop_all_cancels_a_start_still_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        manager = _build_manager(monkeypatch, {"fakea": {"enabled": True, "tag": "old"}})
        await manager.start_all()
        await manager.reload_channel("fakea", {"enabled": True, "tag": "new", "hang_start": True})
        pending = list(manager._start_tasks)
        assert pending

        await asyncio.wait_for(manager.stop_all(), timeout=2.0)

        assert all(task.done() for task in pending)
        assert not manager._start_tasks

    asyncio.run(scenario())
