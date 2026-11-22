"""Vibe-Trading CLI package.

The console entry point is :func:`main`. Interactive routing lives in
:mod:`cli.main`, parser registration is assembled by
:mod:`cli.commands.parser`, and command handlers live in the owning command
modules plus the shared runtime helpers.

``cli._legacy`` remains an import-compatible bridge for older integrations.
It contains no command implementation. New code should import a handler from
its command family module.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
from typing import Any as _Any

_package_root = str(_Path(__file__).resolve().parents[1])
if not _sys.path or _sys.path[0] != _package_root:
    _sys.path.insert(0, _package_root)

from cli import _legacy as _legacy  # noqa: E402
from cli.main import main  # noqa: E402

# These names are retained because they are configuration seams used by
# existing integrations. Command functions are resolved lazily below so they
# are no longer public package re-exports in ``dir(cli)`` or ``__all__``.
_LEGACY_SYNCED_GLOBALS: tuple[str, ...] = (
    "_INIT_ENV_PATH",
    "AGENT_DIR",
    "RUNS_DIR",
    "SWARM_DIR",
    "SESSIONS_DIR",
    "UPLOADS_DIR",
    "_PROVIDER_CHOICES",
)
for _name in _LEGACY_SYNCED_GLOBALS:
    if hasattr(_legacy, _name):
        globals()[_name] = getattr(_legacy, _name)

from rich.prompt import Confirm, IntPrompt, Prompt  # noqa: E402


def _sync_legacy_test_overrides() -> None:
    """Mirror package-level compatibility overrides into the runtime bridge."""
    for name in _LEGACY_SYNCED_GLOBALS:
        if name in globals() and getattr(_legacy, name, None) is not globals()[name]:
            setattr(_legacy, name, globals()[name])


def __getattr__(name: str) -> _Any:
    """Resolve old command imports without publishing a command namespace."""
    if hasattr(_legacy, name):
        value = getattr(_legacy, name)
        if callable(value):
            def wrapper(*args: _Any, **kwargs: _Any) -> _Any:
                _sync_legacy_test_overrides()
                return getattr(_legacy, name)(*args, **kwargs)
            wrapper.__name__ = name
            wrapper.__module__ = __name__
            return wrapper
        return value
    raise AttributeError(name)


__all__ = ["main"]
