"""Routing block for specialist delegation, spliced into the system prompt.

Mirrors the ``strategy_discovery.guard`` fail-safe contract: the block is
emitted only when the delegate tool is actually registered and at least one
specialist definition loaded, and any error yields an empty string rather
than breaking prompt assembly. The main agent's routing policy lives here
because a delegation catalog the model cannot see does not route — the
single biggest production lesson behind this feature.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DELEGATE_TOOL_NAME = "delegate_to_specialist"

_POLICY = """**Specialist delegation** — for domain work below, call `delegate_to_specialist(specialist, task)` instead of doing the domain work yourself. Write `task` as a self-contained brief: the specialist cannot see this conversation, so include the objective, the expected output, constraints, and every input it needs (symbols, dates, statements, file paths). Its final message and artifact paths are the result — do not redo its work.
- Answer simple one-shot questions that need a single tool call directly; do not delegate them.
- Work outside every listed domain (local code, orchestration, order placement) stays with you.
- Order placement or cancellation is never delegated: no specialist holds write tools by construction.
Specialists:
"""


def specialist_routing_block(registry: Any) -> str:
    """Return the delegation policy + catalog when delegation is available.

    Args:
        registry: The run's tool registry (any object with ``get(name)``).

    Returns:
        The routing text with a leading blank line when the delegate tool is
        registered and the roster is non-empty; ``""`` otherwise or on any
        error (fail-safe omission, same contract as the strategy-discovery
        guard).
    """
    try:
        get = getattr(registry, "get", None)
        if not callable(get) or get(DELEGATE_TOOL_NAME) is None:
            return ""
        from src.specialists.loader import load_specialists

        specs = load_specialists()
        if not specs:
            return ""
        lines = [_POLICY]
        for spec in specs.values():
            lines.append(f"- `{spec.name}` — {spec.description}")
        return "\n\n" + "\n".join(lines) + "\n"
    except Exception:  # noqa: BLE001 — prompt assembly must never raise
        logger.debug("specialist routing block omitted", exc_info=True)
        return ""
