"""One live session service per sessions directory, across processes.

``SessionService`` marks every pending or running attempt it finds on disk as
interrupted when it is constructed (restart recovery). That is right only when
no other live service writes the same directory, so each owner — the HTTP
server's service and every ``vibe_trading.Client`` — claims the directory
first. The claim is an exclusive advisory lock on ``<sessions>/.service.lock``
held for as long as the owner serves; the operating system drops it when the
process exits, so a crashed owner never leaves a stale claim behind.

Within one process the claim is keyed by owner name: the same owner may claim
again (the HTTP server rebuilds its service lazily), any other owner is
refused, and an owner holds one directory at a time.
"""

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
        # An owner serves one directory at a time: the HTTP server rebuilding
        # its service over another directory gives up the previous one.
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
