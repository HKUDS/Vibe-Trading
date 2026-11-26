"""Path safety helpers used by file-access tools.

Three helpers, three threat models:

* `safe_path(p, workdir)` — tool-controlled sandbox. Resolves `p` under
  `workdir` and rejects any escape. Used by `read_file` / `write_file` /
  `edit_file` where the LLM must stay inside the current run dir.

* `safe_user_path(p)` — user-supplied broker files. Accepts files only under
  explicit import roots, not the whole home directory or project tree.

* `safe_document_path(p)` — document-reader inputs. Uses the same import-root
  boundary as `safe_user_path()`.

A file policy scoped to a spawned child's workspace replaces its configured
write roots for that child.

All helpers raise ``ValueError`` on rejection — callers already expect this.
"""

from __future__ import annotations

import json
from pathlib import Path

from dataclasses import dataclass

from src.config.env_schema import APIConfig

# Runtime records and copied evidence inside a run workspace: never a task output.
RUNTIME_DIRS = frozenset({"upstream", "tool-results", "context-results", "__pycache__"})
RUNTIME_FILES = frozenset({
    "req.json", "state.json", "llm_usage.json", "run_manifest.json", "thread.jsonl",
    "artifacts/identity_evidence.json",
})


def is_runtime_path(relative: str) -> bool:
    """Check whether a workspace-relative path is runtime state or hidden.

    Args:
        relative: POSIX path relative to a run workspace.

    Returns:
        True for a runtime record, a path under a runtime directory, or any dot-named part.
    """
    return relative in RUNTIME_FILES or any(
        part in RUNTIME_DIRS or part.startswith(".") for part in relative.split("/")
    )


_ALLOWED_FILE_ROOTS_ENV = "VIBE_TRADING_ALLOWED_FILE_ROOTS"
_ALLOWED_RUN_ROOTS_ENV = "VIBE_TRADING_ALLOWED_RUN_ROOTS"
_ALLOWED_WRITE_ROOTS_ENV = "VIBE_TRADING_ALLOWED_WRITE_ROOTS"

# MCP clients spawn the server themselves, so a shell export never reaches it.
_ENV_SCOPE_HINT = (
    "Put it in the runtime .env (read by both the web and MCP servers) or "
    "in the MCP client's server env block — exporting it in a shell does not "
    "reach a spawned MCP server."
)

# The env var that widens each resolve_safe_path purpose; rejections name it
# so the escape hatch is discoverable from the error itself.
_PURPOSE_ENV_HINTS = {
    "write": _ALLOWED_WRITE_ROOTS_ENV,
    "file": _ALLOWED_FILE_ROOTS_ENV,
}


def _describe_roots(roots: list[Path]) -> str:
    """Render allowed roots as an indented list for a rejection message."""
    return "Allowed roots:\n" + "\n".join(f"  - {root}" for root in roots)


def _rejects_unc(p: str) -> None:
    """Raise ValueError if `p` starts with a UNC share prefix."""
    if p.startswith("\\\\") or p.startswith("//"):
        raise ValueError(f"UNC paths are not allowed: {p!r}")


def _contained_path(candidate: Path, root: Path) -> Path | None:
    """Resolve containment using filesystem identity for existing root aliases.

    A case-insensitive filesystem can resolve ``dropbox`` and ``Dropbox`` to
    the same directory while Path.resolve preserves the spelling. Only accept
    such an alias when samefile proves it; never case-fold authorization paths.
    """
    root = root.resolve()
    if candidate.is_relative_to(root):
        return candidate
    for ancestor in (candidate, *candidate.parents):
        try:
            if ancestor.samefile(root):
                return root / candidate.relative_to(ancestor)
        except OSError:
            continue
    return None


