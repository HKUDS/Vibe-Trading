"""One-time migration of code-relative state into the runtime root.

Before issue #904 was fixed, ``sessions/``, ``runs/``, ``.swarm/runs/`` and
``uploads/`` were resolved relative to the installed code (``site-packages``
on a pip install, the checkout on an editable install). They now live under
:func:`src.config.paths.get_runtime_root`. This module moves data from the
old location on first run so history survives upgrades and reinstalls.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from src.config.paths import get_runtime_root

logger = logging.getLogger(__name__)

# (legacy subpath, runtime-root subpath). ``.swarm`` loses its dot: hiding a
# directory inside the already-hidden runtime root serves no purpose.
_LEGACY_DIRS: tuple[tuple[str, str], ...] = (
    ("sessions", "sessions"),
    ("runs", "runs"),
    (".swarm/runs", "swarm/runs"),
    ("uploads", "uploads"),
)


def default_legacy_root() -> Path:
    """Return the pre-#904 state root: the directory containing the packages.

    In the repo layout this is ``agent/``; in an installed distribution it is
    ``site-packages`` itself (the bug this migration cleans up after).
    """
    return Path(__file__).resolve().parents[2]


def _has_content(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def migrate_legacy_state(
    legacy_root: Path | None = None, runtime_root: Path | None = None
) -> list[tuple[Path, Path]]:
    """Move legacy code-relative state directories under the runtime root.

    Idempotent: once a legacy directory has been moved (or was never there),
    later calls do nothing. When both the legacy and the new location hold
    data, the new location wins and the legacy directory is left in place for
    the user to reconcile — never silently merged.

    Returns:
        The ``(source, destination)`` pairs that were actually moved.
    """
    legacy_root = legacy_root if legacy_root is not None else default_legacy_root()
    runtime_root = runtime_root if runtime_root is not None else get_runtime_root()
    if legacy_root.resolve() == runtime_root.resolve():
        return []

    moved: list[tuple[Path, Path]] = []
    for legacy_sub, new_sub in _LEGACY_DIRS:
        source = legacy_root / legacy_sub
        destination = runtime_root / new_sub
        if not _has_content(source):
            continue
        if _has_content(destination):
            logger.warning(
                "Both %s and %s contain data; keeping %s. Reconcile or delete %s manually.",
                source,
                destination,
                destination,
                source,
            )
            continue
        if destination.is_dir():
            destination.rmdir()  # pre-created empty dir would make shutil.move nest
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        logger.info("Migrated %s -> %s", source, destination)
        moved.append((source, destination))
    return moved
