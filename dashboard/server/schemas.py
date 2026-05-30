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

1. FactorManifest      -> research/manifests/factor_<symbol>.json
2. StrategyManifest    -> research/manifests/<strategy_id>/manifest.json
3. TestnetStatus       -> runs/testnet/<id>/testnet_status.json
4. CandidatesManifest  -> research/manifests/candidates_<symbol>.json

A small SelectionManifest is also modelled for research/manifests/selection.json
(stage 5 output), so its sample fixture can be validated.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    """Disposition of a factor based on |IC| (rule lives in factor_extended.verdict_from_ic).

    |IC| >= 0.10           -> single_use
    0.03 <= |IC| < 0.10    -> ensemble_only
    |IC| < 0.03            -> reject

    Lowered ensemble_only floor from 0.05 → 0.03 on 2026-05-27 to widen the
    candidate funnel; see ADR project_stage1_verdict_gate_lowering_adr.
    """

    SINGLE_USE = "single_use"
    ENSEMBLE_ONLY = "ensemble_only"
    REJECT = "reject"
    DATA_UNAVAILABLE = "data_unavailable"


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


class LiveStatus(str, Enum):
    """Operational state of a testnet run."""

    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class AlertSeverity(str, Enum):
    """Severity level for a testnet monitoring alert."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


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

    Invariant: ``stability`` must be null whenever ``cross_regime_ic`` is null.
    """

    name: str = Field(..., description="Factor identifier, e.g. 'funding_rate'.")
    # NOTE: schema does not cross-validate that ic_by_horizon keys match
    # FactorManifest.horizons_h — producers are responsible for consistency.
    ic_by_horizon: Dict[int, Optional[float]] = Field(
        ...,
        description="Map of forward-return horizon (hours) -> Spearman IC. Value null when sample insufficient (e.g. sparse OI history from API limits).",
    )
    ir: float = Field(..., description="Information ratio (mean rolling IC / std).")
    sample_size: int = Field(..., ge=0, description="Paired observations used.")
    cross_regime_ic: Optional[Dict[str, Optional[float]]] = Field(
        default=None,
        description="Map of regime label -> IC; null until task 2.3 has run. Inner value may be null when a regime has insufficient samples for that factor.",
    )
    stability: Optional[FactorStability] = Field(
        default=None,
        description="regime_stable / conditional; null until cross-regime done.",
    )
    verdict: FactorVerdict = Field(
        ..., description="single_use / ensemble_only / reject."
    )

    @model_validator(mode="after")
    def cross_regime_fields_are_consistent(self):
        if self.cross_regime_ic is None and self.stability is not None:
            raise ValueError("stability must be null when cross_regime_ic is null")
        return self


class FactorManifest(_Manifest):
    """Top-level factor manifest for one symbol."""

    schema_version: int = Field(default=1, ge=1, le=1)
    symbol: str = Field(..., description="Trading symbol, e.g. 'BTC'.")
    generated_at: datetime = Field(..., description="ISO-8601 UTC timestamp.")
    period_days: int = Field(..., gt=0, description="Sample length in days.")
    # NOTE: schema does not cross-validate that horizons_h matches FactorEntry.ic_by_horizon keys.
    horizons_h: List[int] = Field(..., description="Forward-return horizons tested.")
    factors: List[FactorEntry] = Field(..., description="One entry per factor.")


# ---------------------------------------------------------------------------
# 0. Factor candidates — stage 0 output / stage 1 input
# ---------------------------------------------------------------------------


class FactorCandidate(_Manifest):
    name: str = Field(..., description="因子識別名，例 'funding_z_30d'。")
    formula: str = Field(..., description="自然語 + 虛擬公式，供人工審閱，stage 1 不直接 eval。")
    feature_key: Optional[str] = None
    data_source: Optional[str] = Field(default=None, description="對應 SOURCE_REGISTRY 的 key，例 'okx_funding'。")
    transform: Optional[str] = Field(default=None, description="對應 TRANSFORM_REGISTRY 的 key，例 'z_30d'。")
    expected_ic_sign: Literal["+", "-", "?"] = Field(..., description="預期 IC 符號：'+' 正向、'-' 反向、'?' 未知。")
    economic_logic: str = Field(..., description="為何此因子具備 alpha 的經濟邏輯解釋。")
    horizons_h: List[int] = Field(..., description="候選因子適用的前向報酬時窗（小時）清單。")
    category: Literal[
        "funding",
        "basis",
        "oi",
        "momentum",
        "volatility",
        "stablecoin",
        "whale",
        "skew",
    ] = Field(..., description="訊號類別：funding / basis / oi / momentum / volatility / stablecoin / whale / skew。")


class EvidenceEntry(_Manifest):
    feature_key: str = Field(..., description="Column name in the feature parquet store.")
    category: str = Field(..., description="Indicator category, e.g. momentum/trend/volatility/volume.")
    ic_by_horizon: Dict[int, Optional[float]] = Field(..., description="Horizon hours → Spearman IC.")
    ir: float = Field(..., description="Information ratio.")
    sample_size: int = Field(..., ge=0, description="Number of paired observations.")