def safe_path(p: str, workdir: Path) -> Path:
    """Resolve `p` under `workdir` and ensure it stays inside.

    Args:
        p: User-supplied path (relative or absolute).  ``~`` expansion is
            supported so callers can pass home-relative paths.
        workdir: Workspace root. `p` must resolve to a location inside.

    Returns:
        Absolute resolved path inside `workdir`.

    Raises:
        ValueError: If `p` uses a UNC share, or its resolved form escapes
            `workdir`. Callers surface this back to the LLM as a tool error.
    """
    _rejects_unc(p)
    base = Path(workdir).resolve()
    # Expand ~ so home-relative paths (e.g. ~/.vibe-trading/scripts/foo.py)
    # resolve correctly instead of being treated as literal directory names.
    expanded = Path(p).expanduser()
    if expanded.is_absolute():
        resolved = expanded.resolve()
    else:
        resolved = (base / p).resolve()
    contained = _contained_path(resolved, base)
    if contained is None:
        raise ValueError(f"Path {p!r} escapes the workspace root")
    return contained


def _agent_root() -> Path:
    """Return the agent package root."""
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class FileRoots:
    """Operator-configured additions to the built-in containment roots."""

    reads: str
    writes: str
    runs: str
    runtime_root: Path
    swarm_runs_root: Path
    home: Path
    cwd: Path
    confined_writes: Path | None = None

    @classmethod
    def from_config(cls, config: APIConfig) -> FileRoots:
        """Capture root declarations from a trusted host configuration."""
        from src.config.paths import get_runtime_root, get_swarm_runs_dir

        return cls(
            runtime_root=get_runtime_root(),
            swarm_runs_root=get_swarm_runs_dir(),
            home=Path.home(),
            cwd=Path.cwd(),
            reads=config.vibe_trading_allowed_file_roots,
            writes=config.vibe_trading_allowed_write_roots,
            runs=config.vibe_trading_allowed_run_roots,
        )


def _configured_roots(raw: str) -> list[Path]:
    roots: list[Path] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        _rejects_unc(item)
        roots.append(Path(item).expanduser().resolve())
    return roots


def _default_file_roots(roots: FileRoots) -> list[Path]:
    """Return default roots for uploaded/imported user files."""
    cwd, home, runtime_root = roots.cwd, roots.home, roots.runtime_root
    agent_root = _agent_root()
    return [
        agent_root / "uploads",
        agent_root / "runs",
        cwd / "uploads",
        cwd / "data",
        home / ".vibe-trading" / "uploads",
        home / ".vibe-trading" / "imports",
        runtime_root / "uploads",
        runtime_root / "runs",
        runtime_root / "imports",
    ]


def _default_run_roots(roots: FileRoots) -> list[Path]:
    """Return default roots for generated backtest/tool run directories."""
    cwd, home, runtime_root = roots.cwd, roots.home, roots.runtime_root
    agent_root = _agent_root()
    return [
        agent_root / "runs",
        agent_root / ".swarm" / "runs",  # un-migrated legacy swarm runs
        roots.swarm_runs_root,
        cwd / "runs",
        home / ".vibe-trading" / "shadow_runs",
        home / ".vibe-trading" / "runs",
        runtime_root / "shadow_runs",
        runtime_root / "runs",
    ]


def allowed_file_roots(*, roots: FileRoots) -> list[Path]:
    """Return all roots allowed for document and broker-file reads."""
    return list(dict.fromkeys(root.resolve() for root in [*_default_file_roots(roots), *_configured_roots(roots.reads)]))


def allowed_write_roots(*, roots: FileRoots) -> list[Path]:
    """Return all roots allowed for file writes and edits.

    Child tools receive only the workspace specified by their file policy.
    """
    if roots.confined_writes is not None:
        return [roots.confined_writes]
    configured = _configured_roots(roots.writes)

    cwd, home, runtime_root = roots.cwd, roots.home, roots.runtime_root
    agent_root = _agent_root()
    defaults = [
        agent_root / "uploads",
        agent_root / "runs",
        cwd / "uploads",
        home / ".vibe-trading" / "uploads",
        home / ".vibe-trading" / "runs",
        runtime_root / "uploads",
        runtime_root / "runs",
    ]

    return list(dict.fromkeys(root.resolve() for root in [*defaults, *configured]))


