"""Manifest schemas — the cross-workstream contract for quant-strategy-dashboard.

A *manifest* is a structured JSON file describing a research artifact. It is
written progressively as pipeline stages complete (design decision D3). Three
workstreams depend on these models:

- WS1 (research pipeline) writes manifests conforming to these schemas.
- WS2 (FastAPI backend) reads & validates manifests with these schemas.
- WS3 (React frontend) derives TypeScript types from these schemas.

Scope of this file: DATA SHAPE + enums + canonical constants only. Gate and
verdict *computation* logic belongs to a later task (2.12) and is intentionally
NOT implemented here.

Three manifest types are modelled:

1. FactorManifest   -> research/manifests/factor_<symbol>.json
2. StrategyManifest -> research/manifests/<strategy_id>/manifest.json
3. TestnetStatus    -> runs/testnet/<id>/testnet_status.json

A small SelectionManifest is also modelled for research/manifests/selection.json
(stage 5 output), so its sample fixture can be validated.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Canonical gate thresholds — pinned by the contract (alpha-workflow §3).
# Computation of gate pass/fail is task 2.12; these constants only PIN the
# numbers so every workstream agrees on the same thresholds.
# ---------------------------------------------------------------------------

GATE_MIN_SHARPE: float = 1.5
GATE_MAX_DRAWDOWN: float = 0.10  # 10% — drawdown expressed as a positive fraction
GATE_MIN_TRADES: int = 100
GATE_MIN_PROFIT_FACTOR: float = 1.5
GATE_MIN_WALK_FORWARD_SHARPE: float = 1.0  # each walk-forward window
# Monte-Carlo: 95% CI of the return distribution must NOT cross zero.

#: Names of the two FATAL gate checks. Failing either is a hard block that
#: cannot be overridden in the promotion dialog (design D7).
FATAL_GATE_CHECKS: tuple[str, ...] = (
    "oos_sharpe_positive",
    "alpha_not_fee_illusion",
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FactorStability(str, Enum):
    """Whether a factor's edge holds across market regimes."""

    REGIME_STABLE = "regime_stable"
    CONDITIONAL = "conditional"


class FactorVerdict(str, Enum):
    """Disposition of a factor based on |IC| (rule lives in task 2.12).

    |IC| >= 0.10           -> single_use
    0.05 <= |IC| < 0.10    -> ensemble_only
    |IC| < 0.05            -> reject
    """

    SINGLE_USE = "single_use"
    ENSEMBLE_ONLY = "ensemble_only"
    REJECT = "reject"


class RecommendedAction(str, Enum):
    """Diagnosis feedback action — makes the pipeline feedback loop explicit."""

    PROCEED = "proceed"
    BACK_TO_STAGE_2 = "back_to_stage_2"
    BACK_TO_STAGE_4 = "back_to_stage_4"


class RedFlagCode(str, Enum):
    """Auto-derived red-flag codes surfaced on the strategy red-flag banner."""

    OOS_SHARPE_FAR_BELOW_IS = "oos_sharpe_far_below_is"
    UNDERPERFORMS_HODL = "underperforms_hodl"
    TOO_FEW_TRADES = "too_few_trades"
    ALPHA_IS_FEE_ILLUSION = "alpha_is_fee_illusion"
    OVERFIT_SUSPECT = "overfit_suspect"
    REGIME_CONDITIONAL = "regime_conditional"


# ---------------------------------------------------------------------------
# Base config — manifests are written by multiple producers; forbidding extra
# fields catches typos in producers before they reach the dashboard.
# ---------------------------------------------------------------------------


class _Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 1. Factor manifest — research/manifests/factor_<symbol>.json
# ---------------------------------------------------------------------------


