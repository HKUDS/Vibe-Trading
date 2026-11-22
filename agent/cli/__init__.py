"""Vibe-Trading console entry point."""
from __future__ import annotations

import sys
from pathlib import Path

_package_root = str(Path(__file__).resolve().parents[1])
if not sys.path or sys.path[0] != _package_root:
    sys.path.insert(0, _package_root)

from cli.main import main  # noqa: E402

__all__ = ["main"]
