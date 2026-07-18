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
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
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


def increment_daily_count(broker: str) -> int:
    """Persist ``broker``'s incremented count for today (atomic). Returns new count."""
    today = _utc_today()
    count = read_daily_count(broker) + 1
    path = _counter_path(broker)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    tmp.write_text(json.dumps({"date": today, "count": count}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return count
