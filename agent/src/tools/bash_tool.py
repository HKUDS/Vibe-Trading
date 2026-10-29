"""Bash tool: execute shell commands under run_dir."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from typing import Any

from src.agent.tools import BaseTool
from src.tools._shell_safety import broad_python_kill_error

_OUTPUT_LIMIT = 50_000
_DEFAULT_TIMEOUT = 120
# How long to wait for output to drain after killing a timed-out process
# tree before giving up (the pipes are held by grandchildren).
_DRAIN_TIMEOUT = 5


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a subprocess and its whole descendant tree.

    On Windows, ``cmd.exe /c <command>`` spawns grandchildren (e.g. a piped
    ``findstr``) that inherit the stdout/stderr pipe write handles. Killing
    only the shell leaves those grandchildren alive, so a later
    ``communicate()`` blocks forever waiting for EOF that never arrives -
    the exact 2026-08-20 hang (bash call at 19:20:55 never returned, cmd.exe
    + findstr still alive 20 minutes later). ``taskkill /F /T`` kills the
    tree; POSIX uses ``killpg`` on the process group.

    Args:
        proc: The Popen object whose tree should be killed.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


class BashTool(BaseTool):
    """Execute shell commands in the working directory."""

    name = "bash"
    description = (
        "Execute a shell command in the working directory. On Windows the "
        "shell is cmd.exe, not PowerShell. Use for installing packages, "
        "running scripts, or inspecting files. Never kill Python processes "
        "by name; stop a background_run task with cancel_background. "
        "Heredocs (<<) are NOT supported on cmd.exe - write your script to "
        "a file with write_file first, then run it (e.g. python script.py)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
        },
        "required": ["command"],
    }
    repeatable = True
    is_readonly = False

    def execute(self, **kwargs: Any) -> str:
        """Execute a shell command.

        Args:
            **kwargs: Must include command. Optional run_dir used as cwd.

        Returns:
            JSON string with stdout, stderr, and exit_code.
        """
        command = kwargs["command"]
        cwd = kwargs.get("run_dir")
        safety_error = broad_python_kill_error(command)
        if safety_error:
            return json.dumps(
                {"status": "error", "error": safety_error},
                ensure_ascii=False,
            )
        # cmd.exe has no heredocs; return a clear message instead of the
        # cryptic "<< was unexpected at this time." stderr. Only multi-line
        # commands with a heredoc delimiter are flagged, so a single-line
        # bit shift (python -c "print(1 << 2)") is unaffected. POSIX shells
        # support heredocs natively, so this only applies on Windows.
        if os.name == "nt" and "\n" in command and re.search(
            r"<<\s*['\"]?[A-Za-z_][A-Za-z0-9_]*", command
        ):
            return json.dumps(
                {
                    "status": "error",
                    "error_code": "heredoc_unsupported",
                    "message": (
                        "Heredoc syntax (<<) is not supported on Windows cmd.exe. "
                        "Write your script to a file first (write_file), then run "
                        "it, e.g. python path\\to\\script.py."
                    ),
                },
                ensure_ascii=False,
            )

        # Spawn with a dedicated process group so a timeout can kill the
        # WHOLE tree, not just cmd.exe. Without this, grandchildren that
        # inherited the pipe handles keep communicate() blocked forever.
        creationflags = 0
        start_new_session = False
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            start_new_session = True
        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "error": f"Could not start command: {exc}",
            }, ensure_ascii=False)

        try:
            stdout, stderr = proc.communicate(timeout=_DEFAULT_TIMEOUT)
        except subprocess.TimeoutExpired:
            # Kill the tree, then drain with a bounded second wait. The tree
            # kill closes the inherited pipe handles, so the drain returns.
            _kill_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=_DRAIN_TIMEOUT)
            except Exception:
                stdout, stderr = "", ""
            stdout = (stdout or "")[:_OUTPUT_LIMIT]
            stderr = (stderr or "")[:_OUTPUT_LIMIT]
            return json.dumps({
                "status": "error",
                "error_code": "tool_timeout",
                "error": f"Command timed out after {_DEFAULT_TIMEOUT}s",
                "stdout": stdout,
                "stderr": stderr,
            }, ensure_ascii=False)

        stdout = stdout[:_OUTPUT_LIMIT] if len(stdout) > _OUTPUT_LIMIT else stdout
        stderr = stderr[:_OUTPUT_LIMIT] if len(stderr) > _OUTPUT_LIMIT else stderr
        return json.dumps({
            "status": "ok" if proc.returncode == 0 else "error",
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }, ensure_ascii=False)
