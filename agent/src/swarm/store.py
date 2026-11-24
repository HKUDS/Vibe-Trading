"""Swarm multi-agent system — run state persistence."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pydantic import ValidationError

from pathlib import Path

from src.config.accessor import get_env_config

from src.swarm.models import RunStatus, SwarmEvent, SwarmRun
from src.tools.redaction import redact_internal_paths


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _last_event_timestamp(events_file: Path) -> datetime | None:
    """Return the timestamp of the last line in ``events.jsonl``."""
    if not events_file.exists():
        return None
    try:
        text = events_file.read_text(encoding="utf-8")
    except OSError:
        return None
    # JSONL records end at LF; U+2028/U+2029 inside event data are not record breaks.
    for line in reversed(text.split("\n")):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except ValueError:
            continue
        return _parse_iso(payload.get("timestamp"))
    return None


def swarm_runs_root() -> Path:
    """Single source of truth for where swarm runs are persisted."""
    from src.config.paths import get_swarm_runs_dir

    return get_swarm_runs_dir()


_TRANSIENT_WINERRORS = (5, 32)  # ERROR_ACCESS_DENIED, ERROR_SHARING_VIOLATION
_REPLACE_ATTEMPTS = 6
_REPLACE_BACKOFF = (0.025, 0.05, 0.1, 0.2, 0.4)  # seconds; len == attempts - 1


def _is_transient_windows_error(exc: OSError) -> bool:
    """True for the Windows access/sharing race on os.replace."""
    return getattr(exc, "winerror", None) in _TRANSIENT_WINERRORS


def _replace_with_retry(tmp: Path, target: Path) -> None:
    """``os.replace`` retried on the Windows concurrent-access race."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, target)
            return
        except OSError as exc:
            if not _is_transient_windows_error(exc):
                raise
            if attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF[attempt])


