"""Regression tests for ``FeishuChannel.stop()`` hot-swap safety.

Production defect (Feishu row of #1569, following the DingTalk zombie-stream
fix in #1520): ``stop()`` only cleared ``_running``, but ``run_ws``'s loop
blocks inside ``self._ws_client.start()`` → ``loop.run_until_complete(...)``
which sleeps forever, and lark's receive loop runs with ``auto_reconnect=True``
— so after a hot swap the old WebSocket stayed connected and BOTH the old and
the replacement adapter answered messages. ``stop()`` must best-effort close
the SDK connection and terminate the dedicated event loop so the thread exits.

The fake ws client mirrors the real lifecycle: ``start()`` blocks inside
``run_until_complete`` on the thread's dedicated loop, exactly like lark's
``Client.start()``, so only ``loop.stop()`` (from ``FeishuChannel.stop()``)
can unwind it.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from src.channels.bus.queue import MessageBus
from src.channels.feishu import FeishuChannel


class FakeConn:
    """Stand-in for the ``websockets`` protocol object lark holds as ``_conn``."""

    def __init__(self, *, hang: bool = False) -> None:
        self.close_calls = 0
        self.closed = threading.Event()
        self._hang = hang

    async def close(self) -> None:
        self.close_calls += 1
        if self._hang:
            await asyncio.sleep(3600)
        self.closed.set()


class FakeWsClient:
    """Mimics ``lark.ws.Client``: ``start()`` blocks until the loop is stopped."""

    def __init__(self, conn: FakeConn | None = None) -> None:
        self._conn = conn if conn is not None else FakeConn()
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        loop = asyncio.get_event_loop()
        loop.run_until_complete(asyncio.sleep(3600))


def _make_channel() -> FeishuChannel:
    return FeishuChannel({"app_id": "cli_a", "app_secret": "sec"}, MessageBus())


def _start_ws_thread(
    channel: FeishuChannel, ws_client: FakeWsClient
) -> tuple[threading.Thread, list[asyncio.AbstractEventLoop]]:
    """Run the ``run_ws`` loop shape on a real thread with the fake client."""
    loops: list[asyncio.AbstractEventLoop] = []

    def run_ws_like() -> None:
        ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(ws_loop)
        loops.append(ws_loop)
        channel._ws_loop = ws_loop
        try:
            while channel._running:
                try:
                    ws_client.start()
                except Exception:  # noqa: BLE001 - mirrors run_ws's warning branch
                    pass
                if channel._running:
                    time.sleep(0.05)
        finally:
            channel._ws_loop = None
            asyncio.set_event_loop(None)
            ws_loop.close()

    channel._ws_client = ws_client
    channel._running = True
    thread = threading.Thread(target=run_ws_like, daemon=True)
    thread.start()
    return thread, loops


async def _wait_until_ws_running(channel: FeishuChannel) -> None:
    """Park until the dedicated loop is actually running inside ``start()``."""
    for _ in range(500):
        ws_loop = channel._ws_loop
        if ws_loop is not None and ws_loop.is_running():
            return
        await asyncio.sleep(0.01)
    pytest.fail("fake ws loop never started")


def test_stop_terminates_ws_thread_and_closes_connection() -> None:
    """Fails pre-fix: ``_running = False`` alone never unwound ``start()``."""

    async def scenario() -> None:
        channel = _make_channel()
        ws_client = FakeWsClient()
        thread, loops = _start_ws_thread(channel, ws_client)
        await _wait_until_ws_running(channel)

        await asyncio.wait_for(channel.stop(), timeout=5)
        await asyncio.to_thread(thread.join, 5.0)

        assert not thread.is_alive()
        assert ws_client._conn.close_calls == 1
        assert ws_client._conn.closed.is_set()
        # auto_reconnect must not resurrect the stream after the loop stop.
        assert ws_client.start_calls == 1
        assert channel._ws_loop is None
        assert loops[0].is_closed()

        # A second stop() is a no-op.
        await asyncio.wait_for(channel.stop(), timeout=5)
        assert ws_client._conn.close_calls == 1
        assert ws_client.start_calls == 1

    asyncio.run(scenario())


def test_stop_bounds_a_hanging_connection_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wedged ``conn.close()`` must not wedge ``stop()``; the loop still dies."""

    async def scenario() -> None:
        monkeypatch.setattr(FeishuChannel, "_WS_CLOSE_TIMEOUT_S", 0.05)
        channel = _make_channel()
        ws_client = FakeWsClient(FakeConn(hang=True))
        thread, _ = _start_ws_thread(channel, ws_client)
        await _wait_until_ws_running(channel)

        await asyncio.wait_for(channel.stop(), timeout=5)
        await asyncio.to_thread(thread.join, 5.0)

        assert not thread.is_alive()
        assert ws_client._conn.close_calls == 1

    asyncio.run(scenario())


def test_stop_without_start_is_safe() -> None:
    async def scenario() -> None:
        channel = _make_channel()

        await channel.stop()

        assert channel._ws_loop is None
        assert channel.is_running is False
        # Idempotent when never started.
        await channel.stop()

    asyncio.run(scenario())
