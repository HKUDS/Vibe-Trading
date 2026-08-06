"""``/memo`` — Investment memo.

Thin handler: the execution skeleton, the worked numeric example and the
missing-data policy all live in :mod:`.playbooks`, and the render/dispatch
logic in :mod:`.runner`. Running it produces thesis, variant view,
probability-weighted scenarios, falsifiable kill criteria and a monitoring
set.
"""

from __future__ import annotations

from typing import Any

from .runner import run_playbook


def run(ctx: Any = None, *args: str) -> int:
    """Render or dispatch the ``/memo`` playbook.

    Args:
        ctx: Interactive context supplying ``pending_prompt``.
        *args: Raw slash-command arguments.

    Returns:
        Process-style exit code; ``0`` on every user-facing path.
    """
    return run_playbook("memo", ctx, *args)


__all__ = ["run"]
