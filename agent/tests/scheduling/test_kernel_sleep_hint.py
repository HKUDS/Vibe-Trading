"""Tests for the kernel's adaptive-sleep extension (``sleep_hint_fn``) and the
read-only ``task`` property — the seam the live runtime scheduler adopts in
step 2 of the scheduler unification.

House style (see test_kernel.py): async scenarios are driven with
``asyncio.run`` — no pytest-asyncio in this repo — with an injected ``now_fn``
instead of the wall clock, ``asyncio.sleep(0)`` yield loops or
``asyncio.Event`` handshakes instead of real waiting, and
``asyncio.wait_for`` timeouts so a wedged kernel fails the test instead of
hanging the suite.
"""

from __future__ import annotations

import asyncio
import itertools
import logging

import pytest

from src.scheduling.kernel import SchedulerKernel


async def _noop_tick(now_ms: int) -> None:  # pragma: no cover - does nothing
    pass


def _tasks_named(name: str) -> list[asyncio.Task]:
    """Return the not-yet-finished tasks with ``name``, excluding this one."""
    current = asyncio.current_task()
    return [t for t in asyncio.all_tasks() if t.get_name() == name and t is not current]


def test_sleep_hint_replaces_the_fixed_tick() -> None:
    """A 60s fixed tick would never reach the second tick inside the timeout;
    the hint shortens the inter-tick sleep to 1ms."""
    ticks: list[int] = []

    async def scenario() -> None:
        second = asyncio.Event()

        async def on_tick(now_ms: int) -> None:
            ticks.append(now_ms)
            if len(ticks) >= 2:
                second.set()

        kernel = SchedulerKernel(
            tick_interval_ms=60_000,
            now_fn=lambda: 1000,
            on_tick=on_tick,
            sleep_hint_fn=lambda now_ms: 1,
        )
        kernel.start()
        await asyncio.wait_for(second.wait(), timeout=2.0)
        await asyncio.wait_for(kernel.stop(), timeout=5.0)

    asyncio.run(scenario())

    assert len(ticks) >= 2


def test_sleep_hint_receives_a_fresh_post_tick_now() -> None:
    """The hint is sampled against a freshly read clock, after the tick."""
    clock = itertools.count(1000, 1000)
    tick_nows: list[int] = []
    hint_nows: list[int] = []

    async def scenario() -> None:
        second = asyncio.Event()

        async def on_tick(now_ms: int) -> None:
            tick_nows.append(now_ms)
            if len(tick_nows) >= 2:
                second.set()

        def hint(now_ms: int) -> int:
            hint_nows.append(now_ms)
            return 1

        kernel = SchedulerKernel(
            tick_interval_ms=60_000, now_fn=lambda: next(clock), on_tick=on_tick, sleep_hint_fn=hint
        )
        kernel.start()
        await asyncio.wait_for(second.wait(), timeout=2.0)
        await asyncio.wait_for(kernel.stop(), timeout=5.0)

    asyncio.run(scenario())

    assert tick_nows[:2] == [1000, 3000]
    assert hint_nows[0] == 2000


def test_negative_sleep_hint_is_clamped_to_zero() -> None:
    kernel = SchedulerKernel(sleep_hint_fn=lambda now_ms: -5)
    assert kernel._next_sleep_ms() == 0


def test_next_sleep_ms_without_a_hint_is_the_fixed_tick() -> None:
    kernel = SchedulerKernel(tick_interval_ms=4321)
    assert kernel.sleep_hint_fn is None
    assert kernel._next_sleep_ms() == 4321


def test_raising_sleep_hint_falls_back_to_the_fixed_tick() -> None:
    def bad_hint(now_ms: int) -> int:
        raise RuntimeError("boom")

    kernel = SchedulerKernel(tick_interval_ms=999, sleep_hint_fn=bad_hint)
    assert kernel._next_sleep_ms() == 999


def test_raising_sleep_hint_does_not_kill_the_loop() -> None:
    ticks: list[int] = []

    async def scenario() -> None:
        third = asyncio.Event()

        async def on_tick(now_ms: int) -> None:
            ticks.append(now_ms)
            if len(ticks) >= 3:
                third.set()

        def bad_hint(now_ms: int) -> int:
            raise RuntimeError("boom")

        kernel = SchedulerKernel(tick_interval_ms=1, on_tick=on_tick, sleep_hint_fn=bad_hint)
        kernel.start()
        await asyncio.wait_for(third.wait(), timeout=5.0)
        assert kernel.is_running
        await asyncio.wait_for(kernel.stop(), timeout=5.0)

    asyncio.run(scenario())

    assert len(ticks) >= 3


