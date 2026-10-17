"""Generic scheduler kernel: tick loop, wakeup, backoff, injectable clock.

Extracted from the loop machinery of ``src/scheduled_research/executor.py``
(scheduler unification) so every scheduler in the repo can share one
tick/wakeup/backoff implementation. The kernel is strictly generic: it knows
nothing about delivery outboxes, verdicts, briefings or playbooks — domain
logic attaches through the constructor's ``on_tick`` callback and stays in
the consumer's module.

Responsibilities (the complete list):

* :meth:`SchedulerKernel.start` / :meth:`SchedulerKernel.stop` /
  :attr:`SchedulerKernel.is_running` — lifecycle of the background task,
  with a ``task.cancel()`` fallback so shutdown never waits a full tick;
* :meth:`SchedulerKernel._run` / :meth:`SchedulerKernel._sleep_or_wake` —
  the tick loop with per-tick exception isolation and an ``asyncio.Event``
  wakeup that shortens the inter-tick sleep; the sleep is the fixed
  ``tick_interval_ms`` unless a consumer-provided ``sleep_hint_fn`` replaces
  it with an adaptive "next deadline" hint (the seam the live runtime
  scheduler's ``min(next_due - now, max_recheck)`` sleep adopts);
* :meth:`SchedulerKernel.request_wake` — thread-safe, coalescing request to
  cut the current sleep short;
* :meth:`SchedulerKernel.retry_delay_ms` — bounded exponential backoff;
* constructor parameter validation.

The kernel never reads the environment: retry knobs are plain constructor
arguments whose defaults mirror ``AgentTuningConfig`` in
``src/config/env_schema.py`` (``max_consecutive_failures=3``,
``retry_base_delay_ms=60_000``, ``retry_max_delay_ms=3_600_000``); callers
inject configured values.

Single-writer invariant: one kernel instance is owned by exactly one
composition root — today the FastAPI lifespan owns the scheduled-research
executor's kernel, and the live runtime owns one kernel per runner start —
so the kernel never coordinates multiple owners and must not be started from
two loops.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from src.scheduling.types import NowFn, OnTickFn, SleepHintFn

logger = logging.getLogger(__name__)

#: Default poll interval of the background loop (mirrors the executor's
#: ``DEFAULT_TICK_INTERVAL_MS``; consumers may override per instance).
DEFAULT_TICK_INTERVAL_MS = 60 * 1000

#: Default ``asyncio`` task name; injectable so consumers keep their own
#: observable task identity (e.g. ``"scheduled-research-executor"``).
DEFAULT_TASK_NAME = "scheduler-kernel"

#: Mirrors of the env-schema defaults — see the module docstring. The kernel
#: itself never touches ``os.environ``.
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3
DEFAULT_RETRY_BASE_DELAY_MS = 60 * 1000
DEFAULT_RETRY_MAX_DELAY_MS = 3_600_000


def _now_ms() -> int:
    """Return current wall-clock time in epoch milliseconds."""
    return int(time.time() * 1000)


class SchedulerKernel:
    """Background tick loop with wakeup, backoff and an injectable clock.

    The loop calls ``on_tick(now_ms)`` once per tick, isolates its exceptions
    (one failing tick never kills the loop; ``asyncio.CancelledError``
    propagates so :meth:`stop` stays bounded), then sleeps — the fixed
    ``tick_interval_ms``, or when ``sleep_hint_fn`` is injected, the hint it
    returns for the post-tick clock — unless a :meth:`request_wake` shortens
    the sleep.

    Due-ness, next-run advancement and per-job error recording are the
    consumer's own ``on_tick`` composition — the kernel stores the retry
    policy and exposes it read-only, but never interprets jobs itself.
    """

    def __init__(
        self,
        *,
        tick_interval_ms: int = DEFAULT_TICK_INTERVAL_MS,
        now_fn: NowFn = _now_ms,
        enabled: bool = True,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
        retry_base_delay_ms: int = DEFAULT_RETRY_BASE_DELAY_MS,
        retry_max_delay_ms: int = DEFAULT_RETRY_MAX_DELAY_MS,
        on_tick: Optional[OnTickFn] = None,
        task_name: str = DEFAULT_TASK_NAME,
        sleep_hint_fn: Optional[SleepHintFn] = None,
    ) -> None:
        """Initialize the kernel.

        Args:
            tick_interval_ms: Poll interval for the background loop. Also the
                fallback sleep when ``sleep_hint_fn`` is set but raises.
            now_fn: Injectable wall-clock source returning epoch milliseconds.
            enabled: When false, :meth:`start` and :meth:`stop` are no-ops.
            max_consecutive_failures: Failures allowed before a consumer
                treats a job as terminal (stored policy; the kernel itself
                does not enforce it — see the class docstring).
            retry_base_delay_ms: Base delay for exponential retry backoff.
            retry_max_delay_ms: Upper bound for exponential retry backoff.
            on_tick: Async callable invoked once per tick with ``now_ms``.
            task_name: Name of the background ``asyncio`` task.
            sleep_hint_fn: Optional consumer-provided "next deadline" sleep
                hint. Called after each tick with a freshly read ``now_ms``;
                its return value (clamped non-negative) replaces
                ``tick_interval_ms`` as the inter-tick sleep, letting an
                adaptive-sleep consumer keep its sleep shape. A hint that
                raises is logged and falls back to ``tick_interval_ms``.

        Raises:
            ValueError: If the retry policy is invalid.
        """
        if max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be at least 1")
        if retry_base_delay_ms < 0:
            raise ValueError("retry_base_delay_ms must be non-negative")
        if retry_max_delay_ms < retry_base_delay_ms:
            raise ValueError("retry_max_delay_ms must be at least retry_base_delay_ms")
        self._tick_interval_ms = tick_interval_ms
        self._now_fn = now_fn
        self._enabled = enabled
        self._max_consecutive_failures = max_consecutive_failures
        self._retry_base_delay_ms = retry_base_delay_ms
        self._retry_max_delay_ms = retry_max_delay_ms
        self._on_tick = on_tick
        self._task_name = task_name
        self._sleep_hint_fn = sleep_hint_fn
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._wakeup: asyncio.Event | None = None
        self._stopping = False

    # -- policy surface (read-only) -----------------------------------------

    @property
    def tick_interval_ms(self) -> int:
        """Return the poll interval of the background loop."""
        return self._tick_interval_ms

    @property
    def enabled(self) -> bool:
        """Return whether start/stop manage a background task at all."""
        return self._enabled

    @property
    def max_consecutive_failures(self) -> int:
        """Return the stored failure budget of the retry policy."""
        return self._max_consecutive_failures

    @property
    def retry_base_delay_ms(self) -> int:
        """Return the base delay of the retry policy."""
        return self._retry_base_delay_ms

    @property
    def retry_max_delay_ms(self) -> int:
        """Return the upper bound of the retry policy."""
        return self._retry_max_delay_ms

    @property
    def task_name(self) -> str:
        """Return the name given to the background task on :meth:`start`."""
        return self._task_name

    @property
    def on_tick(self) -> Optional[OnTickFn]:
        """Return the injected per-tick callback (the only one the loop calls)."""
        return self._on_tick

    @property
    def sleep_hint_fn(self) -> Optional[SleepHintFn]:
        """Return the injected adaptive-sleep hint, or ``None`` for fixed-tick."""
        return self._sleep_hint_fn

    # -- lifecycle ------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Return whether the background loop task is active."""
        return self._task is not None and not self._task.done()

    @property
    def task(self) -> asyncio.Task | None:
        """Return the background loop task, or ``None`` when not started.

        Read-only handle for owners that must await or inspect the loop task
        itself (e.g. a driver coroutine parking on the scheduler's lifetime).
        """
        return self._task

    def start(self) -> None:
        """Start the background loop.

        Idempotent. When disabled, this is a no-op. Must be called from the
        event loop that will own the task.
        """
        if not self._enabled:
            return
        if self.is_running:
            if self._stopping:
                # A stop() is in flight and the old loop task has not been reaped
                # yet: refuse rather than risk racing the teardown. Logged so a
                # refused restart is visible instead of a silent no-op.
                logger.warning("scheduler kernel start refused: a stop is in flight")
            return
        self._stopping = False
        self._wakeup = asyncio.Event()
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run(), name=self._task_name)

    async def stop(self) -> None:
        """Stop the background loop and wait for it to finish.

        Idempotent. When disabled or not started, this is a no-op. Bounded
        even when a tick is wedged: the wakeup set below releases a sleeping
        loop in the common case, and ``task.cancel()`` is the fallback so
        shutdown never blocks for a full tick (or forever) if the wakeup
        raced the loop's sleep or the tick itself is stuck. The loop-task
        handle is released only if this stop() still owns it.
        """
        if not self._enabled:
            return
        task = self._task
        if task is None:
            return
        self._stopping = True
        if self._wakeup is not None:
            self._wakeup.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # Release the handle only if this stop() still owns it. A concurrent
        # start() can legitimately land between the old loop task finishing and
        # this line (once the task is done, is_running is False) and install a
        # NEW loop task; clearing it here would orphan a running loop that
        # reports itself stopped and that no later stop() can reach.
        if self._task is task:
            self._task = None

    # -- loop internals -------------------------------------------------------

    async def _run(self) -> None:
        # Captured here rather than at construction: the kernel is built
        # before the owner's loop exists, and request_wake needs a loop that
        # is actually running to schedule onto.
        self._loop = asyncio.get_running_loop()
        while not self._stopping:
            try:
                if self._on_tick is not None:
                    await self._on_tick(self._now_fn())
            except asyncio.CancelledError:
                raise
            except Exception:
                # Per-tick isolation: one failing tick must not kill the
                # loop; the next tick runs on schedule.
                logger.error("scheduler kernel tick failed", exc_info=True)
            if self._stopping:
                break
            await self._sleep_or_wake(self._next_sleep_ms())

    def _next_sleep_ms(self) -> int:
        """Return the inter-tick sleep: the consumer's hint, or the fixed tick.

        The hint is read against a freshly sampled clock (post-tick), so an
        adaptive consumer computes its deadline against the same "now" shape
        its own loop would have. A raising hint is logged and demoted to the
        fixed tick — a buggy hint slows the loop down but never kills it.
        """
        if self._sleep_hint_fn is None:
            return self._tick_interval_ms
        try:
            return max(0, self._sleep_hint_fn(self._now_fn()))
        except Exception:
            logger.error("scheduler kernel sleep hint failed; using fixed tick", exc_info=True)
            return self._tick_interval_ms

    async def _sleep_or_wake(self, sleep_ms: int) -> None:
        wakeup = self._wakeup
        if wakeup is None:
            await asyncio.sleep(sleep_ms / 1000.0)
            return
        # Re-check after re-entering: if stop() flipped _stopping and set the
        # event between the loop's check and here, return at once rather than
        # clearing the wakeup and blocking for a full tick on shutdown.
        if self._stopping:
            return
        wakeup.clear()
        try:
            await asyncio.wait_for(wakeup.wait(), timeout=sleep_ms / 1000.0)
        except asyncio.TimeoutError:
            pass

    # -- cross-thread wakeup ----------------------------------------------------

    def request_wake(self) -> None:
        """Ask the loop to cut its current sleep short, as soon as it can.

        Thread-safe: called from whichever thread an event arrives on, so it
        must not block and must not touch the loop directly. Wakes coalesce:
        a wakeup already pending (set but not yet consumed by the loop)
        covers anything that arrives while it is pending, so a second request
        is a no-op. Without a running loop this is a no-op — the periodic
        tick is what makes the consumer correct, and this only makes it
        prompt.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        wakeup = self._wakeup
        if wakeup is None or wakeup.is_set():
            return
        try:
            loop.call_soon_threadsafe(self._set_wakeup)
        except RuntimeError:
            # The loop closed between the check and the call; the next tick
            # (or the owner's shutdown path) picks the work up.
            pass

    def _set_wakeup(self) -> None:
        """Set the wakeup event; runs on the loop thread via call_soon."""
        if self._wakeup is not None:
            self._wakeup.set()

    # -- retry policy -----------------------------------------------------------

    def retry_delay_ms(self, consecutive_failures: int) -> int:
        """Return bounded exponential backoff for a failure count.

        ``1 -> base``, ``2 -> 2*base``, ``3 -> 4*base`` … clamped by
        ``retry_max_delay_ms``; a zero base disables backoff entirely. The
        exponent is capped at 62 so absurd failure counts cannot overflow
        into slow big-int arithmetic.
        """
        exponent = max(0, consecutive_failures - 1)
        if self._retry_base_delay_ms == 0:
            return 0
        delay = self._retry_base_delay_ms * (2 ** min(exponent, 62))
        return min(delay, self._retry_max_delay_ms)
