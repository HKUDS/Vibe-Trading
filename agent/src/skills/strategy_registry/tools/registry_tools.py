"""Strategy Registry MCP tools: list, query, and get quant strategies.

Exposes three MCP tools for browsing the strategy registry aligned with the
Vibe-Trading MCP server conventions (``@mcp.tool()``, JSON-string returns).

Tools:
    - ``list_strategies``: paginated listing of all strategies
    - ``query_strategies``: filtered query by scenario / source / min-sharpe
    - ``get_strategy``: full detail for a single strategy by ID
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP

from src.skills.strategy_registry.registry import StrategyRegistry
from src.skills.strategy_registry.registry.models import Scenario, StrategyEntry

logger = logging.getLogger(__name__)

mcp = FastMCP("strategy-registry")

_MAX_LIMIT = 50
# Used to fetch all entries for counting before paginating.
_FETCH_ALL = 10_000


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _strategy_summary(entry: StrategyEntry) -> dict[str, Any]:
    """Build a lightweight summary dict for listing / query results."""
    sharpe: float | None = None
    bench = entry.benchmark_results
    if bench and isinstance(bench, dict):
        sharpe = bench.get("sharpe")
    return {
        "strategy_id": entry.strategy_id,
        "name": entry.name,
        "source": entry.source,
        "area": entry.area,
        "effective_scenarios": [s.value for s in entry.effective_scenarios],
        "sharpe": sharpe,
    }


def _strategy_full(entry: StrategyEntry) -> dict[str, Any]:
    """Build a full dict from a StrategyEntry (all fields)."""
    return entry.model_dump()


def _json_ok(**payload: Any) -> str:
    """Standard MCP JSON success envelope."""
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False, indent=2)


def _json_error(error: str, **extra: Any) -> str:
    """Standard MCP JSON error envelope."""
    return json.dumps(
        {"status": "error", "error": error, **extra}, ensure_ascii=False, indent=2
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_strategies(limit: int = 50, offset: int = 0) -> str:
    """List all strategies in the registry with summary metadata.

    Returns a paginated list of {strategy_id, name, source, area,
    effective_scenarios, sharpe} summaries.

    Args:
        limit: Maximum strategies to return (default 50, capped at 50).
        offset: Number of strategies to skip for pagination (default 0).
    """
    limit = max(1, min(limit, _MAX_LIMIT))
    offset = max(0, offset)

    try:
        all_entries = StrategyRegistry.list(limit=_FETCH_ALL, offset=0)
    except Exception as exc:
        logger.exception("StrategyRegistry.list() failed")
        return _json_error(f"registry access failed: {exc}")

    total = len(all_entries)
    page = all_entries[offset : offset + limit]
    summaries = [_strategy_summary(e) for e in page]

    return _json_ok(
        total=total,
        returned=len(summaries),
        offset=offset,
        items=summaries,
    )


@mcp.tool()
def query_strategies(
    scenario: str | None = None,
    market: str | None = None,
    min_sharpe: float | None = None,
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> str:
    """Query strategies filtered by scenario, market, source, or minimum Sharpe.

    Returns {strategy_id, name, source, area, effective_scenarios, sharpe}
    summaries for strategies matching all provided filters.

    Args:
        scenario: Filter by effective scenario (e.g. 'bear_market_defense',
            'value_rotation').  Must be a valid Scenario enum value.
        market: Filter by market universe (e.g. 'china_a', 'us', 'hk').
            Matches against ``implementation.universe``.
        min_sharpe: Minimum benchmark Sharpe ratio (inclusive).
        source: Filter by strategy source ('builtin', 'sdm', 'user').
        limit: Maximum results (default 50, capped at 50).
        offset: Number of results to skip for pagination (default 0).
    """
    # Validate scenario parameter before delegating to the registry.
    if scenario is not None:
        try:
            Scenario(scenario)
        except ValueError:
            valid = sorted([s.value for s in Scenario])
            return _json_error(
                f"invalid scenario '{scenario}'",
                valid_scenarios=valid,
            )

    limit = max(1, min(limit, _MAX_LIMIT))
    offset = max(0, offset)

    try:
        # Fetch all matching entries first so we can report the total count.
        all_matches = StrategyRegistry.query(
            scenario=scenario,
            market=market,
            min_sharpe=min_sharpe,
            source=source,
            limit=_FETCH_ALL,
            offset=0,
        )
    except Exception as exc:
        logger.exception("StrategyRegistry.query() failed")
        return _json_error(f"registry query failed: {exc}")

    total = len(all_matches)
    page = all_matches[offset : offset + limit]
    summaries = [_strategy_summary(e) for e in page]

    return _json_ok(
        total=total,
        returned=len(summaries),
        offset=offset,
        filters={
            "scenario": scenario,
            "market": market,
            "min_sharpe": min_sharpe,
            "source": source,
        },
        items=summaries,
    )


@mcp.tool()
def get_strategy(strategy_id: str) -> str:
    """Get full details for a single strategy by its ID.

    Returns the complete StrategyEntry including description, tuning_hints,
    benchmark_results, and implementation metadata.

    Args:
        strategy_id: Unique strategy identifier (e.g. 'quantsplaybook_ffscore').
    """
    try:
        entry = StrategyRegistry.get(strategy_id)
    except Exception as exc:
        logger.exception("StrategyRegistry.get() failed")
        return _json_error(f"registry access failed: {exc}")

    if entry is None:
        return _json_error(
            "strategy not found",
            strategy_id=strategy_id,
        )

    return _json_ok(strategy=_strategy_full(entry))