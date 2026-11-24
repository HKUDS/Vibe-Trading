"""``/dcf`` — Discounted cash flow valuation."""

from __future__ import annotations

from typing import Any

from .runner import run_playbook


def run(ctx: Any = None, *args: str) -> int:
    """Render or dispatch the ``/dcf`` playbook."""
    return run_playbook("dcf", ctx, *args)


__all__ = ["run"]
