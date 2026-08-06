"""Evidence-gated facade over Alpha Zoo and the SDM strategy store.

``StrategyDiscoveryFacade`` unifies the two strategy surfaces (Alpha Zoo
registry + Strategy Development Manager store) behind one read-only catalog
and answers per-regime questions **only from harness-computed evidence**. It
never invents performance numbers: when the evidence table is empty it says
so, and when a dependency degrades (registry failed to load, store
unreachable) it logs a warning and returns an honest partial result instead
of raising.

Heavy dependencies (``src.factors.registry``, ``src.strategy_store``) are
imported lazily inside methods — module import stays cheap and tests can
inject fakes through the constructor.
"""

from __future__ import annotations

import dataclasses
import logging
import math
from typing import Any

from src.strategy_discovery.evidence_store import EvidenceStore
from src.strategy_discovery.models import (
    BORDERLINE_BREAKEVEN_BPS,
    BORDERLINE_COVERAGE_BUFFER_DAYS,
    BORDERLINE_TRADE_BUFFER,
    MIN_COVERAGE_DAYS,
    MIN_TRADES,
    QUALITY_ORDER,
    REGIMES,
    StrategySummary,
    coverage_days_from_ranges,
)

logger = logging.getLogger(__name__)

_VALID_SOURCES = ("alpha_zoo", "sdm")

#: Upper bound used when draining the SDM artifact list for catalog display.
_SDM_SCAN_LIMIT = 100_000

#: Extra warning appended to rows that pass every filter but sit inside the
#: #969 adversarial buffer bands. Verbatim contract text — tools match it.
_BORDERLINE_WARNING = (
    "borderline-evidence: just inside one or more thresholds — "
    "cite the raw figures, not the verdict"
)

#: Note attached to query results when the evidence table is completely empty.
#: Honest wording: there is NO user-runnable CLI/workflow that populates the
#: store — rows land only via the evidence harness library API.
_EMPTY_EVIDENCE_NOTE = (
    "No per-regime evidence computed yet. The evidence store is populated only "
    "by the evidence harness library API "
    "(src.strategy_discovery.evidence_harness.rebuild_evidence over "
    "reproducible run artifacts); automated workflow wiring is still pending, "
    "so until then rows come from harness runs executed by developers/"
    "integrators. The facade refuses to assess regimes without evidence."
)


def _error(message: str) -> dict[str, Any]:
    """Standard error envelope shared with the other agent tool modules."""
    return {"status": "error", "error": message}


