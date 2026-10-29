"""Background tasks: thread execution + notification queue."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.tools import BaseTool
from src.tools._shell_safety import broad_python_kill_error

WORKDIR = Path(__file__).resolve().parents[2]
_COMMAND_TIMEOUT_SECONDS = 300.0
_TERMINATION_GRACE_SECONDS = 2.0
_MAX_OUTPUT_CHARS = 50_000


@dataclass(frozen=True)
class BackgroundScope:
    """Which conversation or worker owns a background task.

    The host that builds the tool registry supplies this. It never appears in a
    model-visible tool schema: a model must not be able to claim another
    session's task, or read its output, by naming an owner.

    Ownership is by ``owner_id`` alone. ``attempt_id`` records which attempt
    started the task so later bookkeeping can attribute it; a later attempt of
    the same owner still sees tasks started by the earlier one.
    """

    owner_id: str
    attempt_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not str(self.owner_id).strip():
            raise ValueError("a background scope must have a non-empty owner_id")


def _start_process(command: str) -> subprocess.Popen[str]:
    """Start a shell command in a process group that can be stopped as a unit."""
    kwargs: dict[str, Any] = {
        "shell": True,
        "cwd": WORKDIR,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def _signal_posix_process_group(process: subprocess.Popen[str], sig: int) -> None:
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS answers EPERM, not ESRCH, when every member of the group has
        # exited but is not yet reaped (verified 2026-10-21). The group is our
        # own, so nothing is left to signal; letting it raise turned a timed-out
        # command into status "error" on a loaded host.
        pass


def _taskkill_windows_process_tree(process: subprocess.Popen[str]) -> None:
    """Ask Windows to stop the process and every descendant."""
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        if process.poll() is None:
            process.kill()


def _force_stop_process_tree(process: subprocess.Popen[str]) -> None:
    """Force-stop one tracked process tree without draining its pipes."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        _taskkill_windows_process_tree(process)
    else:
        _signal_posix_process_group(process, signal.SIGKILL)