class FactorEntry(_Manifest):
    """IC/IR evaluation for a single factor.

    ``cross_regime_ic`` and ``stability`` are nullable: stage 1 may emit a
    factor manifest before the cross-regime IC pass (task 2.3) has run. When
    null, the dashboard shows a "cross-regime not done" warning and the
    pipeline MUST NOT be blocked.
    """

    name: str = Field(..., description="Factor identifier, e.g. 'funding_rate'.")
    ic_by_horizon: Dict[int, float] = Field(
        ...,
        description="Map of forward-return horizon (hours) -> Spearman IC.",
    )
    ir: float = Field(..., description="Information ratio (mean rolling IC / std).")
    sample_size: int = Field(..., ge=0, description="Paired observations used.")
    cross_regime_ic: Optional[Dict[str, float]] = Field(
        default=None,
        description="Map of regime label -> IC; null until task 2.3 has run.",
    )
    stability: Optional[FactorStability] = Field(
        default=None,
        description="regime_stable / conditional; null until cross-regime done.",
    )
    verdict: FactorVerdict = Field(
        ..., description="single_use / ensemble_only / reject."
    )


class FactorManifest(_Manifest):
    """Top-level factor manifest for one symbol."""

    schema_version: int = Field(default=1, ge=1)
    symbol: str = Field(..., description="Trading symbol, e.g. 'BTC'.")
    generated_at: str = Field(..., description="ISO-8601 UTC timestamp.")
    period_days: int = Field(..., gt=0, description="Sample length in days.")
    horizons_h: List[int] = Field(..., description="Forward-return horizons tested.")
    factors: List[FactorEntry] = Field(..., description="One entry per factor.")


# ---------------------------------------------------------------------------
# 2. Strategy manifest — research/manifests/<strategy_id>/manifest.json
# ---------------------------------------------------------------------------


class SpecBlock(_Manifest):
    """The strategy specification (stage 2 output)."""

    source_run: Optional[str] = Field(
        default=None, description="Run dir this block was derived from, if any."
    )
    strategy_id: str
    symbol: str
    spec_yaml: str = Field(..., description="Path to the strategy YAML.")
    description: Optional[str] = None


class GenerationBlock(_Manifest):
    """How the strategy was generated (LLM swarm — Tier 3 audit data)."""

    source_run: Optional[str] = None
    method: str = Field(..., description="e.g. 'crypto_trading_desk swarm'.")
    model: Optional[str] = Field(default=None, description="LLM model id.")
    rationale: Optional[str] = Field(
        default=None, description="LLM prose — post-hoc rationalisation, not evidence."
    )
    factors_used: List[str] = Field(default_factory=list)


class ReproducibilityBlock(_Manifest):
    """Stamps that let a run be reproduced (Tier 2 audit data)."""

    source_run: Optional[str] = None
    git_commit: Optional[str] = None
    config_hash: Optional[str] = None
    engine: Optional[str] = None
    data_source: Optional[str] = None
    seed: Optional[int] = None


class BacktestMetrics(_Manifest):
    """Headline metrics for one backtest run directory.

    Every metrics block carries ``source_run`` so the dashboard can trace each
    number back to a concrete run directory.
    """

    source_run: str = Field(..., description="Run directory this block came from.")
    sharpe: Optional[float] = None
    max_drawdown: Optional[float] = Field(
        default=None, description="Positive fraction, e.g. 0.08 == 8%."
    )
    trades: Optional[int] = Field(default=None, ge=0)
    profit_factor: Optional[float] = None
    total_return: Optional[float] = None
    win_rate: Optional[float] = None


class WalkForwardWindow(_Manifest):
    """One walk-forward window's out-of-sample result."""

    window: str = Field(..., description="Window label, e.g. '2023-Q1'.")
    sharpe: Optional[float] = None
    total_return: Optional[float] = None


class WalkForwardBlock(_Manifest):
    source_run: str
    windows: List[WalkForwardWindow] = Field(default_factory=list)


