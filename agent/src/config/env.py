"""Centralized environment-variable access for agent runtime code.

Application modules should import this accessor instead of reading os.environ
directly. Keeping environment reads inside src.config lets CI enforce a
single configuration boundary without changing the runtime contract.
"""

from __future__ import annotations

import os


def get_env(name: str, default: str | None = None) -> str | None:
    """Return one environment variable through the centralized config layer."""
    return os.environ.get(name, default)
