"""``/comps`` — Comparable company analysis."""

from __future__ import annotations

from typing import Any

from .runner import run_playbook


def run(ctx: Any = None, *args: str) -> int:
    """Render or dispatch the ``/comps`` playbook.

    Args:
        ctx: Interactive context supplying pending_prompt.
        *args: Raw slash-command arguments.

    Returns:
        Zero after displaying the playbook card, queuing a turn, or printing the prompt.
    """
    return run_playbook("comps", ctx, *args)


__all__ = ["run"]
