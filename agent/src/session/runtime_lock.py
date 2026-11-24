"""Lease each sessions directory exclusively so restart recovery cannot interrupt a live writer."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Dict, Tuple

try:  # POSIX advisory lock (Linux/macOS).
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows byte-range lock.
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

#: Lock file inside the sessions directory.
LOCK_FILENAME = ".service.lock"
#: Owner name of the HTTP server's session service.
HTTP_SERVER_OWNER = "the HTTP server's session service"

_HELD: Dict[Path, Tuple[int, str]] = {}
_GUARD = threading.Lock()


class SessionsDirInUseError(RuntimeError):
    """Another live session service owns the sessions directory."""


def _try_lock(fd: int) -> bool:
    """Take an exclusive non-blocking lock on ``fd``; False when it is held."""
    if fcntl is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    if msvcrt is not None:  # pragma: no cover - exercised on Windows only
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    raise RuntimeError("no file-lock primitive on this platform")  # pragma: no cover


def claim_sessions_dir(sessions_dir: Path | str, owner: str) -> Path:
    """Claim a sessions directory for one live session service."""
    key = Path(sessions_dir).expanduser().resolve()
    with _GUARD:
        held = _HELD.get(key)
        if held is not None:
            if held[1] == owner:
                return key
            raise SessionsDirInUseError(f"{key} is already served by {held[1]} in this process")
        key.mkdir(parents=True, exist_ok=True)
        fd = os.open(key / LOCK_FILENAME, os.O_RDWR | os.O_CREAT, 0o600)
        if not _try_lock(fd):
            os.close(fd)
            raise SessionsDirInUseError(
                f"another process (a running `vibe-trading serve` or Client) serves {key}; "
                "stop it or use another VIBE_TRADING_HOME"
            )
        # Release the previous directory because each owner may serve only one.
        for other, (other_fd, other_owner) in list(_HELD.items()):
            if other_owner == owner:
                del _HELD[other]
                os.close(other_fd)
        _HELD[key] = (fd, owner)
        return key


def release_sessions_dir(sessions_dir: Path | str, owner: str) -> None:
    """Release a claim made by ``owner``; a no-op for any other owner."""
    key = Path(sessions_dir).expanduser().resolve()
    with _GUARD:
        held = _HELD.get(key)
        if held is None or held[1] != owner:
            return
        del _HELD[key]
        os.close(held[0])  # Closing the descriptor drops the lock.
