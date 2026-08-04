"""Registration guard for the strategy-discovery tool trio.

This module is the single source of truth for the Strategy Discovery routing
text injected into the agent's Task-Routing prompt section, and for checking
whether the three read-only discovery tools are actually registered. It is
fail-safe by design: when any tool is missing (or the registry object does
not quack as expected) the routing block is omitted rather than advertising
tools the agent cannot call — the exact failure mode of the rejected #896.

The module must stay dependency-free: context builders import it eagerly, so
it may never pull in the facade, the store, or any heavy module.
"""

from __future__ import annotations

from typing import Any

#: The three read-only discovery tools. All three must be registered before
#: any routing text is emitted (atomic advertisement).
STRATEGY_DISCOVERY_TOOLS = (
    "list_strategies",
    "query_strategies",
    "get_strategy_evidence",
)

ROUTING_BLOCK: str = """**Strategy Discovery** — user asks what strategies exist, which fit a market regime (bear/bull/structural), or what state registered strategies are in:
1. `list_strategies()` — unified catalog across Alpha Zoo + SDM store
2. `query_strategies(regime=...)` — evidence-gated per-regime results; report trades, date coverage, breakeven and warnings verbatim; NEVER present insufficient or marginal evidence as a recommendation
3. `get_strategy_evidence(strategy_id=...)` — full per-regime evidence breakdown
Never recommend a strategy whose supporting regime evidence is missing or insufficient."""


def tools_registered(registry: Any) -> bool:
    """Return True when all strategy-discovery tools exist in *registry*.

    Accepts any registry-like object: prefers ``registry.has(name)`` when
    available, otherwise membership in ``registry._tools``. Errors are treated
    as "not registered" so prompt assembly can never crash here.
    """
    try:
        has = getattr(registry, "has", None)
        if callable(has):
            return all(bool(has(name)) for name in STRATEGY_DISCOVERY_TOOLS)
        tools = getattr(registry, "_tools", {})
        return all(name in tools for name in STRATEGY_DISCOVERY_TOOLS)
    except Exception:  # noqa: BLE001 — fail-safe omission, never raise
        return False


def routing_block(registry: Any) -> str:
    """Routing text to splice into the Task-Routing section.

    Returns :data:`ROUTING_BLOCK` only when *every* tool in
    :data:`STRATEGY_DISCOVERY_TOOLS` is registered; otherwise ``""``. Never
    raises — a partially wired registry simply yields no routing text.
    """
    try:
        if tools_registered(registry):
            return ROUTING_BLOCK
        return ""
    except Exception:  # noqa: BLE001 — fail-safe omission, never raise
        return ""