def _json_safe(value: Any) -> Any:
    """Deep-copy *value* replacing non-finite floats with ``None``.

    Guarantees every returned envelope serializes under strict JSON (no
    NaN/Infinity tokens) without silently shifting finite numbers.
    """
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _is_int(value: Any) -> bool:
    """True for real integers only (bool is explicitly excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


class StrategyDiscoveryFacade:
    """Read-only unified discovery surface over Alpha Zoo + SDM + evidence."""

    def __init__(
        self,
        evidence_store: EvidenceStore | None = None,
        sdm_store=None,
        alpha_registry=None,
    ) -> None:
        """Wire the facade. Every dependency is injectable for tests.

        Args:
            evidence_store: Evidence backend. Default constructed lazily on
                first use (``EvidenceStore()``).
            sdm_store: SDM artifact store. Default resolved lazily through
                ``src.strategy_store._shared.get_store()``.
            alpha_registry: Alpha Zoo registry. Default resolved lazily via
                the process-wide shared
                ``src.factors.registry.get_default_registry()`` singleton —
                constructing a ``Registry()`` per facade instance would re-run
                the AST scan of every zoo module (~0.85s) on each construction.
        """
        self._evidence_store = evidence_store
        self._sdm_store = sdm_store
        self._alpha_registry = alpha_registry
        self._evidence_store_failed = False
        self._sdm_failed = False
        self._alpha_failed = False

    # -- lazy dependency resolution -------------------------------------------

    def _get_evidence_store(self) -> EvidenceStore | None:
        """Return the evidence store, constructing the default lazily."""
        if self._evidence_store is None and not self._evidence_store_failed:
            try:
                self._evidence_store = EvidenceStore()
            except Exception:  # noqa: BLE001 — degrade, never crash the facade
                logger.warning(
                    "EvidenceStore default construction failed; evidence lookups "
                    "degrade to empty results",
                    exc_info=True,
                )
                self._evidence_store_failed = True
        return self._evidence_store

    def _get_sdm_store(self) -> Any:
        """Return the SDM store, lazily importing the shared singleton."""
        if self._sdm_store is None and not self._sdm_failed:
            try:
                # Local import; intentional — keeps module import dependency-free.
                from src.strategy_store._shared import get_store

                self._sdm_store = get_store()
            except Exception:  # noqa: BLE001 — degrade to zero SDM entries
                logger.warning(
                    "SDM strategy store unavailable; SDM catalog entries degraded to none",
                    exc_info=True,
                )
                self._sdm_failed = True
        return self._sdm_store

    def _get_alpha_registry(self) -> Any:
        """Return the Alpha Zoo registry, tolerating a failed zoo load.

        The default resolution goes through the process-wide
        ``get_default_registry()`` singleton: building a fresh ``Registry()``
        AST-scans every zoo module (~0.85s), which must not happen per facade
        instance. Constructor-injected registries (tests) bypass this path.
        """
        if self._alpha_registry is None and not self._alpha_failed:
            try:
                # Local import; intentional — zoo scan must never block package import.
                from src.factors.registry import get_default_registry

                self._alpha_registry = get_default_registry()
            except Exception:  # noqa: BLE001 — degrade to zero alphas
                logger.warning(
                    "Alpha Zoo registry unavailable; alpha catalog entries degraded to none",
                    exc_info=True,
                )
                self._alpha_failed = True
        return self._alpha_registry

    # -- catalog construction --------------------------------------------------

    @staticmethod
    def _join_meta_list(value: Any) -> str | None:
        """Render a meta list/tuple field as a comma-joined string (or None)."""
        if isinstance(value, (list, tuple)) and value:
            return ", ".join(str(item) for item in value)
        if isinstance(value, str) and value:
            return value
        return None

    def _alpha_description(self, meta: dict[str, Any]) -> str | None:
        """Build a display description from alpha meta (theme + notes joined)."""
        parts: list[str] = []
        theme = self._join_meta_list(meta.get("theme"))
        if theme:
            parts.append(f"themes: {theme}")
        notes = meta.get("notes")
        if isinstance(notes, str) and notes.strip():
            parts.append(notes.strip())
        return "; ".join(parts) or None

    def _alpha_summaries(self) -> list[StrategySummary]:
        """Catalog entries for every loaded Alpha Zoo alpha (sorted)."""
        registry = self._get_alpha_registry()
        if registry is None:
            return []
        try:
            alpha_ids = registry.list()
        except Exception:  # noqa: BLE001 — degrade to zero alphas
            logger.warning("Alpha Zoo registry listing failed", exc_info=True)
            return []

        summaries: list[StrategySummary] = []
        for alpha_id in alpha_ids:
            try:
                alpha = registry.get(alpha_id)
            except Exception:  # noqa: BLE001 — skip a broken entry, keep the rest
                logger.warning("Alpha Zoo entry %s unreadable", alpha_id, exc_info=True)
                continue
            meta = getattr(alpha, "meta", None) or {}
            summaries.append(
                StrategySummary(
                    strategy_id=f"alpha_zoo:{alpha.id}",
                    name=meta.get("nickname") or alpha.id,
                    source="alpha_zoo",
                    description=self._alpha_description(meta),
                    status=None,
                    universe=self._join_meta_list(meta.get("universe")),
                )
            )
        summaries.sort(key=lambda summary: summary.strategy_id)
        return summaries

    def _sdm_summaries(self) -> list[StrategySummary]:
        """Catalog entries for every SDM artifact (sorted)."""
        store = self._get_sdm_store()
        if store is None:
            return []
        try:
            try:
                artifacts = store.list_artifacts(limit=_SDM_SCAN_LIMIT)
            except TypeError:
                # Injected fakes may expose a no-arg list_artifacts().
                artifacts = store.list_artifacts()
        except Exception:  # noqa: BLE001 — degrade to zero SDM entries
            logger.warning("SDM artifact listing failed", exc_info=True)
            return []

        summaries: list[StrategySummary] = []
        for artifact in artifacts:
            try:
                status = getattr(artifact.status, "value", artifact.status)
                signal_definition = getattr(artifact, "signal_definition", None) or None
                summaries.append(
                    StrategySummary(
                        strategy_id=f"sdm:{artifact.id}",
                        name=str(artifact.name),
                        source="sdm",
                        description=(
                            signal_definition[:300] if signal_definition else None
                        ),
                        status=status if status is not None else None,
                        universe=getattr(artifact, "universe", None),
                    )
                )
            except Exception:  # noqa: BLE001 — skip a broken entry, keep the rest
                logger.warning("SDM artifact unreadable", exc_info=True)
                continue
        summaries.sort(key=lambda summary: summary.strategy_id)
        return summaries

    def _evidence_by_strategy(self) -> dict[str, tuple[str, ...]]:
        """Map strategy_id -> sorted regimes that have evidence rows."""
        store = self._get_evidence_store()
        grouped: dict[str, set[str]] = {}
        if store is None:
            return {}
        try:
            for row in store.get_rows():
                grouped.setdefault(row.strategy_id, set()).add(row.regime)
        except Exception:  # noqa: BLE001 — evidence enrichment is best-effort
            logger.warning(
                "Evidence enrichment lookup failed; omitting evidence flags",
                exc_info=True,
            )
            return {}
        return {
            strategy_id: tuple(sorted(regimes))
            for strategy_id, regimes in grouped.items()
        }

    # -- public API --------------------------------------------------------------

    def list_strategies(
        self,
        limit: int = 20,
        offset: int = 0,
        source: str | None = None,
    ) -> dict:
        """Unified catalog: alpha_zoo entries first, then sdm entries."""
        if not _is_int(limit) or limit <= 0:
            return _error("limit must be a positive integer")
        if not _is_int(offset) or offset < 0:
            return _error("offset must be a non-negative integer")
        if source is not None and source not in _VALID_SOURCES:
            return _error(
                f"source must be one of {'|'.join(_VALID_SOURCES)} or omitted, got {source!r}"
            )

        try:
            items: list[StrategySummary] = []
            if source in (None, "alpha_zoo"):
                items.extend(self._alpha_summaries())
            if source in (None, "sdm"):
                items.extend(self._sdm_summaries())

            evidence_map = self._evidence_by_strategy()
            enriched: list[StrategySummary] = []
            for summary in items:
                regimes = evidence_map.get(summary.strategy_id, ())
                enriched.append(
                    dataclasses.replace(
                        summary,
                        has_evidence=bool(regimes),
                        regimes_with_evidence=regimes,
                    )
                )

            page = enriched[offset : offset + limit]
            envelope: dict[str, Any] = {
                "status": "ok",
                "total": len(enriched),
                "returned": len(page),
                "offset": offset,
                "source": source,
                "items": [dataclasses.asdict(summary) for summary in page],
            }
            return _json_safe(envelope)
        except Exception:  # noqa: BLE001 — never raise from the public facade
            logger.exception("list_strategies failed")
            return _error("list_strategies failed internally; see logs")

    def query_strategies(
        self,
        regime: str | None = None,
        min_sharpe: float | None = None,
        min_evidence_quality: str = "adequate",
        min_trades: int = 10,
        cost_feasible: bool = True,
        limit: int = 10,
    ) -> dict:
        """Evidence-gated query: only rows backed by stored evidence qualify."""
        if regime is not None and regime not in REGIMES:
            return _error(
                f"unknown regime {regime!r}; valid regimes: {', '.join(REGIMES)}"
            )
        if min_evidence_quality != "any" and min_evidence_quality not in QUALITY_ORDER:
            return _error(
                "min_evidence_quality must be one of "
                f"{', '.join(sorted(QUALITY_ORDER))} or 'any'"
            )
        if not _is_int(min_trades) or min_trades < 0:
            return _error("min_trades must be a non-negative integer")
        if min_sharpe is not None and not (
            isinstance(min_sharpe, (int, float))
            and not isinstance(min_sharpe, bool)
            and math.isfinite(min_sharpe)
        ):
            return _error("min_sharpe must be a finite number or None")
        if not _is_int(limit) or limit <= 0:
            return _error("limit must be a positive integer")

        try:
            store = self._get_evidence_store()
            rows = []
            table_empty = True
            if store is not None:
                try:
                    rows = store.get_rows(regime=regime)
                    table_empty = store.row_count() == 0
                except Exception:  # noqa: BLE001 — degrade to no evidence
                    logger.warning(
                        "Evidence query failed; returning no evidence rows",
                        exc_info=True,
                    )
                    rows = []
                    table_empty = True

            quality_floor = (
                QUALITY_ORDER[min_evidence_quality]
                if min_evidence_quality != "any"
                else -1
            )

            def passes(row) -> bool:
                if QUALITY_ORDER.get(row.evidence_quality, 0) < quality_floor:
                    return False
                if row.trades_in_regime < min_trades:
                    return False
                if cost_feasible and (
                    row.breakeven_fee_bps is None or row.cost_sensitive
                ):
                    # Fail-closed: a null breakeven means the cost screen is
                    # unverifiable (multi-position run), which is not a pass.
                    return False
                if min_sharpe is not None and (
                    row.sharpe_in_regime is None or row.sharpe_in_regime < min_sharpe
                ):
                    return False
                return True

            filtered = [row for row in rows if passes(row)]
            filtered.sort(
                key=lambda row: (
                    -QUALITY_ORDER.get(row.evidence_quality, 0),
                    -row.trades_in_regime,
                    row.strategy_id,
                    row.regime,
                )
            )

            items: list[dict[str, Any]] = []
            for row in filtered[:limit]:
                data = dataclasses.asdict(row)
                borderline = self._is_borderline(row)
                data["borderline"] = borderline
                if borderline:
                    data["warnings"] = [*data["warnings"], _BORDERLINE_WARNING]
                items.append(data)

            envelope: dict[str, Any] = {
                "status": "ok",
                "count": len(filtered),
                "returned": len(items),
                "filters": {
                    "regime": regime,
                    "min_sharpe": min_sharpe,
                    "min_evidence_quality": min_evidence_quality,
                    "min_trades": min_trades,
                    "cost_feasible": cost_feasible,
                },
                "items": items,
            }
            if table_empty:
                envelope["note"] = _EMPTY_EVIDENCE_NOTE
            return _json_safe(envelope)
        except Exception:  # noqa: BLE001 — never raise from the public facade
            logger.exception("query_strategies failed")
            return _error("query_strategies failed internally; see logs")

    def get_strategy_evidence(
        self, strategy_id: str, regime: str | None = None
    ) -> dict:
        """Full per-regime evidence breakdown for one strategy."""
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            return _error("strategy_id is required (non-empty string)")
        if regime is not None and regime not in REGIMES:
            return _error(
                f"unknown regime {regime!r}; valid regimes: {', '.join(REGIMES)}"
            )

        try:
            rows = []
            store = self._get_evidence_store()
            if store is not None:
                try:
                    rows = store.get_rows(strategy_id=strategy_id, regime=regime)
                except Exception:  # noqa: BLE001 — degrade to no evidence
                    logger.warning(
                        "Evidence lookup failed for %s; returning no rows",
                        strategy_id,
                        exc_info=True,
                    )
                    rows = []

            envelope: dict[str, Any] = {
                "status": "ok",
                "strategy_id": strategy_id,
                "regime": regime,
                "found": bool(rows),
                "rows": [dataclasses.asdict(row) for row in rows],
            }
            if not rows:
                scope = f" in regime {regime!r}" if regime is not None else ""
                envelope["note"] = (
                    f"No evidence rows found for strategy_id {strategy_id!r}{scope}. "
                    "Evidence rows are written only by the evidence harness "
                    "library API over reproducible run artifacts."
                )
            return _json_safe(envelope)
        except Exception:  # noqa: BLE001 — never raise from the public facade
            logger.exception("get_strategy_evidence failed")
            return _error("get_strategy_evidence failed internally; see logs")

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _is_borderline(row) -> bool:
        """True when a passing row sits inside the #969 adversarial buffer bands."""
        if row.trades_in_regime < MIN_TRADES + BORDERLINE_TRADE_BUFFER:
            return True
        if (
            row.breakeven_fee_bps is not None
            and row.breakeven_fee_bps < BORDERLINE_BREAKEVEN_BPS
        ):
            return True
        coverage = coverage_days_from_ranges(row.date_ranges)
        if coverage < MIN_COVERAGE_DAYS + BORDERLINE_COVERAGE_BUFFER_DAYS:
            return True
        return False