class MonteCarloBlock(_Manifest):
    """Monte-Carlo resampling: the 95% CI of the return distribution."""

    source_run: str
    n_simulations: Optional[int] = Field(default=None, ge=0)
    ci_low: Optional[float] = Field(default=None, description="95% CI lower bound.")
    ci_high: Optional[float] = Field(default=None, description="95% CI upper bound.")
    ci_crosses_zero: Optional[bool] = Field(
        default=None, description="True if the 95% CI straddles zero (a fail signal)."
    )


class BenchmarkBlock(_Manifest):
    """Strategy performance vs a HODL benchmark."""

    source_run: str
    strategy_return: Optional[float] = None
    hodl_return: Optional[float] = None
    excess_return: Optional[float] = None
    beats_hodl: Optional[bool] = None


class RegimeMetrics(_Manifest):
    """Metrics for the strategy within a single market regime."""

    regime: str = Field(..., description="Regime label, e.g. 'bull', 'bear', 'chop'.")
    source_run: str
    sharpe: Optional[float] = None
    max_drawdown: Optional[float] = None
    total_return: Optional[float] = None
    trades: Optional[int] = Field(default=None, ge=0)


class CostStressLevel(_Manifest):
    """One fee/slippage stress scenario."""

    label: str = Field(..., description="Scenario label, e.g. 'baseline', '2x', '3x'.")
    source_run: str
    fee_multiplier: float = Field(..., gt=0)
    sharpe: Optional[float] = None
    total_return: Optional[float] = None
    profit_factor: Optional[float] = None


class CostStressBlock(_Manifest):
    """The cost-stress sweep — exposes the 'alpha is a fee illusion' failure."""

    source_run: str
    levels: List[CostStressLevel] = Field(default_factory=list)


class BacktestBlock(_Manifest):
    """All backtest results for a strategy, aggregated across run directories."""

    in_sample: BacktestMetrics
    oos: Optional[BacktestMetrics] = Field(
        default=None, description="Out-of-sample run; null until OOS run exists."
    )
    walk_forward: Optional[WalkForwardBlock] = None
    monte_carlo: Optional[MonteCarloBlock] = None
    benchmark: Optional[BenchmarkBlock] = None
    by_regime: List[RegimeMetrics] = Field(default_factory=list)
    cost_stress: Optional[CostStressBlock] = None


class OptimizationBlock(_Manifest):
    """Stage 4 optimization output (parameter sweep)."""

    source_run: Optional[str] = None
    method: Optional[str] = Field(default=None, description="e.g. 'quant_strategy_desk swarm'.")
    swept_params: List[str] = Field(default_factory=list)
    best_params: Dict[str, float] = Field(default_factory=dict)
    improvement_summary: Optional[str] = None


class DiagnosisBlock(_Manifest):
    """Stage 3 diagnosis output — drives the explicit feedback loop."""

    source_run: Optional[str] = None
    recommended_action: RecommendedAction
    summary: Optional[str] = None
    findings: List[str] = Field(default_factory=list)


class GateThreshold(_Manifest):
    """One gate criterion's pass/fail evaluation."""

    name: str = Field(..., description="Threshold identifier, e.g. 'min_sharpe'.")
    threshold: float = Field(..., description="Required value.")
    actual: Optional[float] = Field(
        default=None, description="Observed value; null if not yet measured."
    )
    passed: bool = Field(..., description="Whether this criterion passed.")
    fatal: bool = Field(
        default=False, description="True for the two non-overridable FATAL gates."
    )


class GateBlock(_Manifest):
    """GO/NO-GO gate result. Computation of these values is task 2.12."""

    source_run: Optional[str] = None
    thresholds: List[GateThreshold] = Field(
        ..., description="Per-criterion pass/fail breakdown."
    )
    overall_pass: bool = Field(..., description="True only if every gate passed.")
    fatal_fail: bool = Field(
        ..., description="True if any FATAL gate failed (hard block, no override)."
    )
    red_flags: List[RedFlagCode] = Field(
        default_factory=list, description="Auto-derived red-flag codes."
    )