def test_sleep_hint_fn_is_exposed_read_only() -> None:
    def hint(now_ms: int) -> int:
        return 7

    kernel = SchedulerKernel(sleep_hint_fn=hint)
    assert kernel.sleep_hint_fn is hint
    with pytest.raises(AttributeError):
        kernel.sleep_hint_fn = None  # read-only property


def test_task_property_tracks_the_loop_lifecycle() -> None:
    async def scenario() -> None:
        kernel = SchedulerKernel(tick_interval_ms=60_000)
        assert kernel.task is None
        kernel.start()
        assert kernel.task is not None
        assert not kernel.task.done()
        await asyncio.wait_for(kernel.stop(), timeout=5.0)
        assert kernel.task is None

    asyncio.run(scenario())


def test_wakeup_still_shortens_a_hinted_sleep() -> None:
    """request_wake cuts a long hinted sleep short — the hint does not
    disarm the wakeup path."""
    ticks: list[int] = []

    async def scenario() -> None:
        second = asyncio.Event()

        async def on_tick(now_ms: int) -> None:
            ticks.append(now_ms)
            if len(ticks) >= 2:
                second.set()

        kernel = SchedulerKernel(
            tick_interval_ms=60_000,
            now_fn=lambda: 1000,
            on_tick=on_tick,
            sleep_hint_fn=lambda now_ms: 60_000,
        )
        kernel.start()
        for _ in range(1000):
            await asyncio.sleep(0)
            if ticks:
                break
        assert ticks, "first tick did not run"
        kernel.request_wake()
        await asyncio.wait_for(second.wait(), timeout=2.0)
        await asyncio.wait_for(kernel.stop(), timeout=5.0)

    asyncio.run(scenario())

    assert len(ticks) >= 2


def test_concurrent_start_while_stopping_does_not_orphan_the_loop() -> None:
    """Regression: the old unconditional ``self._task = None`` at the tail of
    stop() nulled a NEW loop task installed by a start() that landed in the
    microstep where the old task was already done but stop() had not resumed.
    The kernel must release the handle only if this stop() still owns it."""

    async def scenario() -> None:
        kernel = SchedulerKernel(
            tick_interval_ms=60_000,
            now_fn=lambda: 1000,
            on_tick=_noop_tick,
            task_name="t-orphan",
            sleep_hint_fn=lambda now_ms: 60_000,
        )
        kernel.start()
        first = kernel.task
        assert first is not None
        # Registered BEFORE stop() awaits the task, so this callback runs in
        # the same completion batch but ahead of stop()'s own resume callback:
        # at that point first is done (is_running is False) and start()
        # legitimately installs a NEW loop task.
        first.add_done_callback(lambda _t: kernel.start())
        try:
            await asyncio.wait_for(kernel.stop(), timeout=5.0)

            live = _tasks_named("t-orphan")
            assert len(live) == 1, "the restarted loop must still be alive"
            assert kernel.task is not None
            assert kernel.task is not first
            assert not kernel.task.done()
            assert kernel.is_running is True

            # And the public stop() must be able to reap the replacement.
            await asyncio.wait_for(kernel.stop(), timeout=5.0)
            assert _tasks_named("t-orphan") == []
            assert kernel.task is None
        finally:
            for t in _tasks_named("t-orphan"):
                t.cancel()

    asyncio.run(scenario())


def test_start_refused_while_stop_in_flight_logs_and_does_not_spawn_second_task() -> None:
    """While stop() is in flight and its loop task has not been reaped yet
    (is_running still True), start() must refuse: no second loop task, and a
    visible refusal log instead of a silent no-op."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    async def scenario() -> None:
        kernel = SchedulerKernel(
            tick_interval_ms=60_000,
            now_fn=lambda: 1000,
            on_tick=_noop_tick,
            task_name="t-refuse",
            sleep_hint_fn=lambda now_ms: 60_000,
        )
        kernel.start()
        first = kernel.task
        assert first is not None
        stopper = asyncio.create_task(kernel.stop())
        await asyncio.sleep(0)  # let stop() set _stopping and cancel the loop
        assert kernel._stopping is True

        kernel.start()  # refused: the old task is still running (not reaped)
        assert len(_tasks_named("t-refuse")) == 1  # no second loop spawned

        await asyncio.wait_for(stopper, timeout=5.0)
        assert kernel.task is None
        assert kernel.is_running is False

    handler = _Capture()
    kernel_logger = logging.getLogger("src.scheduling.kernel")
    old_propagate = kernel_logger.propagate
    kernel_logger.propagate = False
    kernel_logger.addHandler(handler)
    try:
        asyncio.run(scenario())
    finally:
        kernel_logger.removeHandler(handler)
        kernel_logger.propagate = old_propagate

    assert any(
        record.levelno == logging.WARNING and "start refused" in record.getMessage()
        for record in records
    )
