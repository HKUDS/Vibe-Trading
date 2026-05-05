"""Path safety helpers used by file-access tools.

Three helpers, three threat models:

* `safe_path(p, workdir)` — tool-controlled sandbox. Resolves `p` under
  `workdir` and rejects any escape. Used by `read_file` / `write_file` /
  `edit_file` where the LLM must stay inside the current run dir.

* `safe_user_path(p)` — user-supplied broker files. Accepts files only under
  explicit import roots, not the whole home directory or project tree.

* `safe_document_path(p)` — document-reader inputs. Uses the same import-root
  boundary as `safe_user_path()`.

All helpers raise ``ValueError`` on rejection — callers already expect this.
"""

from __future__ import annotations

import os
from pathlib import Path

_ALLOWED_FILE_ROOTS_ENV = "VIBE_TRADING_ALLOWED_FILE_ROOTS"
_ALLOWED_RUN_ROOTS_ENV = "VIBE_TRADING_ALLOWED_RUN_ROOTS"


def _rejects_unc(p: str) -> None:
    """Raise ValueError if `p` starts with a UNC share prefix."""
    if p.startswith("\\\\") or p.startswith("//"):
        raise ValueError(f"UNC paths are not allowed: {p!r}")


def safe_path(p: str, workdir: Path) -> Path:
    """Resolve `p` under `workdir` and ensure it stays inside.

    Args:
        p: User-supplied path (relative or absolute).
        workdir: Workspace root. `p` must resolve to a location inside.

    Returns:
        Absolute resolved path inside `workdir`.

    Raises:
        ValueError: If `p` uses a UNC share, or its resolved form escapes
            `workdir`. Callers surface this back to the LLM as a tool error.
    """
    _rejects_unc(p)
    base = Path(workdir).resolve()
    resolved = (base / p).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Path {p!r} escapes workspace {base}") from exc
    return resolved


def _agent_root() -> Path:
    """Return the agent package root."""
    return Path(__file__).resolve().parents[2]


def _configured_file_roots() -> list[Path]:
    """Return file roots configured through the environment."""
    raw = os.getenv(_ALLOWED_FILE_ROOTS_ENV, "")
    roots: list[Path] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        _rejects_unc(item)
        roots.append(Path(item).expanduser().resolve())
    return roots


def _default_file_roots() -> list[Path]:
    """Return default roots for uploaded/imported user files."""
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    agent_root = _agent_root()
    return [
        agent_root / "uploads",
        agent_root / "runs",
        cwd / "uploads",
        cwd / "data",
        home / ".vibe-trading" / "uploads",
        home / ".vibe-trading" / "imports",
    ]


def _default_run_roots() -> list[Path]:
    """Return default roots for generated backtest/tool run directories."""
    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    agent_root = _agent_root()
    return [
        agent_root / "runs",
        cwd / "runs",
        home / ".vibe-trading" / "shadow_runs",
        agent_root / ".swarm",        # Swarm worker artifact directories
        cwd / ".swarm",               # Local swarm runs (outside agent dir)
    ]


def _allowed_file_roots() -> list[Path]:
    """Return all roots allowed for document and broker-file reads."""
    roots: list[Path] = []
    for root in [*_default_file_roots(), *_configured_file_roots()]:
        resolved = root.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _allowed_run_roots() -> list[Path]:
    """Return all roots allowed for run_dir-based tools."""
    raw = os.getenv(_ALLOWED_RUN_ROOTS_ENV, "")
    configured: list[Path] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        _rejects_unc(item)
        configured.append(Path(item).expanduser().resolve())

    roots: list[Path] = []
    for root in [*_default_run_roots(), *configured]:
        resolved = root.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _safe_import_path(p: str, *, purpose: str) -> Path:
    """Validate a user-supplied path against explicit import roots.

    Args:
        p: User-supplied path. `~` expansion is supported.
        purpose: Human-readable purpose for error messages.

    Returns:
        Absolute resolved path inside an allowed import root.

    Raises:
        ValueError: If `p` is a UNC share or resolves outside all allowed
            import roots.
    """
    _rejects_unc(p)
    resolved = Path(p).expanduser().resolve()

    for root in _allowed_file_roots():
        if resolved.is_relative_to(root):
            return resolved

    raise ValueError(
        f"Path {p!r} is outside allowed {purpose} roots. "
        f"Set {_ALLOWED_FILE_ROOTS_ENV} to add an import directory."
    )


def safe_user_path(p: str) -> Path:
    """Validate a user-supplied broker/export file path.

    Args:
        p: User-supplied path. `~` expansion is supported.

    Returns:
        Absolute resolved path inside an allowed import root.

    Raises:
        ValueError: If `p` is a UNC share or resolves outside all allowed
            import roots.
    """
    return _safe_import_path(p, purpose="user-file")


def safe_document_path(p: str) -> Path:
    """Validate a document-reader file path.

    Args:
        p: User-supplied document path. `~` expansion is supported.

    Returns:
        Absolute resolved path inside an allowed import root.

    Raises:
        ValueError: If `p` is a UNC share or resolves outside all allowed
            import roots.
    """
    return _safe_import_path(p, purpose="document")


def safe_run_dir(p: str) -> Path:
    """Validate a run directory used by generated-code tools.

    Args:
        p: User/LLM-supplied run directory. `~` expansion is supported.

    Returns:
        Absolute resolved path inside an allowed run root.

    Raises:
        ValueError: If `p` is a UNC share or resolves outside all allowed run
            roots.
    """
    _rejects_unc(p)
    resolved = Path(p).expanduser().resolve()

    for root in _allowed_run_roots():
        if resolved.is_relative_to(root):
            return resolved

    raise ValueError(
        f"run_dir {p!r} is outside allowed run roots. "
        f"Set {_ALLOWED_RUN_ROOTS_ENV} to add a run directory."
    )