class StrategyManifest(_Manifest):
    """Top-level strategy manifest, written progressively across stages 2-5.

    Only ``spec`` is required: a manifest may exist after stage 2 with later
    blocks still null. ``gate`` is computed once enough backtest blocks exist.
    """

    schema_version: int = Field(default=1, ge=1)
    strategy_id: str
    symbol: str
    generated_at: str = Field(..., description="ISO-8601 UTC timestamp.")
    pipeline_stage: int = Field(
        ..., ge=1, le=5, description="Highest pipeline stage completed (1-5)."
    )
    spec: SpecBlock
    generation: Optional[GenerationBlock] = None
    reproducibility: Optional[ReproducibilityBlock] = None
    backtest: Optional[BacktestBlock] = None
    optimization: Optional[OptimizationBlock] = None
    diagnosis: Optional[DiagnosisBlock] = None
    gate: Optional[GateBlock] = None


# ---------------------------------------------------------------------------
# Selection manifest — research/manifests/selection.json (stage 5 output)
# ---------------------------------------------------------------------------


class SelectionEntry(_Manifest):
    """One strategy's ranking in the stage-5 selection."""

    strategy_id: str
    symbol: str
    rank: int = Field(..., ge=1)
    score: float
    selected: bool = Field(..., description="Whether this strategy was selected.")


class SelectionManifest(_Manifest):
    """Stage 5 selection result — ranks all gate-passing strategies."""

    schema_version: int = Field(default=1, ge=1)
    generated_at: str = Field(..., description="ISO-8601 UTC timestamp.")
    method: Optional[str] = Field(default=None, description="Scoring method used.")
    ranking: List[SelectionEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3. Testnet status — runs/testnet/<id>/testnet_status.json
# ---------------------------------------------------------------------------


class LiveBlock(_Manifest):
    """Current live testnet state."""

    started_at: str = Field(..., description="ISO-8601 UTC timestamp.")
    updated_at: str = Field(..., description="ISO-8601 UTC timestamp.")
    status: str = Field(..., description="e.g. 'running', 'paused', 'stopped'.")
    equity: Optional[float] = None
    open_positions: int = Field(default=0, ge=0)
    trades: int = Field(default=0, ge=0)
    sharpe: Optional[float] = None
    max_drawdown: Optional[float] = None


class VsBacktestBlock(_Manifest):
    """Live vs backtest comparison."""

    live_sharpe: Optional[float] = None
    backtest_sharpe: Optional[float] = None
    sharpe_ratio: Optional[float] = Field(
        default=None, description="live_sharpe / backtest_sharpe."
    )
    live_slippage: Optional[float] = None
    assumed_slippage: Optional[float] = None
    unfilled_orders: int = Field(default=0, ge=0)


class KillswitchBlock(_Manifest):
    """Kill-switch state and thresholds (DD-based)."""

    triggered: bool = Field(default=False)
    triggered_at: Optional[str] = None
    reason: Optional[str] = None
    pause_drawdown: float = Field(
        default=0.05, description="Drawdown fraction that pauses trading."
    )
    terminate_drawdown: float = Field(
        default=0.07, description="Drawdown fraction that terminates trading."
    )


class TestnetAlert(_Manifest):
    """A single monitoring alert."""

    timestamp: str = Field(..., description="ISO-8601 UTC timestamp.")
    severity: str = Field(..., description="e.g. 'info', 'warning', 'critical'.")
    message: str


class TestnetStatus(_Manifest):
    """Top-level testnet status manifest."""

    # The name starts with "Test" — tell pytest this is not a test class.
    __test__ = False

    schema_version: int = Field(default=1, ge=1)
    testnet_id: str
    strategy_id: str
    symbol: str
    live: LiveBlock
    vs_backtest: Optional[VsBacktestBlock] = None
    killswitch: KillswitchBlock
    alerts: List[TestnetAlert] = Field(default_factory=list)
