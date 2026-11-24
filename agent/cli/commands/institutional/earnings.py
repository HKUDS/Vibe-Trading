"""``/earnings`` — Earnings review."""

from __future__ import annotations

from typing import Any

from .runner import run_playbook


def run(ctx: Any = None, *args: str) -> int:
    """Render or dispatch the ``/earnings`` playbook."""
    return run_playbook("earnings", ctx, *args)


__all__ = ["run"]