def _terminate_process_tree(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Terminate a timed-out process tree, drain its pipes, and reap its root."""
    if os.name == "nt":
        _taskkill_windows_process_tree(process)
        try:
            return process.communicate(timeout=_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            if process.poll() is None:
                process.kill()
            return process.communicate()

    _signal_posix_process_group(process, signal.SIGTERM)
    try:
        stdout, stderr = process.communicate(timeout=_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _signal_posix_process_group(process, signal.SIGKILL)
        return process.communicate()

    # The shell can exit before a descendant that ignored SIGTERM. The group
    # retains the shell's process-group id, so this final signal prevents an
    # orphan even when that descendant closed its inherited output pipes.
    _signal_posix_process_group(process, signal.SIGKILL)
    return stdout, stderr


def _combined_output(stdout: str | None, stderr: str | None) -> str:
    return ((stdout or "") + (stderr or "")).strip()[:_MAX_OUTPUT_CHARS]


class BackgroundManager:
    """Background thread execution + notification queue, addressed by owner.

    One instance is a *handle*: it carries the scope its methods read and write
    under. :meth:`for_scope` hands out another handle over the same task table,
    so a session and its later attempts share their tasks while a different
    session sees none of them.
    """

    def __init__(self, scope: Optional[BackgroundScope] = None) -> None:
        self.tasks: Dict[str, dict] = {}
        # (owner_id, payload). Kept as pairs so the payload shape consumers and
        # existing tests see stays exactly what it was; routing is internal.
        self._notifications: List[tuple[str, dict]] = []
        self._lock = threading.Lock()
        self._scope = scope or BackgroundScope(owner_id=f"isolated:{uuid.uuid4().hex}")

    @property
    def scope(self) -> BackgroundScope:
        """The owner this handle reads and writes under."""
        return self._scope

    def for_scope(self, scope: BackgroundScope) -> "BackgroundManager":
        """Return a handle over the same task table bound to another owner."""
        other = BackgroundManager(scope=scope)
        other.tasks = self.tasks
        other._notifications = self._notifications
        other._lock = self._lock
        return other

    def _owns(self, task: dict) -> bool:
        return task.get("owner_id") == self._scope.owner_id

    def run(self, command: str) -> str:
        """Start a background task and return its task_id.

        Args:
            command: Shell command to execute.

        Returns:
            JSON string containing status and task_id.
        """
        safety_error = broad_python_kill_error(command)
        if safety_error:
            return json.dumps(
                {"status": "error", "error": safety_error},
                ensure_ascii=False,
            )

        task_id = uuid.uuid4().hex[:8]
        started_at = time.monotonic()
        with self._lock:
            self.tasks[task_id] = {
                "status": "running",
                "result": None,
                "command": command,
                "exit_code": None,
                "process": None,
                "cancel_requested": False,
                "started_at": started_at,
                "owner_id": self._scope.owner_id,
                "attempt_id": self._scope.attempt_id,
            }
        threading.Thread(target=self._execute, args=(task_id, command), daemon=True).start()
        return json.dumps({"status": "ok", "task_id": task_id, "message": f"Started: {command[:80]}"})

    def _execute(self, task_id: str, command: str) -> None:
        exit_code: int | None = None
        process: subprocess.Popen[str] | None = None
        output = ""
        status = "error"
        try:
            process = _start_process(command)
            with self._lock:
                task = self.tasks.get(task_id)
                if task is None:
                    _force_stop_process_tree(process)
                    return
                task["process"] = process
                cancel_requested = bool(task.get("cancel_requested"))
            if cancel_requested:
                _force_stop_process_tree(process)

            try:
                stdout, stderr = process.communicate(timeout=_COMMAND_TIMEOUT_SECONDS)
                output = _combined_output(stdout, stderr)
                exit_code = process.returncode
                status = "completed" if exit_code == 0 else "error"
            except subprocess.TimeoutExpired:
                stdout, stderr = _terminate_process_tree(process)
                partial_output = _combined_output(stdout, stderr)
                timeout_message = f"Timeout ({_COMMAND_TIMEOUT_SECONDS:g}s)"
                output = (
                    f"{partial_output}\n{timeout_message}"
                    if partial_output
                    else timeout_message
                )
                output = output[:_MAX_OUTPUT_CHARS]
                status = "timeout"
        except Exception as e:
            output, status = str(e), "error"

        with self._lock:
            task = self.tasks.get(task_id)
            if task is None:
                return
            if task.get("cancel_requested"):
                status = "cancelled"
                cancel_message = "Cancelled by request"
                output = (
                    f"{output}\n{cancel_message}"
                    if output
                    else cancel_message
                )
                output = output[:_MAX_OUTPUT_CHARS]
            task["status"] = status
            task["result"] = output or "(no output)"
            task["exit_code"] = exit_code
            task["process"] = None
            started_at = task.get("started_at")
            if isinstance(started_at, (int, float)):
                task["duration_seconds"] = round(
                    max(0.0, time.monotonic() - started_at),
                    3,
                )
            self._notifications.append((
                task["owner_id"],
                {
                    "task_id": task_id, "status": status,
                    "command": command[:80], "result": (output or "")[:500],
                    "exit_code": exit_code,
                },
            ))

    def cancel(self, task_id: str) -> str:
        """Cancel one task by its tracked process group.

        Args:
            task_id: Identifier returned by :meth:`run`.

        Returns:
            JSON string describing the cancellation request.
        """
        with self._lock:
            task = self.tasks.get(task_id)
            # A task owned by another session is reported exactly like a task id
            # that never existed, so probing cannot confirm one exists.
            if task is None or not self._owns(task):
                return json.dumps({
                    "status": "error",
                    "error": f"Unknown task {task_id}",
                })

            task_status = task["status"]
            if task_status == "cancelling":
                return json.dumps({
                    "status": "ok",
                    "task_id": task_id,
                    "task_status": "cancelling",
                    "message": "Cancellation already requested",
                })
            if task_status != "running":
                return json.dumps({
                    "status": "error",
                    "error": f"Task {task_id} is already {task_status}",
                    "task_status": task_status,
                })

            process = task.get("process")
            if process is not None and process.poll() is not None:
                return json.dumps({
                    "status": "error",
                    "error": f"Task {task_id} is already finishing",
                    "task_status": task_status,
                })

            task["cancel_requested"] = True
            task["status"] = "cancelling"

        if process is not None:
            _force_stop_process_tree(process)
        return json.dumps({
            "status": "ok",
            "task_id": task_id,
            "task_status": "cancelling",
            "message": "Cancellation requested",
        })

    def check(self, task_id: Optional[str] = None) -> str:
        task: dict | None = None
        task_summaries: list[tuple[str, str, str]] = []
        with self._lock:
            if task_id:
                t = self.tasks.get(task_id)
                task = dict(t) if t is not None and self._owns(t) else None
            else:
                task_summaries = [
                    (tid, t["status"], t["command"])
                    for tid, t in self.tasks.items()
                    if self._owns(t)
                ]

        if task_id:
            t = task
            if not t:
                return json.dumps({"status": "error", "error": f"Unknown task {task_id}"})
            status = t["status"]
            result = t.get("result")
            payload = {
                "status": status,
                "command": t["command"][:60],
                "result": result or "(running)",
                "exit_code": t.get("exit_code"),
                "attempt_id": t.get("attempt_id"),
            }
            started_at = t.get("started_at")
            if isinstance(started_at, (int, float)):
                duration = t.get("duration_seconds")
                if not isinstance(duration, (int, float)):
                    duration = max(0.0, time.monotonic() - started_at)
                elapsed = round(duration, 1)
                payload["elapsed_seconds"] = elapsed
                payload["timeout_seconds"] = _COMMAND_TIMEOUT_SECONDS
                if status in {"running", "cancelling"}:
                    remaining = max(0.0, _COMMAND_TIMEOUT_SECONDS - duration)
                    payload["timeout_remaining_seconds"] = round(remaining, 1)
                    if not result:
                        payload["result"] = (
                            f"({status} for {elapsed:g}s; automatic timeout "
                            f"after {_COMMAND_TIMEOUT_SECONDS:g}s; use "
                            "cancel_background(task_id) to stop safely)"
                        )
            return json.dumps(payload, ensure_ascii=False)
        lines = [
            f"{tid}: [{status}] {command[:60]}"
            for tid, status, command in task_summaries
        ]
        return "\n".join(lines) if lines else "No background tasks."

    def drain_notifications(self) -> List[dict]:
        """Return this owner's queued notifications, oldest first.

        Notifications belonging to other owners stay queued for them; draining
        one session can never consume another's result.
        """
        with self._lock:
            mine = [payload for owner, payload in self._notifications
                    if owner == self._scope.owner_id]
            self._notifications[:] = [(owner, payload) for owner, payload in self._notifications
                                      if owner != self._scope.owner_id]
        return mine


_BG = BackgroundManager()


def get_background_manager() -> BackgroundManager:
    """Return an unowned handle over the process-wide task table.

    Every call binds its own isolated scope, so two callers each get a private
    view and cannot see, read or cancel each other's tasks. A host that wants a
    session or worker to receive its own completion notifications must build a
    scoped handle with :meth:`BackgroundManager.for_scope` and hand the same
    object to both the tool registry and ``AgentLoop``.
    """
    return _BG.for_scope(BackgroundScope(owner_id=f"isolated:{uuid.uuid4().hex}"))


class BackgroundRunTool(BaseTool):
    name = "background_run"
    description = (
        "Run a shell command in a tracked background process group. Returns "
        "task_id immediately and times out after 300 seconds. On Windows the "
        "shell is cmd.exe, not PowerShell. Poll with check_background and stop "
        "only with cancel_background; never use taskkill/pkill/killall."
    )
    parameters = {"type": "object", "properties": {
        "command": {"type": "string", "description": "Shell command to run in background"},
    }, "required": ["command"]}
    is_readonly = False

    def __init__(self, background: Optional[BackgroundManager] = None) -> None:
        self.background = background if background is not None else get_background_manager()

    def execute(self, **kw: Any) -> str:
        return self.background.run(kw["command"])


class CheckBackgroundTool(BaseTool):
    name = "check_background"
    description = (
        "Check background task status, elapsed time, and remaining time before "
        "the 300-second automatic timeout. Omit task_id to list all. To stop "
        "a running task, pass its task_id to cancel_background."
    )
    parameters = {"type": "object", "properties": {
        "task_id": {"type": "string"},
    }, "required": []}
    repeatable = True

    def __init__(self, background: Optional[BackgroundManager] = None) -> None:
        self.background = background if background is not None else get_background_manager()

    def execute(self, **kw: Any) -> str:
        return self.background.check(kw.get("task_id"))


class CancelBackgroundTool(BaseTool):
    """Cancel one process group created by :class:`BackgroundRunTool`."""

    name = "cancel_background"
    description = (
        "Cancel exactly one background_run task by task_id using its tracked "
        "process group/PID. Never kills processes by executable name."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "task_id returned by background_run",
            },
        },
        "required": ["task_id"],
    }
    is_readonly = False

    def __init__(self, background: Optional[BackgroundManager] = None) -> None:
        self.background = background if background is not None else get_background_manager()

    def execute(self, **kw: Any) -> str:
        return self.background.cancel(kw["task_id"])
