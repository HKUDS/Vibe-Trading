"""``/screen`` — Systematic idea screen."""

from __future__ import annotations

from typing import Any

from .runner import run_playbook


def run(ctx: Any = None, *args: str) -> int:
    """Render or dispatch the ``/screen`` playbook."""
    return run_playbook("screen", ctx, *args)


__all__ = ["run"]
