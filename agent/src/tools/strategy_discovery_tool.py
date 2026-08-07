"""Strategy-discovery agent tools: evidence-gated discovery surface.

Four tools — ``list_strategies`` / ``query_strategies`` /
``get_strategy_evidence`` / ``refresh_strategy_evidence`` — expose the
Strategy Discovery facade over the Alpha Zoo registry and the SDM strategy
store. The surface is evidence-gated: strategies carry computed per-regime
evidence rows instead of boolean scenario tags, and anything below the
evidence thresholds is flagged ``insufficient`` / ``marginal`` rather than
recommended.

The first three tools are read-only. The fourth,
``refresh_strategy_evidence``, is a WRITE tool with a deliberately narrow
scope: it rebuilds ONLY the disposable facade-owned evidence cache from
local backtest run artifacts (manifest-driven; plan D6/D7). It never writes
to the Alpha Zoo or SDM sources of truth, and it uses no network and no
credentials.

The facade is constructed lazily inside each ``execute()`` (never at import
time), parameter types are coerced/validated defensively (bad input yields
an error envelope, never a traceback), and any unexpected exception is
wrapped into the standard ``{"status": "error", ...}`` envelope.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
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


# ---------------------------------------------------------------------------
# refresh_strategy_evidence — manifest-driven cache rebuild (WRITE tool)
# ---------------------------------------------------------------------------

#: Stable skip-reason prefix for run dirs that resolve outside the allowed
#: roots (plan D7). The offending path follows the colon so the envelope stays
#: machine-readable and actionable at the same time.
PATH_OUTSIDE_ALLOWED_ROOTS = "path-outside-allowed-roots"


def _allowed_refresh_run_roots() -> list[Path]:
    """Roots a refresh run_dir may live inside (plan D7).

    The runtime runs root (``get_runtime_root()/"runs"``, honouring
    ``VIBE_TRADING_HOME``) plus any operator-configured
    ``VIBE_TRADING_ALLOWED_RUN_ROOTS`` entries. Environment access goes
    through the config accessor (never ``os.environ`` directly — the
    repository's AST CI gate forbids that here); any config-layer failure
    degrades to the runtime runs root only.
    """
    roots: list[Path] = []
    try:
        from src.config.paths import get_runtime_root

        runtime_runs = (get_runtime_root() / "runs").resolve()
        roots.append(runtime_runs)
    except Exception:  # noqa: BLE001 — config layer optional for this package
        logger.debug("runtime runs root unavailable", exc_info=True)
    try:
        from src.config.accessor import get_env_config

        raw = get_env_config().api.vibe_trading_allowed_run_roots or ""
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            resolved = Path(item).expanduser().resolve()
            if resolved not in roots:
                roots.append(resolved)
    except Exception:  # noqa: BLE001 — degrade to the runtime runs root only
        logger.debug("allowed run roots config unavailable", exc_info=True)
    return roots


def _run_dir_allowed(run_dir: Path, roots: list[Path]) -> bool:
    """Whether a resolved run dir lives inside one of the allowed roots."""
    return any(run_dir.is_relative_to(root) for root in roots)


def load_manifest(path: str | Path) -> list:
    """Read a refresh manifest file and return its run-spec entry list.

    Two shapes are accepted (plan §4.6): a JSON object with a ``runs`` array
    (``{"runs": [{strategy_id, run_dir, position_size?}, ...]}``) or a bare
    JSON array of the same entries.

    Raises:
        ValueError: With an operator-facing message when the file is missing
            or unreadable, is not valid JSON, or has the wrong shape. The
            agent tool and the CLI share this helper so both surfaces report
            the same failure the same way.
    """
    manifest_path = Path(str(path)).expanduser()
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"manifest file {manifest_path} is missing or unreadable "
            f"({exc.strerror or 'I/O error'})"
        ) from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"manifest file {manifest_path} is not valid JSON: {exc.msg} "
            f"at line {exc.lineno} column {exc.colno}"
        ) from exc
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        runs = parsed.get("runs")
        if not isinstance(runs, list):
            raise ValueError(
                f"manifest file {manifest_path} must be a JSON object with a "
                "'runs' array or a bare JSON array of run specs"
            )
        return runs
    raise ValueError(
        f"manifest file {manifest_path} must be a JSON object with a 'runs' "
        "array or a bare JSON array of run specs"
    )


def validate_refresh_entries(
    entries: list,
) -> tuple[list[dict], list[dict]]:
    """Split raw manifest entries into rebuild-ready specs and skip records.

    Per-entry validation (plan §4.6/D7): the entry must be a mapping with a
    non-empty ``strategy_id`` (capped at ``_MAX_STRING_PARAM_CHARS``) and a
    non-empty ``run_dir`` that resolves (expanduser + resolve) inside the
    allowed run roots. Offending entries are returned as
    ``{"run_dir": ..., "reason": ...}`` skip records — the remaining entries
    still process. An optional ``position_size`` is passed through untouched
    (the harness validates it).

    Returns:
        ``(specs, skipped)`` — specs ready for ``rebuild_evidence`` and the
        skip records for the envelope.
    """
    roots = _allowed_refresh_run_roots()
    specs: list[dict] = []
    skipped: list[dict] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            skipped.append(
                {
                    "run_dir": None,
                    "reason": f"run spec at index {index} is not an object",
                }
            )
            continue
        run_dir_raw = entry.get("run_dir")
        run_dir_label = (
            str(run_dir_raw)
            if isinstance(run_dir_raw, str) and run_dir_raw.strip()
            else None
        )
        strategy_id = entry.get("strategy_id")
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            skipped.append(
                {
                    "run_dir": run_dir_label,
                    "reason": "missing strategy_id or run_dir",
                }
            )
            continue
        if len(strategy_id) > _MAX_STRING_PARAM_CHARS:
            skipped.append(
                {
                    "run_dir": run_dir_label,
                    "reason": (
                        f"strategy_id is too long ({len(strategy_id)} chars; "
                        f"max {_MAX_STRING_PARAM_CHARS})"
                    ),
                }
            )
            continue
        if run_dir_label is None:
            skipped.append(
                {"run_dir": None, "reason": "missing strategy_id or run_dir"}
            )
            continue
        try:
            resolved = Path(run_dir_label).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            skipped.append(
                {
                    "run_dir": run_dir_label,
                    "reason": f"run_dir could not be resolved: {exc}",
                }
            )
            continue
        if not _run_dir_allowed(resolved, roots):
            skipped.append(
                {
                    "run_dir": run_dir_label,
                    "reason": f"{PATH_OUTSIDE_ALLOWED_ROOTS}:{run_dir_label}",
                }
            )
            continue
        spec: dict = {
            "strategy_id": strategy_id.strip(),
            "run_dir": str(resolved),
        }
        if "position_size" in entry:
            spec["position_size"] = entry["position_size"]
        specs.append(spec)
    return specs, skipped


def refresh_strategy_evidence_core(
    *,
    manifest_path: str | None = None,
    runs: list | None = None,
) -> dict:
    """Shared refresh core for the agent tool and the CLI (one code path).

    Validates the exactly-one-source rule, loads the manifest (or accepts
    inline ``runs``), validates every entry (path containment included), and
    rebuilds the DEFAULT evidence store — ``EvidenceStore()`` resolution:
    env override → runtime root → ``~/.vibe-trading``; NEVER a CWD-relative
    path.

    Returns:
        The strict envelope ``{status, runs, strategies, rows, skipped}``
        where ``runs`` counts every supplied entry (processed + skipped) and
        ``skipped`` merges entry-level skips with harness skips.

    Raises:
        ValueError: Operator-facing usage errors (exactly-one rule violated,
            manifest missing/invalid/wrong shape, ``runs`` not an array).
    """
    if manifest_path is not None and runs is not None:
        raise ValueError("provide exactly one of manifest_path or runs, not both")
    if manifest_path is None and runs is None:
        raise ValueError(
            "refresh_strategy_evidence requires exactly one of manifest_path " "or runs"
        )
    if manifest_path is not None:
        entries = load_manifest(manifest_path)
    else:
        if not isinstance(runs, list):
            raise ValueError(
                "runs must be an array of {strategy_id, run_dir, "
                "position_size?} objects"
            )
        entries = runs

    specs, skipped = validate_refresh_entries(entries)
    if not specs:
        # Nothing admissible to rebuild from. Do NOT call rebuild_evidence:
        # an empty rebuild clears the store, and wiping the cache because
        # every input entry was invalid would be a destructive surprise.
        return {
            "status": "ok",
            "runs": len(entries),
            "strategies": 0,
            "rows": 0,
            "skipped": skipped,
        }

    from src.strategy_discovery import EvidenceStore, rebuild_evidence

    result = dict(rebuild_evidence(specs, EvidenceStore()))
    result["runs"] = len(entries)
    result["skipped"] = skipped + list(result.get("skipped", []))
    return result


class RefreshStrategyEvidenceTool(BaseTool):
    """Rebuild the disposable strategy-evidence cache from run artifacts."""

    name = "refresh_strategy_evidence"
    description = (
        "Rebuild the strategy-discovery evidence cache from real backtest "
        "run artifacts. WRITE tool, disposable-cache scope only: it replaces "
        "the facade-owned evidence cache (drop-and-rebuild by contract) and "
        "never touches the Alpha Zoo or SDM sources of truth; no network, no "
        "credentials. Provide EXACTLY ONE of manifest_path (JSON manifest: "
        '{"runs": [{strategy_id, run_dir, position_size?}, ...]} — a bare '
        "JSON array of the same entries is also accepted) or runs (inline "
        "array of the same objects). Runs that fail the ingestion gates "
        "(unhealthy artifacts, path outside the allowed run roots) are "
        "skipped with machine-readable reasons while the rest still process."
    )
    parameters = {
        "type": "object",
        "properties": {
            "manifest_path": {
                "type": "string",
                "description": (
                    "Path to a JSON manifest file: an object with a 'runs' "
                    "array or a bare JSON array of "
                    "{strategy_id, run_dir, position_size?} entries. "
                    "Provide exactly one of manifest_path or runs."
                ),
            },
            "runs": {
                "type": "array",
                "description": (
                    "Inline run specs: an array of "
                    "{strategy_id, run_dir, position_size?} objects. "
                    "Provide exactly one of manifest_path or runs."
                ),
                "items": {"type": "object"},
            },
        },
        "required": [],
    }
    is_readonly = False
    repeatable = True

    def execute(self, **kwargs: Any) -> str:
        try:
            manifest_path = _coerce_opt_str(
                kwargs.get("manifest_path"), "manifest_path"
            )
        except ValueError as exc:
            return _err(str(exc))
        runs = kwargs.get("runs")
        if runs is not None and not isinstance(runs, list):
            return _err(
                "runs must be an array of {strategy_id, run_dir, "
                "position_size?} objects"
            )
        try:
            result = refresh_strategy_evidence_core(
                manifest_path=manifest_path, runs=runs
            )
        except ValueError as exc:
            return _err(str(exc))
        except Exception:
            # Full detail goes to the server logs only; the envelope must not
            # echo raw exception text (it can leak internal paths).
            logger.exception("refresh_strategy_evidence failed")
            return _err("refresh_strategy_evidence failed internally; see server logs")
        return _envelope(result)
