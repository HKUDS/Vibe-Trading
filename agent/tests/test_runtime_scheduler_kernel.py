"""Tests for the live-runtime scheduler's kernel adoption (step 2 of the
scheduler unification): ``src/live/runtime/scheduler.py`` is now a thin façade
over ``src.scheduling.kernel.SchedulerKernel``.

The pre-move behavior battery (``test_runtime_scheduler.py``) is unmodified and
still green; this file pins the *new* structural facts: kernel ownership, the
stable task name and ``_task`` handle, delegation to the shared trigger
grammar, the adaptive sleep hint, and wake-on-mutation.

House style: ``asyncio.run`` scenarios with an injected ``now_fn`` instead of
the wall clock, yield loops / ``asyncio.Event`` handshakes instead of real
waiting, and ``asyncio.wait_for`` timeouts so a wedged scheduler fails the
test instead of hanging the suite.
"""

from __future__ import annotations

import asyncio

import pytest

from src.live.runtime.scheduler import (
    DEFAULT_MAX_RECHECK_MS,
    TASK_NAME,
    Job,
    Scheduler,
    advance_after_fire,
    compute_sleep_ms,
)
from src.scheduling.kernel import SchedulerKernel
from src.scheduling.triggers import next_once_due, trigger_interval_ms


def _job(jid: str, next_run_at: int, schedule: str = "interval:1000") -> Job:
    return Job(id=jid, next_run_at=next_run_at, schedule=schedule)


# ---- kernel ownership and the stable task handle ----------------------------


def test_scheduler_owns_a_kernel_with_the_live_task_name() -> None:
    async def on_fire(job: Job) -> None:  # pragma: no cover - never fires here
        pass

    sched = Scheduler(on_fire)
    assert isinstance(sched._kernel, SchedulerKernel)
    assert sched._kernel.task_name == TASK_NAME == "live-scheduler"
    assert sched._kernel.on_tick == sched._fire_due
    assert sched._kernel.sleep_hint_fn == sched._sleep_hint


def test_task_property_tracks_the_kernel_task_lifecycle() -> None:
    """``live_routes._runner_scheduler_task`` reads ``scheduler._task`` and
    treats None/done as "nothing to await" — the property must keep that
    contract across the kernel adoption."""

    async def scenario() -> None:
        sched = Scheduler(_noop_fire)
        assert sched._task is None
        sched.start()
        task = sched._task
        assert task is not None and not task.done()
        assert task.get_name() == "live-scheduler"
        await asyncio.wait_for(sched.stop(), timeout=5.0)
        assert sched._task is None

    asyncio.run(scenario())


async def _noop_fire(job: Job) -> None:  # pragma: no cover - never fires here
    pass


# ---- delegation to the shared trigger grammar --------------------------------


def test_interval_ms_matches_the_shared_grammar_on_every_spec_shape() -> None:
    specs = [
        "interval:5000",
        "interval:0",
        "interval:-5",
        "interval:nope",
        "interval:",
        "once",
        "ONCE",
        " Once ",
        "weird",
        "",
        "  ",
    ]
    for spec in specs:
        assert _job("a", 0, spec).interval_ms() == trigger_interval_ms(spec)


def test_advance_after_fire_matches_the_shared_next_run_math() -> None:
    for spec in ("interval:1000", "interval:bad", "once", "weird", ""):
        job = _job("a", next_run_at=100, schedule=spec)
        keep = advance_after_fire(job, now_ms=5000)
        expected = next_once_due(spec, 5000)
        if expected is None:
            assert keep is False
            assert job.next_run_at == 100  # untouched
        else:
            assert keep is True
            assert job.next_run_at == expected


# ---- adaptive sleep hint ------------------------------------------------------


def test_sleep_hint_is_compute_sleep_ms_over_the_live_set() -> None:
    sched = Scheduler(_noop_fire, max_recheck_ms=5000)
    assert sched._sleep_hint(0) == 5000  # no jobs -> idle poll at the cap
    sched.add_job(_job("a", 800))
    assert sched._sleep_hint(300) == 500
    assert sched._sleep_hint(300) == compute_sleep_ms(sched.jobs(), 300, 5000)
    assert sched._sleep_hint(900) == 0  # due now -> fire immediately


def test_loop_does_not_fire_before_the_deadline_and_wakes_on_add() -> None:
    """The kernel sleeps the hint, not a fixed tick: with the clock pinned
    before the deadline nothing fires, and an add_job (which requests a wake)
    re-evaluates at once instead of waiting the sleep out."""
    fired: list[str] = []
    now = [0]

    async def on_fire(job: Job) -> None:
        fired.append(job.id)

    async def scenario() -> None:
        sched = Scheduler(on_fire, now_fn=lambda: now[0], max_recheck_ms=60_000)
        sched.add_job(_job("a", 10_000, "once"))
        sched.start()
        for _ in range(200):
            await asyncio.sleep(0)
        assert fired == []  # slept adaptively; deadline not reached
        assert sched._task is not None and not sched._task.done()

        now[0] = 10_000
        sched.add_job(_job("b", 10_000, "once"))  # mutation wakes the loop

        async def wait_for_both() -> None:
            while sorted(fired) != ["a", "b"]:
                await asyncio.sleep(0.005)

        await asyncio.wait_for(wait_for_both(), timeout=2.0)
        assert sched.jobs() == []  # both one-shots removed
        await asyncio.wait_for(sched.stop(), timeout=5.0)

    asyncio.run(scenario())

    assert sorted(fired) == ["a", "b"]


def test_add_and_remove_job_request_a_wake() -> None:
    """add_job / remove_job must cut a long adaptive sleep short — pinned via
    a recording stand-in over the kernel's request_wake."""

    class _RecordingKernel(SchedulerKernel):
        def __init__(self) -> None:
            super().__init__(tick_interval_ms=60_000)
            self.wakes = 0

        def request_wake(self) -> None:
            self.wakes += 1

    async def scenario() -> None:
        sched = Scheduler(_noop_fire)
        kernel = _RecordingKernel()
        sched._kernel = kernel
        sched.add_job(_job("a", 10**12))
        assert kernel.wakes == 1
        assert sched.remove_job("a") is True
        assert kernel.wakes == 2
        assert sched.remove_job("a") is False
        assert kernel.wakes == 2  # a miss does not wake

    asyncio.run(scenario())


def test_default_max_recheck_is_unchanged() -> None:
    sched = Scheduler(_noop_fire)
    assert sched._max_recheck_ms == DEFAULT_MAX_RECHECK_MS == 5 * 60 * 1000
    # No jobs: the hinted sleep is the idle-poll cap.
    assert sched._sleep_hint(0) == DEFAULT_MAX_RECHECK_MS


def test_task_property_on_the_facade_is_read_only() -> None:
    """``_task`` was a writable attribute before the kernel adoption; as a
    property it must reject assignment so owners cannot bypass the kernel's
    guarded handle release."""
    sched = Scheduler(_noop_fire)
    with pytest.raises(AttributeError):
        sched._task = None
