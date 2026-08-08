"""Tests for the scheduled research job store.

Covers: happy-path CRUD, atomic persistence, invalid schedule rejection,
idempotent upsert, and empty-store behaviour.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.scheduled_research.models import (
    JobStatus,
    ScheduledResearchJob,
    validate_schedule,
    validate_timezone,
)
from src.scheduled_research.store import CorruptStoreError, ScheduledResearchJobStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    job_id: str = "job-001",
    prompt: str = "analyse AAPL momentum",
    schedule: str = "60000",
) -> ScheduledResearchJob:
    now = int(time.time() * 1000)
    return ScheduledResearchJob(
        id=job_id,
        prompt=prompt,
        schedule=schedule,
        next_run_at=now + 60_000,
        status=JobStatus.PENDING,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# validate_schedule unit tests
# ---------------------------------------------------------------------------


class TestValidateSchedule:
    def test_accepts_interval_ms(self) -> None:
        validate_schedule("60000")

    def test_accepts_cron_string(self) -> None:
        validate_schedule("0 */6 * * *")

    def test_accepts_cron_with_plain_numbers(self) -> None:
        validate_schedule("30 8 * * 1")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("")

    def test_rejects_zero_interval(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("0")

    def test_rejects_negative_interval(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("-1000")

    def test_rejects_malformed_cron(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("* * * *")  # only 4 fields

    def test_rejects_non_numeric_cron_field(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("abc * * * *")

    def test_rejects_cron_with_invalid_step(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("*/0 * * * *")  # step of 0 is not allowed

    def test_rejects_out_of_range_minute(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("99 * * * *")  # minute > 59

    def test_rejects_out_of_range_hour(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("0 25 * * *")  # hour > 23

    def test_rejects_zero_day_of_month(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("0 0 0 * *")  # day-of-month is 1-31

    def test_rejects_out_of_range_step(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("*/99 * * * *")  # minute step > 59

    def test_accepts_boundary_values(self) -> None:
        validate_schedule("59 23 31 12 6")  # all field maxima

    def test_accepts_weekday_range(self) -> None:
        validate_schedule("30 23 * * 1-5")

    def test_rejects_oversized_interval(self) -> None:
        validate_schedule("9" * 15)  # ~31,000 years is the accepted ceiling
        with pytest.raises(ValueError, match="interval is too large"):
            validate_schedule("9" * 16)

    def test_accepts_list_and_mixed_range(self) -> None:
        validate_schedule("0 9 * * 1,3,5")
        validate_schedule("0 9 * * 1,3-5")
        validate_schedule("0 9 1-15 * *")

    def test_rejects_reversed_range(self) -> None:
        with pytest.raises(ValueError, match="reversed"):
            validate_schedule("0 9 * * 5-1")

    def test_rejects_out_of_range_list_and_range_ends(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("0 9 * * 1-8")  # dow high end > 6
        with pytest.raises(ValueError):
            validate_schedule("0 9 * * 1,9")  # dow list member > 6

    def test_rejects_range_step_and_wildcard_in_list(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("0 9 * * 1-5/2")  # range steps are not part of the grammar
        with pytest.raises(ValueError):
            validate_schedule("0 9 * * *,1")  # wildcard cannot appear in a list

    def test_rejects_empty_list_atoms(self) -> None:
        with pytest.raises(ValueError):
            validate_schedule("0 9 * * 1,,3")
        with pytest.raises(ValueError):
            validate_schedule("0 9 * * 1-")
        with pytest.raises(ValueError):
            validate_schedule("0 9 * * -5")


class TestValidateTimezone:
    def test_accepts_none(self) -> None:
        validate_timezone(None)

    def test_accepts_iana_keys(self) -> None:
        validate_timezone("UTC")
        validate_timezone("Pacific/Auckland")
        validate_timezone("Australia/Adelaide")

    def test_rejects_unknown_key(self) -> None:
        with pytest.raises(ValueError, match="not a recognized IANA timezone"):
            validate_timezone("Not/AZone")

    def test_rejects_empty_and_blank(self) -> None:
        with pytest.raises(ValueError):
            validate_timezone("")
        with pytest.raises(ValueError):
            validate_timezone("   ")


# ---------------------------------------------------------------------------
# Store CRUD tests
# ---------------------------------------------------------------------------


class TestScheduledResearchJobStore:
    def test_empty_store_returns_empty_list(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        assert store.list_jobs() == []

    def test_load_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        assert store.load() == {}

    def test_upsert_then_list(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        job = _make_job()
        store.upsert(job)
        result = store.list_jobs()
        assert len(result) == 1
        assert result[0].id == job.id
        assert result[0].status == JobStatus.PENDING

    def test_get_returns_job(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        job = _make_job()
        store.upsert(job)
        fetched = store.get(job.id)
        assert fetched is not None
        assert fetched.id == job.id
        assert fetched.prompt == job.prompt

    def test_get_missing_returns_none(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        assert store.get("nonexistent") is None

    def test_delete_removes_job(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        job = _make_job()
        store.upsert(job)
        removed = store.delete(job.id)
        assert removed is True
        assert store.get(job.id) is None

    def test_delete_missing_returns_false(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        assert store.delete("ghost") is False

    def test_idempotent_upsert_replaces_not_duplicates(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        job = _make_job()
        store.upsert(job)
        updated = ScheduledResearchJob(
            id=job.id,
            prompt="updated prompt",
            schedule=job.schedule,
            next_run_at=job.next_run_at,
            status=JobStatus.COMPLETED,
            created_at=job.created_at,
        )
        store.upsert(updated)
        jobs = store.list_jobs()
        assert len(jobs) == 1
        assert jobs[0].prompt == "updated prompt"
        assert jobs[0].status == JobStatus.COMPLETED

    def test_filter_by_status(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        pending = _make_job("p1")
        completed = ScheduledResearchJob(
            id="c1",
            prompt="done",
            schedule="60000",
            status=JobStatus.COMPLETED,
            next_run_at=int(time.time() * 1000),
            created_at=int(time.time() * 1000),
        )
        store.upsert(pending)
        store.upsert(completed)
        pending_only = store.list_jobs(status="pending")
        assert len(pending_only) == 1
        assert pending_only[0].id == "p1"

    def test_list_honours_limit(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        for i in range(5):
            store.upsert(_make_job(f"job-{i:03d}"))
        assert len(store.list_jobs(limit=3)) == 3

    def test_upsert_rejects_malformed_schedule(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        bad_job = ScheduledResearchJob(
            id="bad",
            prompt="x",
            schedule="not-a-schedule",
            next_run_at=int(time.time() * 1000),
            created_at=int(time.time() * 1000),
        )
        with pytest.raises(ValueError):
            store.upsert(bad_job)

    def test_corrupt_store_raises_and_quarantines(self, tmp_path: Path) -> None:
        store_path = tmp_path / "jobs.json"
        store_path.write_text("{{not valid json}}", encoding="utf-8")
        store = ScheduledResearchJobStore(path=store_path)
        with pytest.raises(CorruptStoreError) as exc_info:
            store.load()
        assert not store_path.exists(), "original corrupt file should be gone"
        assert exc_info.value.quarantined.exists(), "quarantined file must exist"

    def test_atomic_write_cleans_up_temp_on_success(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        store.upsert(_make_job())
        # Verify no leftover .tmp files after a successful write
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"unexpected temp files: {tmp_files}"

    def test_persisted_data_round_trips(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        job = _make_job("rt-001", schedule="0 */4 * * *")
        store.upsert(job)

        # Open a fresh store instance to simulate restart
        store2 = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        fetched = store2.get("rt-001")
        assert fetched is not None
        assert fetched.prompt == job.prompt
        assert fetched.schedule == "0 */4 * * *"

    def test_timezone_round_trips_through_store(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        job = _make_job("tz-001", schedule="30 23 * * 1-5")
        job.timezone = "Pacific/Auckland"
        store.upsert(job)

        fetched = ScheduledResearchJobStore(path=tmp_path / "jobs.json").get("tz-001")
        assert fetched is not None
        assert fetched.timezone == "Pacific/Auckland"

    def test_legacy_record_without_timezone_loads_as_none(self, tmp_path: Path) -> None:
        store_path = tmp_path / "jobs.json"
        legacy = _make_job("legacy-tz").to_dict()
        legacy.pop("timezone")
        store_path.write_text(
            json.dumps({"schema_version": 1, "jobs": [legacy]}), encoding="utf-8"
        )

        fetched = ScheduledResearchJobStore(path=store_path).get("legacy-tz")
        assert fetched is not None
        assert fetched.timezone is None

    def test_upsert_accepts_unresolvable_timezone_shape(self, tmp_path: Path) -> None:
        # Resolvability depends on the host tz database; the store checks only
        # the shape so lifecycle writes never crash on foreign keys.
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        job = _make_job("tz-shape", schedule="0 12 * * *")
        job.timezone = "Not/AZone"
        store.upsert(job)
        fetched = store.get("tz-shape")
        assert fetched is not None
        assert fetched.timezone == "Not/AZone"

    def test_upsert_rejects_blank_timezone(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        job = _make_job("tz-blank")
        job.timezone = "   "
        with pytest.raises(ValueError, match="timezone"):
            store.upsert(job)

    def test_from_dict_degrades_non_string_timezone_to_none(self) -> None:
        # Loading must never raise: the store quarantines the entire file when
        # one record fails, so an unusable value falls back to UTC semantics.
        raw = _make_job("tz-type").to_dict()
        raw["timezone"] = 13
        assert ScheduledResearchJob.from_dict(raw).timezone is None

    def test_from_dict_normalizes_blank_timezone_to_none(self) -> None:
        # A blank string must load as None so every loaded record satisfies
        # the shape check the store re-runs on executor lifecycle writes.
        raw = _make_job("tz-blank-load").to_dict()
        raw["timezone"] = "   "
        assert ScheduledResearchJob.from_dict(raw).timezone is None

    def test_retry_state_round_trips_and_legacy_jobs_get_defaults(self, tmp_path: Path) -> None:
        store_path = tmp_path / "jobs.json"
        store = ScheduledResearchJobStore(path=store_path)
        job = _make_job("retrying")
        job.consecutive_failures = 2
        job.last_error = "TimeoutError: provider timed out"
        job.failure_kind = "dispatch"
        store.upsert(job)

        fetched = ScheduledResearchJobStore(path=store_path).get("retrying")
        assert fetched is not None
        assert fetched.consecutive_failures == 2
        assert fetched.last_error == "TimeoutError: provider timed out"
        assert fetched.failure_kind == "dispatch"

        legacy = _make_job("legacy").to_dict()
        for field in ("consecutive_failures", "last_error", "failure_kind"):
            legacy.pop(field)
        store_path.write_text(
            json.dumps({"schema_version": 1, "jobs": [legacy]}),
            encoding="utf-8",
        )

        migrated = ScheduledResearchJobStore(path=store_path).get("legacy")
        assert migrated is not None
        assert migrated.consecutive_failures == 0
        assert migrated.last_error is None
        assert migrated.failure_kind is None

    def test_cron_schedule_accepted(self, tmp_path: Path) -> None:
        store = ScheduledResearchJobStore(path=tmp_path / "jobs.json")
        cron_job = _make_job("cron-1", schedule="*/30 * * * *")
        store.upsert(cron_job)
        assert store.get("cron-1") is not None


class TestLegacyTimezoneValues:
    def test_non_string_timezone_degrades_that_job_to_utc(self, tmp_path: Path) -> None:
        # Before the timezone field existed the key was ignored entirely; a
        # record carrying a non-string value must still load, and must not
        # take the rest of the store down with it.
        store_path = tmp_path / "jobs.json"
        good = _make_job("good").to_dict()
        bad = _make_job("bad").to_dict()
        bad["timezone"] = 123
        store_path.write_text(
            json.dumps({"schema_version": 1, "jobs": [good, bad]}), encoding="utf-8"
        )

        jobs = ScheduledResearchJobStore(path=store_path).load()

        assert set(jobs) == {"good", "bad"}
        assert jobs["bad"].timezone is None
        assert jobs["good"].timezone is None
        assert store_path.exists()  # not quarantined
        assert not list(tmp_path.glob("*.corrupt-*"))
