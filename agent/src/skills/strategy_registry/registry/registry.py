"""StrategyRegistry: in-memory registry of builtin (YAML seed) + SDM strategies.

Design contract:
    - All methods are ``@classmethod`` — the registry is a process-wide singleton.
    - ``load()`` scans YAML seed files, validates against ``StrategyEntry``.
    - The bundled seed directory is auto-loaded on first read access, so callers
      never have to prime the registry themselves.
    - SDM entries are lazily fetched from ``strategy_store`` via ``get_store()``.
    - ``yaml.safe_load`` only, with a 5 MB size cap per file.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .models import Scenario, StrategyEntry

logger = logging.getLogger(__name__)

_MAX_YAML_BYTES = 5_000_000

# Seed YAML shipped with the skill: <skill>/seed, i.e. one level up from registry/.
_BUNDLED_SEED_DIR = Path(__file__).resolve().parent.parent / "seed"


class StrategyRegistry:
    """In-memory registry of quant strategies (builtin YAML seed + SDM artifacts).

    All methods are ``@classmethod``. Call ``load()`` once at startup, then use
    ``list()`` / ``get()`` / ``query()`` / ``health()`` on the hot path.
    """

    _builtin: dict[str, StrategyEntry] = {}
    _loaded: bool = False

    # ------------------------------------------------------------------
    # load
    # ------------------------------------------------------------------

    @classmethod
    def ensure_loaded(cls) -> None:
        """Load the bundled seed directory once, on first read access.

        Read paths (``list`` / ``get`` / ``query`` / ``health``) call this so the
        builtin catalog is available without an explicit startup hook. An
        explicit ``load()`` also marks the registry as loaded, so callers that
        prime a custom seed directory are never overridden.
        """
        if cls._loaded:
            return
        cls.load(_BUNDLED_SEED_DIR)

    @classmethod
    def load(cls, seed_dir: str | Path) -> int:
        """Load all ``.yaml`` seed files from *seed_dir* into ``_builtin``.

        Each file is validated against ``StrategyEntry``.  Invalid files are
        skipped with a warning logged.  Returns the number of successfully
        loaded entries.
        """
        seed_path = Path(seed_dir)
        if not seed_path.is_dir():
            logger.warning("StrategyRegistry: seed_dir not found: %s", seed_path)
            cls._loaded = True
            return 0

        loaded: dict[str, StrategyEntry] = {}
        for yaml_file in sorted(seed_path.glob("*.yaml")):
            try:
                entry = cls._load_yaml_file(yaml_file)
            except Exception:
                logger.warning(
                    "StrategyRegistry: skipping %s (failed to load)",
                    yaml_file.name,
                    exc_info=True,
                )
                continue

            if entry.strategy_id in loaded:
                logger.warning(
                    "StrategyRegistry: duplicate strategy_id %r in %s, skipped",
                    entry.strategy_id,
                    yaml_file.name,
                )
                continue
            loaded[entry.strategy_id] = entry

        cls._builtin = loaded
        cls._loaded = True
        logger.info("StrategyRegistry: loaded %d builtin strategies from %s", len(loaded), seed_path)
        return len(loaded)

    @classmethod
    def _load_yaml_file(cls, path: Path) -> StrategyEntry:
        import yaml

        size = path.stat().st_size
        if size > _MAX_YAML_BYTES:
            raise ValueError(f"{path.name}: {size}B exceeds {_MAX_YAML_BYTES}B YAML cap")

        text = path.read_text(encoding="utf-8")
        raw = yaml.safe_load(text)

        if not isinstance(raw, dict):
            raise ValueError(f"{path.name}: YAML root must be a mapping, got {type(raw).__name__}")

        return StrategyEntry(**raw)

    # ------------------------------------------------------------------
    # list
    # ------------------------------------------------------------------

    @classmethod
    def list(cls, limit: int = 50, offset: int = 0) -> list[StrategyEntry]:
        """Return builtin + SDM entries as a flat list of ``StrategyEntry``.

        SDM entries are lazy-fetched from the strategy store.  Results are
        sorted by ``strategy_id`` for deterministic ordering.
        """
        cls.ensure_loaded()
        entries: list[StrategyEntry] = list(cls._builtin.values())
        entries.extend(cls._sdm_entries())
        entries.sort(key=lambda e: e.strategy_id)
        return entries[offset : offset + limit]

    # ------------------------------------------------------------------
    # get
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, strategy_id: str) -> StrategyEntry | None:
        """Return a single entry by *strategy_id*, or ``None``."""
        cls.ensure_loaded()
        if strategy_id in cls._builtin:
            return cls._builtin[strategy_id]
        # Try SDM
        for entry in cls._sdm_entries():
            if entry.strategy_id == strategy_id:
                return entry
        return None

    # ------------------------------------------------------------------
    # query
    # ------------------------------------------------------------------

    @classmethod
    def query(
        cls,
        scenario: Scenario | str | None = None,
        market: str | None = None,
        min_sharpe: float | None = None,
        source: str | None = None,
        decay_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[StrategyEntry]:
        """Unified facade query with optional filters.

        Args:
            scenario: Filter entries where *scenario* is in
                ``effective_scenarios``.  SDM entries are matched through the
                theme tags mapped by ``StrategyEntry.from_artifact``.
            market: Filter by ``implementation.universe`` — applies to builtin
                and SDM entries alike.  Entries without a universe are excluded
                while this filter is active.
            min_sharpe: Filter by ``benchmark_results.sharpe >= min_sharpe``.
            source: ``"builtin"`` only, ``"sdm"`` only, or ``None`` for both.
            decay_status: Filter by lifecycle status (e.g. ``"active"``,
                ``"decayed"``).  Builtin entries are ``"active"`` by default.
            limit: Max results returned.
            offset: Pagination offset.

        Returns:
            Sorted list of matching ``StrategyEntry`` objects (empty list when
            no matches).
        """
        cls.ensure_loaded()
        results: list[StrategyEntry] = []

        # Resolve scenario to enum
        scenario_enum: Scenario | None = None
        if scenario is not None:
            if isinstance(scenario, Scenario):
                scenario_enum = scenario
            else:
                try:
                    scenario_enum = Scenario(scenario)
                except ValueError:
                    logger.warning(
                        "StrategyRegistry.query: unknown scenario %r, ignoring filter",
                        scenario,
                    )
                    scenario_enum = None

        # Builtin entries
        if source is None or source == "builtin":
            for entry in cls._builtin.values():
                if not cls._match_entry(entry, scenario_enum, market, min_sharpe, decay_status):
                    continue
                results.append(entry)

        # SDM entries
        if source is None or source == "sdm":
            for entry in cls._sdm_entries():
                if not cls._match_entry(entry, scenario_enum, market, min_sharpe, decay_status):
                    continue
                results.append(entry)

        results.sort(key=lambda e: e.strategy_id)
        return results[offset : offset + limit]

    # ------------------------------------------------------------------
    # health
    # ------------------------------------------------------------------

    @classmethod
    def health(cls) -> dict[str, Any]:
        """Return a health snapshot: ``{builtin_loaded, sdm_available, total}``."""
        cls.ensure_loaded()
        sdm_available = cls._sdm_is_available()
        sdm_count = len(cls._sdm_entries()) if sdm_available else 0
        return {
            "builtin_loaded": len(cls._builtin),
            "sdm_available": sdm_available,
            "total": len(cls._builtin) + sdm_count,
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @classmethod
    def _match_entry(
        cls,
        entry: StrategyEntry,
        scenario_enum: Scenario | None,
        market: str | None,
        min_sharpe: float | None,
        decay_status: str | None = None,
    ) -> bool:
        """Return ``True`` if *entry* passes all active filters."""
        # Scenario filter
        if scenario_enum is not None:
            if scenario_enum not in entry.effective_scenarios:
                return False

        # Market filter — matched against implementation.universe for every source
        if market is not None:
            impl = entry.implementation
            if impl is None:
                return False
            if impl.get("universe") != market:
                return False

        # Sharpe filter
        if min_sharpe is not None:
            bench = entry.benchmark_results
            if bench is None:
                return False
            sharpe = bench.get("sharpe")
            if sharpe is None or sharpe < min_sharpe:
                return False

        # Lifecycle / decay filter
        if decay_status is not None and entry.status != decay_status:
            return False

        return True

    # ------------------------------------------------------------------
    # SDM bridge (lazy)
    # ------------------------------------------------------------------

    @classmethod
    def _sdm_entries(cls) -> list[StrategyEntry]:
        """Fetch SDM entries from the strategy store (lazy import)."""
        try:
            from src.strategy_store._shared import get_store
        except ImportError:
            logger.debug("StrategyRegistry: strategy_store not available")
            return []

        try:
            store = get_store()
        except Exception:
            logger.debug("StrategyRegistry: get_store() failed", exc_info=True)
            return []

        try:
            artifacts = store.list_artifacts(limit=1000)
        except Exception:
            logger.debug("StrategyRegistry: list_artifacts() failed", exc_info=True)
            return []

        entries: list[StrategyEntry] = []
        for artifact in artifacts:
            try:
                entries.append(
                    StrategyEntry.from_artifact(artifact, bench=cls._latest_bench(store, artifact.id))
                )
            except Exception:
                logger.debug(
                    "StrategyRegistry: failed to convert artifact %r",
                    getattr(artifact, "id", "?"),
                    exc_info=True,
                )
        return entries

    @staticmethod
    def _latest_bench(store: Any, artifact_id: str) -> Any | None:
        """Return the newest ``BenchResult`` for *artifact_id*, or ``None``.

        Sharpe lives in the bench history rather than on the artifact, so it has
        to be fetched here for ``min_sharpe`` to be able to match SDM entries.
        """
        try:
            history = store.get_bench_history(artifact_id, limit=1)
        except Exception:
            logger.debug(
                "StrategyRegistry: get_bench_history(%r) failed", artifact_id, exc_info=True
            )
            return None
        return history[0] if history else None

    @classmethod
    def _sdm_is_available(cls) -> bool:
        """Return ``True`` if the strategy store is importable and reachable."""
        try:
            from src.strategy_store._shared import get_store

            get_store()
            return True
        except Exception:
            return False
