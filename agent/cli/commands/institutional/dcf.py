"""``/dcf`` — Discounted cash flow valuation.

Thin handler: the execution skeleton, the worked numeric example and the
missing-data policy all live in :mod:`.playbooks`, and the render/dispatch
logic in :mod:`.runner`. Running it produces value per share, the terminal-
value share of enterprise value, an exit-multiple cross-check and a WACC x g
sensitivity grid.
"""

from __future__ import annotations

from typing import Any

from .runner import run_playbook


def run(ctx: Any = None, *args: str) -> int:
    """Render or dispatch the ``/dcf`` playbook.

    Args:
        ctx: Interactive context supplying ``pending_prompt``.
        *args: Raw slash-command arguments.

    Returns:
        Process-style exit code; ``0`` on every user-facing path.
    """
    return run_playbook("dcf", ctx, *args)


__all__ = ["run"]