class SwarmStore:
    """File-based persistence store for SwarmRun."""

    def __init__(self, base_dir: Path) -> None:
        """Initialize SwarmStore."""
        self.base_dir = base_dir
        self._write_lock = threading.Lock()

    def run_dir(self, run_id: str) -> Path:
        """Return the directory path for a given run."""
        candidate = Path(run_id)
        if (
            not run_id.strip()
            or candidate.is_absolute()
            or len(candidate.parts) != 1
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or "/" in run_id
            or "\\" in run_id
        ):
            raise ValueError(f"run_id {run_id!r} must be a bare run directory name")
        return self.base_dir / candidate.name

    def create_run(self, run: SwarmRun) -> Path:
        """Create the directory structure for a new run and write initial state."""
        rd = self.run_dir(run.id)
        rd.mkdir(parents=True, exist_ok=False)
        (rd / "tasks").mkdir()
        (rd / "inboxes").mkdir()
        (rd / "artifacts").mkdir()
        self._atomic_write(rd / "run.json", run.model_dump_json(indent=2))
        return rd

    def load_run(self, run_id: str) -> SwarmRun | None:
        """Load the state for a given run."""
        run_file = self.run_dir(run_id) / "run.json"
        if not run_file.exists():
            return None
        # The file may be read mid-replace by a concurrent writer; retry a
        # transient read/parse failure before giving up (same race as
        # _replace_with_retry, reader side).
        last: Exception | None = None
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                return SwarmRun.model_validate_json(run_file.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                last = exc
                if attempt < len(_REPLACE_BACKOFF):
                    time.sleep(_REPLACE_BACKOFF[attempt])
        assert last is not None  # loop body sets `last` or returns
        if isinstance(last, ValueError):
            raise ValueError("Invalid swarm run record") from None
        raise type(last)(redact_internal_paths(str(last))) from None

    def request_cancel(self, run_id: str) -> bool:
        """Queue cancellation beside the run record for its owning process."""
        run_dir = self.run_dir(run_id)
        if run_dir.is_symlink():
            return False
        run = self.load_run(run_id)
        if run is None or run.status not in {RunStatus.pending, RunStatus.running}:
            return False
        request = run_dir / "cancel.request"
        try:
            with request.open("x"):
                pass
        except FileExistsError:
            return not request.is_symlink() and request.is_file()
        except FileNotFoundError:
            return False
        return True

    def update_run(self, run: SwarmRun) -> None:
        """Atomically update run state."""
        rd = self.run_dir(run.id)
        if not rd.exists():
            raise FileNotFoundError(f"Run directory not found: {rd.name}")
        self._atomic_write(rd / "run.json", run.model_dump_json(indent=2))

    def list_runs(self, limit: int = 50) -> list[SwarmRun]:
        """List all runs sorted by created_at descending."""
        if not self.base_dir.exists():
            return []

        runs: list[SwarmRun] = []
        for entry in self.base_dir.iterdir():
            if not entry.is_dir():
                continue
            run_file = entry / "run.json"
            if run_file.exists():
                try:
                    run = SwarmRun.model_validate_json(run_file.read_text(encoding="utf-8"))
                    runs.append(run)
                except (json.JSONDecodeError, ValueError):
                    continue

        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    def append_event(self, run_id: str, event: SwarmEvent) -> None:
        """Append an event to events.jsonl."""
        self.append_event_if(run_id, event)

    def append_event_if(
        self,
        run_id: str,
        event: SwarmEvent,
        accept: Callable[[], bool] | None = None,
    ) -> bool:
        """Check admission under the journal lock so an expired writer cannot trail the terminal event."""
        rd = self.run_dir(run_id)
        if not rd.exists():
            raise FileNotFoundError(f"Run directory not found: {rd.name}")
        events_file = rd / "events.jsonl"
        with self._write_lock:
            if accept is not None and not accept():
                return False
            with events_file.open("a", encoding="utf-8") as f:
                f.write(event.model_dump_json() + "\n")
        return True

    def read_events(self, run_id: str, after_index: int = 0) -> list[SwarmEvent]:
        """Read the event log with optional offset for SSE incremental streaming."""
        events_file = self.run_dir(run_id) / "events.jsonl"
        if not events_file.exists():
            return []

        events: list[SwarmEvent] = []
        text = events_file.read_bytes()
        lines = text.splitlines()
        # ``append_event`` is not atomic across processes/instances: a reader
        # (the SSE poll loop, ``_persist_recovery``) can observe a final line
        # that is still being written, or one cut short by a crashed host. That
        # unterminated tail is not an event yet, so skip it instead of raising
        # and killing the stream; the next poll sees it whole.
        tail_unterminated = bool(text) and not text.endswith(b"\n")
        for position, line in enumerate(lines[after_index:], start=after_index):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                events.append(SwarmEvent.model_validate_json(stripped))
            except ValidationError as exc:
                if (
                    tail_unterminated
                    and position == len(lines) - 1
                    and all(error["type"] == "json_invalid" for error in exc.errors())
                ):
                    break
                raise
        return events

    def hydrate_run(self, run: SwarmRun) -> SwarmRun:
        """Return a copy of ``run`` with live ``tasks/*.json`` merged in."""
        from src.swarm.task_store import TaskStore

        tasks_dir = self.run_dir(run.id) / "tasks"
        if not tasks_dir.exists():
            return run
        live = TaskStore(self.run_dir(run.id)).load_all()
        if not live:
            return run
        by_id = {task.id: task for task in live}
        merged = [by_id.get(task.id, task) for task in run.tasks]
        # Surface any task that only exists in the live store (defensive — DAG
        # validation runs at start_run so it shouldn't happen, but a future
        # caller that mutates the task set will not silently drop tasks).
        seen = {task.id for task in merged}
        merged.extend(task for tid, task in by_id.items() if tid not in seen)
        from src.swarm.delivery import refresh_report
        from src.swarm.models import RunStatus
        from src.swarm.task_store import topological_layers

        hydrated = run.model_copy(update={"tasks": merged})
        layers = topological_layers(merged)
        if not hydrated.final_report or hydrated.status not in (RunStatus.completed, RunStatus.failed, RunStatus.cancelled):
            refresh_report(hydrated, layers[-1] if layers else [])
        else:
            hydrated.report_is_partial = hydrated.status != RunStatus.completed
        return hydrated

    def compute_stale_threshold(self, run: SwarmRun) -> float:
        """Per-run silence budget before a ``running`` run looks abandoned."""
        interval = get_env_config().swarm.swarm_heartbeat_interval_s
        heartbeat_floor = max(60.0, interval * 10.0)

        agent_budgets = [
            max(1, int(agent.timeout_seconds or 300)) * (max(0, int(agent.max_retries)) + 1)
            for agent in run.agents
        ]
        retry_ceiling = (max(agent_budgets) if agent_budgets else 300) + 60

        return float(max(60.0, min(heartbeat_floor, retry_ceiling)))

    def is_run_stale(self, run: SwarmRun, *, now: datetime | None = None) -> bool:
        """Read-only check: is this ``running`` run silent past its threshold?."""
        from src.swarm.models import RunStatus

        if run.status != RunStatus.running:
            return False
        last_activity = _last_event_timestamp(self.run_dir(run.id) / "events.jsonl")
        last_activity = last_activity or _parse_iso(run.created_at)
        if last_activity is None:
            return False
        now = now or datetime.now(timezone.utc)
        return (now - last_activity).total_seconds() > self.compute_stale_threshold(run)

    def reconcile_run(self, run: SwarmRun, *, write: bool = True) -> SwarmRun:
        """Single source of truth for "what does this run actually look like"."""
        from src.swarm.models import RunStatus, TaskStatus

        hydrated = self.hydrate_run(run)
        now = datetime.now(timezone.utc)
        terminal_run = {RunStatus.completed, RunStatus.failed, RunStatus.cancelled}
        terminal_task = {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}

        if hydrated.status in terminal_run:
            return hydrated

        all_terminal = bool(hydrated.tasks) and all(t.status in terminal_task for t in hydrated.tasks)
        if all_terminal:
            recovered = self._recover_terminal(hydrated, now=now)
            if write and recovered is not hydrated:
                self._persist_recovery(recovered, kind="run_recovered_terminal", reason="all tasks terminal")
            return recovered

        if self.is_run_stale(hydrated, now=now):
            reaped = self._reap_stale(hydrated, now=now)
            if write and reaped is not hydrated:
                threshold = int(self.compute_stale_threshold(hydrated))
                self._persist_recovery(
                    reaped,
                    kind="run_reaped",
                    reason=f"no event for >{threshold}s; host process likely exited",
                    extra={"stale_seconds": threshold},
                )
            return reaped

        return hydrated

    def _recover_terminal(self, run: SwarmRun, *, now: datetime) -> SwarmRun:
        """Pure: derive a terminal SwarmRun from already-terminal tasks."""
        from src.swarm.models import RunStatus, TaskStatus

        statuses = {t.status for t in run.tasks}
        if statuses <= {TaskStatus.completed}:
            new_status = RunStatus.completed
        elif TaskStatus.failed in statuses:
            new_status = RunStatus.failed
        elif statuses <= {TaskStatus.cancelled, TaskStatus.completed}:
            new_status = RunStatus.cancelled
        else:
            new_status = RunStatus.failed

        from src.swarm.delivery import refresh_report
        from src.swarm.task_store import topological_layers

        recovered = run.model_copy(update={
            "status": new_status,
            "completed_at": run.completed_at or now.isoformat(),
        })
        layers = topological_layers(recovered.tasks)
        refresh_report(recovered, layers[-1] if layers else [])
        return recovered

    def _reap_stale(self, run: SwarmRun, *, now: datetime) -> SwarmRun:
        """Pure: mark non-terminal tasks failed; derive run status from tasks."""
        from src.swarm.models import TaskStatus

        terminal_task = {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}
        last_event_at = _last_event_timestamp(self.run_dir(run.id) / "events.jsonl")
        threshold = int(self.compute_stale_threshold(run))
        error_msg = (
            f"Run reaped: no event for >{threshold}s "
            f"(last event at {last_event_at.isoformat() if last_event_at else 'never'}); "
            "host process likely exited before completion."
        )

        updated_tasks = []
        for task in run.tasks:
            if task.status in terminal_task:
                updated_tasks.append(task)
            else:
                updated_tasks.append(
                    task.model_copy(
                        update={
                            "status": TaskStatus.failed,
                            "error": error_msg,
                            "completed_at": now.isoformat(),
                        }
                    )
                )

        # Same derivation as terminal recovery — if every task happened to be
        # completed before the host died, the run is completed, not failed.
        post = run.model_copy(update={"tasks": updated_tasks})
        return self._recover_terminal(post, now=now)

    def _persist_recovery(
        self,
        run: SwarmRun,
        *,
        kind: str,
        reason: str,
        extra: dict | None = None,
    ) -> None:
        """Write a reconciled SwarmRun back to disk and append a recovery event."""
        from src.swarm.task_store import TaskStore

        try:
            task_store = TaskStore(self.run_dir(run.id))
            for task in run.tasks:
                task_store.save_task(task)
            self.update_run(run)
        except Exception:  # pragma: no cover — best-effort sweep
            logger = __import__("logging").getLogger(__name__)
            logger.warning("Failed to persist reconciliation for run %s", run.id, exc_info=True)
            return

        existing = self.read_events(run.id)
        if any(e.type == kind for e in existing):
            return
        try:
            data = {"reason": reason}
            if extra:
                data.update(extra)
            self.append_event(
                run.id,
                SwarmEvent(
                    type=kind,
                    data=data,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ),
            )
        except Exception:  # pragma: no cover
            pass

    def reap_stale_running_runs(self) -> list[str]:
        """Sweep all run directories and reconcile each one."""
        from src.swarm.models import RunStatus

        if not self.base_dir.exists():
            return []

        reaped: list[str] = []
        for entry in self.base_dir.iterdir():
            if not entry.is_dir():
                continue
            run = self.load_run(entry.name)
            if run is None or run.status != RunStatus.running:
                continue
            reconciled = self.reconcile_run(run, write=True)
            if reconciled.status != RunStatus.running:
                reaped.append(run.id)
        return reaped

    def _atomic_write(self, path: Path, content: str) -> None:
        """Atomically write a file: write to .tmp then rename."""
        # self._write_lock only serializes callers on this SwarmStore
        # instance; mcp_server._get_swarm_store() builds a fresh instance
        # per tool call, so two concurrent pollers of the same run each get
        # their own lock. A shared ".tmp" name let one writer's rename
        # consume the other's still-unwritten temp file, silently losing an
        # update or raising FileNotFoundError. A per-write unique name keeps
        # each writer's temp file private regardless of how many SwarmStore
        # instances are racing.
        tmp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with self._write_lock:
            tmp_path.write_text(content, encoding="utf-8")
            _replace_with_retry(tmp_path, path)
