"""The event hook makes delivery prompt; the sweep is what makes it correct.

A briefing that waits for the next poll is still delivered, just late. The
hook exists to remove that wait — and must never be able to cost anything
else, so it runs off the SSE publish path and coalesces.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.scheduled_research.executor import ScheduledResearchExecutor
from src.scheduled_research.models import DeliveryStatus, ScheduledResearchJob
from src.scheduled_research.store import ScheduledResearchJobStore
from src.session.events import EventBus, SSEEvent


def _job(**overrides) -> ScheduledResearchJob:
    base = dict(id="j1", prompt="p", schedule="60000", next_run_at=0)
    base.update(overrides)
    return ScheduledResearchJob(**base)


def test_a_listener_that_raises_cannot_break_the_event_stream() -> None:
    """This is the SSE hot path; a bad listener must cost nothing."""
    bus = EventBus()
    seen: list[str] = []

    def _explodes(_event: SSEEvent) -> None:
        raise RuntimeError("listener is broken")

    bus.add_listener(_explodes)
    bus.add_listener(lambda event: seen.append(event.event_type))

    bus.emit("s1", "attempt.completed", {})

    assert seen == ["attempt.completed"]
    # And the event still reached the buffer every reconnecting client reads.
    assert len(bus.replay("s1", replay_all=True)) == 1


def test_a_removed_listener_stops_hearing_events() -> None:
    bus = EventBus()
    seen: list[str] = []
    listener = lambda event: seen.append(event.event_type)  # noqa: E731

    bus.add_listener(listener)
    bus.emit("s1", "attempt.completed", {})
    bus.remove_listener(listener)
    bus.emit("s1", "attempt.failed", {})

    assert seen == ["attempt.completed"]


def test_a_requested_sweep_delivers_without_waiting_for_a_tick(tmp_path: Path) -> None:
    """The whole point: the briefing goes out when the run ends, not later."""
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    job = _job(delivery_channel="telegram", delivery_target="chat-1")
    job.delivery.status = DeliveryStatus.PENDING
    job.delivery.session_id = "s1"
    job.delivery.key = "j1:s1:telegram"
    store.upsert(job)
    sent: list[str] = []

    async def _sender(_channel, _target, text):
        sent.append(text)

    async def _scenario() -> None:
        executor = ScheduledResearchExecutor(
            store,
            lambda _j: None,
            enabled=False,
            briefing_reader=lambda _s: ("completed", "prompt briefing"),
            channel_sender=_sender,
        )
        executor._loop = asyncio.get_running_loop()
        executor.request_sweep()
        # Yield until the coalesced task has run.
        for _ in range(10):
            await asyncio.sleep(0)
            if sent:
                break

    asyncio.run(_scenario())

    assert sent == ["prompt briefing"]
    assert store.get("j1").delivery.status is DeliveryStatus.SENT


def test_requesting_a_sweep_without_a_running_loop_is_a_no_op(tmp_path: Path) -> None:
    """Construction happens before the server loop exists."""
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    executor = ScheduledResearchExecutor(store, lambda _j: None, enabled=False)

    executor.request_sweep()  # must not raise

    assert executor._sweep_task is None
