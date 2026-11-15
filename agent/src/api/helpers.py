"""Path constants, dotenv I/O, SPA deep-link middleware, and path-parameter validation."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from src.config.dotenv import (
    _atomic_write_secret as _atomic_write_secret,
    _dotenv_key as _dotenv_key,
    _ensure_agent_env_file as _ensure_agent_env_file,
    _format_env_value as _format_env_value,
    _read_env_values as _read_env_values,
    _strip_env_value as _strip_env_value,
    _write_env_values as _write_env_values,
)
from src.config.paths import get_runs_dir, get_sessions_dir, get_uploads_dir


# ============================================================================
# Path constants
# ============================================================================

# helpers.py lives at agent/src/api/helpers.py — 4 levels up to Vibe-Trading/.
# AGENT_DIR stays a code location; state dirs resolve under the user-level
# runtime root (#904).
_AGENT_DIR = Path(__file__).resolve().parent.parent.parent  # agent/

RUNS_DIR = get_runs_dir()
SESSIONS_DIR = get_sessions_dir()
UPLOADS_DIR = get_uploads_dir()
AGENT_DIR = _AGENT_DIR
ENV_PATH = Path.home() / ".vibe-trading" / ".env"
LEGACY_ENV_PATH = AGENT_DIR / ".env"
ENV_EXAMPLE_PATH = AGENT_DIR / ".env.example"


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


def _project_relative_path(path: Path) -> str:
    """Return a project-relative display path without leaking an absolute path."""
    if path == ENV_PATH:
        return "~/.vibe-trading/.env"
    try:
        return path.resolve().relative_to(AGENT_DIR.parent.resolve()).as_posix()
    except ValueError:
        return path.name


def _is_configured_secret(value: str, placeholders: set[str]) -> bool:
    """Return True when a secret is set and not a documented placeholder."""
    normalized = value.strip().strip('"').strip("'")
    if not normalized:
        return False
    return normalized.lower() not in {p.lower() for p in placeholders}


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
