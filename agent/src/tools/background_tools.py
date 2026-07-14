"""Background tasks: thread execution + notification queue."""

from __future__ import annotations

import json
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent.tools import BaseTool
from src.tools.redaction import redact_internal_paths, redact_payload, redact_text

WORKDIR = Path(__file__).resolve().parents[2]

#: Hard ceiling on the per-task output buffer (bytes). Long-running high-output
#: commands must not be allowed to OOM the agent: we cap reads here so a
#: pathological child cannot exhaust memory before the timeout fires.
_OUTPUT_BYTE_CAP = 50_000
#: Per-stream read chunk size for the streaming reader below.
_STREAM_CHUNK = 4096
#: Wall-clock cap for background subprocess execution (seconds).
_EXEC_TIMEOUT = 300


def _stream_and_cap(stream, cap: int) -> str:
    """Drain a subprocess stream into a bounded UTF-8 string.

    Reads in :data:`_STREAM_CHUNK`-byte chunks and stops once ``cap`` bytes
    have been collected. Anything past the cap is discarded silently — the
    same truncation policy as the previous :func:`subprocess.run` slice, but
    without buffering the full child output in memory first.

    Args:
        stream: The subprocess stdout/stderr pipe (``None`` when the child
            closed the stream before we read).
        cap: Maximum number of bytes to retain.

    Returns:
        Decoded text (errors='replace') truncated to ``cap`` bytes.
    """
    if stream is None:
        return ""
    collected = bytearray()
    while len(collected) < cap:
        chunk = stream.read(_STREAM_CHUNK)
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8", errors="replace")
        remaining = cap - len(collected)
        if len(chunk) > remaining:
            collected.extend(chunk[:remaining])
            break
        collected.extend(chunk)
    return collected.decode("utf-8", errors="replace")


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
        # Guard every mutation of ``self.tasks`` so concurrent ``run`` calls
        # cannot race with ``check`` (which iterates the dict) and raise
        # ``RuntimeError: dictionary changed size during iteration``.
        with self._lock:
            self.tasks[task_id] = {"status": "running", "result": None, "command": command}
        threading.Thread(target=self._execute, args=(task_id, command), daemon=True).start()
        return json.dumps({"status": "ok", "task_id": task_id, "message": f"Started: {command[:80]}"})

    def _execute(self, task_id: str, command: str) -> None:
        proc: subprocess.Popen | None = None
        try:
            # Use Popen with explicit stdout/stderr pipes and bounded reads
            # instead of ``capture_output=True`` so the child output cannot
            # OOM the parent. ``bufsize=0`` lets the read loop see bytes as
            # they arrive instead of buffering the full stream first.
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=WORKDIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,  # read raw bytes; we decode with errors='replace'
                bufsize=0,
            )
            try:
                stdout_text = _stream_and_cap(proc.stdout, _OUTPUT_BYTE_CAP)
                stderr_text = _stream_and_cap(proc.stderr, _OUTPUT_BYTE_CAP)
                rc = proc.wait(timeout=_EXEC_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_text = _stream_and_cap(proc.stdout, _OUTPUT_BYTE_CAP)
                stderr_text = _stream_and_cap(proc.stderr, _OUTPUT_BYTE_CAP)
                output = "Timeout (300s)"
                status = "timeout"
                safe_output = redact_internal_paths(redact_text(output) or "(no output)")
                # Lock the status/result writes so concurrent ``check``
                # iterations see a consistent snapshot.
                with self._lock:
                    self.tasks[task_id]["status"] = status
                    self.tasks[task_id]["result"] = safe_output
                    self._notifications.append({
                        "task_id": task_id, "status": status,
                        "command": command[:80],
                        "result": redact_internal_paths(
                            redact_text((stdout_text + stderr_text)[:500])
                        ),
                    })
                return
            output = (stdout_text + stderr_text).strip()
            if rc != 0:
                output = f"{output}\n[exit_code={rc}]".strip()
            status = "completed"
        except Exception as e:
            output, status = str(e), "error"
            if proc is not None and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass
        # Redact before storing: BG task output is a shell surface that can
        # leak secrets (API keys) and internal paths back to the agent. Match
        # the same surface used by the bash tool's audit trace. ``redact_text``
        # handles free-form command output (key=value shell prints); the
        # structured redaction is a no-op here because the buffer is a string.
        safe_output = redact_internal_paths(redact_text(output) or "(no output)")
        with self._lock:
            self.tasks[task_id]["status"] = status
            self.tasks[task_id]["result"] = safe_output
            self._notifications.append({
                "task_id": task_id, "status": status,
                "command": command[:80],
                "result": redact_internal_paths(redact_text((output or "")[:500])),
            })

    def check(self, task_id: Optional[str] = None) -> str:
        if task_id:
            with self._lock:
                t = self.tasks.get(task_id)
            if not t:
                return json.dumps({"status": "error", "error": f"Unknown task {task_id}"})
            return json.dumps({"status": t["status"], "command": t["command"][:60],
                                "result": t.get("result") or "(running)"}, ensure_ascii=False)
        # Snapshot under lock so a concurrent ``run``/``_execute`` cannot
        # mutate the dict during iteration and raise RuntimeError.
        with self._lock:
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
