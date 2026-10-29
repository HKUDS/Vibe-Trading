"""Durable records for background tasks, and conservative restart recovery.

A background task currently lives only in memory, so a process restart loses
the fact that a command ever ran and the user is left guessing. This stores one
small record per task under the canonical runtime root and, on a new process,
reconciles what it finds.

Recovery is deliberately one-way and never executes anything. A record left in
``running`` or ``cancelling`` belongs to a process that is gone; it becomes
``interrupted`` or ``outcome_unknown`` with a recovery reason. It is never
re-run, and a stored PID is descriptive only: it is not used to signal a
process, because that pid may have been reused by an unrelated program.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Optional

from src.tools.redaction import redact_text

SCHEMA_VERSION = 1
#: Preview length kept per field. Enough to identify a command or outcome
#: without becoming a second copy of the run's full output.
MAX_PREVIEW_CHARS = 2_000
_TASK_ID_RE = re.compile(r"^[0-9a-f]{8,64}$")

#: Statuses a task can hold while its owning process is still alive.
LIVE_STATUSES = frozenset({"running", "cancelling"})
#: Statuses whose result is worth reading back after a restart.
TERMINAL_STATUSES = frozenset({"completed", "error", "timeout", "cancelled"})


class BackgroundStoreError(RuntimeError):
    """A record could not be stored or read back safely."""


@dataclass
class TaskRecord:
    """What survives a restart for one background task."""

    schema_version: int
    task_id: str
    owner_id: str
    status: str
    command_preview: str
    attempt_id: Optional[str] = None
    exit_code: Optional[int] = None
    result_preview: str = ""
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    duration_seconds: Optional[float] = None
    recovery_reason: Optional[str] = None
    #: Descriptive only. Never used to signal a process after a restart.
    pid: Optional[int] = None
    updated_at: float = field(default_factory=time.time)

    @property
    def is_live(self) -> bool:
        return self.status in LIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def _preview(value: object) -> str:
    """Bound and redact one untrusted field before it reaches disk."""
    return redact_text(str(value or ""))[:MAX_PREVIEW_CHARS]


def _owner_token(owner_id: str) -> str:
    """Stable layout-only token for an owner id.

    A hash rather than the raw id: the owner carries a session identifier that
    is not a secret but is not a filename either, and the raw form would put
    user-supplied separators into the path.
    """
    return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:16]


class BackgroundTaskStore:
    """One JSON record per task, written atomically under a fixed root."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._directory = self.root / "background-tasks"

    def _path_for(self, record: TaskRecord) -> Path:
        if not _TASK_ID_RE.match(record.task_id):
            raise BackgroundStoreError(f"unsafe background task id: {record.task_id!r}")
        return self._directory / f"{_owner_token(record.owner_id)}-{record.task_id}.json"

    def save(self, record: TaskRecord) -> Path:
        """Persist one record, replacing any previous copy of it."""
        path = self._path_for(record)
        self._write_json_atomically(path, asdict(record))
        return path

    def load_all(self) -> tuple[list[TaskRecord], list[str]]:
        """Return readable records and the paths that could not be read.

        A corrupt or unknown-version file is reported, never overwritten and
        never guessed at: silently dropping it would hide the task, and
        silently reinterpreting it would invent an outcome.
        """
        records: list[TaskRecord] = []
        unreadable: list[str] = []
        if not self._directory.exists():
            return records, unreadable
        for path in sorted(self._directory.glob("*.json")):
            record = self._load_one(path)
            if record is None:
                unreadable.append(str(path))
            else:
                records.append(record)
        return records, unreadable

    def _load_one(self, path: Path) -> Optional[TaskRecord]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("schema_version") != SCHEMA_VERSION:
            return None
        try:
            return TaskRecord(**payload)
        except TypeError:
            return None

    @staticmethod
    def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        content = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            try:
                with os.fdopen(fd, "wb") as handle:
                    fd = -1
                    handle.write(content)
                    handle.flush()
                    if hasattr(os, "fchmod"):
                        os.fchmod(handle.fileno(), 0o600)
                    os.fsync(handle.fileno())
            finally:
                if fd >= 0:
                    os.close(fd)
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def record_from_task(task_id: str, task: dict, *, started_at: Optional[float] = None) -> TaskRecord:
    """Project an in-memory task entry onto its durable shape."""
    started = task.get("started_at")
    return TaskRecord(
        schema_version=SCHEMA_VERSION,
        task_id=task_id,
        owner_id=str(task.get("owner_id") or ""),
        attempt_id=task.get("attempt_id"),
        status=str(task.get("status") or "error"),
        command_preview=_preview(task.get("command")),
        result_preview=_preview(task.get("result")),
        exit_code=task.get("exit_code") if isinstance(task.get("exit_code"), int) else None,
        started_at=float(started) if isinstance(started, (int, float)) else started_at,
        ended_at=task.get("ended_at"),
        duration_seconds=task.get("duration_seconds"),
        pid=task.get("pid") if isinstance(task.get("pid"), int) else None,
    )


def reconcile_after_restart(
    records: Iterable[TaskRecord],
) -> tuple[list[TaskRecord], list[TaskRecord]]:
    """Turn a previous process's live records into explicit outcomes.

    Nothing is re-run and nothing is signalled. A record left ``running`` cannot
    be distinguished from one whose output was never written, so it becomes
    ``interrupted``; a record left ``cancelling`` cannot be distinguished from
    one whose reaping never finished, so it becomes ``outcome_unknown``. Both
    carry a recovery reason rather than being dropped.
    """
    recovered: list[TaskRecord] = []
    unchanged: list[TaskRecord] = []
    for record in records:
        if record.status == "running":
            recovered.append(
                replace(
                    record,
                    status="interrupted",
                    recovery_reason="service_restart",
                    ended_at=time.time(),
                )
            )
        elif record.status == "cancelling":
            recovered.append(
                replace(
                    record,
                    status="outcome_unknown",
                    recovery_reason="service_restart_before_reap_completed",
                    ended_at=time.time(),
                )
            )
        else:
            unchanged.append(record)
    return recovered, unchanged
