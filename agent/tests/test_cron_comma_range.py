"""Regression: cron parser must support comma-separated lists and hyphen ranges.

The original _parse_cron_field only handled ``*``, ``*/N``, and single
integers. Standard cron expressions like ``0,15,30,45 * * * *`` (every
quarter hour) or ``0 9-17 * * 1-5`` (hourly during market hours on
weekdays) were rejected by validate_schedule and would raise ValueError.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.scheduled_research.executor import _parse_cron_field, next_due
from src.scheduled_research.models import validate_schedule


def _ms(year, month, day, hour, minute) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


# --------------------------------------------------------------------------- #
# validate_schedule accepts comma lists and ranges
# --------------------------------------------------------------------------- #


def test_validate_comma_list_minutes() -> None:
    validate_schedule("0,15,30,45 * * * *")  # should not raise


def test_validate_range_hours() -> None:
    validate_schedule("0 9-17 * * 1-5")  # should not raise


def test_validate_mixed_comma_and_range() -> None:
    validate_schedule("0,30 8-10,14-16 * * *")  # should not raise


def test_validate_inverted_range_rejected() -> None:
    with pytest.raises(ValueError, match="inverted range"):
        validate_schedule("0 17-9 * * *")


def test_validate_comma_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="out of range"):
        validate_schedule("0,99 * * * *")


def test_validate_range_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match="out of range"):
        validate_schedule("0 0-25 * * *")


# --------------------------------------------------------------------------- #
# _parse_cron_field returns correct sets
# --------------------------------------------------------------------------- #


def test_parse_comma_list() -> None:
    assert _parse_cron_field("0,15,30,45", 0, 59) == {0, 15, 30, 45}


def test_parse_range() -> None:
    assert _parse_cron_field("9-17", 0, 23) == set(range(9, 18))


def test_parse_mixed_comma_range() -> None:
    assert _parse_cron_field("0,30-32", 0, 59) == {0, 30, 31, 32}


def test_parse_single_number_still_works() -> None:
    assert _parse_cron_field("30", 0, 59) == {30}


def test_parse_star_still_works() -> None:
    assert _parse_cron_field("*", 0, 59) is None


def test_parse_star_slash_still_works() -> None:
    assert _parse_cron_field("*/15", 0, 59) == {0, 15, 30, 45}


# --------------------------------------------------------------------------- #
# next_due computes correct fire times for comma/range schedules
# --------------------------------------------------------------------------- #


def test_next_due_comma_list_minutes() -> None:
    """0,15,30,45 * * * * fires at :00, :15, :30, :45 every hour."""
    after = _ms(2026, 6, 20, 10, 10)  # 10:10
    assert next_due("0,15,30,45 * * * *", after) == _ms(2026, 6, 20, 10, 15)


def test_next_due_range_hours() -> None:
    """0 9-17 * * 1-5 fires at :00 of every hour from 9 to 17 on weekdays."""
    # 2026-06-22 is a Monday
    after = _ms(2026, 6, 22, 8, 30)  # 08:30 Monday
    assert next_due("0 9-17 * * 1-5", after) == _ms(2026, 6, 22, 9, 0)


def test_next_due_range_hours_skips_outside_range() -> None:
    """After 17:00 the next fire is the next day at 9:00 (if a weekday)."""
    # 2026-06-22 is a Monday; after 17:00 Monday → 09:00 Tuesday
    after = _ms(2026, 6, 22, 17, 30)
    assert next_due("0 9-17 * * 1-5", after) == _ms(2026, 6, 23, 9, 0)


def test_next_due_range_weekdays_skips_weekend() -> None:
    """0 9-17 * * 1-5 does not fire on Saturday or Sunday."""
    # 2026-06-26 is a Friday; after 17:00 Friday → 09:00 Monday
    after = _ms(2026, 6, 26, 17, 30)
    assert next_due("0 9-17 * * 1-5", after) == _ms(2026, 6, 29, 9, 0)


def test_validate_rejects_star_slash_in_comma_list() -> None:
    """*/5,10 is accepted by validation but crashes the parser — must be rejected."""
    with pytest.raises(ValueError, match="not valid"):
        validate_schedule("*/5,10 * * * *")


def test_validate_rejects_star_in_comma_list() -> None:
    """*,5 is not a valid cron field — star must be whole-field only."""
    with pytest.raises(ValueError, match="not valid"):
        validate_schedule("*,5 * * * *")


def test_validate_rejects_star_slash_after_comma() -> None:
    """10,*/5 is also invalid — step atoms must be whole-field only."""
    with pytest.raises(ValueError, match="not valid"):
        validate_schedule("10,*/5 * * * *")
