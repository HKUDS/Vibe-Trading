"""Regression: EventBus.clear must notify and remove subscribers.

The original clear() only removed the buffer but left subscriber queues
in self._subscribers. Subscribers would keep receiving heartbeats
forever on a cleared session, and future publish() calls would still
enqueue to those dead queues.

The fix sends a ``session_cleared`` sentinel to each subscriber queue
and removes the subscriber list so the subscribe() generator can break
out of its loop.
"""

from __future__ import annotations

import asyncio

import pytest

from src.session.events import EventBus


def test_clear_removes_buffer() -> None:
    bus = EventBus()
    bus.emit("s1", 'item.started', {"kind": 'tool.started', 'item': {'type': 'tool_result', 'name': 'x'}, 'live_id': "tool:" + str('')})
    bus.clear("s1")
    assert bus.replay("s1", replay_all=True) == []


def test_clear_removes_subscribers() -> None:
    """After clear, the subscriber list for the session must be empty."""
    bus = EventBus()

    async def _run() -> None:
        gen = bus.subscribe("s1")
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.05)
        bus.clear("s1")
        assert "s1" not in bus._subscribers
        # The generator yields the sentinel, then breaks.
        event = await asyncio.wait_for(task, timeout=2.0)
        assert event.event_type == "session_cleared"
        # Next __anext__ should raise StopAsyncIteration (generator exited).
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

    asyncio.run(_run())


def test_clear_sends_session_cleared_sentinel() -> None:
    """Subscribers must receive a session_cleared event before the generator exits."""
    bus = EventBus()
    received: list[str] = []

    async def _run() -> None:
        gen = bus.subscribe("s1")
        task = asyncio.ensure_future(_collect(gen))
        await asyncio.sleep(0.05)
        bus.clear("s1")
        await asyncio.wait_for(task, timeout=2.0)

    async def _collect(gen) -> None:
        async for event in gen:
            received.append(event.event_type)

    asyncio.run(_run())
    assert "session_cleared" in received


def test_publish_after_clear_does_not_enqueue() -> None:
    """After clear, publish must not enqueue to any subscriber queue."""
    bus = EventBus()

    async def _run() -> None:
        gen = bus.subscribe("s1")
        task = asyncio.ensure_future(gen.__anext__())
        await asyncio.sleep(0.05)
        bus.clear("s1")
        bus.emit("s1", 'item.started', {"kind": 'tool.started', 'item': {'type': 'tool_result', 'name': 'x'}, 'live_id': "tool:" + str('')})
        assert "s1" not in bus._subscribers
        event = await asyncio.wait_for(task, timeout=2.0)
        assert event.event_type == "session_cleared"

    asyncio.run(_run())


def test_clear_nonexistent_session_does_not_crash() -> None:
    bus = EventBus()
    bus.clear("nonexistent")  # should not raise


def test_subscribe_terminates_after_clear() -> None:
    """The subscribe generator must stop after clear sends the sentinel."""
    bus = EventBus()
    received: list[str] = []

    async def _subscribe() -> None:
        async for event in bus.subscribe("s1"):
            received.append(event.event_type)

    async def _run() -> None:
        task = asyncio.create_task(_subscribe())
        await asyncio.sleep(0.1)
        bus.clear("s1")
        await asyncio.wait_for(task, timeout=2.0)

    asyncio.run(_run())
    assert "session_cleared" in received
