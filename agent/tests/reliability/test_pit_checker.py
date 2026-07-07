"""Tests for Phase 2 PIT timestamp checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.reliability.pit.checker import PITChecker
from src.reliability.pit.model import PITTimestampSet


def test_missing_available_at_warns_not_pit_safe() -> None:
    checker = PITChecker(dataset_kind="fundamental", as_of=datetime(2026, 7, 1, tzinfo=timezone.utc))

    result = checker.check(PITTimestampSet(published_at=datetime(2026, 6, 1, tzinfo=timezone.utc)))

    assert any(warning.code == "PIT_AVAILABLE_AT_MISSING" for warning in result.warnings)
    assert result.pit_safe is False


def test_available_at_after_as_of_records_future_data_violation() -> None:
    as_of = datetime(2026, 7, 1, tzinfo=timezone.utc)
    checker = PITChecker(dataset_kind="news", as_of=as_of)

    result = checker.check(PITTimestampSet(available_at=as_of + timedelta(days=1)))

    assert any(violation.code == "PIT_FUTURE_DATA" for violation in result.violations)
    assert any(violation.hard_failure for violation in result.violations)
    assert result.pit_safe is False


def test_ohlcv_available_at_inferred_warning() -> None:
    as_of = datetime(2026, 7, 2, tzinfo=timezone.utc)
    checker = PITChecker(dataset_kind="ohlcv", as_of=as_of)

    result = checker.check(PITTimestampSet(effective_at=datetime(2026, 7, 1, tzinfo=timezone.utc)))

    assert any(warning.code == "PIT_AVAILABLE_AT_INFERRED" for warning in result.warnings)
    assert result.pit_safe is True


def test_missing_as_of_warns() -> None:
    checker = PITChecker(dataset_kind="ohlcv")

    result = checker.check(PITTimestampSet(available_at=datetime(2026, 7, 1, tzinfo=timezone.utc)))

    assert any(warning.code == "PIT_MISSING_AS_OF" for warning in result.warnings)
