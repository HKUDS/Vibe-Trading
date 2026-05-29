"""Single source of truth for the CLI version string.

Reads ``vibe-trading-ai``'s installed package metadata when available
(``pip install -e .`` is enough). Falls back to the static constant
below for un-installed checkouts (e.g. running straight from a clone
with ``PYTHONPATH=agent``).

Keep the fallback in sync with ``pyproject.toml`` ``[project] version``.
"""

from __future__ import annotations

from typing import Final

try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    try:
        __version__: Final[str] = _pkg_version("vibe-trading-ai")
    except PackageNotFoundError:
        __version__ = "0.1.8"
except ImportError:  # pragma: no cover — importlib.metadata is stdlib on 3.8+
    __version__ = "0.1.8"


__all__ = ["__version__"]