def _fallback_candidate(file_path: str, base: Path) -> Path:
    """Resolve a fallback against the supplied run directory, not the CWD."""
    candidate = Path(file_path).expanduser()
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def resolve_safe_path(
    file_path: str,
    run_dir: str | None,
    allowed_roots: list[Path],
    *,
    roots: FileRoots,
    purpose: str = "workspace",
) -> Path:
    """Resolve a file path under run_dir with fallback to allowed roots.

    Args:
        file_path: Relative or absolute path (supports tilde expansion).
        run_dir: Optional run directory to resolve against.
        allowed_roots: List of fallback allowed root directories.
        purpose: Context name for error messages.

    Returns:
        Absolute resolved Path.

    Raises:
        ValueError: If path cannot be resolved or escapes boundaries.
    """
    _rejects_unc(file_path)

    hint_env = _PURPOSE_ENV_HINTS.get(purpose)
    if purpose == "write" and roots.confined_writes is not None:
        # No setting widens a confinement, so none is suggested.
        hint_env = None
    hint = f"\nSet {hint_env} to add a directory. {_ENV_SCOPE_HINT}" if hint_env else ""

    # Try resolving against run_dir if provided
    if run_dir:
        # A rejected network path must never enter the fallback resolver.
        _rejects_unc(run_dir)
        try:
            run_root = safe_run_dir(run_dir, roots=roots)
        except ValueError as exc:
            # If safe_run_dir fails, check if the path is in allowed_roots first
            candidate = _fallback_candidate(file_path, Path(run_dir).expanduser())
            for root in allowed_roots:
                contained = _contained_path(candidate, root)
                if contained is not None:
                    return contained
            raise exc

        try:
            return safe_path(file_path, run_root)
        except ValueError as exc:
            # Fallback to allowed roots if safe_path containment fails
            candidate = _fallback_candidate(file_path, run_root)
            for root in allowed_roots:
                contained = _contained_path(candidate, root)
                if contained is not None:
                    return contained
            raise ValueError(
                f"Path {file_path!r} escapes run_dir {run_dir!r} and is not in allowed {purpose} roots.\n"
                f"{_describe_roots(allowed_roots)}{hint}"
            ) from exc

    # If no run_dir, path must resolve inside one of the allowed roots
    candidate = Path(file_path).expanduser().resolve()
    for root in allowed_roots:
        contained = _contained_path(candidate, root)
        if contained is not None:
            return contained

    raise ValueError(
        f"run_dir is required to write/edit {file_path!r}, or the path must resolve inside allowed {purpose} roots.\n"
        f"{_describe_roots(allowed_roots)}{hint}"
    )


OUTSIDE_WRITE_ROOTS = "outside_write_roots"
OUTSIDE_READABLE_ROOTS = "outside_readable_roots"


def resolve_output_dir(
    output_dir: str, run_dir: str | None, *, roots: FileRoots, tool_roots: tuple[Path, ...] = (),
) -> Path:
    """Resolve a caller-chosen output directory the way write_file resolves a path.

    Args:
        output_dir: Relative (to ``run_dir``) or absolute directory, ``~`` expanded.
        run_dir: The run directory of the call, if it has one.
        roots: File roots authorized by the host.
        tool_roots: The tool's own output roots; ignored when writes are
            confined to a workspace.

    Returns:
        The resolved directory inside ``run_dir`` or an allowed write root.

    Raises:
        ValueError: The directory resolves outside ``run_dir`` and every
            allowed root; the message lists the allowed roots.
    """
    allowed = allowed_write_roots(roots=roots)
    if roots.confined_writes is None:
        allowed = list(dict.fromkeys([*allowed, *(root.resolve() for root in tool_roots)]))
    return resolve_safe_path(output_dir, run_dir, allowed, roots=roots, purpose="write")


def _allowed_run_roots(*, roots: FileRoots) -> list[Path]:
    """Return all roots allowed for run_dir-based tools."""
    configured = _configured_roots(roots.runs)

    return list(dict.fromkeys(root.resolve() for root in [*_default_run_roots(roots), *configured]))


def _import_candidate(p: str, *, roots: FileRoots) -> Path:
    """Return the filesystem candidate for an import path.

    Browser uploads are exposed as ``uploads/<name>`` so the UI never needs
    a local absolute path. Resolve that handle back to the user-level upload
    root before enforcing the allowlist.
    """
    candidate = Path(p).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()

    parts = candidate.parts
    if parts and parts[0] == "uploads":
        return ((roots.runtime_root / "uploads") / Path(*parts[1:])).resolve()
    if len(parts) >= 2 and parts[0] == "agent" and parts[1] == "uploads":
        return ((roots.runtime_root / "uploads") / Path(*parts[2:])).resolve()
    return (roots.cwd / candidate).resolve()


