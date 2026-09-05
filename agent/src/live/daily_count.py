"""Per-broker daily order counter (UTC calendar day, atomic write).

Shared by every live order path (the MCP ``LiveOrderGuardTool`` keeps its own
in-class copy for now; the direct-SDK gate uses these helpers). The counter is
advisory defense-in-depth — the broker enforces the real ceiling — so any
read failure reads as ``0`` (fail-open on the count only, never on the order).
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import date as calendar_date
from datetime import datetime, timezone
from typing import BinaryIO, Iterator

try:  # POSIX advisory lock (Linux/macOS).
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows advisory byte-range lock.
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

from src.live.paths import broker_dir

_COUNTER_FILENAME = "trade_counter.json"
_LOCK_FILENAME = ".order_submit.lock"


class DailyOrderLockUnavailable(RuntimeError):
    """Raised when another process holds the broker's order permit lock."""


class DailyCountError(RuntimeError):
    """Raised when action-ID accounting cannot be trusted or persisted."""


def _counter_path(broker: str):
    return broker_dir(broker) / _COUNTER_FILENAME


def _utc_today() -> str:
    """Return today's UTC calendar date as ``YYYY-MM-DD``."""
    return datetime.now(timezone.utc).date().isoformat()


def _try_lock(handle: BinaryIO) -> None:
    """Acquire a non-blocking cross-process advisory lock."""
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if msvcrt is not None:  # pragma: no cover - exercised on Windows CI
        # Lock byte 0 beyond EOF without writing a sentinel byte (see ledger.py).
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    raise OSError("no supported advisory lock backend")


def _unlock(handle: BinaryIO) -> None:
    """Release the platform advisory lock."""
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    elif msvcrt is not None:  # pragma: no cover - exercised on Windows CI
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def daily_order_lock(broker: str) -> Iterator[None]:
    """Hold one non-blocking order-admission lock for ``broker``.

    The caller must keep this lock through the final daily-count check, broker
    submission, and durable count increment. Lock contention fails closed.

    Raises:
        DailyOrderLockUnavailable: If the lock cannot be acquired immediately.
    """
    path = broker_dir(broker) / _LOCK_FILENAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = path.open("a+b")
    except OSError as exc:
        raise DailyOrderLockUnavailable(
            f"the {broker} order-submission lock is unavailable"
        ) from exc
    try:
        _try_lock(handle)
    except OSError as exc:
        handle.close()
        raise DailyOrderLockUnavailable(
            f"another {broker} order submission is already in progress"
        ) from exc
    try:
        yield
    finally:
        try:
            _unlock(handle)
        finally:
            handle.close()


def read_daily_count(broker: str) -> int:
    """Return today's order count for ``broker`` (UTC rollover; 0 on any miss)."""
    path = _counter_path(broker)
    if not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(raw, dict) or raw.get("date") != _utc_today():
        return 0
    try:
        return int(raw.get("count", 0))
    except (TypeError, ValueError):
        return 0


def increment_daily_count(broker: str, action_id: str | None = None) -> int:
    """Persist ``broker``'s incremented count for today (atomic). Returns new count."""
    today = _utc_today()
    if action_id is not None and not (1 <= len(action_id) <= 128):
        raise DailyCountError("action_id must contain 1-128 characters")
    try:
        counter_date, action_ids = _read_action_ids(broker)
    except DailyCountError:
        if action_id is not None:
            raise
        counter_date = None
        action_ids = []
    if action_id is not None and counter_date is not None and counter_date > today:
        raise DailyCountError("daily order count date is in the future")
    count = read_daily_count(broker)
    if action_id is not None and action_id in action_ids:
        return count
    if counter_date != today:
        action_ids = []
    count += 1
    if action_id is not None:
        action_ids.append(action_id)
    path = _counter_path(broker)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    payload = json.dumps({"date": today, "count": count, "action_ids": action_ids}, ensure_ascii=False)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tmp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    except Exception as exc:
        try:
            tmp.unlink()
        except OSError as cleanup_exc:
            exc.add_note(f"temporary count cleanup also failed: {cleanup_exc}")
        raise DailyCountError("daily order count could not be persisted") from exc
    return count


def _read_action_ids(broker: str) -> tuple[str | None, list[str]]:
    path = _counter_path(broker)
    if not path.is_file():
        return None, []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DailyCountError("daily order count cannot be read") from exc
    if not isinstance(raw, dict):
        raise DailyCountError("daily order count has an invalid schema")
    date, count, values = raw.get("date"), raw.get("count"), raw.get("action_ids", [])
    try:
        valid_date = (
            isinstance(date, str)
            and calendar_date.fromisoformat(date).isoformat() == date
        )
    except ValueError:
        valid_date = False
    if (
        not valid_date
        or isinstance(count, bool) or not isinstance(count, int) or count < 0
        or not isinstance(values, list)
        or any(
            not isinstance(value, str) or not (1 <= len(value) <= 128)
            for value in values
        )
        or len(set(values)) != len(values)
        or len(values) > count
    ):
        raise DailyCountError("daily order count has an invalid schema")
    return date, values
