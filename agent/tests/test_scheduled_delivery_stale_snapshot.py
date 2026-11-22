"""The delivery sweep must not write back a job snapshot taken before an await.

``sweep_deliveries`` loaded every job once and then awaited ``channel_sender``
for each briefing. A kernel tick or a PATCH that rewrote another job (or the
same job) during that send was then rolled back when the sweep upserted its
stale copy: ``next_run_at`` went back into the past and the job fired twice.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.scheduled_research.executor import ScheduledResearchExecutor
from src.scheduled_research.models import (
    DeliveryRecord,
    DeliveryStatus,
    JobStatus,
    ScheduledResearchJob,
)
from src.scheduled_research.store import ScheduledResearchJobStore

NOW = 1_800_000_000_000
HOUR_MS = 3_600_000


def _pending_delivery(job_id: str, session_id: str) -> DeliveryRecord:
    return DeliveryRecord(
        status=DeliveryStatus.PENDING,
        session_id=session_id,
        key=f"{job_id}:{session_id}:telegram",
        updated_at=NOW,
    )


def _job(job_id: str, **overrides) -> ScheduledResearchJob:
    base = dict(
        id=job_id,
        prompt=f"brief {job_id}",
        schedule=str(HOUR_MS),
        created_at=1,
        next_run_at=NOW + 10 * HOUR_MS,
        status=JobStatus.COMPLETED,
    )
    base.update(overrides)
    return ScheduledResearchJob(**base)


class _BlockingSender:
    """Channel sender that stays in flight until the test releases it."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, channel, target, text, *rest):
        self.started.set()
        await self.release.wait()
        return None


def _executor(store, sender, dispatch=None, briefing_reader=None):
    async def _no_dispatch(job):  # pragma: no cover - only used when a job is due
        raise AssertionError(f"unexpected dispatch of {job.id}")

    executor = ScheduledResearchExecutor(
        store,
        dispatch=dispatch or _no_dispatch,
        now_fn=lambda: NOW,
        enabled=False,
        max_consecutive_failures=3,
        retry_base_delay_ms=1000,
        retry_max_delay_ms=10_000,
        briefing_reader=briefing_reader
        or (lambda sid: ("completed", "briefing " + sid)),
        channel_sender=sender,
    )
    executor._recovered_stale_running = True
    return executor


def test_sweep_does_not_roll_back_a_job_the_tick_fired_during_a_send(
    tmp_path: Path,
) -> None:
    """Job b fires while job a's briefing is on the wire; b must fire only once."""
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    store.save(
        {
            "a": _job(
                "a",
                delivery_channel="telegram",
                delivery_target="chat",
                delivery=_pending_delivery("a", "SA"),
            ),
            "b": _job(
                "b",
                created_at=2,
                next_run_at=NOW - 1000,
                delivery=DeliveryRecord(
                    status=DeliveryStatus.NONE,
                    session_id="SB1",
                    updated_at=NOW - HOUR_MS,
                ),
            ),
        }
    )
    dispatched: list[str] = []

    async def dispatch(job):
        dispatched.append(job.id)
        return f"SB{len(dispatched) + 1}"

    async def scenario() -> None:
        sender = _BlockingSender()
        executor = _executor(store, sender, dispatch=dispatch)
        sweep = asyncio.create_task(executor.sweep_deliveries())
        await sender.started.wait()
        await executor.tick(NOW)  # fires b while a's send is still in flight
        assert store.get("b").next_run_at == NOW + HOUR_MS
        sender.release.set()
        await sweep

        b = store.get("b")
        assert b.next_run_at == NOW + HOUR_MS, "the sweep rolled b's next_run_at back"
        assert b.delivery.session_id == "SB2", "the sweep restored b's previous firing"
        await executor.tick(NOW + 1)

    asyncio.run(scenario())
    assert dispatched == ["b"], f"b was dispatched {len(dispatched)} times"


def test_sweep_keeps_an_edit_made_to_the_job_while_its_briefing_was_sent(
    tmp_path: Path,
) -> None:
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    store.save(
        {
            "a": _job(
                "a",
                delivery_channel="telegram",
                delivery_target="chat",
                delivery=_pending_delivery("a", "SA"),
            )
        }
    )

    async def scenario() -> None:
        sender = _BlockingSender()
        executor = _executor(store, sender)
        sweep = asyncio.create_task(executor.sweep_deliveries())
        await sender.started.wait()
        edited = store.get("a")  # e.g. PATCH /scheduled-runs/a
        edited.prompt = "edited prompt"
        edited.next_run_at = NOW + 2 * HOUR_MS
        store.upsert(edited)
        sender.release.set()
        assert await sweep == 1

    asyncio.run(scenario())
    a = store.get("a")
    assert a.delivery.status is DeliveryStatus.SENT
    assert a.last_verdict is not None and a.last_verdict.session_id == "SA"
    assert (
        a.prompt == "edited prompt"
    ), "the sweep reverted an edit made during the send"
    assert a.next_run_at == NOW + 2 * HOUR_MS


def test_sweep_does_not_resurrect_a_job_deleted_while_its_briefing_was_sent(
    tmp_path: Path,
) -> None:
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    store.save(
        {
            "a": _job(
                "a",
                delivery_channel="telegram",
                delivery_target="chat",
                delivery=_pending_delivery("a", "SA"),
            )
        }
    )

    async def scenario() -> None:
        sender = _BlockingSender()
        executor = _executor(store, sender)
        sweep = asyncio.create_task(executor.sweep_deliveries())
        await sender.started.wait()
        jobs = store.load()  # e.g. DELETE /scheduled-runs/a
        del jobs["a"]
        store.save(jobs)
        sender.release.set()
        await sweep

    asyncio.run(scenario())
    assert store.get("a") is None, "the sweep resurrected a deleted job"


def test_failed_briefing_read_does_not_revert_an_edit_made_during_an_earlier_send(
    tmp_path: Path,
) -> None:
    store = ScheduledResearchJobStore(tmp_path / "jobs.json")
    store.save(
        {
            "a": _job(
                "a",
                delivery_channel="telegram",
                delivery_target="chat",
                delivery=_pending_delivery("a", "SA"),
            ),
            "c": _job(
                "c",
                created_at=3,
                delivery_channel="telegram",
                delivery_target="chat",
                delivery=_pending_delivery("c", "SC"),
            ),
        }
    )

    def reader(session_id):
        if session_id == "SC":
            raise OSError("session store unavailable")
        return ("completed", "briefing " + session_id)

    async def scenario() -> None:
        sender = _BlockingSender()
        executor = _executor(store, sender, briefing_reader=reader)
        sweep = asyncio.create_task(executor.sweep_deliveries())
        await sender.started.wait()
        edited = store.get("c")
        edited.prompt = "edited prompt"
        store.upsert(edited)
        sender.release.set()
        await sweep

    asyncio.run(scenario())
    c = store.get("c")
    assert c.delivery.attempts == 1
    assert c.delivery.status is DeliveryStatus.PENDING
    assert c.prompt == "edited prompt", "the failure write reverted an edit to the job"