def _safe_import_path(p: str, *, roots: FileRoots, purpose: str) -> Path:
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
    resolved = _import_candidate(p, roots=roots)

    roots = allowed_file_roots(roots=roots)
    for root in roots:
        if resolved.is_relative_to(root):
            return resolved

    raise ValueError(
        f"Path {p!r} is outside allowed {purpose} roots.\n"
        f"{_describe_roots(roots)}\n"
        f"Set {_ALLOWED_FILE_ROOTS_ENV} to add an import directory. {_ENV_SCOPE_HINT}"
    )


def safe_user_path(p: str, *, roots: FileRoots) -> Path:
    """Validate a user-supplied broker/export file path.

    Args:
        p: User-supplied path. `~` expansion is supported.

    Returns:
        Absolute resolved path inside an allowed import root.

    Raises:
        ValueError: If `p` is a UNC share or resolves outside all allowed
            import roots.
    """
    return _safe_import_path(p, roots=roots, purpose="user-file")


def safe_document_path(p: str, *, roots: FileRoots) -> Path:
    """Validate a document-reader file path.

    Args:
        p: User-supplied document path. `~` expansion is supported.

    Returns:
        Absolute resolved path inside an allowed import root.

    Raises:
        ValueError: If `p` is a UNC share or resolves outside all allowed
            import roots.
    """
    return _safe_import_path(p, roots=roots, purpose="document")


def safe_run_dir(p: str, *, roots: FileRoots) -> Path:
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

    roots = _allowed_run_roots(roots=roots)
    for root in roots:
        if resolved.is_relative_to(root):
            return resolved

    raise ValueError(
        f"run_dir {p!r} is outside allowed run roots.\n"
        f"{_describe_roots(roots)}\n"
        f"Set {_ALLOWED_RUN_ROOTS_ENV} to add a run directory. {_ENV_SCOPE_HINT}"
    )


def session_workspace_for_run(run_dir: str | Path, *, roots: FileRoots) -> Path | None:
    """Return the owning session workspace for a generated run directory.

    The session id is read from the run's persisted request envelope. This
    keeps workspace access scoped to the session that owns the run and avoids
    exposing every session workspace as a global file root.
    """
    try:
        run = safe_run_dir(str(run_dir), roots=roots)
        request = run / "req.json"
        payload = json.loads(request.read_text(encoding="utf-8"))
        context = payload.get("context") if isinstance(payload, dict) else None
        context = context if isinstance(context, dict) else payload
        session_id = context.get("session_id") if isinstance(context, dict) else None
        if not isinstance(session_id, str) or not session_id:
            return None
        declared = context.get("session_workspace") if isinstance(context, dict) else None
        if isinstance(declared, str) and declared:
            workspace = Path(declared).expanduser().resolve()
            if workspace.name == "workspace" and workspace.is_dir():
                return workspace
        sessions_root = (roots.runtime_root / "sessions").resolve()
        workspace = (sessions_root / session_id / "workspace").resolve()
        if not workspace.is_relative_to(sessions_root):
            return None
        return workspace
    except (OSError, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        return None


def safe_run_id(run_id: str, *, roots: FileRoots) -> Path:
    """Resolve a bare run id to an existing allowed run directory.

    Args:
        run_id: Bare run directory name, not a path.

    Returns:
        Existing run directory under one of the allowed run roots.

    Raises:
        ValueError: If the run id is empty, path-shaped, or not found.
    """
    _rejects_unc(run_id)
    candidate = Path(run_id)
    if (
        not run_id.strip()
        or candidate.is_absolute()
        or len(candidate.parts) != 1
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError(f"run_id {run_id!r} must be a bare run directory name")

    roots = _allowed_run_roots(roots=roots)
    for root in roots:
        resolved = (root / candidate.name).resolve()
        if resolved.is_relative_to(root) and resolved.is_dir():
            return resolved

    raise ValueError(
        f"run_id {run_id!r} was not found under allowed run roots.\n"
        f"{_describe_roots(roots)}"
    )
