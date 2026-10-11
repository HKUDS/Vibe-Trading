"""Session SSE event buffer recovery tests."""

from __future__ import annotations

import asyncio
import threading
import time

from src.session.events import EventBus, SSEEvent


def test_first_connect_does_not_replay_completed_history_by_default() -> None:
    bus = EventBus()
    bus.emit("s1", "tool_call", {"tool": "load_skill"})

    assert bus.replay("s1") == []


def test_active_run_first_connect_can_replay_entire_buffer() -> None:
    bus = EventBus()
    first = bus.emit("s1", "tool_call", {"tool": "load_skill"})
    second = bus.emit("s1", "tool_result", {"tool": "load_skill", "status": "ok"})

    assert bus.replay("s1", replay_all=True) == [first, second]


def test_last_event_id_replay_still_returns_only_later_events() -> None:
    bus = EventBus()
    first = bus.emit("s1", "tool_call", {"tool": "load_skill"})
    second = bus.emit("s1", "tool_result", {"tool": "load_skill", "status": "ok"})
    third = bus.emit("s1", "text_delta", {"delta": "done"})

    assert bus.replay("s1", last_event_id=first.event_id, replay_all=True) == [second, third]


def test_replay_all_with_unknown_last_event_id_returns_buffer() -> None:
    """A non-buffered heartbeat id must not cause active terminal events to be skipped."""
    bus = EventBus()
    first = bus.emit("s1", "tool_call", {"tool": "load_skill"})
    terminal = bus.emit("s1", "attempt.completed", {"summary": "done"})

    assert bus.replay("s1", last_event_id="synthetic-heartbeat-id", replay_all=True) == [
        first,
        terminal,
    ]


def test_synthetic_heartbeat_frame_has_no_replay_id() -> None:
    heartbeat = SSEEvent(event_id=None, event_type="heartbeat", data={"ts": 1}, session_id="s1")

    frame = heartbeat.to_sse()

    assert "event: heartbeat" in frame
    assert "id:" not in frame


def test_subscribe_does_not_double_deliver_an_event_published_during_replay() -> None:
    """A publish() landing between queue registration and the replay snapshot
    must not be returned through both paths.
    """

    class SlowEventBus(EventBus):
        def replay(self, *args, **kwargs):
            time.sleep(0.15)
            return super().replay(*args, **kwargs)

    async def run() -> list:
        bus = SlowEventBus()
        bus.set_loop(asyncio.get_running_loop())
        baseline = bus.emit("s1", "baseline", {})

        def publish_from_another_thread() -> None:
            time.sleep(0.05)
            bus.emit("s1", "race", {})

        thread = threading.Thread(target=publish_from_another_thread)
        thread.start()

        gen = bus.subscribe("s1", last_event_id=baseline.event_id)
        received = []

        async def collect_one() -> None:
            async for event in gen:
                received.append(event.event_id)
                return

        await asyncio.wait_for(collect_one(), timeout=3)
        thread.join()

        try:
            await asyncio.wait_for(gen.__anext__(), timeout=0.3)
            received.append("unexpected-second-event")
        except asyncio.TimeoutError:
            pass
        return received

    received = asyncio.run(run())

    assert len(received) == 1