class CandidatesManifest(_Manifest):
    schema_version: int = Field(default=1, ge=1, le=1, description="Schema 版本，目前固定為 1。")
    symbol: str = Field(..., description="交易標的短名，例 'eth'。")
    generated_at: datetime = Field(..., description="ISO-8601 UTC 時間戳記。")
    source_swarm_run: Optional[str] = Field(default=None, description="產出此 manifest 的 swarm run id；null 表示非 swarm 產出。")
    candidates: List[FactorCandidate] = Field(..., description="候選因子清單，每項為 FactorCandidate。")


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
        default=None, ge=0.0, le=1.0, description="Positive fraction, e.g. 0.08 == 8%."
    )
    trades: Optional[int] = Field(default=None, ge=0)
    profit_factor: Optional[float] = Field(default=None, ge=0.0)
    total_return: Optional[float] = None
    win_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)


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

    # source_run is the parent sweep run; each CostStressLevel also carries its
    # own source_run which may differ (e.g. a sub-run per fee scenario).
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

    @model_validator(mode="after")
    def gate_flags_are_consistent(self):
        all_passed = all(t.passed for t in self.thresholds)
        any_fatal_failed = any(t.fatal and not t.passed for t in self.thresholds)

        if self.overall_pass and not all_passed:
            raise ValueError(
                "overall_pass may be True only if every threshold has passed=True"
            )
        if self.fatal_fail and not any_fatal_failed:
            raise ValueError(
                "fatal_fail may be True only if at least one fatal threshold has passed=False"
            )
        if not self.fatal_fail and any_fatal_failed:
            raise ValueError(
                "fatal_fail must be True when any fatal threshold has passed=False"
            )
        return self


