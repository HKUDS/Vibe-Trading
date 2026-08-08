"""Tests for the scheduled research executor."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from src.scheduled_research.executor import (
    ScheduledResearchExecutor,
    is_due,
    next_due,
    scheduler_enabled_from_env,
)
from src.scheduled_research.models import JobStatus, ScheduledResearchJob
from src.scheduled_research.store import ScheduledResearchJobStore


def _ms(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def _local_ms(tz: str, year: int, month: int, day: int, hour: int, minute: int, *, fold: int = 0) -> int:
    """Epoch-ms of a wall-clock time in an IANA zone (``fold=0`` = first occurrence)."""
    local = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(tz), fold=fold)
    return int(local.timestamp() * 1000)


def _store(tmp_path: Path) -> ScheduledResearchJobStore:
    return ScheduledResearchJobStore(path=tmp_path / "jobs.json")


def _job(
    job_id: str = "job-001",
    *,
    schedule: str = "1000",
    next_run_at: int = 0,
    status: JobStatus = JobStatus.PENDING,
    created_at: int = 0,
    timezone: str | None = None,
) -> ScheduledResearchJob:
    return ScheduledResearchJob(
        id=job_id,
        prompt=f"prompt for {job_id}",
        schedule=schedule,
        next_run_at=next_run_at,
        status=status,
        created_at=created_at,
        timezone=timezone,
    )


def test_interval_job_fires_and_persists_completion(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job(schedule="5000", next_run_at=1000))
    calls: list[tuple[str, JobStatus]] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append((job.id, job.status))

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(1500)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    assert calls == [("job-001", JobStatus.RUNNING)]
    assert saved.status == JobStatus.COMPLETED
    assert saved.last_run_at == 1500
    assert saved.next_run_at == 6500


def test_cron_job_next_due_and_not_before_due_time(tmp_path: Path) -> None:
    store = _store(tmp_path)
    before_due = _ms(2026, 6, 20, 5, 59)
    due_at = _ms(2026, 6, 20, 6, 0)
    following_due = _ms(2026, 6, 20, 12, 0)
    assert next_due("0 */6 * * *", before_due) == due_at

    store.upsert(_job(schedule="0 */6 * * *", next_run_at=due_at))
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(due_at - 1)
        assert calls == []
        await executor.tick(due_at)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    assert calls == ["job-001"]
    assert saved.status == JobStatus.COMPLETED
    assert saved.last_run_at == due_at
    assert saved.next_run_at == following_due


def test_cron_uses_standard_or_semantics_for_restricted_day_fields() -> None:
    thursday = _ms(2026, 6, 11, 0, 1)

    # The 12th is a Friday, so it matches day-of-week even though it is not
    # the 13th day of the month.
    assert next_due("0 0 13 * 5", thursday) == _ms(2026, 6, 12, 0, 0)

    friday = _ms(2026, 6, 12, 0, 1)
    # The 13th is a Saturday, so the following run matches day-of-month even
    # though it is not Friday.
    assert next_due("0 0 13 * 5", friday) == _ms(2026, 6, 13, 0, 0)


def test_cron_wildcard_day_field_leaves_other_day_field_authoritative() -> None:
    thursday = _ms(2026, 6, 11, 0, 1)

    assert next_due("0 0 13 * *", thursday) == _ms(2026, 6, 13, 0, 0)
    assert next_due("0 0 * * 5", thursday) == _ms(2026, 6, 12, 0, 0)


def test_dispatch_failure_stays_retryable_and_tick_continues(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job("bad", next_run_at=10))
    store.upsert(_job("good", next_run_at=20))
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)
        if job.id == "bad":
            raise RuntimeError("boom")

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(
            store,
            dispatch,
            max_consecutive_failures=3,
            retry_base_delay_ms=1000,
            retry_max_delay_ms=4000,
        )
        await executor.tick(100)

    asyncio.run(scenario())

    bad = store.get("bad")
    good = store.get("good")
    assert bad is not None
    assert good is not None
    assert calls == ["bad", "good"]
    assert bad.status == JobStatus.PENDING
    assert bad.consecutive_failures == 1
    assert bad.failure_kind == "dispatch"
    assert bad.last_error == "RuntimeError: boom"
    assert bad.next_run_at == 1100
    assert good.status == JobStatus.COMPLETED


def test_transient_dispatch_failure_retries_then_success_resets_state(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job(schedule="1000", next_run_at=0))
    calls = 0

    async def dispatch(job: ScheduledResearchJob) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("provider timed out")

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(
            store,
            dispatch,
            max_consecutive_failures=3,
            retry_base_delay_ms=1000,
            retry_max_delay_ms=4000,
        )
        await executor.tick(100)
        await executor.tick(1099)
        assert calls == 1
        await executor.tick(1100)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    assert calls == 2
    assert saved.status == JobStatus.COMPLETED
    assert saved.consecutive_failures == 0
    assert saved.failure_kind is None
    assert saved.last_error is None
    assert saved.last_run_at == 1100
    assert saved.next_run_at == 2100


def test_repeated_dispatch_failures_become_terminal_at_threshold(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job(schedule="1000", next_run_at=0))
    calls = 0

    async def dispatch(job: ScheduledResearchJob) -> None:
        nonlocal calls
        calls += 1
        raise ConnectionError("provider unavailable")

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(
            store,
            dispatch,
            max_consecutive_failures=2,
            retry_base_delay_ms=0,
            retry_max_delay_ms=0,
        )
        await executor.tick(100)
        await executor.tick(1100)
        await executor.tick(10_000)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    assert calls == 2
    assert saved.status == JobStatus.FAILED
    assert saved.consecutive_failures == 2
    assert saved.failure_kind == "dispatch"
    assert saved.last_error == "ConnectionError: provider unavailable"
    assert saved.next_run_at == 2100


def test_persisted_dispatch_error_is_redacted_and_bounded(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job(next_run_at=0))
    secret = "scheduler-secret-value"
    raw_error = f"api_key={secret} path={Path.home()}/private/trace " + ("x" * 2000)

    async def dispatch(job: ScheduledResearchJob) -> None:
        raise RuntimeError(raw_error)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(
            store,
            dispatch,
            max_consecutive_failures=1,
            retry_base_delay_ms=0,
            retry_max_delay_ms=0,
        )
        await executor.tick(100)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    assert saved.last_error is not None
    assert secret not in saved.last_error
    assert str(Path.home()) not in saved.last_error
    assert "[redacted]" in saved.last_error
    assert "<redacted>/private/trace" in saved.last_error
    assert len(saved.last_error) == 1000
    assert saved.last_error.endswith("...")


def test_stale_running_job_recovers_to_pending_and_fires_on_next_tick(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job("stale", schedule="1000", next_run_at=10, status=JobStatus.RUNNING))
    calls: list[tuple[str, JobStatus]] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append((job.id, job.status))

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        assert executor.recover_stale_running() == 1
        recovered = store.get("stale")
        assert recovered is not None
        assert recovered.status == JobStatus.PENDING
        await executor.tick(100)

    asyncio.run(scenario())

    saved = store.get("stale")
    assert saved is not None
    assert calls == [("stale", JobStatus.RUNNING)]
    assert saved.status == JobStatus.COMPLETED
    assert saved.last_run_at == 100
    assert saved.next_run_at == 1100


def test_impossible_cron_marks_failed_and_tick_continues(tmp_path: Path) -> None:
    store = _store(tmp_path)
    now = _ms(2026, 2, 1, 0, 0)
    store.upsert(_job("bad", schedule="0 0 31 2 *", next_run_at=10))
    store.upsert(_job("good", schedule="1000", next_run_at=20))
    calls: list[str] = []

    with pytest.raises(ValueError):
        next_due("0 0 31 2 *", now)

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(now)

    asyncio.run(scenario())

    bad = store.get("bad")
    good = store.get("good")
    assert bad is not None
    assert good is not None
    assert calls == ["bad", "good"]
    assert bad.status == JobStatus.FAILED
    assert bad.last_run_at == now
    assert bad.next_run_at == 10
    assert bad.failure_kind == "schedule"
    assert "cron schedule has no matching time" in (bad.last_error or "")
    assert good.status == JobStatus.COMPLETED


def test_cancelled_and_running_jobs_are_skipped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job("cancelled", next_run_at=0, status=JobStatus.CANCELLED))
    store.upsert(_job("pending", next_run_at=0, status=JobStatus.PENDING))
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        assert executor.recover_stale_running() == 0
        store.upsert(_job("running", next_run_at=0, status=JobStatus.RUNNING))
        await executor.tick(100)

    asyncio.run(scenario())

    assert is_due(store.get("cancelled"), 100) is False  # type: ignore[arg-type]
    assert is_due(store.get("running"), 100) is False  # type: ignore[arg-type]
    assert calls == ["pending"]
    assert store.get("cancelled").status == JobStatus.CANCELLED  # type: ignore[union-attr]
    assert store.get("running").status == JobStatus.RUNNING  # type: ignore[union-attr]
    assert store.get("pending").status == JobStatus.COMPLETED  # type: ignore[union-attr]


def test_failed_job_is_not_redispatched(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # A terminal FAILED job whose next_run_at is still in the past must not be
    # re-dispatched on the next tick (it would otherwise fire every poll).
    store.upsert(_job("failed", next_run_at=0, status=JobStatus.FAILED))
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(100)

    asyncio.run(scenario())

    assert is_due(store.get("failed"), 100) is False  # type: ignore[arg-type]
    assert calls == []
    assert store.get("failed").status == JobStatus.FAILED  # type: ignore[union-attr]


def test_retry_backoff_is_exponential_and_capped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job(schedule="100", next_run_at=0))

    async def dispatch(job: ScheduledResearchJob) -> None:
        raise TimeoutError("outage")

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(
            store,
            dispatch,
            max_consecutive_failures=4,
            retry_base_delay_ms=1000,
            retry_max_delay_ms=1500,
        )
        await executor.tick(0)
        first = store.get("job-001")
        assert first is not None
        assert first.next_run_at == 1000
        await executor.tick(1000)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    assert saved.consecutive_failures == 2
    assert saved.next_run_at == 2500


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_consecutive_failures": 0}, "max_consecutive_failures"),
        ({"retry_base_delay_ms": -1}, "retry_base_delay_ms"),
        (
            {"retry_base_delay_ms": 100, "retry_max_delay_ms": 99},
            "retry_max_delay_ms",
        ),
    ],
)
def test_invalid_retry_policy_is_rejected(
    tmp_path: Path, kwargs: dict[str, int], message: str
) -> None:
    async def dispatch(job: ScheduledResearchJob) -> None:
        return None

    with pytest.raises(ValueError, match=message):
        ScheduledResearchExecutor(_store(tmp_path), dispatch, **kwargs)


def test_job_deleted_during_dispatch_is_not_resurrected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job("job-001", schedule="1000", next_run_at=0))

    async def dispatch(job: ScheduledResearchJob) -> None:
        # Simulate a user DELETE landing while the run is in flight.
        store.delete(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(100)

    asyncio.run(scenario())

    # The deleted job must not reappear after dispatch completes.
    assert store.get("job-001") is None


def test_job_replaced_during_dispatch_is_not_overwritten(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job("job-001", schedule="1000", next_run_at=0))

    async def dispatch(job: ScheduledResearchJob) -> None:
        # Simulate a user POST replacing the job mid-run. The API stamps a fresh
        # created_at on every create, which is how a replacement is told apart
        # from the in-flight original (even when the schedule is unchanged).
        store.upsert(_job("job-001", schedule="5000", next_run_at=900, created_at=999))

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(100)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    # The replacement definition is preserved, not clobbered by the old run.
    assert saved.schedule == "5000"
    assert saved.next_run_at == 900
    assert saved.created_at == 999
    assert saved.status == JobStatus.PENDING


def test_restart_after_missed_window_honors_persisted_next_run_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job(schedule="5000", next_run_at=1000))
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        first = ScheduledResearchExecutor(store, dispatch)
        await first.tick(20_000)
        assert calls == ["job-001"]

        restarted = ScheduledResearchExecutor(store, dispatch)
        await restarted.tick(20_000)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    assert calls == ["job-001"]
    assert saved.status == JobStatus.COMPLETED
    assert saved.last_run_at == 20_000
    assert saved.next_run_at == 25_000


def test_disabled_executor_start_stop_are_noops(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert(_job(next_run_at=0))
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(
            store,
            dispatch,
            tick_interval_ms=1,
            now_fn=lambda: 100,
            enabled=False,
        )
        executor.start()
        assert executor.is_running is False
        await executor.stop()

    asyncio.run(scenario())

    assert scheduler_enabled_from_env("") is False
    assert scheduler_enabled_from_env("true") is True
    assert calls == []
    assert store.get("job-001").status == JobStatus.PENDING  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Timezone-aware cron evaluation (#953)
# ---------------------------------------------------------------------------


def test_tz_cron_weekday_survives_spring_forward_auckland() -> None:
    # NZ springs forward on Sun 2026-09-27 (02:00 NZST -> 03:00 NZDT). A
    # weekday-23:30 cadence authored in Auckland must fire Fri then Mon at
    # 23:30 local on both sides of the transition, even though the UTC offset
    # moves from +12 to +13.
    friday_fire = _local_ms("Pacific/Auckland", 2026, 9, 25, 23, 30)
    monday_fire = _local_ms("Pacific/Auckland", 2026, 9, 28, 23, 30)
    assert next_due("30 23 * * 1-5", friday_fire, "Pacific/Auckland") == monday_fire

    fired_local = datetime.fromtimestamp(monday_fire / 1000.0, ZoneInfo("Pacific/Auckland"))
    assert (fired_local.weekday(), fired_local.hour, fired_local.minute) == (0, 23, 30)


def test_tz_cron_weekday_survives_fall_back_auckland() -> None:
    # NZ falls back on Sun 2026-04-05 (03:00 NZDT -> 02:00 NZST).
    friday_fire = _local_ms("Pacific/Auckland", 2026, 4, 3, 23, 30)
    monday_fire = _local_ms("Pacific/Auckland", 2026, 4, 6, 23, 30)
    assert next_due("30 23 * * 1-5", friday_fire, "Pacific/Auckland") == monday_fire


def test_tz_cron_weekday_is_evaluated_in_authoring_zone() -> None:
    # Monday 00:30 in Auckland is still Sunday in UTC; the weekday field must
    # follow the authoring wall clock, not the UTC calendar.
    sunday_noon = _local_ms("Pacific/Auckland", 2026, 6, 14, 12, 0)
    monday_first = _local_ms("Pacific/Auckland", 2026, 6, 15, 0, 30)
    result = next_due("30 0 * * 1", sunday_noon, "Pacific/Auckland")
    assert result == monday_first
    assert datetime.fromtimestamp(result / 1000.0, timezone.utc).weekday() == 6  # Sunday in UTC


def test_tz_cron_half_hour_offset_adelaide() -> None:
    # ACST is UTC+9:30, so a 09:00 local fire lands on a half-hour UTC boundary.
    after = _local_ms("Australia/Adelaide", 2026, 6, 10, 9, 0)
    next_fire = _local_ms("Australia/Adelaide", 2026, 6, 11, 9, 0)
    result = next_due("0 9 * * *", after, "Australia/Adelaide")
    assert result == next_fire
    assert result % 3_600_000 == 1_800_000

    # Across the Adelaide spring-forward (Sun 2026-10-04, +9:30 -> +10:30) the
    # local fire time is preserved while the UTC instant shifts by an hour.
    before_transition = _local_ms("Australia/Adelaide", 2026, 10, 3, 9, 0)
    after_transition = _local_ms("Australia/Adelaide", 2026, 10, 4, 9, 0)
    assert next_due("0 9 * * *", before_transition, "Australia/Adelaide") == after_transition


def test_tz_cron_spring_forward_gap_skips_occurrence_new_york() -> None:
    # 02:30 does not exist on Sun 2026-03-08 in America/New_York (02:00 EST
    # jumps to 03:00 EDT). The occurrence is skipped, not shifted.
    saturday_fire = _local_ms("America/New_York", 2026, 3, 7, 2, 30)
    monday_fire = _local_ms("America/New_York", 2026, 3, 9, 2, 30)
    assert next_due("30 2 * * *", saturday_fire, "America/New_York") == monday_fire


def test_tz_cron_fall_back_ambiguous_time_runs_once_at_first_occurrence_new_york() -> None:
    # 01:30 happens twice on Sun 2026-11-01 in America/New_York (EDT 05:30Z,
    # then EST 06:30Z after the clocks fall back). The job runs once, at the
    # first occurrence, and the second occurrence is not a separate firing.
    saturday_fire = _local_ms("America/New_York", 2026, 10, 31, 1, 30)
    first_occurrence = _local_ms("America/New_York", 2026, 11, 1, 1, 30, fold=0)
    assert first_occurrence == _ms(2026, 11, 1, 5, 30)
    assert next_due("30 1 * * *", saturday_fire, "America/New_York") == first_occurrence

    monday_fire = _local_ms("America/New_York", 2026, 11, 2, 1, 30)
    assert next_due("30 1 * * *", first_occurrence, "America/New_York") == monday_fire
    assert next_due("30 1 * * *", first_occurrence, "America/New_York") != _ms(2026, 11, 1, 6, 30)


def test_tz_none_keeps_utc_semantics_for_extended_grammar() -> None:
    # 2026-07-31 is a Friday; the next weekday fire after Friday 11:30 UTC is
    # Monday 11:30 UTC. Without a timezone the new range grammar still
    # evaluates on the UTC wall clock exactly as before.
    assert next_due("30 11 * * 1-5", _ms(2026, 7, 31, 11, 30)) == _ms(2026, 8, 3, 11, 30)


def test_tz_aware_next_due_defaults_match_legacy_signature() -> None:
    reference = _ms(2026, 6, 11, 0, 1)
    for schedule in ("0 */6 * * *", "0 0 13 * 5", "60000"):
        assert next_due(schedule, reference) == next_due(schedule, reference, None)


def test_interval_schedule_ignores_timezone() -> None:
    assert next_due("60000", 5_000, "Pacific/Auckland") == 65_000
    # Even an unresolvable key: interval advancement must not depend on the
    # host's timezone database.
    assert next_due("60000", 5_000, "Not/AZone") == 65_000


def test_unknown_timezone_raises_value_error() -> None:
    with pytest.raises(ValueError, match="not a recognized IANA timezone"):
        next_due("0 12 * * *", 0, "Not/AZone")


def test_tz_cron_is_strictly_after_in_local_zone() -> None:
    exact_fire = _local_ms("Pacific/Auckland", 2026, 6, 15, 12, 0)
    next_day = _local_ms("Pacific/Auckland", 2026, 6, 16, 12, 0)
    assert next_due("0 12 * * *", exact_fire, "Pacific/Auckland") == next_day


def test_executor_advances_tz_job_on_local_calendar(tmp_path: Path) -> None:
    store = _store(tmp_path)
    friday_fire = _local_ms("Pacific/Auckland", 2026, 9, 25, 23, 30)
    monday_fire = _local_ms("Pacific/Auckland", 2026, 9, 28, 23, 30)
    store.upsert(
        _job(
            schedule="30 23 * * 1-5",
            next_run_at=friday_fire,
            timezone="Pacific/Auckland",
        )
    )
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(friday_fire)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    assert calls == ["job-001"]
    assert saved.status == JobStatus.COMPLETED
    assert saved.timezone == "Pacific/Auckland"
    assert saved.next_run_at == monday_fire


def test_executor_marks_job_failed_when_timezone_unresolvable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    # The store checks only the timezone's shape, so a key another host's tz
    # database knew persists fine; this host surfaces it per-job at
    # advancement time instead of crashing lifecycle writes.
    store.upsert(_job(schedule="0 12 * * *", next_run_at=10, timezone="Not/AZone"))
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(20)

    asyncio.run(scenario())

    saved = store.get("job-001")
    assert saved is not None
    assert calls == ["job-001"]
    assert saved.status == JobStatus.FAILED
    assert saved.failure_kind == "schedule"
    assert saved.last_error is not None


def test_tick_continues_past_a_job_whose_lifecycle_write_raises(tmp_path: Path) -> None:
    class ExplodingUpsertStore(ScheduledResearchJobStore):
        def upsert(self, job: ScheduledResearchJob, *, validate: bool = True) -> None:
            if job.id == "bad":
                raise RuntimeError("disk full")
            super().upsert(job, validate=validate)

    store = ExplodingUpsertStore(path=tmp_path / "jobs.json")
    good_store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
    good_store.save({j.id: j for j in (_job("bad", next_run_at=10), _job("good", next_run_at=20))})
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(100)

    asyncio.run(scenario())

    # "bad" exploded on its mark-RUNNING write; "good" must still have run.
    assert calls == ["good"]
    saved = good_store.get("good")
    assert saved is not None
    assert saved.status == JobStatus.COMPLETED


def test_job_with_invalid_persisted_schedule_fails_visibly_once(tmp_path: Path) -> None:
    # A 16-digit interval was accepted by an earlier grammar; it must surface
    # as a failed job rather than retry forever.
    store = _store(tmp_path)
    store.save({"legacy": _job("legacy", schedule="9" * 16, next_run_at=10)})
    calls: list[str] = []

    async def dispatch(job: ScheduledResearchJob) -> None:
        calls.append(job.id)

    async def scenario() -> None:
        executor = ScheduledResearchExecutor(store, dispatch)
        await executor.tick(100)
        await executor.tick(200)

    asyncio.run(scenario())

    saved = store.get("legacy")
    assert saved is not None
    assert calls == []  # never dispatched
    assert saved.status == JobStatus.FAILED
    assert saved.failure_kind == "schedule"
    assert "interval is too large" in (saved.last_error or "")
    assert saved.last_run_at == 100  # second tick left it alone


def test_lifecycle_writes_survive_a_schedule_the_grammar_now_rejects(tmp_path: Path) -> None:
    store = _store(tmp_path)
    job = _job("legacy", schedule="9" * 16, next_run_at=10)
    store.save({job.id: job})

    with pytest.raises(ValueError):
        store.upsert(job)  # creation-style write still validates

    job.status = JobStatus.FAILED
    store.upsert(job, validate=False)  # lifecycle write lands
    saved = store.get("legacy")
    assert saved is not None
    assert saved.status == JobStatus.FAILED
