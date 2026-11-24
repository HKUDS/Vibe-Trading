"""``/attrib`` — Brinson-Fachler performance attribution."""

from __future__ import annotations

from typing import Any

from .runner import run_playbook


def run(ctx: Any = None, *args: str) -> int:
    """Render or dispatch the ``/attrib`` playbook."""
    return run_playbook("attrib", ctx, *args)


__all__ = ["run"]
