"""Configuration and path-safety helpers for the Taiwan extension."""

from __future__ import annotations

import os
import re
from pathlib import Path


class PathSafetyError(ValueError):
    """Raised when a configured path escapes its permitted root."""


_SAFE_SNAPSHOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def data_root() -> Path:
    """Return the configured state root, without creating it."""
    configured = os.getenv("TW_QUANT_DATA_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve(strict=False)
    return (Path.home() / ".vibe-trading" / "tw-quant").resolve(strict=False)


def _resolve_configured_path(value: str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=False)


def db_path() -> Path:
    """Return the configured DuckDB path, relative to ``data_root`` if needed."""
    configured = os.getenv("TW_QUANT_DB_PATH", "").strip()
    return _resolve_configured_path(configured, base=data_root()) if configured else data_root() / "tw_quant.duckdb"


def snapshot_root() -> Path:
    """Return the configured immutable snapshot root."""
    configured = os.getenv("TW_QUANT_SNAPSHOT_ROOT", "").strip()
    return _resolve_configured_path(configured, base=data_root()) if configured else data_root() / "snapshots"


def ensure_within_root(path: Path, root: Path, *, allow_missing: bool = True) -> Path:
    """Resolve *path* and reject traversal or symlink escape from *root*.

    ``Path.resolve(strict=False)`` resolves existing symlinks while retaining
    missing suffixes, which gives the same check for both new and existing
    snapshot paths.
    """
    root_resolved = root.expanduser().resolve(strict=False)
    path_resolved = path.expanduser().resolve(strict=False)
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PathSafetyError(f"path escapes allowed root: {path}") from exc
    if not allow_missing and not path_resolved.exists():
        raise FileNotFoundError(path_resolved)
    return path_resolved


def ensure_data_path(path: Path, *, allow_missing: bool = True) -> Path:
    """Validate a state path against the configured data root."""
    return ensure_within_root(path, data_root(), allow_missing=allow_missing)


def ensure_snapshot_id(snapshot_id: str) -> str:
    """Validate a snapshot identifier as a single safe path segment."""
    value = str(snapshot_id).strip()
    if not value or not _SAFE_SNAPSHOT_ID.fullmatch(value) or value in {".", ".."}:
        raise PathSafetyError(f"invalid snapshot_id: {snapshot_id!r}")
    return value

