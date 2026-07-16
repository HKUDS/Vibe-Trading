"""Background tasks: thread execution + notification queue."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.tools import BaseTool

WORKDIR = Path(__file__).resolve().parents[2]
_COMMAND_TIMEOUT_SECONDS = 300.0
_TERMINATION_GRACE_SECONDS = 2.0
_MAX_OUTPUT_CHARS = 50_000


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
    """Background thread execution + notification queue."""

    def __init__(self) -> None:
        self.tasks: Dict[str, dict] = {}
        self._notifications: List[dict] = []
        self._lock = threading.Lock()

    def run(self, command: str) -> str:
        """Start a background task and return its task_id.

        Args:
            command: Shell command to execute.

        Returns:
            JSON string containing status and task_id.
        """
        task_id = uuid.uuid4().hex[:8]
        self.tasks[task_id] = {"status": "running", "result": None, "command": command}
        threading.Thread(target=self._execute, args=(task_id, command), daemon=True).start()
        return json.dumps({"status": "ok", "task_id": task_id, "message": f"Started: {command[:80]}"})

    def _execute(self, task_id: str, command: str) -> None:
        process: subprocess.Popen[str] | None = None
        try:
            process = _start_process(command)
            try:
                stdout, stderr = process.communicate(timeout=_COMMAND_TIMEOUT_SECONDS)
                output = _combined_output(stdout, stderr)
                status = "completed"
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
        self.tasks[task_id]["status"] = status
        self.tasks[task_id]["result"] = output or "(no output)"
        with self._lock:
            self._notifications.append({
                "task_id": task_id, "status": status,
                "command": command[:80], "result": (output or "")[:500],
            })

    def check(self, task_id: Optional[str] = None) -> str:
        if task_id:
            t = self.tasks.get(task_id)
            if not t:
                return json.dumps({"status": "error", "error": f"Unknown task {task_id}"})
            return json.dumps({"status": t["status"], "command": t["command"][:60],
                                "result": t.get("result") or "(running)"}, ensure_ascii=False)
        lines = [f"{tid}: [{t['status']}] {t['command'][:60]}" for tid, t in self.tasks.items()]
        return "\n".join(lines) if lines else "No background tasks."

    def drain_notifications(self) -> List[dict]:
        with self._lock:
            notifs = list(self._notifications)
            self._notifications.clear()
        return notifs


_BG = BackgroundManager()


def get_background_manager() -> BackgroundManager:
    """Return the global BackgroundManager singleton."""
    return _BG


class BackgroundRunTool(BaseTool):
    name = "background_run"
    description = "Run command in background thread. Returns task_id immediately. Use for long-running operations (ML training, large data processing)."
    parameters = {"type": "object", "properties": {
        "command": {"type": "string", "description": "Shell command to run in background"},
    }, "required": ["command"]}
    is_readonly = False

    def execute(self, **kw: Any) -> str:
        return _BG.run(kw["command"])


class CheckBackgroundTool(BaseTool):
    name = "check_background"
    description = "Check background task status. Omit task_id to list all."
    parameters = {"type": "object", "properties": {
        "task_id": {"type": "string"},
    }, "required": []}
    repeatable = True

    def execute(self, **kw: Any) -> str:
        return _BG.check(kw.get("task_id"))
