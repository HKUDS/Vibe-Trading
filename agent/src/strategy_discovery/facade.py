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
from datetime import date
from typing import Any

from src.strategy_discovery.evidence_store import EvidenceStore
from src.strategy_discovery.models import (
    BORDERLINE_BREAKEVEN_BPS,
    BORDERLINE_COVERAGE_BUFFER_DAYS,
    BORDERLINE_TRADE_BUFFER,
    DECAY_STALE,
    MIN_COVERAGE_DAYS,
    MIN_TRADES,
    QUALITY_ORDER,
    REGIMES,
    StrategySummary,
    classify_decay,
    coverage_days_from_ranges,
    decay_warning,
    evidence_age_days,
    staleness_days,
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
#: Names the population path: the ``refresh_strategy_evidence`` tool (agent +
#: MCP) and the ``vibe-trading strategy-evidence refresh`` CLI command, both
#: of which drive the evidence harness over reproducible run artifacts.
_EMPTY_EVIDENCE_NOTE = (
    "No per-regime evidence computed yet. Populate the store with "
    "`refresh_strategy_evidence` — exposed as an agent/MCP tool and as the "
    "CLI command `vibe-trading strategy-evidence refresh --manifest <path>` — "
    "which rebuilds evidence from reproducible backtest run artifacts "
    "(library callers may drive "
    "src.strategy_discovery.evidence_harness.rebuild_evidence directly). The "
    "facade refuses to assess regimes without evidence."
)

#: SDM lifecycle states that exclude an ``sdm:*`` row from default
#: recommendations regardless of evidence freshness (plan D8 lifecycle
#: mirroring — artifact status only, never the DecayEvaluator FSM).
_SDM_EXCLUDED_STATUSES = ("decayed", "disabled")

#: Stable prefix for lifecycle exclusions surfaced on inspection rows.
_SDM_LIFECYCLE_PREFIX = "sdm-lifecycle:"


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


def _parse_today(today: str | None) -> date:
    """Resolve the injected clock: ISO ``today`` string or the wall clock.

    Raises ``ValueError`` for a non-string or unparseable ``today`` so the
    caller can answer with an error envelope instead of a wrong date.
    """
    if today is None:
        return date.today()
    if not isinstance(today, str):
        raise ValueError(f"today must be an ISO date string or None, got {today!r}")
    return date.fromisoformat(today.strip())


def _decay_fields(row, today: date) -> dict[str, Any]:
    """Read-time decay verdict for one evidence row (plan D1/D2).

    Computed from the row's own ``date_ranges`` window end at query time —
    never persisted. ``staleness_days`` (from ``last_verified``) is reported
    alongside but NEVER gates: refreshing unchanged artifacts must not be
    able to keep a row "fresh" forever.
    """
    age = evidence_age_days(row.date_ranges, today)
    status = classify_decay(row.date_ranges, today)
    return {
        "decay_status": status,
        "evidence_age_days": age,
        "staleness_days": staleness_days(row.last_verified, today),
        "_decay_warning": decay_warning(status, age),
    }


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

    def _sdm_artifact_status(self, artifact_id: str) -> str | None:
        """Read-only SDM artifact status lookup for lifecycle mirroring.

        Degrades gracefully (plan D8): a missing store, a missing
        ``get_artifact`` surface, or any lookup failure returns ``None``
        with a logged warning — the lifecycle gate then SKIPS that row
        rather than crashing or fabricating a status.
        """
        store = self._get_sdm_store()
        if store is None:
            return None
        getter = getattr(store, "get_artifact", None)
        if not callable(getter):
            logger.warning(
                "SDM store exposes no get_artifact(); lifecycle gate skipped "
                "for artifact %s",
                artifact_id,
            )
            return None
        try:
            artifact = getter(artifact_id)
        except Exception:  # noqa: BLE001 — degrade, never crash the facade
            logger.warning(
                "SDM artifact lookup failed for %s; lifecycle gate skipped",
                artifact_id,
                exc_info=True,
            )
            return None
        if artifact is None:
            return None
        status = getattr(artifact, "status", None)
        status = getattr(status, "value", status)
        if isinstance(status, str) and status.strip():
            return status.strip().lower()
        return None

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
        include_stale: bool = False,
        today: str | None = None,
    ) -> dict:
        """Evidence-gated query: only rows backed by stored evidence qualify.

        Gate order (plan D9): quality floor → min_trades → cost_feasible
        (fail-closed null) → min_sharpe → decay gate (stale rows excluded
        unless ``include_stale=True``) → SDM lifecycle gate (``sdm:*`` rows
        whose artifact status is decayed/disabled are ALWAYS excluded from
        recommendations). Decay is computed at read time from each row's
        ``date_ranges`` window end (``evidence_age_days`` drives;
        ``last_verified`` / ``staleness_days`` are reported, never gating).
        ``today`` (ISO string) injects the clock for deterministic tests.
        """
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
        if not isinstance(include_stale, bool):
            return _error("include_stale must be a boolean")
        try:
            today_date = _parse_today(today)
        except ValueError as exc:
            return _error(str(exc))

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

            below_floor = 0
            decay_by_key: dict[tuple[str, str], dict[str, Any]] = {}
            survivors: list[Any] = []
            for row in rows:
                if not passes(row):
                    below_floor += 1
                    continue
                survivors.append(row)

            stale_excluded = 0
            post_decay: list[Any] = []
            for row in survivors:
                decay = _decay_fields(row, today_date)
                decay_by_key[(row.strategy_id, row.regime)] = decay
                if decay["decay_status"] == DECAY_STALE and not include_stale:
                    stale_excluded += 1
                    continue
                post_decay.append(row)

            lifecycle_excluded = 0
            filtered: list[Any] = []
            for row in post_decay:
                if row.strategy_id.startswith("sdm:"):
                    status = self._sdm_artifact_status(row.strategy_id.split(":", 1)[1])
                    if status in _SDM_EXCLUDED_STATUSES:
                        lifecycle_excluded += 1
                        continue
                filtered.append(row)

            filtered.sort(
                key=lambda row: (
                    decay_by_key[(row.strategy_id, row.regime)]["decay_status"]
                    == DECAY_STALE,
                    -QUALITY_ORDER.get(row.evidence_quality, 0),
                    -row.trades_in_regime,
                    row.strategy_id,
                    row.regime,
                )
            )

            items: list[dict[str, Any]] = []
            for row in filtered[:limit]:
                data = dataclasses.asdict(row)
                decay = decay_by_key[(row.strategy_id, row.regime)]
                data["decay_status"] = decay["decay_status"]
                data["evidence_age_days"] = decay["evidence_age_days"]
                data["staleness_days"] = decay["staleness_days"]
                if decay["_decay_warning"] is not None:
                    data["warnings"] = [*data["warnings"], decay["_decay_warning"]]
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
                    "include_stale": include_stale,
                },
                "stale_excluded": stale_excluded,
                "lifecycle_excluded": lifecycle_excluded,
                "items": items,
            }
            if table_empty:
                envelope["note"] = _EMPTY_EVIDENCE_NOTE
            elif rows and not filtered:
                # D11: non-empty table, zero rows pass — say WHY, so the
                # agent can tell users what to fix instead of staring at an
                # unexplained empty list.
                envelope["note"] = (
                    "Evidence exists but every row was excluded by gates: "
                    f"{below_floor} below the quality/cost/trades/Sharpe "
                    f"floors, {stale_excluded} stale-excluded, "
                    f"{lifecycle_excluded} lifecycle-excluded. Use "
                    "include_stale=true to inspect stale rows; "
                    "lifecycle-excluded rows stay out of recommendations "
                    "(inspect them with get_strategy_evidence). Re-backtest "
                    "over a recent window and run refresh_strategy_evidence "
                    "to reinstate stale evidence."
                )
            return _json_safe(envelope)
        except Exception:  # noqa: BLE001 — never raise from the public facade
            logger.exception("query_strategies failed")
            return _error("query_strategies failed internally; see logs")

    def get_strategy_evidence(
        self, strategy_id: str, regime: str | None = None, today: str | None = None
    ) -> dict:
        """Full per-regime evidence breakdown for one strategy.

        Inspection surface (plan D10): returns ALL rows unfiltered — decay
        and lifecycle state are surfaced as fields/notes, never used to drop
        rows here. Each row gains the read-time decay fields
        (``decay_status`` / ``evidence_age_days`` / ``staleness_days``) plus
        the decay warning; ``sdm:*`` strategies additionally carry a
        ``lifecycle_note`` when the SDM artifact status is decayed/disabled
        (lookup failure degrades to omitting the note, never a crash).
        ``today`` (ISO string) injects the clock for deterministic tests.
        """
        if not isinstance(strategy_id, str) or not strategy_id.strip():
            return _error("strategy_id is required (non-empty string)")
        if regime is not None and regime not in REGIMES:
            return _error(
                f"unknown regime {regime!r}; valid regimes: {', '.join(REGIMES)}"
            )
        try:
            today_date = _parse_today(today)
        except ValueError as exc:
            return _error(str(exc))

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

            lifecycle_note: str | None = None
            if strategy_id.startswith("sdm:"):
                status = self._sdm_artifact_status(strategy_id.split(":", 1)[1])
                if status in _SDM_EXCLUDED_STATUSES:
                    lifecycle_note = (
                        f"{_SDM_LIFECYCLE_PREFIX} SDM artifact status is "
                        f"'{status}' — excluded from default recommendations "
                        "regardless of evidence freshness"
                    )

            rendered: list[dict[str, Any]] = []
            for row in rows:
                data = dataclasses.asdict(row)
                decay = _decay_fields(row, today_date)
                data["decay_status"] = decay["decay_status"]
                data["evidence_age_days"] = decay["evidence_age_days"]
                data["staleness_days"] = decay["staleness_days"]
                if decay["_decay_warning"] is not None:
                    data["warnings"] = [*data["warnings"], decay["_decay_warning"]]
                if lifecycle_note is not None:
                    data["lifecycle_note"] = lifecycle_note
                rendered.append(data)

            envelope: dict[str, Any] = {
                "status": "ok",
                "strategy_id": strategy_id,
                "regime": regime,
                "found": bool(rows),
                "rows": rendered,
            }
            if lifecycle_note is not None:
                envelope["lifecycle_note"] = lifecycle_note
            if not rows:
                scope = f" in regime {regime!r}" if regime is not None else ""
                envelope["note"] = (
                    f"No evidence rows found for strategy_id {strategy_id!r}{scope}. "
                    "Evidence rows are written by `refresh_strategy_evidence` "
                    "(agent/MCP tool, or the CLI `vibe-trading strategy-evidence "
                    "refresh`) over reproducible run artifacts."
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
