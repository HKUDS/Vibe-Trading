"""Shared safety checks for host shell commands."""

from __future__ import annotations

import re
from typing import Callable

# Process-wide confirmation hook for bash/background_run. The CLI installs one
# when the user opts in to shell tools, so every registry in the process (the
# run's own, the lazy-loading copy, and swarm workers') asks before running a
# command. API/MCP servers never install it: there the operator opt-in stands.
_shell_confirm: Callable[[str, str], bool] | None = None


def set_shell_confirm(confirm: Callable[[str, str], bool] | None) -> None:
    """Install (or clear) the ``confirm(tool_name, command) -> bool`` hook."""
    global _shell_confirm
    _shell_confirm = confirm


def shell_command_confirmed(tool_name: str, command: str) -> bool:
    """Return whether a shell command may run: True when no hook is installed."""
    return _shell_confirm is None or bool(_shell_confirm(tool_name, command))


def live_trading_signals() -> list[str]:
    """Return reasons this host holds live-trading authority a shell could misuse.

    A host shell can import a broker connector and call ``place_order``
    directly, forge ``mandate.json`` or delete the HALT sentinel, so the live
    gate means nothing while shell tools are on. Read failures count as a
    reason (fail closed).

    shortcut: legacy per-connector JSON credentials (``<runtime_root>/<broker>.json``)
    and keys in ``.env`` are not inspected; add per-connector checks if those
    become the common way to store live keys.

    Returns:
        Human-readable reasons; empty when no live authority was found.
    """
    reasons: list[str] = []
    try:
        from src.live.paths import live_root

        root = live_root()
        for broker_dir in sorted(root.iterdir()) if root.is_dir() else []:
            if (broker_dir / "mandate.json").exists():
                reasons.append(f"a live mandate exists for {broker_dir.name}")
            oauth = broker_dir / "oauth"
            if oauth.is_dir() and any(oauth.iterdir()):
                reasons.append(f"live OAuth tokens are cached for {broker_dir.name}")
    except OSError as exc:
        reasons.append(f"the live-trading state could not be read ({type(exc).__name__})")

    try:
        from src.trading.connections import ConnectionStore
        from src.trading.profiles import profile_by_id

        selected = profile_by_id(None)
        if selected.environment == "live" and not selected.readonly:
            reasons.append(f"the selected trading profile {selected.id} can place live orders")
        for connection in ConnectionStore().list():
            if profile_by_id(connection.profile_id).environment == "live":
                reasons.append(f"connection {connection.id} holds live account credentials")
    except Exception as exc:  # noqa: BLE001 — any failure must keep the shell off
        reasons.append(f"the trading configuration could not be read ({type(exc).__name__})")
    return reasons

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
