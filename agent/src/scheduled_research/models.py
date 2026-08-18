"""Data model for scheduled research jobs.

A ``ScheduledResearchJob`` records everything needed to describe a deferred
research or backtest run: the prompt/query, when to run it, and an opaque
``config`` dict for future backtest parameters. Execution wiring is deferred
to a follow-up PR once the product shape is confirmed.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Set
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schedule validation
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
# Status enum
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    """Lifecycle status of a scheduled research job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryStatus(str, Enum):
    """Outbox state for one job firing's briefing.

    The dispatch path returns once the agent attempt is *accepted*, not when it
    finishes, so "the run completed" and "the briefing was delivered" are two
    different facts and each needs its own record. PENDING means a run was
    dispatched and its result has not been delivered yet; it is the only state
    a sweep needs to look at.
    """

    NONE = "none"
    PENDING = "pending"
    #: Claimed by a sweep that is inside the send call. The claim is a lease,
    #: not a lock: a process that dies mid-send would otherwise strand the row
    #: forever, so a stale SENDING row becomes eligible again once its lease
    #: expires. Without the claim, a concurrent sweep reads PENDING while the
    #: first send is still in flight and delivers the same briefing twice.
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


@dataclass
class DeliveryRecord:
    """What happened to the briefing produced by one firing.

    Attributes:
        status: Outbox state for this firing.
        session_id: The session whose terminal result is to be delivered.
        key: Idempotency key. A send is refused when a record with the same
            key is already ``SENT``, so a restarted poller, a retried sweep and
            an event arriving twice cannot produce a second message.
        error: Redaction-safe diagnostic from the last failed delivery.
        attempts: Failed send attempts for this firing. A channel outage is
            transient, so a failed send stays PENDING and is retried; only the
            attempt threshold, or a run that produced no briefing at all,
            makes the row terminal.
        updated_at: Epoch-millisecond timestamp of the last state change.
    """

    status: DeliveryStatus = DeliveryStatus.NONE
    session_id: Optional[str] = None
    key: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    updated_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain JSON-serializable dict."""
        return {
            "status": self.status.value,
            "session_id": self.session_id,
            "key": self.key,
            "error": self.error,
            "attempts": self.attempts,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DeliveryRecord":
        """Reconstruct from a raw dict, treating absence as "never delivered".

        Args:
            data: A raw dict as produced by :meth:`to_dict`, or ``None`` for a
                record written before delivery existed.

        Returns:
            The reconstructed :class:`DeliveryRecord`.

        Raises:
            TypeError: If a present field has the wrong type.
            ValueError: If ``status`` is not a recognized value.
        """
        if not data:
            return cls()
        if not isinstance(data, dict):
            raise TypeError("'delivery' must be an object or null")
        raw_status = data.get("status", DeliveryStatus.NONE.value)
        try:
            status = DeliveryStatus(raw_status)
        except ValueError as exc:
            raise ValueError(f"unknown delivery status {raw_status!r}") from exc
        for name in ("session_id", "key", "error"):
            value = data.get(name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"'delivery.{name}' must be a string or null")
        updated_at = data.get("updated_at")
        if updated_at is not None and not isinstance(updated_at, int):
            raise TypeError("'delivery.updated_at' must be an integer (epoch ms) or null")
        attempts = data.get("attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            raise TypeError("'delivery.attempts' must be a non-negative integer")
        return cls(
            status=status,
            session_id=data.get("session_id"),
            key=data.get("key"),
            error=data.get("error"),
            attempts=attempts,
            updated_at=updated_at,
        )


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ScheduledResearchJob:
    """Mutable persisted state for a scheduled research / backtest job.

    Attributes:
        id: Unique job identifier (caller-supplied UUID or slug).
        prompt: Research prompt or backtest description.
        schedule: Interval-ms string or 5-field cron expression.
        next_run_at: Epoch-millisecond timestamp for the next intended
            execution. Defaults to the current time when the job is created.
        status: Current lifecycle status.
        created_at: Epoch-millisecond timestamp of job creation.
        last_run_at: Epoch-millisecond timestamp of the most recent executor
            attempt, or ``None`` when the job has not fired yet.
        consecutive_failures: Number of consecutive dispatch failures. A
            successful dispatch resets it to zero.
        last_error: Redaction-safe diagnostic from the latest failed attempt.
        failure_kind: ``"dispatch"`` for provider/session failures or
            ``"schedule"`` when the schedule cannot be advanced.
        config: Opaque dict for future backtest parameters.
        timezone: IANA timezone key the cron schedule is evaluated in, or
            ``None`` for UTC (the semantics every job had before this field
            existed). Interval schedules ignore it.
        delivery_channel: Channel id a finished briefing is pushed to, or
            ``None`` to keep the job's results in the app only. Delivery is
            opt-in per job: absent this, nothing is ever sent anywhere.
        delivery_target: Address within that channel (chat / group / user id).
        delivery: Outbox state for the most recent firing. Separate from
            ``status`` because dispatch returns at enqueue: a job can be
            COMPLETED (accepted) while its briefing is still PENDING delivery.
    """

    id: str
    prompt: str
    schedule: str
    next_run_at: int = field(default_factory=lambda: int(time.time() * 1000))
    status: JobStatus = JobStatus.PENDING
    created_at: int = field(default_factory=lambda: int(time.time() * 1000))
    last_run_at: Optional[int] = None
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    failure_kind: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    timezone: Optional[str] = None
    delivery_channel: Optional[str] = None
    delivery_target: Optional[str] = None
    delivery: DeliveryRecord = field(default_factory=DeliveryRecord)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain JSON-serializable dict.

        Returns:
            A dict containing all job fields, with ``status`` as its string
            value.
        """
        return {
            "id": self.id,
            "prompt": self.prompt,
            "schedule": self.schedule,
            "next_run_at": self.next_run_at,
            "status": self.status.value,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
            "consecutive_failures": self.consecutive_failures,
            "last_error": self.last_error,
            "failure_kind": self.failure_kind,
            "config": self.config,
            "timezone": self.timezone,
            "delivery_channel": self.delivery_channel,
            "delivery_target": self.delivery_target,
            "delivery": self.delivery.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledResearchJob":
        """Reconstruct a job from a plain dict.

        Args:
            data: A raw dict as produced by :meth:`to_dict`.

        Returns:
            The reconstructed ``ScheduledResearchJob``.

        Raises:
            KeyError: If a required field is missing.
            TypeError: If a field has the wrong type.
            ValueError: If ``status`` is not a recognized ``JobStatus`` value.
        """
        job_id = data["id"]
        prompt = data["prompt"]
        schedule = data["schedule"]
        if not isinstance(job_id, str) or not isinstance(prompt, str) or not isinstance(schedule, str):
            raise TypeError("'id', 'prompt', and 'schedule' must be strings")
        next_run_at = data["next_run_at"]
        created_at = data["created_at"]
        if not isinstance(next_run_at, int) or not isinstance(created_at, int):
            raise TypeError("'next_run_at' and 'created_at' must be integers (epoch ms)")
        last_run_at = data.get("last_run_at")
        if last_run_at is not None and not isinstance(last_run_at, int):
            raise TypeError("'last_run_at' must be an integer (epoch ms) or null")
        consecutive_failures = data.get("consecutive_failures", 0)
        if (
            isinstance(consecutive_failures, bool)
            or not isinstance(consecutive_failures, int)
            or consecutive_failures < 0
        ):
            raise TypeError("'consecutive_failures' must be a non-negative integer")
        last_error = data.get("last_error")
        failure_kind = data.get("failure_kind")
        if last_error is not None and not isinstance(last_error, str):
            raise TypeError("'last_error' must be a string or null")
        if failure_kind is not None and failure_kind not in {"dispatch", "schedule"}:
            raise ValueError("'failure_kind' must be 'dispatch', 'schedule', or null")
        # Never raises: the store quarantines the whole file when a single
        # record fails to load, so an unusable timezone value degrades that
        # one job to UTC — the semantics it had before the field existed —
        # instead of taking every other job down with it. Absent, blank, and
        # non-string values all normalize to None.
        raw_tz = data.get("timezone")
        tz = raw_tz if isinstance(raw_tz, str) and raw_tz.strip() else None
        if raw_tz is not None and tz is None:
            logger.warning(
                "scheduled research job %s has an unusable timezone %r; "
                "evaluating its schedule in UTC",
                job_id,
                raw_tz,
            )
        status = JobStatus(data["status"])
        raw_config = data.get("config")
        config: Dict[str, Any] = raw_config if isinstance(raw_config, dict) else {}
        delivery_channel = data.get("delivery_channel")
        delivery_target = data.get("delivery_target")
        for name, value in (
            ("delivery_channel", delivery_channel),
            ("delivery_target", delivery_target),
        ):
            if value is not None and not isinstance(value, str):
                raise TypeError(f"'{name}' must be a string or null")
        return cls(
            id=job_id,
            prompt=prompt,
            schedule=schedule,
            next_run_at=next_run_at,
            status=status,
            created_at=created_at,
            last_run_at=last_run_at,
            consecutive_failures=consecutive_failures,
            last_error=last_error,
            failure_kind=failure_kind,
            config=config,
            timezone=tz,
            delivery_channel=delivery_channel,
            delivery_target=delivery_target,
            delivery=DeliveryRecord.from_dict(data.get("delivery")),
        )
