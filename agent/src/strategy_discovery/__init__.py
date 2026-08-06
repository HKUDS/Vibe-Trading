"""Strategy Discovery: an evidence-gated facade over Alpha Zoo + SDM.

Read-only core package for GitHub issue #969 (supersedes the rejected #896):
a unified strategy catalog, per-regime evidence queries gated on harness-
computed data, and the harness that turns reproducible run artifacts into
evidence rows. The package never ships seed performance data — stores start
empty and every number served to the agent comes from real backtest runs.

Import policy: this package stays cheap to import. Submodules only depend on
the standard library and each other at module level; heavy integrations
(``src.factors.registry``, ``src.strategy_store``) are imported lazily inside
facade methods, and no network I/O happens at import time.
"""

from __future__ import annotations

from src.strategy_discovery.evidence_harness import (
    compute_evidence_for_run,
    rebuild_evidence,
)
from src.strategy_discovery.evidence_store import EvidenceStore
from src.strategy_discovery.facade import StrategyDiscoveryFacade
from src.strategy_discovery.guard import (
    ROUTING_BLOCK,
    STRATEGY_DISCOVERY_TOOLS,
    routing_block,
    tools_registered,
)
from src.strategy_discovery.models import (
    BORDERLINE_BREAKEVEN_BPS,
    BORDERLINE_COVERAGE_BUFFER_DAYS,
    BORDERLINE_TRADE_BUFFER,
    COST_SENSITIVE_BREAKEVEN_BPS,
    EVIDENCE_STAGES,
    MIN_COVERAGE_DAYS,
    MIN_TRADES,
    QUALITY_ADEQUATE,
    QUALITY_INSUFFICIENT,
    QUALITY_MARGINAL,
    QUALITY_ORDER,
    REGIMES,
    EvidenceRow,
    StrategySummary,
    breakeven_fee_bps,
    classify_quality,
    coverage_days_from_ranges,
)

__all__ = [
    "EvidenceRow",
    "StrategySummary",
    "StrategyDiscoveryFacade",
    "EvidenceStore",
    "REGIMES",
    "EVIDENCE_STAGES",
    "QUALITY_ADEQUATE",
    "QUALITY_MARGINAL",
    "QUALITY_INSUFFICIENT",
    "QUALITY_ORDER",
    "MIN_TRADES",
    "MIN_COVERAGE_DAYS",
    "COST_SENSITIVE_BREAKEVEN_BPS",
    "BORDERLINE_TRADE_BUFFER",
    "BORDERLINE_BREAKEVEN_BPS",
    "BORDERLINE_COVERAGE_BUFFER_DAYS",
    "breakeven_fee_bps",
    "classify_quality",
    "coverage_days_from_ranges",
    "STRATEGY_DISCOVERY_TOOLS",
    "ROUTING_BLOCK",
    "tools_registered",
    "routing_block",
    "compute_evidence_for_run",
    "rebuild_evidence",
]
