"""Strategy-discovery agent tools: evidence-gated read-only discovery surface.

Three tools — ``list_strategies`` / ``query_strategies`` /
``get_strategy_evidence`` — expose the Strategy Discovery facade over the
Alpha Zoo registry and the SDM strategy store. The surface is evidence-gated:
strategies carry computed per-regime evidence rows instead of boolean
scenario tags, and anything below the evidence thresholds is flagged
``insufficient`` / ``marginal`` rather than recommended.

All three tools are read-only. The facade is constructed lazily inside each
``execute()`` (never at import time), parameter types are coerced/validated
defensively (bad input yields an error envelope, never a traceback), and any
unexpected exception is wrapped into the standard ``{"status": "error", ...}``
envelope.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.agent.tools import BaseTool

logger = logging.getLogger(__name__)

# Documented evidence-quality ladder. "any" only removes the quality floor;
# the other filters (min_trades, cost_feasible, min_sharpe) still apply, so
# it does NOT literally keep every stored row. The facade interprets levels.
_EVIDENCE_QUALITIES = ("adequate", "marginal", "insufficient", "any")

#: Length cap for free-text string parameters. Values are identifiers
#: (e.g. "alpha_zoo:<id>"), so anything larger is malformed or hostile.
_MAX_STRING_PARAM_CHARS = 500


def _err(msg: str) -> str:
    return json.dumps({"status": "error", "error": msg}, ensure_ascii=False)


def _get_facade() -> Any:
    """Construct the facade lazily so importing this module never touches the
    strategy-discovery storage layer until a tool actually runs."""
    from src.strategy_discovery import StrategyDiscoveryFacade

    return StrategyDiscoveryFacade()


def _envelope(result: Any) -> str:
    """Serialize a facade envelope defensively.

    The facade contract returns ``{"status": "ok", ...}`` or
    ``{"status": "error", "error": ...}`` dicts; anything else is wrapped
    so the agent always receives parseable JSON.
    """
    if not isinstance(result, dict):
        result = {"status": "ok", "result": result}
    return json.dumps(result, ensure_ascii=False)


def _coerce_int(value: Any, name: str, default: int) -> int:
    """Coerce an integer parameter; raise ``ValueError`` on bad input."""
    if value is None:
        return default
    if isinstance(value, bool):  # bool is an int subclass — reject explicitly
        raise ValueError(f"{name} must be an integer, got {value!r}")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _coerce_opt_float(value: Any, name: str) -> float | None:
    """Coerce an optional numeric parameter; reject NaN/inf and bad types."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, got {value!r}")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return result


def _coerce_opt_str(value: Any, name: str) -> str | None:
    """Coerce an optional string parameter; blank/None become ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {value!r}")
    if len(value) > _MAX_STRING_PARAM_CHARS:
        raise ValueError(
            f"{name} is too long ({len(value)} chars; "
            f"max {_MAX_STRING_PARAM_CHARS})"
        )
    text = value.strip()
    return text or None


def _coerce_bool(value: Any, name: str, default: bool) -> bool:
    """Coerce a boolean parameter, tolerating common LLM string forms."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    raise ValueError(f"{name} must be a boolean, got {value!r}")


class ListStrategiesTool(BaseTool):
    """List discoverable strategies from Alpha Zoo and the SDM store."""

    name = "list_strategies"
    description = (
        "List discoverable strategies across the Alpha Zoo registry and the "
        "SDM strategy store. Read-only catalogue of what strategies exist "
        "(identification metadata only). Rows carry evidence status; use "
        "get_strategy_evidence for the per-regime evidence behind any "
        "strategy. Nothing here is a recommendation — rows below the "
        "evidence threshold are flagged insufficient/marginal, not "
        "recommended."
    )
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "default": 20,
                "description": "Maximum number of strategies to return (default 20).",
            },
            "offset": {
                "type": "integer",
                "default": 0,
                "description": "Pagination offset for stable browsing (default 0).",
            },
            "source": {
                "type": "string",
                "description": (
                    "Optional source filter: alpha_zoo|sdm. Omit to browse "
                    "both sources."
                ),
            },
        },
        "required": [],
    }
    is_readonly = True
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        try:
            limit = _coerce_int(kwargs.get("limit"), "limit", 20)
            offset = _coerce_int(kwargs.get("offset"), "offset", 0)
            source = _coerce_opt_str(kwargs.get("source"), "source")
        except ValueError as exc:
            return _err(str(exc))
        if limit <= 0:
            return _err("limit must be > 0")
        if offset < 0:
            return _err("offset must be >= 0")
        try:
            facade = _get_facade()
            result = facade.list_strategies(limit=limit, offset=offset, source=source)
        except Exception:
            # Full detail goes to the server logs only; the envelope must not
            # echo raw exception text (it can leak internal paths).
            logger.exception("list_strategies failed")
            return _err("list_strategies failed internally; see server logs")
        return _envelope(result)


