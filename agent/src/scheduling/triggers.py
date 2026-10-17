"""Trigger grammar and next-run math for the shared scheduling kernel.

Extracted verbatim (scheduler unification) from two prior owners so every
scheduler in the repo can share one trigger vocabulary:

* the schedule grammar — interval-ms strings and simplified 5-field cron with
  ``CRON_BOUNDS`` validation — moved from ``src/scheduled_research/models.py``;
* the next-run math — :func:`next_due`, :func:`next_cron_due`,
  :func:`local_wall_time_to_epoch_ms`, :func:`day_matches` — moved from
  ``src/scheduled_research/executor.py``.

Algorithms are line-for-line equivalent to the pre-move implementation; the
golden vectors in ``agent/tests/scheduling/golden_next_due.json`` (captured
mechanically from the old code *before* the move) pin that equivalence. Only
the spelling of the moved private names changed: the public names drop the
leading underscore (``next_cron_due`` / ``local_wall_time_to_epoch_ms`` /
``day_matches``) and underscore aliases are kept so every existing import
path keeps working.

This module also introduces the ``once`` trigger kind — a pure next-run
function absorbing the ``"once"`` / ``"interval:<ms>"`` semantics of the live
runtime scheduler (``agent/src/live/runtime/scheduler.py``, read-only
reference; nothing is imported from ``src.live`` and no live behavior is
changed). It is provided for future adoption only and is NOT wired anywhere
in this batch.

Everything here is pure and clock-injected: callers pass explicit epoch-ms
references (``after_ms``), so no function reads the wall clock.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Optional, Set
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Schedule validation (moved from src/scheduled_research/models.py)
# ---------------------------------------------------------------------------

# Accept either:
#   * a bare positive integer (interval in milliseconds), e.g. "60000"
#   * a simplified cron expression with 5 fields, e.g. "0 */6 * * *"
#     Fields: minute hour day-of-month month day-of-week
#     Each field may be: *, */n, or a comma-separated list of numbers and
#     low-high ranges (e.g. "1-5", "1,3,5", "1,3-5")
_INTERVAL_MS_RE = re.compile(r"^[1-9][0-9]*$")
_CRON_STEP_RE = re.compile(r"^\*/[1-9][0-9]*$")
_CRON_ATOM_RE = re.compile(r"^([0-9]+)(?:-([0-9]+))?$")
_CRON_PARTS = 5
# Inclusive (low, high) bounds per cron field: minute hour day-of-month month
# day-of-week. Every number in a field — a bare value, a ``*/n`` step, or
# either end of a range — is validated against these bounds so out-of-range
# values (e.g. minute ``99``) are rejected. Day-of-week uses the cron
# convention Sunday == 0; ``7`` is not accepted as a Sunday alias.
CRON_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _validate_cron_field(part: str, low: int, high: int) -> None:
    """Raise ``ValueError`` when one cron field is malformed or out of range."""
    if part == "*":
        return
    if _CRON_STEP_RE.fullmatch(part):
        value = int(part[2:])
        if not low <= value <= high:
            raise ValueError(f"cron field {part!r} is out of range; expected {low}-{high}")
        return
    for atom in part.split(","):
        match = _CRON_ATOM_RE.fullmatch(atom)
        if match is None:
            raise ValueError(
                f"cron field {part!r} is not valid; each field must be *, */n, "
                f"or a comma-separated list of numbers and low-high ranges"
            )
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) is not None else start
        if start > end:
            raise ValueError(f"cron range {atom!r} is reversed; expected low-high")
        if start < low or end > high:
            raise ValueError(f"cron field {atom!r} is out of range; expected {low}-{high}")


def parse_cron_field(part: str, low: int, high: int) -> Optional[Set[int]]:
    """Expand one validated cron field into its matching values.

    Kept beside :func:`validate_schedule` so the accepted grammar and the
    executor's evaluation of it can never drift apart.

    Args:
        part: One whitespace-delimited cron field (already validated).
        low: Inclusive lower bound of the field.
        high: Inclusive upper bound of the field.

    Returns:
        The set of matching integer values, or ``None`` for the ``*`` wildcard.
    """
    if part == "*":
        return None
    if part.startswith("*/"):
        step = int(part[2:])
        return set(range(low, high + 1, step))
    values: Set[int] = set()
    for atom in part.split(","):
        start, _, end = atom.partition("-")
        if end:
            values.update(range(int(start), int(end) + 1))
        else:
            values.add(int(start))
    return values


def is_interval_schedule(schedule: str) -> bool:
    """Return whether *schedule* is the interval-milliseconds form.

    The one place that answers "interval or cron?", so callers that treat the
    two forms differently — the executor's advancement path, the create route's
    timezone handling — cannot disagree about which is which.

    Args:
        schedule: A schedule string in either accepted form.

    Returns:
        ``True`` for a bare positive-integer interval, ``False`` otherwise
        (including malformed input, which the validators reject separately).
    """
    return bool(_INTERVAL_MS_RE.fullmatch(str(schedule).strip()))


def validate_schedule(schedule: str) -> None:
    """Raise ``ValueError`` when *schedule* is malformed.

    Args:
        schedule: Either a positive integer string (interval-ms) or a
            simplified 5-field cron expression.

    Raises:
        ValueError: When the schedule does not match either accepted form.
    """
    if not schedule or not isinstance(schedule, str):
        raise ValueError("schedule must be a non-empty string")

    if _INTERVAL_MS_RE.fullmatch(schedule.strip()):
        # 15 digits ≈ 31,000 years in milliseconds — anything longer is not a
        # usable interval and would only feed int() conversion of huge strings.
        if len(schedule.strip()) > 15:
            raise ValueError("interval is too large; expected at most 15 digits of milliseconds")
        return  # valid interval

    parts = schedule.strip().split()
    if len(parts) != _CRON_PARTS:
        raise ValueError(f"schedule must be a positive integer (ms) or a 5-field cron string; got: {schedule!r}")
    for part, (low, high) in zip(parts, CRON_BOUNDS):
        _validate_cron_field(part, low, high)


def validate_timezone_shape(tz: Optional[str]) -> None:
    """Raise ``ValueError`` when *tz* is not ``None`` or a non-empty string.

    This is the persistence-level check: it deliberately does NOT resolve the
    key, because resolvability depends on the host's timezone database. A
    store written where a key resolved must keep loading and persisting on a
    host where it does not; the executor surfaces the unresolvable key as a
    per-job schedule failure instead.
    """
    if tz is None:
        return
    if not isinstance(tz, str) or not tz.strip():
        raise ValueError("timezone must be a non-empty IANA timezone key or null")


def validate_timezone(tz: Optional[str]) -> None:
    """Raise ``ValueError`` when *tz* is not a resolvable IANA timezone key.

    ``None`` is always valid and means legacy UTC semantics. Resolution goes
    through :class:`zoneinfo.ZoneInfo`, so whatever validates here is exactly
    what the executor can evaluate later.

    Args:
        tz: An IANA timezone key such as ``"Pacific/Auckland"``, or ``None``.

    Raises:
        ValueError: When *tz* is not ``None`` and cannot be resolved.
    """
    validate_timezone_shape(tz)
    if tz is None:
        return
    try:
        ZoneInfo(tz)
    except Exception as exc:
        raise ValueError(f"timezone {tz!r} is not a recognized IANA timezone key") from exc


# ---------------------------------------------------------------------------
# Next-run math (moved from src/scheduled_research/executor.py)
# ---------------------------------------------------------------------------

# Search by day, not by minute, so an impossible date (e.g. Feb 31) fails fast
# instead of scanning years of minutes on the event loop. Four years covers any
# real recurrence, including a Feb-29 leap day; the extra headroom absorbs a
# yearly occurrence landing in a DST spring-forward gap (skipped by policy)
# several years in a row before a real instant exists again.
CRON_SEARCH_LIMIT_DAYS = 6 * 366 + 1


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
    return next_cron_due(spec, after_ms, tz)


def next_cron_due(schedule: str, after_ms: int, tz: str | None = None) -> int:
    minutes, hours, doms, months, dows = (
        parse_cron_field(part, low, high) for part, (low, high) in zip(schedule.split(), CRON_BOUNDS)
    )
    zone = timezone.utc if tz is None else ZoneInfo(tz)
    # Walk candidates on the *local* calendar of ``zone`` so field matching —
    # the weekday in particular — follows the authoring wall clock. Ascending
    # wall order maps to ascending UTC order under a fixed fold policy, so
    # "strictly after" stays a plain epoch comparison.
    day = datetime.fromtimestamp(after_ms / 1000.0, zone).date()
    for offset in range(CRON_SEARCH_LIMIT_DAYS):
        candidate_day = day + timedelta(days=offset)
        if not day_matches(candidate_day, doms, months, dows):
            continue
        for hour in sorted(hours) if hours is not None else range(24):
            for minute in sorted(minutes) if minutes is not None else range(60):
                fire_ms = local_wall_time_to_epoch_ms(candidate_day, hour, minute, zone)
                if fire_ms is not None and fire_ms > after_ms:
                    return fire_ms
    raise ValueError(f"cron schedule has no matching time within search window: {schedule!r}")


def local_wall_time_to_epoch_ms(day: date, hour: int, minute: int, zone: tzinfo) -> int | None:
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


def day_matches(dt: date, doms: set[int] | None, months: set[int] | None, dows: set[int] | None) -> bool:
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


# Legacy private spellings from ``src/scheduled_research/executor.py``, kept as
# aliases so every existing import path (and every monkeypatch-free test that
# references them) keeps working unchanged.
_CRON_SEARCH_LIMIT_DAYS = CRON_SEARCH_LIMIT_DAYS
_next_cron_due = next_cron_due
_local_wall_time_to_epoch_ms = local_wall_time_to_epoch_ms
_day_matches = day_matches


# ---------------------------------------------------------------------------
# once / interval:<ms> trigger kind (live-runtime dialect, NEW — not wired)
# ---------------------------------------------------------------------------

#: The one-shot trigger spec of the live runtime scheduler: fires exactly once
#: and is then removed. Compared case-insensitively after stripping.
ONCE_SPEC = "once"

#: Default cadence applied when a live-style trigger ``schedule`` is a
#: bare/empty/unknown spec — the watch still fires on a sane interval rather
#: than never. Single home of the semantics ``Job.interval_ms()`` in
#: ``agent/src/live/runtime/scheduler.py`` originally carried; the live
#: scheduler's kernel-backed façade delegates here (nothing is imported from
#: ``src.live`` in the other direction).
DEFAULT_TRIGGER_INTERVAL_MS = 60 * 1000


def trigger_interval_ms(schedule: str | None) -> int | None:
    """Return the recurrence interval in ms for a live-style trigger spec.

    Single home of the semantics ``Job.interval_ms()`` in
    ``agent/src/live/runtime/scheduler.py`` originally carried; that method is
    now a delegate to this function:

    * ``"once"`` → ``None``: a one-shot trigger with no recurrence;
    * ``"interval:<ms>"`` → ``<ms>`` when it parses as a positive integer,
      otherwise :data:`DEFAULT_TRIGGER_INTERVAL_MS`;
    * any other bare/empty/unknown non-empty spec →
      :data:`DEFAULT_TRIGGER_INTERVAL_MS`, so a misconfigured job still
      watches on a sane cadence rather than silently never recurring.

    Note this is the live-runtime spec dialect (``"interval:<ms>"`` /
    ``"once"``), distinct from the scheduled-research grammar handled by
    :func:`next_due` (a bare ``"<ms>"`` interval string or a 5-field cron).
    """
    spec = (schedule or "").strip().lower()
    if spec == ONCE_SPEC:
        return None
    if spec.startswith("interval:"):
        raw = spec.split(":", 1)[1].strip()
        try:
            ms = int(raw)
        except ValueError:
            return DEFAULT_TRIGGER_INTERVAL_MS
        return ms if ms > 0 else DEFAULT_TRIGGER_INTERVAL_MS
    return DEFAULT_TRIGGER_INTERVAL_MS


def next_once_due(schedule: str | None, after_ms: int) -> int | None:
    """Return the next run epoch-ms for a ``once``/``interval:<ms>`` trigger.

    ``None`` means the trigger is one-shot (``"once"``): it fires exactly once
    and has no next run — the live scheduler removes such a job after firing.
    A recurring spec advances one interval past ``after_ms`` (not past a stale
    ``next_run_at``), so a trigger that fired late — because the host was
    suspended or the loop was busy — does not immediately re-fire a backlog of
    missed slots.

    Args:
        schedule: A live-style trigger spec (see :func:`trigger_interval_ms`).
        after_ms: Reference time in epoch ms — typically the fire time.

    Returns:
        The next run in epoch ms, or ``None`` for the one-shot kind.
    """
    interval = trigger_interval_ms(schedule)
    if interval is None:
        return None
    return after_ms + interval


__all__ = [
    "CRON_BOUNDS",
    "CRON_SEARCH_LIMIT_DAYS",
    "DEFAULT_TRIGGER_INTERVAL_MS",
    "ONCE_SPEC",
    "day_matches",
    "is_interval_schedule",
    "local_wall_time_to_epoch_ms",
    "next_cron_due",
    "next_due",
    "next_once_due",
    "parse_cron_field",
    "trigger_interval_ms",
    "validate_schedule",
    "validate_timezone",
    "validate_timezone_shape",
    # legacy private aliases
    "_CRON_SEARCH_LIMIT_DAYS",
    "_day_matches",
    "_local_wall_time_to_epoch_ms",
    "_next_cron_due",
]