class StrategyManifest(_Manifest):
    """Top-level strategy manifest, written progressively across stages 2-5.

    Only ``spec`` is required: a manifest may exist after stage 2 with later
    blocks still null. ``gate`` is computed once enough backtest blocks exist.
    """

    schema_version: int = Field(default=1, ge=1, le=1)
    strategy_id: str
    symbol: str
    generated_at: datetime = Field(..., description="ISO-8601 UTC timestamp.")
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

    schema_version: int = Field(default=1, ge=1, le=1)
    generated_at: datetime = Field(..., description="ISO-8601 UTC timestamp.")
    method: Optional[str] = Field(default=None, description="Scoring method used.")
    ranking: List[SelectionEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 3. Testnet status — runs/testnet/<id>/testnet_status.json
# ---------------------------------------------------------------------------


class LiveBlock(_Manifest):
    """Current live testnet state."""

    started_at: datetime = Field(..., description="ISO-8601 UTC timestamp.")
    updated_at: datetime = Field(..., description="ISO-8601 UTC timestamp.")
    status: LiveStatus = Field(..., description="running / paused / stopped.")
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
    triggered_at: Optional[datetime] = None
    reason: Optional[str] = None
    pause_drawdown: float = Field(
        default=0.05, description="Drawdown fraction that pauses trading."
    )
    terminate_drawdown: float = Field(
        default=0.07, description="Drawdown fraction that terminates trading."
    )


class TestnetAlert(_Manifest):
    """A single monitoring alert."""

    timestamp: datetime = Field(..., description="ISO-8601 UTC timestamp.")
    severity: AlertSeverity = Field(..., description="info / warning / critical.")
    message: str


class TestnetStatus(_Manifest):
    """Top-level testnet status manifest."""

    # The name starts with "Test" — tell pytest this is not a test class.
    __test__ = False

    schema_version: int = Field(default=1, ge=1, le=1)
    testnet_id: str
    strategy_id: str
    symbol: str
    live: LiveBlock
    vs_backtest: Optional[VsBacktestBlock] = None
    killswitch: KillswitchBlock
    alerts: List[TestnetAlert] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 2b — signal-engine compiler schemas
# ---------------------------------------------------------------------------

# DSL patterns for entry condition strings
_PERSIST_SUFFIX_RE = re.compile(r"\s+persist\s+(\d+)/(\d+)$")
_INDICATOR_PERCENTILE_RE = re.compile(r"^([a-z][a-z0-9_]*_percentile_\d+d)\s+(<=|>=|<|>|==)\s+(-?\d+(?:\.\d+)?)")
_INDICATOR_ZSCORE_RE = re.compile(r"^([a-z][a-z0-9_]*_zscore_\d+d)\s+(<=|>=|<|>|==)\s+(-?\d+(?:\.\d+)?)")
_INDICATOR_RAW_RE = re.compile(r"^([a-z][a-z0-9_]*)\s+(<=|>=|<|>|==)\s+(-?\d+(?:\.\d+)?)")


def _parse_condition(cond: str) -> tuple:
    """Parse a DSL entry condition string into a structured tuple.

    DSL forms:
      <indicator>_percentile_<n>d <op> <value> [persist <m>/<n>]
      <indicator>_zscore_<n>d <op> <value> [persist <m>/<n>]
      <indicator> <op> <value> [persist <m>/<n>]

    Returns:
        (indicator_expr: str, op: str, value: float,
         persist_m: Optional[int], persist_n: Optional[int])

    Raises:
        ValueError: if the condition does not match any recognised DSL pattern.
    """
    cond = cond.rstrip()

    # Extract optional persist suffix first
    persist_m: Optional[int] = None
    persist_n: Optional[int] = None
    persist_match = _PERSIST_SUFFIX_RE.search(cond)
    if persist_match:
        persist_m = int(persist_match.group(1))
        persist_n = int(persist_match.group(2))
        cond = cond[: persist_match.start()]

    # Try each pattern in order of specificity
    for pattern in (_INDICATOR_PERCENTILE_RE, _INDICATOR_ZSCORE_RE, _INDICATOR_RAW_RE):
        m = pattern.match(cond.strip())
        if m:
            indicator_expr = m.group(1)
            op = m.group(2)
            value = float(m.group(3))
            return (indicator_expr, op, value, persist_m, persist_n)

    raise ValueError(f"Unrecognised condition DSL: {cond!r}")


# ---------------------------------------------------------------------------
# 4. IndicatorSpec — references a stage1 factor output
# ---------------------------------------------------------------------------


class IndicatorSpec(_Manifest):
    """Spec for one indicator referenced in a StrategySpec."""

    source: str = Field(
        ...,
        description="Stage-1 factor output key, e.g. 'stage1:funding_zscore_30d'.",
        pattern=r"^stage1:[a-z][a-z0-9_]*$",
    )
    smoothing: str = Field(
        ...,
        description="Smoothing applied before signal comparison: none, sma_<n>, or ema_<n>.",
        pattern=r"^(none|sma_\d+|ema_\d+)$",
    )


# ---------------------------------------------------------------------------
# 5. EntryBlock — one directional entry rule
# ---------------------------------------------------------------------------


class EntryBlock(_Manifest):
    """Long or short entry specification with DSL conditions."""

    description: str
    conditions: List[str] = Field(..., description="DSL condition strings.")
    logic: Literal["all", "any"] = Field(
        default="all",
        description=(
            "How to combine multiple conditions: 'all' = AND (consensus, "
            "default — backward-compatible), 'any' = OR (majority-of-1, useful "
            "when each factor independently has edge but their intersection "
            "is too sparse for meaningful trade counts)."
        ),
    )

    @field_validator("conditions", mode="after")
    @classmethod
    def conditions_are_valid_dsl(cls, v: List[str]) -> List[str]:
        for idx, cond in enumerate(v):
            try:
                _parse_condition(cond)
            except ValueError as exc:
                raise ValueError(f"conditions[{idx}] is invalid: {exc}") from exc
        return v


# ---------------------------------------------------------------------------
# 6. ExitRule — discriminated union of exit rule variants
# ---------------------------------------------------------------------------


class _ExitTimeBased(_Manifest):
    condition: Literal["time_based"]
    max_hold_hours: int


class _ExitTakeProfit(_Manifest):
    condition: Literal["take_profit_pct"]
    value: float


class _ExitStopLoss(_Manifest):
    condition: Literal["stop_loss_pct"]
    value: float


_SIGNAL_INVALIDATION_EXPR_RE = re.compile(
    r"^[a-z][a-z0-9_]*_percentile_\d+d between \d+(\.\d+)?,\d+(\.\d+)?$"
)


class _ExitSignalInvalidation(_Manifest):
    condition: Literal["signal_invalidation"]
    expression: str = Field(..., description="Percentile-range DSL expression.")

    @field_validator("expression", mode="after")
    @classmethod
    def expression_matches_dsl(cls, v: str) -> str:
        if not _SIGNAL_INVALIDATION_EXPR_RE.match(v):
            raise ValueError(
                f"expression must match '<indicator>_percentile_<n>d between <lo>,<hi>'; got {v!r}"
            )
        return v


ExitRule = Annotated[
    Union[
        _ExitTimeBased,
        _ExitTakeProfit,
        _ExitStopLoss,
        _ExitSignalInvalidation,
    ],
    Field(discriminator="condition"),
]


# ---------------------------------------------------------------------------
# 7. StrategySpec — top-level compiler input (from stage 2 YAML)
# ---------------------------------------------------------------------------


class StrategySpec(_Manifest):
    """Structured representation of a stage-2 YAML strategy specification.

    Compiler-relevant fields are strictly typed; stage-2 attaches extra
    metadata (hypothesis, hold_period, position_sizing, parameter_search_ranges,
    expected_behavior, caveats) for humans/dashboard that the compiler ignores.
    """

    model_config = ConfigDict(extra="ignore")

    name: str
    archetype: str
    symbol: str
    timeframe_signal: Literal["1H", "4H", "8h", "1D"]
    indicators: Dict[str, IndicatorSpec]
    entry_long: Optional[EntryBlock] = None
    entry_short: Optional[EntryBlock] = None
    exit_rules: List[ExitRule]
