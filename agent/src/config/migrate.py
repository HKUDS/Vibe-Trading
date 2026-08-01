"""One-time migration of code-relative state into the runtime root.

Before issue #904 was fixed, ``sessions/``, ``runs/``, ``.swarm/runs/`` and
``uploads/`` were resolved relative to the installed code (``site-packages``
on a pip install, the checkout on an editable install). They now live under
:func:`src.config.paths.get_runtime_root`. This module moves data from the
old location on first run so history survives upgrades and reinstalls.

Merge semantics are child-level: each session/run/upload entry moves
individually, and only a same-named entry already present at the destination
is skipped (session and run ids are timestamped/random, so real collisions
mean the entry was already migrated). This keeps destinations that other
features already populate — autopilot runs, channel media uploads — from
blocking migration of the rest. Each child lands via a hidden
``.migrating-*`` staging name plus an atomic rename, so an interrupted move
can never surface a half-copied entry; staging leftovers are recovered on
the next run (redone while the source still exists, promoted once it is
gone).
"""

from __future__ import annotations

import logging
import os
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

_STAGING_PREFIX = ".migrating-"


def default_legacy_root() -> Path:
    """Return the pre-#904 state root: the directory containing the packages.

    In the repo layout this is ``agent/``; in an installed distribution it is
    ``site-packages`` itself (the bug this migration cleans up after).
    """
    return Path(__file__).resolve().parents[2]


def _has_content(path: Path) -> bool:
    return path.is_dir() and any(path.iterdir())


def _recover_staging(source: Path, destination: Path) -> None:
    """Resolve ``.migrating-*`` leftovers from an interrupted earlier run.

    A leftover whose final name already exists, or whose source entry is
    still present (the copy was cut short; the move can simply be redone),
    is discarded. One whose source entry is gone is a completed move that
    missed its rename — promote it instead of losing the data.
    """
    if not destination.is_dir():
        return
    for staged in destination.glob(f"{_STAGING_PREFIX}*"):
        name = staged.name.removeprefix(_STAGING_PREFIX).split("-", 1)[-1]
        final = destination / name
        if final.exists() or (source / name).exists():
            shutil.rmtree(staged, ignore_errors=True)
        else:
            staged.rename(final)
            logger.info("Recovered interrupted migration of %s", final)


def _merge_children(source: Path, destination: Path) -> int:
    """Move ``source``'s children into ``destination``; skip name collisions."""
    destination.mkdir(parents=True, exist_ok=True)
    moved = 0
    for child in sorted(source.iterdir()):
        final = destination / child.name
        if final.exists():
            logger.warning(
                "Not migrating %s: %s already exists. Reconcile or delete the old copy manually.",
                child,
                final,
            )
            continue
        staged = destination / f"{_STAGING_PREFIX}{os.getpid()}-{child.name}"
        try:
            shutil.move(str(child), str(staged))
            staged.rename(final)
        except OSError:
            logger.warning("Failed to migrate %s; leaving it in place.", child, exc_info=True)
            # A fully-staged copy whose source is gone must survive for
            # _recover_staging; a partial one (source intact) is discarded.
            if child.exists():
                shutil.rmtree(staged, ignore_errors=True)
            continue
        moved += 1
    return moved


def _remove_empty_source(source: Path) -> None:
    try:
        source.rmdir()
        if source.parent.name == ".swarm":
            source.parent.rmdir()  # drop the legacy shell once its last child is gone
    except OSError:
        pass  # non-empty (collision children remain) or already gone


def migrate_legacy_state(
    legacy_root: Path | None = None, runtime_root: Path | None = None
) -> list[tuple[Path, Path]]:
    """Move legacy code-relative state directories under the runtime root.

    Idempotent: once a legacy entry has been moved (or was never there),
    later calls do nothing. A directory that looks like an unrelated Python
    package (``site-packages/runs`` may be someone else's distribution) is
    never touched, and a failure in one directory never blocks the others.

    Returns:
        The ``(source, destination)`` pairs where at least one child moved.
    """
    legacy_root = legacy_root if legacy_root is not None else default_legacy_root()
    runtime_root = runtime_root if runtime_root is not None else get_runtime_root()
    if legacy_root.resolve() == runtime_root.resolve():
        return []

    moved: list[tuple[Path, Path]] = []
    for legacy_sub, new_sub in _LEGACY_DIRS:
        source = legacy_root / legacy_sub
        destination = runtime_root / new_sub
        try:
            _recover_staging(source, destination)
            if not _has_content(source):
                continue
            if (source / "__init__.py").exists():
                logger.warning(
                    "Skipping %s: it looks like a Python package, not Vibe-Trading state.",
                    source,
                )
                continue
            if _merge_children(source, destination):
                moved.append((source, destination))
                logger.info("Migrated %s -> %s", source, destination)
            _remove_empty_source(source)
        except OSError:
            logger.warning("Migrating %s failed; continuing.", source, exc_info=True)
    return moved
