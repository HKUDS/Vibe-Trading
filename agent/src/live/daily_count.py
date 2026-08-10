"""Per-broker daily order counter (UTC calendar day, atomic write).

Shared by every live order path (the MCP ``LiveOrderGuardTool`` keeps its own
in-class copy for now; the direct-SDK gate uses these helpers). The counter is
advisory defense-in-depth — the broker enforces the real ceiling — so any
read failure reads as ``0`` (fail-open on the count only, never on the order).
"""

import fcntl
import json
from datetime import datetime, timezone

from src.live.paths import broker_dir

_COUNTER_FILENAME = "trade_counter.json"
_LOCK_FILENAME = "trade_counter.lock"


def _counter_path(broker: str):
    return broker_dir(broker) / _COUNTER_FILENAME


def _lock_path(broker: str):
    return broker_dir(broker) / _LOCK_FILENAME


def _utc_today() -> str:
    """Return today's UTC calendar date as ``YYYY-MM-DD``."""
    return datetime.now(timezone.utc).date().isoformat()


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
    """Persist ``broker``'s incremented count for today (atomic). Returns new count.

    The read-modify-write is guarded by an ``flock`` on a sibling lock file so
    two concurrent orders cannot both read the same count and lose an increment.
    The lock is held only across the counter file read + write, not across the
    broker call.
    """
    today = _utc_today()
    path = _counter_path(broker)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = _lock_path(broker)

    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            count = read_daily_count(broker) + 1
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_text(
                json.dumps({"date": today, "count": count}, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(path)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
    return count