class QueryStrategiesTool(BaseTool):
    """Query strategies whose computed per-regime evidence passes filters."""

    name = "query_strategies"
    description = (
        "Query the strategy store for strategies whose computed evidence "
        "passes the given filters. Evidence-gated: results are ranked by "
        "per-regime evidence rows from reproducible backtests, not scenario "
        "tags. Strategies below the evidence thresholds are flagged "
        "insufficient/marginal rather than recommended. The cost screen "
        "keeps only strategies that clear the sizing-corrected breakeven."
    )
    parameters = {
        "type": "object",
        "properties": {
            "regime": {
                "type": "string",
                "description": (
                    "Optional market-regime filter: "
                    "bear_market/bull_market/structural. Omit to query all "
                    "regimes."
                ),
            },
            "min_sharpe": {
                "type": "number",
                "description": "Optional minimum Sharpe on the evidence rows.",
            },
            "min_evidence_quality": {
                "type": "string",
                "enum": list(_EVIDENCE_QUALITIES),
                "default": "adequate",
                "description": (
                    "Minimum evidence quality to keep: adequate (default), "
                    "marginal, insufficient, or any. 'any' only removes the "
                    "quality floor — rows must still pass the other filters "
                    "(min_trades, cost_feasible, min_sharpe) to be kept."
                ),
            },
            "min_trades": {
                "type": "integer",
                "default": 10,
                "description": (
                    "Minimum executed-trade count for evidence to count "
                    "(default 10)."
                ),
            },
            "cost_feasible": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Keep only strategies that pass the sizing-corrected "
                    "cost-breakeven screen (default true)."
                ),
            },
            "limit": {
                "type": "integer",
                "default": 10,
                "description": "Maximum number of strategies to return (default 10).",
            },
        },
        "required": [],
    }
    is_readonly = True
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        try:
            regime = _coerce_opt_str(kwargs.get("regime"), "regime")
            min_sharpe = _coerce_opt_float(kwargs.get("min_sharpe"), "min_sharpe")
            min_trades = _coerce_int(kwargs.get("min_trades"), "min_trades", 10)
            cost_feasible = _coerce_bool(
                kwargs.get("cost_feasible"), "cost_feasible", True
            )
            limit = _coerce_int(kwargs.get("limit"), "limit", 10)
        except ValueError as exc:
            return _err(str(exc))

        quality_raw = kwargs.get("min_evidence_quality")
        quality = "adequate" if quality_raw is None else quality_raw
        if not isinstance(quality, str) or quality not in _EVIDENCE_QUALITIES:
            return _err(
                "min_evidence_quality must be one of "
                "adequate|marginal|insufficient|any, got "
                f"{quality_raw!r}"
            )
        if min_trades < 0:
            return _err("min_trades must be >= 0")
        if limit <= 0:
            return _err("limit must be > 0")

        try:
            facade = _get_facade()
            result = facade.query_strategies(
                regime=regime,
                min_sharpe=min_sharpe,
                min_evidence_quality=quality,
                min_trades=min_trades,
                cost_feasible=cost_feasible,
                limit=limit,
            )
        except Exception:
            # Full detail goes to the server logs only; the envelope must not
            # echo raw exception text (it can leak internal paths).
            logger.exception("query_strategies failed")
            return _err("query_strategies failed internally; see server logs")
        return _envelope(result)


class GetStrategyEvidenceTool(BaseTool):
    """Return the per-regime evidence rows for one strategy."""

    name = "get_strategy_evidence"
    description = (
        "Return the computed per-regime evidence rows for one strategy. "
        "Shows what reproducible backtests support the strategy in each "
        "regime (trade count, coverage, Sharpe, cost breakeven). Rows below "
        "the evidence thresholds are flagged insufficient/marginal rather "
        "than recommended; the facade refuses regime assessments without "
        "computed evidence."
    )
    parameters = {
        "type": "object",
        "properties": {
            "strategy_id": {
                "type": "string",
                "description": (
                    "Strategy identifier from list_strategies or " "query_strategies."
                ),
            },
            "regime": {
                "type": "string",
                "description": (
                    "Optional regime filter: "
                    "bear_market/bull_market/structural. Omit for all "
                    "regimes."
                ),
            },
        },
        "required": ["strategy_id"],
    }
    is_readonly = True
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        try:
            strategy_id = _coerce_opt_str(kwargs.get("strategy_id"), "strategy_id")
            regime = _coerce_opt_str(kwargs.get("regime"), "regime")
        except ValueError as exc:
            return _err(str(exc))
        if not strategy_id:
            return _err("get_strategy_evidence requires strategy_id (string)")
        try:
            facade = _get_facade()
            result = facade.get_strategy_evidence(strategy_id, regime=regime)
        except Exception:
            # Full detail goes to the server logs only; the envelope must not
            # echo raw exception text (it can leak internal paths).
            logger.exception("get_strategy_evidence failed")
            return _err("get_strategy_evidence failed internally; see server logs")
        return _envelope(result)
