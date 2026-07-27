"""Shared safety checks for host shell commands."""

from __future__ import annotations

import re

_PYTHON_PROCESS = r"python(?:w|\d+(?:\.\d+)*)?(?:\.exe)?\b"
_TASKKILL_PYTHON = re.compile(
    rf"\btaskkill(?:\.exe)?\b"
    rf"[^;&\r\n]*(?:/im\s+{_PYTHON_PROCESS}|get-process\s+"
    rf"(?:-name\s+)?{_PYTHON_PROCESS})",
    re.IGNORECASE,
)
_UNIX_PYTHON_KILL = re.compile(
    rf"^(?:sudo\s+)?(?:pkill|killall)\b[^;&\r\n]*{_PYTHON_PROCESS}",
    re.IGNORECASE,
)
_POWERSHELL_PREFIX = re.compile(
    r"^(?:powershell|pwsh)(?:\.exe)?\b",
    re.IGNORECASE,
)
_POWERSHELL_PYTHON_BY_NAME = re.compile(
    rf"\bstop-process\b[^;&\r\n]*-name\s+{_PYTHON_PROCESS}",
    re.IGNORECASE,
)
_POWERSHELL_PYTHON_PIPE = re.compile(
    rf"\bget-process\s+(?:-name\s+)?{_PYTHON_PROCESS}"
    r"[^;&\r\n]*\|\s*stop-process\b",
    re.IGNORECASE,
)
_BROAD_PYTHON_KILL_ERROR = (
    "Broad Python process termination is blocked because it can terminate "
    "Vibe-Trading itself. Use cancel_background with the task_id returned "
    "by background_run."
)


def broad_python_kill_error(command: str) -> str | None:
    """Return an error when a shell command broadly kills Python by name.

    Args:
        command: Shell source submitted to a shell-capable tool.

    Returns:
        An actionable error for unsafe broad termination, otherwise ``None``.
    """
    for segment in re.split(r"[;\r\n]|(?<![<>])&(?![<>])", command):
        normalized = segment.strip().replace('"', " ").replace("'", " ")
        normalized = re.sub(r"\s+", " ", normalized)
        if _TASKKILL_PYTHON.search(normalized):
            return _BROAD_PYTHON_KILL_ERROR
        if _UNIX_PYTHON_KILL.search(normalized):
            return _BROAD_PYTHON_KILL_ERROR
        if _POWERSHELL_PREFIX.search(normalized) and (
            _POWERSHELL_PYTHON_BY_NAME.search(normalized)
            or _POWERSHELL_PYTHON_PIPE.search(normalized)
        ):
            return _BROAD_PYTHON_KILL_ERROR
    return None
