"""Single source of truth for the CLI version string."""

from __future__ import annotations

from typing import Final


def _version_from_pyproject() -> str:
    """Read ``[project] version`` from the repo's ``pyproject.toml``."""
    import tomllib
    from pathlib import Path

    # agent/cli/_version.py -> parents[2] is the repo root holding pyproject.toml.
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"


try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    try:
        __version__: Final[str] = _pkg_version("vibe-trading-ai")
    except PackageNotFoundError:
        __version__ = _version_from_pyproject()
except ImportError:  # pragma: no cover — importlib.metadata is stdlib on 3.8+
    __version__ = _version_from_pyproject()


__all__ = ["__version__"]
