"""Executor for persisted scheduled research jobs.

The executor polls :class:`ScheduledResearchJobStore`, dispatches due jobs via
an injected async callable, and persists lifecycle/next-run updates after each
attempt. Schedule math is intentionally pure and clock-injected so tests can
exercise it without sleeping or reading wall-clock time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from src.config.accessor import get_env_config
from src.scheduled_research.models import (
    CRON_BOUNDS,
    JobStatus,
    ScheduledResearchJob,
    parse_cron_field,
    validate_schedule,
    validate_timezone,
)
from src.scheduled_research.store import ScheduledResearchJobStore
from src.tools.redaction import redact_internal_paths, redact_text

logger = logging.getLogger(__name__)

DEFAULT_TICK_INTERVAL_MS = 60 * 1000
SCHEDULER_ENABLED_ENV = "VIBE_TRADING_ENABLE_SCHEDULER"
_MAX_PERSISTED_ERROR_CHARS = 1000

NowFn = Callable[[], int]
DispatchCallback = Callable[[ScheduledResearchJob], Awaitable[None]]

_TRUE_VALUES = {"1", "true", "yes", "on"}
# Search by day, not by minute, so an impossible date (e.g. Feb 31) fails fast
# instead of scanning years of minutes on the event loop. Four years covers any
# real recurrence, including a Feb-29 leap day; the extra headroom absorbs a
# yearly occurrence landing in a DST spring-forward gap (skipped by policy)
# several years in a row before a real instant exists again.
_CRON_SEARCH_LIMIT_DAYS = 6 * 366 + 1


def _now_ms() -> int:
    """Return current wall-clock time in epoch milliseconds."""
    return int(time.time() * 1000)


def scheduler_enabled_from_env(value: str | None = None) -> bool:
    """Return whether the scheduled-research executor should run.

    The feature is disabled by default. Pass *value* in tests to avoid mutating
    process environment.
    """
    if value is not None:
        return value.strip().lower() in _TRUE_VALUES
    return get_env_config().agent_tuning.vibe_trading_enable_scheduler


def is_due(job: ScheduledResearchJob, now_ms: int) -> bool:
    """Return whether *job* should fire at ``now_ms``.

    Cancelled and failed jobs are terminal and never re-dispatched; a failed
    job in particular keeps its old ``next_run_at`` (advancement may itself be
    what failed), so excluding it here prevents a re-dispatch loop every tick.
    Already-running jobs are left alone during live polling. Executor startup
    recovers stale persisted ``RUNNING`` jobs separately.
    """
    if job.status in {JobStatus.CANCELLED, JobStatus.RUNNING, JobStatus.FAILED}:
        return False
    return job.next_run_at <= now_ms


def _persisted_error(exc: Exception) -> str:
    """Return a bounded, redaction-safe error for durable job state."""
    message = f"{type(exc).__name__}: {exc}"
    safe = redact_text(redact_internal_paths(message)).replace("\x00", "")
    if len(safe) <= _MAX_PERSISTED_ERROR_CHARS:
        return safe
    return f"{safe[: _MAX_PERSISTED_ERROR_CHARS - 3]}..."


def next_due(schedule: str, after_ms: int, tz: str | None = None) -> int:
    """Return the first due epoch-ms strictly after ``after_ms``.

    Supports the scheduled-research schedule format: a bare positive integer
    string for interval milliseconds, or a simplified 5-field cron expression.
    Cron is evaluated on the wall clock of *tz* (an IANA timezone key) when
    one is given, in UTC otherwise — the semantics every job had before the
    field existed. Interval schedules ignore *tz* entirely.
    """
    validate_schedule(schedule)
    spec = schedule.strip()
    if spec.isdigit():
        # Before the timezone check: interval schedules must keep advancing
        # even when the stored key cannot resolve on this host.
        return after_ms + int(spec)
    validate_timezone(tz)
    return _next_cron_due(spec, after_ms, tz)


def _next_cron_due(schedule: str, after_ms: int, tz: str | None = None) -> int:
    minutes, hours, doms, months, dows = (
        parse_cron_field(part, low, high) for part, (low, high) in zip(schedule.split(), CRON_BOUNDS)
    )
    zone = timezone.utc if tz is None else ZoneInfo(tz)
    # Walk candidates on the *local* calendar of ``zone`` so field matching —
    # the weekday in particular — follows the authoring wall clock. Ascending
    # wall order maps to ascending UTC order under a fixed fold policy, so
    # "strictly after" stays a plain epoch comparison.
    day = datetime.fromtimestamp(after_ms / 1000.0, zone).date()
    for offset in range(_CRON_SEARCH_LIMIT_DAYS):
        candidate_day = day + timedelta(days=offset)
        if not _day_matches(candidate_day, doms, months, dows):
            continue
        for hour in sorted(hours) if hours is not None else range(24):
            for minute in sorted(minutes) if minutes is not None else range(60):
                fire_ms = _local_wall_time_to_epoch_ms(candidate_day, hour, minute, zone)
                if fire_ms is not None and fire_ms > after_ms:
                    return fire_ms
    raise ValueError(f"cron schedule has no matching time within search window: {schedule!r}")


def _local_wall_time_to_epoch_ms(day: date, hour: int, minute: int, zone: tzinfo) -> int | None:
    """Resolve one local wall time to a UTC epoch-ms instant.

    DST policy (#953): a nonexistent wall time — the spring-forward gap —
    returns ``None`` so the occurrence is skipped; ``ZoneInfo`` would
    otherwise silently map it past the transition (PEP 495) and run it. An
    ambiguous wall time — the fall-back fold — resolves with ``fold=0``, the
    first occurrence, so it runs exactly once.
    """
    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
    as_utc = local.astimezone(timezone.utc)
    if as_utc.astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
        return None  # wall time does not exist in this zone (DST gap)
    return int(as_utc.timestamp() * 1000)


def _day_matches(dt: date, doms: set[int] | None, months: set[int] | None, dows: set[int] | None) -> bool:
    if months is not None and dt.month not in months:
        return False

    cron_day_of_week = (dt.weekday() + 1) % 7  # cron convention: Sunday == 0
    day_of_month_matches = doms is None or dt.day in doms
    day_of_week_matches = dows is None or cron_day_of_week in dows

    # Standard five-field cron treats day-of-month and day-of-week as an OR
    # when both fields are restricted. A wildcard in either field keeps the
    # other field authoritative.
    if doms is not None and dows is not None:
        return day_of_month_matches or day_of_week_matches
    return day_of_month_matches and day_of_week_matches


class ScheduledResearchExecutor:
    """Background poller that dispatches due scheduled research jobs."""

    def __init__(
        self,
        store: ScheduledResearchJobStore,
        dispatch: DispatchCallback,
        *,
        tick_interval_ms: int = DEFAULT_TICK_INTERVAL_MS,
        now_fn: NowFn = _now_ms,
        enabled: bool = True,
        max_consecutive_failures: int | None = None,
        retry_base_delay_ms: int | None = None,
        retry_max_delay_ms: int | None = None,
    ) -> None:
        """Initialize the executor.

        Args:
            store: Durable scheduled job store.
            dispatch: Async callable invoked once for each due job.
            tick_interval_ms: Poll interval for the background loop.
            now_fn: Injectable wall-clock source returning epoch milliseconds.
            enabled: When false, :meth:`start` and :meth:`stop` are no-ops.
            max_consecutive_failures: Dispatch failures allowed before a job
                becomes terminal. Defaults to environment configuration.
            retry_base_delay_ms: Base delay for exponential retry backoff.
            retry_max_delay_ms: Upper bound for exponential retry backoff.

        Raises:
            ValueError: If the retry policy is invalid.
        """
        tuning = None
        if None in (max_consecutive_failures, retry_base_delay_ms, retry_max_delay_ms):
            tuning = get_env_config().agent_tuning
        self._store = store
        self._dispatch = dispatch
        self._tick_interval_ms = tick_interval_ms
        self._now_fn = now_fn
        self._enabled = enabled
        self._max_consecutive_failures = (
            max_consecutive_failures
            if max_consecutive_failures is not None
            else tuning.vibe_trading_scheduler_max_consecutive_failures
        )
        self._retry_base_delay_ms = (
            retry_base_delay_ms
            if retry_base_delay_ms is not None
            else tuning.vibe_trading_scheduler_retry_base_delay_ms
        )
        self._retry_max_delay_ms = (
            retry_max_delay_ms
            if retry_max_delay_ms is not None
            else tuning.vibe_trading_scheduler_retry_max_delay_ms
        )
        if self._max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be at least 1")
        if self._retry_base_delay_ms < 0:
            raise ValueError("retry_base_delay_ms must be non-negative")
        if self._retry_max_delay_ms < self._retry_base_delay_ms:
            raise ValueError("retry_max_delay_ms must be at least retry_base_delay_ms")
        self._task: asyncio.Task | None = None
        self._wakeup: asyncio.Event | None = None
        self._stopping = False
        self._recovered_stale_running = False

    @property
    def is_running(self) -> bool:
        """Return whether the background loop task is active."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the background loop.

        Idempotent. When disabled, this is a no-op.
        """
        if not self._enabled or self.is_running:
            return
        self._stopping = False
        self.recover_stale_running()
        self._wakeup = asyncio.Event()
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._run(), name="scheduled-research-executor")

    async def stop(self) -> None:
        """Stop the background loop and wait for it to finish.

        Idempotent. When disabled or not started, this is a no-op.
        """
        if not self._enabled:
            return
        task = self._task
        if task is None:
            return
        self._stopping = True
        if self._wakeup is not None:
            self._wakeup.set()
        # The set() above wakes a sleeping loop in the common case. Cancel as a
        # fallback so shutdown never blocks for a full tick if the wakeup raced
        # the loop's sleep, then await the task to let it unwind cleanly.
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def tick(self, now_ms: int | None = None) -> None:
        """Run one poll/dispatch pass.

        Args:
            now_ms: Optional explicit reference time. Defaults to ``now_fn``.
        """
        self.recover_stale_running()
        now = self._now_fn() if now_ms is None else now_ms
        jobs = sorted(
            (job for job in self._store.load().values() if is_due(job, now)),
            key=lambda job: job.next_run_at,
        )
        for job in jobs:
            # One job's unexpected persistence/lifecycle error must not starve
            # every job sorted after it, tick after tick.
            try:
                await self._run_job(job, now)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("scheduled research job %s failed its run cycle", job.id, exc_info=True)

    def recover_stale_running(self) -> int:
        """Reset jobs left ``RUNNING`` by a previous executor process.

        This runs at most once per executor instance. Jobs that become
        ``RUNNING`` after this recovery step are treated as live in-flight work
        and remain skipped by :func:`is_due`.
        """
        if self._recovered_stale_running:
            return 0

        jobs = self._store.load()
        recovered = 0
        for job in jobs.values():
            if job.status != JobStatus.RUNNING:
                continue
            job.status = JobStatus.PENDING
            recovered += 1
            logger.warning("recovering stale scheduled research job %s from running to pending", job.id)

        if recovered:
            self._store.save(jobs)
        self._recovered_stale_running = True
        return recovered

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self.tick(self._now_fn())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("scheduled research executor tick failed", exc_info=True)
            if self._stopping:
                break
            await self._sleep_or_wake(self._tick_interval_ms)

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

    async def _run_job(self, job: ScheduledResearchJob, now_ms: int) -> None:
        # The tick snapshot may be stale by the time we reach this job (an
        # earlier dispatch was awaited). Re-read and confirm identity before
        # marking it RUNNING so a job the user deleted or replaced in the
        # meantime is not resurrected or dispatched.
        current = self._store.get(job.id)
        if current is None or not self._same_record(current, job) or not is_due(current, now_ms):
            return
        job = current

        # A persisted schedule the current grammar rejects (an older release
        # accepted a form since narrowed) must surface as a failed job, not as
        # an exception on the way to dispatch: that would leave the record
        # PENDING and due, retrying on every tick forever with nothing visible
        # to the user.
        try:
            validate_schedule(job.schedule)
        except ValueError as exc:
            logger.error("scheduled research job %s has an invalid schedule", job.id, exc_info=True)
            job.status = JobStatus.FAILED
            job.failure_kind = "schedule"
            job.last_error = _persisted_error(exc)
            job.last_run_at = now_ms
            self._persist_completion(job)
            return

        job.status = JobStatus.RUNNING
        # Lifecycle writes bypass validation: this record is already persisted,
        # and a write that cannot land would strand the job mid-flight.
        self._store.upsert(job, validate=False)

        dispatch_error: Exception | None = None
        try:
            await self._dispatch(job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("scheduled research dispatch failed for job %s", job.id, exc_info=True)
            dispatch_error = exc
            job.consecutive_failures += 1
        else:
            job.consecutive_failures = 0

        job.last_run_at = now_ms
        try:
            scheduled_next_run = next_due(job.schedule, now_ms, job.timezone)
        except Exception as exc:
            logger.error("scheduled research schedule advancement failed for job %s", job.id, exc_info=True)
            job.status = JobStatus.FAILED
            job.failure_kind = "schedule"
            job.last_error = _persisted_error(exc)
            self._persist_completion(job)
            return

        job.next_run_at = scheduled_next_run
        if dispatch_error is None:
            job.status = JobStatus.COMPLETED
            job.failure_kind = None
            job.last_error = None
        else:
            job.failure_kind = "dispatch"
            job.last_error = _persisted_error(dispatch_error)
            if job.consecutive_failures >= self._max_consecutive_failures:
                job.status = JobStatus.FAILED
            else:
                job.status = JobStatus.PENDING
                retry_delay = self._retry_delay_ms(job.consecutive_failures)
                job.next_run_at = max(scheduled_next_run, now_ms + retry_delay)
                logger.warning(
                    "scheduled research job %s will retry after failure %d/%d at %d",
                    job.id,
                    job.consecutive_failures,
                    self._max_consecutive_failures,
                    job.next_run_at,
                )
        self._persist_completion(job)

    def _retry_delay_ms(self, consecutive_failures: int) -> int:
        """Return bounded exponential backoff for a dispatch failure count."""
        exponent = max(0, consecutive_failures - 1)
        if self._retry_base_delay_ms == 0:
            return 0
        delay = self._retry_base_delay_ms * (2 ** min(exponent, 62))
        return min(delay, self._retry_max_delay_ms)

    @staticmethod
    def _same_record(current: ScheduledResearchJob, job: ScheduledResearchJob) -> bool:
        """Return whether *current* is the same scheduled run we started.

        ``created_at`` is assigned once at creation, so a replacement POST for
        the same id (which the API stamps with a fresh ``created_at``) is
        distinguishable even when the schedule is unchanged.
        """
        return current.id == job.id and current.created_at == job.created_at

    def _persist_completion(self, job: ScheduledResearchJob) -> None:
        """Write a finished job back, unless it was changed during dispatch.

        Dispatch is awaited, so a concurrent DELETE or POST for the same id can
        land while a run is in flight. Reload first: if the record is gone the
        user cancelled it (do not resurrect), and if it is a different record
        (replaced via POST) let the new definition own its lifecycle. Only
        persist our completion when it still refers to the same scheduled run.
        """
        current = self._store.get(job.id)
        if current is None:
            logger.info("scheduled research job %s deleted during dispatch; skipping completion write", job.id)
            return
        if not self._same_record(current, job):
            logger.info("scheduled research job %s replaced during dispatch; skipping completion write", job.id)
            return
        self._store.upsert(job, validate=False)
