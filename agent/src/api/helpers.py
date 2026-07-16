"""Path constants, dotenv I/O, SPA deep-link middleware, and path-parameter validation."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import FileResponse

from src.api._compat import host_attr as _host_attr


# ============================================================================
# Path constants
# ============================================================================

# helpers.py lives at agent/src/api/helpers.py — 4 levels up to Vibe-Trading/.
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent  # agent/

# User data dir: single source of truth for CLI + Web UI (pip install safe).
# Never write secrets or run artifacts into site-packages.
_USER_DATA_DIR = Path.home() / ".vibe-trading"
_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

RUNS_DIR = _USER_DATA_DIR / "runs"
SESSIONS_DIR = _USER_DATA_DIR / "sessions"
UPLOADS_DIR = _USER_DATA_DIR / "uploads"
AGENT_DIR = _AGENT_DIR
# Always use ~/.vibe-trading/.env (same as CLI / providers.llm). One-shot migrate
# from legacy agent/.env or site-packages/.env when home file is missing.
_HOME_ENV_PATH = _USER_DATA_DIR / ".env"
LEGACY_ENV_PATH = _LEGACY_ENV_PATH = AGENT_DIR / ".env"
if not _HOME_ENV_PATH.exists() and _LEGACY_ENV_PATH.exists():
    try:
        _HOME_ENV_PATH.write_text(_LEGACY_ENV_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        _HOME_ENV_PATH.chmod(0o600)
    except OSError:
        pass
ENV_PATH = _HOME_ENV_PATH
ENV_EXAMPLE_PATH = AGENT_DIR / ".env.example"

for _d in (RUNS_DIR, SESSIONS_DIR, UPLOADS_DIR):
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


# ============================================================================
# SPA deep-link fallback
# ============================================================================

_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent.parent / "frontend" / "dist"
_SPA_HTML_EXACT_PATHS: frozenset[str] = frozenset({"/correlation"})
_SPA_HTML_PATH_REGEX: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/runs/[^/]+/?$"),
)


def _is_spa_html_route(path: str) -> bool:
    """Return True when *path* corresponds to a frontend SPA page that shadows
    an API endpoint and should fall back to ``index.html`` on browser
    navigation."""
    if path in _SPA_HTML_EXACT_PATHS:
        return True
    return any(pattern.match(path) for pattern in _SPA_HTML_PATH_REGEX)


async def _spa_html_deep_link_fallback(request: Request, call_next):
    """Serve ``frontend/dist/index.html`` when a browser navigates directly to
    an SPA path that also exists as an API endpoint."""
    if request.method == "GET":
        accept = request.headers.get("accept", "")
        if "text/html" in accept and _is_spa_html_route(request.url.path):
            index = _FRONTEND_DIST / "index.html"
            if index.exists():
                return FileResponse(str(index))
    return await call_next(request)


# ============================================================================
# Dotenv helpers
# ============================================================================


def _atomic_write_secret(path: Path, content: str) -> None:
    """Write *content* to *path* atomically with 0600 permissions.

    The file holds provider API keys, so a crash mid-write must never leave a
    half-written or world-readable secret. The primary path writes to a sibling
    temp file (created 0600 by ``mkstemp``) and ``os.replace``s it onto the
    target — an atomic swap on the same filesystem.

    Fallback: when the parent directory is read-only (the ``.env`` is
    bind-mounted into a container whose rootfs is ``read_only: true``, so no
    sibling temp file can be created) the swap is impossible. There we write in
    place, still enforcing 0600; atomicity is sacrificed for that one edge but
    the secret still persists and stays owner-only.
    """
    data = content.encode("utf-8")
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.", suffix=".tmp")
    except OSError:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return
    try:
        os.write(fd, data)
        # ``os.fchmod`` is unavailable on Windows.  Keep descriptor-level
        # permission hardening on platforms that support it, then use the
        # portable path-based best effort after the descriptor is closed.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        # Windows ACLs govern effective access and chmod may be unsupported
        # or map only to the read-only flag.
        pass
    try:
        os.replace(tmp, path)
    except BaseException:
        # Never leave a stray temp file holding the secret behind.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _ensure_agent_env_file(path: Path | None = None) -> Path:
    """Ensure ``~/.vibe-trading/.env`` exists (CLI + Web UI shared config)."""
    # Always materialize the home path so Settings writes do not land in
    # site-packages under a pip install.
    env_path = path or _HOME_ENV_PATH
    env_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not env_path.exists():
        # Legacy migration only applies to the primary home .env, not to
        # arbitrary paths (e.g. test temp dirs) — we must not copy the
        # real ~/.vibe-trading/.env into test targets.
        if env_path == _HOME_ENV_PATH:
            legacy = _host_attr("ENV_PATH", ENV_PATH)
            if legacy != env_path and Path(legacy).exists():
                try:
                    _atomic_write_secret(env_path, Path(legacy).read_text(encoding="utf-8"))
                except OSError:
                    _atomic_write_secret(env_path, "# Created by Vibe-Trading Web UI settings.\n")
                return env_path
        _atomic_write_secret(env_path, "# Created by Vibe-Trading Web UI settings.\n")
    return env_path


def _strip_env_value(value: str) -> str:
    """Remove basic dotenv quotes and inline comments."""
    value = value.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def _read_env_values(path: Path) -> Dict[str, str]:
    """Read active KEY=value entries from a dotenv file."""
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _strip_env_value(value)
    return values


def _project_relative_path(path: Path) -> str:
    """Return a display path without leaking an absolute home directory path."""
    try:
        rel = path.resolve().relative_to(_USER_DATA_DIR.resolve()).as_posix()
        return f"~/.vibe-trading/{rel}" if rel != "." else "~/.vibe-trading"
    except ValueError:
        pass
    try:
        return path.resolve().relative_to(AGENT_DIR.parent.resolve()).as_posix()
    except ValueError:
        return path.name


def _format_env_value(value: str) -> str:
    """Format a dotenv value without allowing multiline injection."""
    if "\n" in value or "\r" in value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Environment values cannot contain newlines",
        )
    value = value.strip()
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or "#" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _write_env_values(
    path: Path,
    updates: Dict[str, str],
    *,
    remove_keys: Optional[set[str]] = None,
) -> None:
    """Upsert active dotenv values while preserving comments and ordering.

    ``remove_keys`` deletes matching *active* (non-comment) lines outright, so a
    stale credential from a previous provider cannot survive a switch and get
    resurrected on restart. Keys in ``updates`` always win over ``remove_keys``.
    """
    remove_keys = {k for k in (remove_keys or set()) if k not in updates}
    _ensure_agent_env_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    for index, raw in enumerate(lines):
        stripped = raw.lstrip()
        is_comment = stripped.startswith("#")
        candidate = stripped[1:].lstrip() if is_comment else stripped
        if "=" not in candidate:
            continue
        key = candidate.split("=", 1)[0].strip()
        if key in updates and key not in seen:
            lines[index] = f"{key}={_format_env_value(updates[key])}"
            seen.add(key)
    missing = [key for key in updates if key not in seen]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Updated from Web UI")
        for key in missing:
            lines.append(f"{key}={_format_env_value(updates[key])}")
    if remove_keys:
        kept: list[str] = []
        for raw in lines:
            stripped = raw.lstrip()
            if not stripped.startswith("#") and "=" in stripped:
                if stripped.split("=", 1)[0].strip() in remove_keys:
                    continue
            kept.append(raw)
        lines = kept
    _atomic_write_secret(path, "\n".join(lines) + "\n")


# Heuristic placeholder detector — matches lowercased, bracket-stripped values.
_PLACEHOLDER_HINT_RE = re.compile(
    r"""
      your[-_\s]?(key|token|api|secret|value)   # your-key, your_token, your api
    | change[-_\s]?me                            # change-me, changeme
    | replace[-_\s]?me                           # replace-me
    | placeholder
    | ^x+$                                       # whole value is x's
    | xxx                                        # embedded xxx (sk-xxx)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _is_configured_secret(value: str, placeholders: set[str]) -> bool:
    """Return True when a secret is set and not a documented placeholder."""
    normalized = value.strip().strip('"').strip("'").strip()
    # Peel off angle-bracket wrappers like ``<your-key>`` so the heuristic can
    # inspect the inner token.
    normalized = normalized.strip("<>").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered in {p.lower() for p in placeholders}:
        return False
    # Catch common placeholder shapes not in the documented set, e.g.
    # ``your-key-here``, ``<your-api-key>``, ``change-me``, ``xxxxx``.
    if _PLACEHOLDER_HINT_RE.search(lowered):
        return False
    return True


def _coerce_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ============================================================================
# Path-parameter validation
# ============================================================================

_SAFE_PATH_PARAM_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def _validate_path_param(value: str, kind: str) -> None:
    """Reject path parameters that could escape the parent directory."""
    if not _SAFE_PATH_PARAM_RE.fullmatch(value or ""):
        raise HTTPException(status_code=400, detail=f"invalid {kind}")
