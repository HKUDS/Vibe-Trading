"""Schema and gate core for quant reliability scorecards."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.reliability.config import reliability_enabled
from src.reliability.quant.diagnostics import (
    CapacityDiagnosticsSummary,
    DiagnosticsReadinessReport,
    ExecutionDiagnosticsSummary,
    FactorDiagnosticsSummary,
    PortfolioDiagnosticsSummary,
)
from src.reliability.quant.scorecard_explainer import ConclusionLevel, TriggeredRule


SCORECARD_SCHEMA_VERSION = "1.0.0"

SCORECARD_DIMENSION_KEYS: frozenset[str] = frozenset(
    {
        "pit_clean",
        "oos_split",
        "cost_model",
        "benchmark",
        "trial_count",
        "execution_realism",
        "universe_pit",
        "capacity",
        "cost_sensitivity",
        "ic_stability",
        "regime_stability",
        "crowding_risk",
        "random_control",
    }
)

HARD_FAILURE_CODES: frozenset[str] = frozenset(
    {
        "PIT_FUTURE_DATA",
        "QUANT_NO_COST_MODEL_TRADABLE_CLAIM",
        "QUANT_NO_BENCHMARK_ALPHA_CLAIM",
        "QUANT_NO_OOS_GENERALIZATION_CLAIM",
        "QUANT_HISTORICAL_UNIVERSE_MISSING",
        "QUANT_EXECUTION_TIMESTAMPS_MISSING",
        "QUANT_TRIAL_COUNT_MISSING_BEST_TRIAL",
        "QUANT_ASHARE_MARKET_RULES_MISSING",
        "POLICY_DENY_IGNORED",
        "QUANT_SCORECARD_LLM_OVERRIDE_ATTEMPT",
        "QUANT_HIGH_CROWDING_NO_STRESS_TEST",
        "QUANT_REGIME_NEGATIVE_IC_NO_ACTIVATION",
        "QUANT_IS_IC_NEAR_ZERO",
    }
)

ConclusionCap = Literal[
    "exploratory",
    "research_candidate",
    "paper_trade_candidate",
    "not_reliable",
]


class QuantIssue(BaseModel):
    """Structured warning or hard failure for scorecard gates."""

    model_config = ConfigDict(allow_inf_nan=False)

    code: str
    severity: Literal["info", "warning", "hard_failure"] = "warning"
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionTimestampSet(BaseModel):
    """Execution realism timestamps required for tradability claims."""

    model_config = ConfigDict(allow_inf_nan=False)

    signal_time: bool = True
    decision_time: bool = True
    order_time: bool = True
    fill_time: bool = True
    price_time: bool = True

    def missing_fields(self) -> list[str]:
        """Return timestamp labels that are not available."""
        return [
            name
            for name in (
                "signal_time",
                "decision_time",
                "order_time",
                "fill_time",
                "price_time",
            )
            if not bool(getattr(self, name))
        ]

    def all_present(self) -> bool:
        """Return whether every required execution timestamp is present."""
        return not self.missing_fields()


class ClaimSet(BaseModel):
    """Legacy compact claims made by a result/report that require evidence gates."""

    model_config = ConfigDict(allow_inf_nan=False)

    tradable: bool = False
    paper_tradable: bool = False
    live_tradable: bool = False
    generalization: bool = False
    alpha: bool = False
    best_trial: bool = False

    def claims_tradability(self) -> bool:
        """Return whether any claim implies paper/live/tradable readiness."""
        return self.tradable or self.paper_tradable or self.live_tradable


class EvidenceSet(BaseModel):
    """Evidence available to the scorecard gate."""

    model_config = ConfigDict(allow_inf_nan=False)

    cost_model_present: bool = True
    oos_present: bool = True
    benchmark_present: bool = True
    trial_count: int | None = 1
    execution_timestamps: ExecutionTimestampSet = Field(default_factory=ExecutionTimestampSet)
    pit_violation_codes: list[str] = Field(default_factory=list)
    historical_universe_present: bool = True
    ashare_market_rules_present: bool = True
    policy_denies_ignored: bool = False
    llm_override_attempt: bool = False
    high_crowding_without_stress: bool = False
    regime_negative_ic_without_activation: bool = False
    random_control_present: bool = True


class ScorecardInputs(BaseModel):
    """Inputs used to derive a scorecard from existing artifacts/metadata."""

    model_config = ConfigDict(allow_inf_nan=False)

    scorecard_id: str
    protocol_ref: str | None = None
    data_audit_refs: list[str] = Field(default_factory=list)
    backtest_refs: list[str] = Field(default_factory=list)
    alpha_bench_refs: list[str] = Field(default_factory=list)
    claims: ClaimSet = Field(default_factory=ClaimSet)
    evidence: EvidenceSet = Field(default_factory=EvidenceSet)
    score_breakdown: dict[str, float] | None = None
    warnings: list[QuantIssue] = Field(default_factory=list)
    hard_failures: list[QuantIssue] = Field(default_factory=list)
    experimental_metrics: dict[str, Any] = Field(default_factory=dict)


class BacktestReliabilityScorecard(BaseModel):
    """Schema-versioned scorecard with v1.2.1 policy/audit extensions."""

    model_config = ConfigDict(allow_inf_nan=False, arbitrary_types_allowed=False, extra="ignore")

    scorecard_id: str = Field(default_factory=lambda: f"sc_{uuid4().hex}")
    schema_version: str = SCORECARD_SCHEMA_VERSION
    run_id: str | None = None
    protocol_ref: str | None = None
    data_audit_refs: list[str] = Field(default_factory=list)
    backtest_refs: list[str] = Field(default_factory=list)
    alpha_bench_refs: list[str] = Field(default_factory=list)
    score: float = 0.0
    score_breakdown: dict[str, float] = Field(default_factory=lambda: {key: 0.0 for key in SCORECARD_DIMENSION_KEYS})
    conclusion_cap: ConclusionCap = "exploratory"
    conclusion_level: ConclusionLevel = "exploratory"
    crowding: dict[str, Any] | None = None
    regime_ic: dict[str, Any] | None = None
    walk_forward: dict[str, Any] | None = None
    ic_horizons: list[dict[str, Any]] = Field(default_factory=list)
    cost_sensitivity: dict[str, Any] | None = None
    capacity: dict[str, Any] | None = None
    execution_realism: dict[str, Any] | None = None
    neutralized_ic: dict[str, Any] | None = None
    random_control: dict[str, Any] | None = None
    warnings: list[QuantIssue | str] = Field(default_factory=list)
    hard_failures: list[QuantIssue | str] = Field(default_factory=list)
    experimental_metrics: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    triggered_rules: list[TriggeredRule] = Field(default_factory=list)
    policy_rule_version: str | None = None
    claim_set_ref: str | None = None
    methodology_fact_ref: str | None = None
    policy_decision_ids: list[str] = Field(default_factory=list)
    market: str | None = None
    override_attempted: bool = False
    factor_diagnostics: FactorDiagnosticsSummary | None = None
    portfolio_diagnostics: PortfolioDiagnosticsSummary | None = None
    execution_diagnostics: ExecutionDiagnosticsSummary | None = None
    capacity_diagnostics: CapacityDiagnosticsSummary | None = None
    diagnostics_readiness: DiagnosticsReadinessReport | None = None

    @model_validator(mode="before")
    @classmethod
    def _fill_legacy_defaults(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        run_id = data.get("run_id")
        if not data.get("scorecard_id") and run_id:
            data["scorecard_id"] = f"sc_{run_id}"
        data.setdefault("score", 0.0)
        data.setdefault("score_breakdown", {key: 0.0 for key in SCORECARD_DIMENSION_KEYS})
        if data.get("conclusion_level") and not data.get("conclusion_cap"):
            level = data["conclusion_level"]
            data["conclusion_cap"] = level if level in {"not_reliable", "exploratory", "research_candidate", "paper_trade_candidate"} else "paper_trade_candidate"
        if data.get("conclusion_cap") and not data.get("conclusion_level"):
            data["conclusion_level"] = data["conclusion_cap"]
        data["warnings"] = [] if data.get("warnings") is None else data.get("warnings", [])
        data["hard_failures"] = [] if data.get("hard_failures") is None else data.get("hard_failures", [])
        data["policy_decision_ids"] = [] if data.get("policy_decision_ids") is None else data.get("policy_decision_ids", [])
        return data

    @model_validator(mode="before")
    @classmethod
    def _reject_unknown_score_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        breakdown = value.get("score_breakdown")
        if isinstance(breakdown, dict):
            unknown = set(breakdown) - SCORECARD_DIMENSION_KEYS
            if unknown:
                raise ValueError(f"unknown score_breakdown keys: {sorted(unknown)}")
        return value

    @field_validator("score")
    @classmethod
    def _score_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite")
        return float(value)

    @field_validator("score_breakdown")
    @classmethod
    def _breakdown_values_are_finite(cls, value: dict[str, float]) -> dict[str, float]:
        normalized: dict[str, float] = {}
        for key, item in value.items():
            if key not in SCORECARD_DIMENSION_KEYS:
                raise ValueError(f"unknown score_breakdown key: {key}")
            as_float = float(item)
            if not math.isfinite(as_float):
                raise ValueError(f"score_breakdown[{key}] must be finite")
            normalized[key] = as_float
        return normalized

    @field_validator("triggered_rules", mode="before")
    @classmethod
    def _triggered_rules_tolerate_missing(cls, value: object) -> object:
        return [] if value is None else value

    @model_validator(mode="after")
    def _fill_missing_dimensions(self) -> "BacktestReliabilityScorecard":
        missing = sorted(SCORECARD_DIMENSION_KEYS - set(self.score_breakdown))
        if missing:
            self.score_breakdown = {
                **{key: 0.0 for key in sorted(SCORECARD_DIMENSION_KEYS)},
                **self.score_breakdown,
            }
            if not any(_issue_code(issue) == "QUANT_SCORECARD_DIMENSION_DEFAULTED" for issue in self.warnings):
                self.warnings.append(
                    QuantIssue(
                        code="QUANT_SCORECARD_DIMENSION_DEFAULTED",
                        severity="warning",
                        message="missing scorecard dimensions defaulted to zero",
                        metadata={"dimensions": missing},
                    )
                )
        else:
            self.score_breakdown = {key: float(self.score_breakdown[key]) for key in sorted(SCORECARD_DIMENSION_KEYS)}
        return self

    @classmethod
    def minimal(
        cls,
        *,
        scorecard_id: str,
        warnings: list[QuantIssue] | None = None,
        hard_failures: list[QuantIssue] | None = None,
        conclusion_cap: ConclusionCap | None = None,
    ) -> "BacktestReliabilityScorecard":
        """Create a zeroed scorecard with the fixed dimensions."""
        failures = list(hard_failures or [])
        cap = conclusion_cap or ("not_reliable" if failures else "exploratory")
        return cls(
            scorecard_id=scorecard_id,
            schema_version=SCORECARD_SCHEMA_VERSION,
            score=0.0,
            score_breakdown={key: 0.0 for key in SCORECARD_DIMENSION_KEYS},
            conclusion_cap=cap,
            conclusion_level=cap,
            warnings=list(warnings or []),
            hard_failures=failures,
        )


def should_generate_scorecard() -> bool:
    """Return whether reliability scorecard artifacts should be generated."""
    return reliability_enabled()


def build_scorecard(inputs: ScorecardInputs) -> BacktestReliabilityScorecard:
    """Derive a scorecard from evidence and claims."""
    breakdown = {key: 1.0 for key in SCORECARD_DIMENSION_KEYS}
    if inputs.score_breakdown is not None:
        breakdown.update(inputs.score_breakdown)

    warnings: list[QuantIssue | str] = list(inputs.warnings)
    hard_failures: list[QuantIssue | str] = list(inputs.hard_failures)
    evidence = inputs.evidence
    claims = inputs.claims
    cap: ConclusionCap = "paper_trade_candidate"

    if evidence.pit_violation_codes:
        breakdown["pit_clean"] = 0.0
        for code in evidence.pit_violation_codes:
            hard_failures.append(_hard_failure(code, "PIT violation detected"))

    if not evidence.cost_model_present:
        breakdown["cost_model"] = 0.0
        cap = _cap_at_research_candidate(cap)
        warnings.append(_warning("QUANT_COST_MODEL_MISSING", "cost model is missing"))
        if claims.claims_tradability():
            hard_failures.append(
                _hard_failure(
                    "QUANT_NO_COST_MODEL_TRADABLE_CLAIM",
                    "tradability claim requires a cost model",
                )
            )

    if not evidence.oos_present:
        breakdown["oos_split"] = 0.0
        cap = _cap_at_research_candidate(cap)
        warnings.append(_warning("QUANT_OOS_MISSING", "OOS or walk-forward evidence is missing"))
        if claims.generalization:
            hard_failures.append(
                _hard_failure(
                    "QUANT_NO_OOS_GENERALIZATION_CLAIM",
                    "generalization claim requires OOS or walk-forward evidence",
                )
            )

    if not evidence.benchmark_present:
        breakdown["benchmark"] = 0.0
        cap = _cap_at_research_candidate(cap)
        warnings.append(_warning("QUANT_BENCHMARK_MISSING", "benchmark evidence is missing"))
        if claims.alpha:
            hard_failures.append(
                _hard_failure(
                    "QUANT_NO_BENCHMARK_ALPHA_CLAIM",
                    "alpha claim requires benchmark evidence",
                )
            )

    if evidence.trial_count is None:
        breakdown["trial_count"] = 0.0
        cap = _cap_at_research_candidate(cap)
        warnings.append(_warning("QUANT_TRIAL_COUNT_MISSING", "trial_count is missing"))
        if claims.best_trial:
            hard_failures.append(
                _hard_failure(
                    "QUANT_TRIAL_COUNT_MISSING_BEST_TRIAL",
                    "best trial display requires trial_count",
                )
            )
    elif evidence.trial_count <= 0:
        breakdown["trial_count"] = 0.0
        warnings.append(_warning("QUANT_TRIAL_COUNT_NONPOSITIVE", "trial_count must be positive"))

    missing_timestamps = evidence.execution_timestamps.missing_fields()
    if missing_timestamps:
        breakdown["execution_realism"] = 0.0
        cap = _cap_at_research_candidate(cap)
        warnings.append(
            _warning(
                "QUANT_EXECUTION_TIMESTAMPS_MISSING",
                "execution timestamp evidence is incomplete",
                metadata={"missing": missing_timestamps},
            )
        )
        if claims.claims_tradability():
            hard_failures.append(
                _hard_failure(
                    "QUANT_EXECUTION_TIMESTAMPS_MISSING",
                    "tradability claim requires signal/decision/order/fill/price timestamps",
                    metadata={"missing": missing_timestamps},
                )
            )

    if not evidence.historical_universe_present:
        breakdown["universe_pit"] = 0.0
        hard_failures.append(
            _hard_failure(
                "QUANT_HISTORICAL_UNIVERSE_MISSING",
                "historical universe membership is missing",
            )
        )

    if not evidence.ashare_market_rules_present and claims.claims_tradability():
        hard_failures.append(
            _hard_failure(
                "QUANT_ASHARE_MARKET_RULES_MISSING",
                "A-share tradability claim requires market-rule coverage",
            )
        )

    if evidence.policy_denies_ignored:
        hard_failures.append(_hard_failure("POLICY_DENY_IGNORED", "policy deny was ignored"))

    if evidence.llm_override_attempt:
        hard_failures.append(
            _hard_failure(
                "QUANT_SCORECARD_LLM_OVERRIDE_ATTEMPT",
                "scorecard or conclusion gate override was attempted",
            )
        )

    if evidence.high_crowding_without_stress:
        breakdown["crowding_risk"] = 0.0
        hard_failures.append(
            _hard_failure(
                "QUANT_HIGH_CROWDING_NO_STRESS_TEST",
                "high crowding risk requires stress testing",
            )
        )

    if evidence.regime_negative_ic_without_activation:
        breakdown["regime_stability"] = 0.0
        hard_failures.append(
            _hard_failure(
                "QUANT_REGIME_NEGATIVE_IC_NO_ACTIVATION",
                "negative regime IC requires regime-conditional activation",
            )
        )

    if not evidence.random_control_present:
        breakdown["random_control"] = 0.0
        cap = _cap_at_research_candidate(cap)
        warnings.append(_warning("QUANT_RANDOM_CONTROL_MISSING", "random control evidence is missing"))

    if hard_failures:
        cap = "not_reliable"

    score = sum(breakdown.values()) / len(SCORECARD_DIMENSION_KEYS)
    return BacktestReliabilityScorecard(
        scorecard_id=inputs.scorecard_id,
        schema_version=SCORECARD_SCHEMA_VERSION,
        protocol_ref=inputs.protocol_ref,
        data_audit_refs=inputs.data_audit_refs,
        backtest_refs=inputs.backtest_refs,
        alpha_bench_refs=inputs.alpha_bench_refs,
        score=round(score, 6),
        score_breakdown=breakdown,
        conclusion_cap=cap,
        conclusion_level=cap,
        warnings=warnings,
        hard_failures=hard_failures,
        experimental_metrics=inputs.experimental_metrics,
    )


def write_backtest_scorecard_artifact(
    *,
    config: dict[str, Any],
    metrics: dict[str, Any],
    run_dir: Path,
) -> Any | None:
    """Build and persist a backtest scorecard artifact, mutating config refs."""
    if not should_generate_scorecard():
        return None

    from src.reliability.artifacts.store import ArtifactStore

    card = build_scorecard(_scorecard_inputs_from_backtest(config, metrics, run_dir))
    record = ArtifactStore().write_json(
        card.model_dump(mode="json"),
        artifact_type="scorecard",
        generated_by="quant_scorecard.backtest",
        metadata={
            "surface": "backtest",
            "run_dir": str(run_dir),
            "metric_keys": sorted(str(key) for key in metrics),
        },
        parent_artifacts=[
            str(ref.get("artifact_id"))
            for ref in config.get("_irr_artifact_refs", [])
            if isinstance(ref, dict) and ref.get("artifact_id")
        ],
        schema_version=card.schema_version,
    )
    if record is None:
        return None

    ref = record.to_ref().model_dump(mode="json")
    config.setdefault("_quant_scorecard_refs", []).append(ref)
    config.setdefault("_irr_artifact_refs", []).append(ref)
    return record


def build_alpha_bench_scorecard(
    strict_result: dict[str, Any],
    *,
    scorecard_id: str | None = None,
) -> BacktestReliabilityScorecard:
    """Build a scorecard from existing strict alpha-bench random-control output."""
    random_control_present = bool(strict_result.get("random_control"))
    rows = [
        _strict_random_control_row(row)
        for row in strict_result.get("rows", [])
        if isinstance(row, dict)
    ]
    oos_present = bool(strict_result.get("oos_split")) or any(
        row.get("alpha_t_train") is not None and row.get("alpha_t_test") is not None
        for row in rows
    )
    card = build_scorecard(
        ScorecardInputs(
            scorecard_id=scorecard_id or f"sc_{uuid4().hex}",
            alpha_bench_refs=[str(strict_result.get("report_path"))]
            if strict_result.get("report_path")
            else [],
            evidence=EvidenceSet(
                oos_present=oos_present,
                random_control_present=random_control_present,
            ),
            score_breakdown={
                "random_control": 1.0 if random_control_present else 0.0,
                "oos_split": 1.0 if oos_present else 0.0,
                "ic_stability": 1.0 if rows else 0.0,
            },
        )
    )
    return card.model_copy(
        update={
            "random_control": {
                "source": "bench_runner_strict",
                "random_control": random_control_present,
                "n_random_seeds": strict_result.get("n_random_seeds"),
                "oos_split": strict_result.get("oos_split"),
                "rows": rows,
            }
        }
    )


def write_alpha_bench_scorecard_artifact(
    strict_result: dict[str, Any],
    *,
    scorecard_id: str | None = None,
) -> Any | None:
    """Persist an alpha-bench scorecard artifact from strict bench output."""
    if not should_generate_scorecard():
        return None

    from src.reliability.artifacts.store import ArtifactStore

    card = build_alpha_bench_scorecard(strict_result, scorecard_id=scorecard_id)
    return ArtifactStore().write_json(
        card.model_dump(mode="json"),
        artifact_type="scorecard",
        generated_by="quant_scorecard.alpha_bench_strict",
        metadata={
            "surface": "alpha_bench",
            "zoo": strict_result.get("zoo"),
            "universe": strict_result.get("universe"),
            "period": strict_result.get("period"),
        },
        schema_version=card.schema_version,
    )


def _cap_at_research_candidate(current: ConclusionCap) -> ConclusionCap:
    if current in {"not_reliable", "exploratory", "research_candidate"}:
        return current
    return "research_candidate"


def _warning(code: str, message: str, *, metadata: dict[str, Any] | None = None) -> QuantIssue:
    return QuantIssue(
        code=code,
        severity="warning",
        message=message,
        metadata=dict(metadata or {}),
    )


def _hard_failure(code: str, message: str, *, metadata: dict[str, Any] | None = None) -> QuantIssue:
    return QuantIssue(
        code=code,
        severity="hard_failure",
        message=message,
        metadata=dict(metadata or {}),
    )


def _scorecard_inputs_from_backtest(
    config: dict[str, Any],
    metrics: dict[str, Any],
    run_dir: Path,
) -> ScorecardInputs:
    claims = config.get("claims") if isinstance(config.get("claims"), dict) else {}
    timestamps = config.get("execution_timestamps") if isinstance(config.get("execution_timestamps"), dict) else {}
    validation = metrics.get("validation") if isinstance(metrics.get("validation"), dict) else {}
    walk_forward = validation.get("walk_forward") if isinstance(validation.get("walk_forward"), dict) else None
    benchmark_present = bool(
        config.get("benchmark")
        or metrics.get("benchmark_ticker")
        or config.get("benchmark_policy")
    )
    oos_present = bool(config.get("oos_present") or walk_forward)
    trial_count = config.get("trial_count")
    if trial_count is not None:
        trial_count = int(trial_count)

    return ScorecardInputs(
        scorecard_id=str(config.get("scorecard_id") or f"sc_{uuid4().hex}"),
        protocol_ref=config.get("protocol_hash") or config.get("protocol_ref"),
        data_audit_refs=[str(item) for item in config.get("_data_audit_ids", [])],
        backtest_refs=[str(run_dir)],
        claims=ClaimSet(
            tradable=bool(claims.get("tradable") or config.get("claim_tradable")),
            paper_tradable=bool(claims.get("paper_tradable") or config.get("claim_paper_tradable")),
            live_tradable=bool(claims.get("live_tradable") or config.get("claim_live_tradable")),
            generalization=bool(claims.get("generalization") or config.get("claim_generalization")),
            alpha=bool(claims.get("alpha") or config.get("claim_alpha")),
            best_trial=bool(claims.get("best_trial") or config.get("best_trial")),
        ),
        evidence=EvidenceSet(
            cost_model_present=_has_cost_model(config),
            oos_present=oos_present,
            benchmark_present=benchmark_present,
            trial_count=trial_count,
            execution_timestamps=ExecutionTimestampSet(
                signal_time=bool(timestamps.get("signal_time")),
                decision_time=bool(timestamps.get("decision_time")),
                order_time=bool(timestamps.get("order_time")),
                fill_time=bool(timestamps.get("fill_time")),
                price_time=bool(timestamps.get("price_time")),
            ) if timestamps else ExecutionTimestampSet(),
            pit_violation_codes=[str(code) for code in config.get("_pit_violation_codes", [])],
            historical_universe_present=bool(
                config.get("historical_universe_source")
                or not config.get("historical_universe_required", False)
            ),
            ashare_market_rules_present=bool(config.get("ashare_market_rules_present", True)),
            policy_denies_ignored=bool(config.get("policy_denies_ignored", False)),
            llm_override_attempt=bool(config.get("scorecard_llm_override_attempt", False)),
            high_crowding_without_stress=bool(config.get("high_crowding_without_stress", False)),
            regime_negative_ic_without_activation=bool(
                config.get("regime_negative_ic_without_activation", False)
            ),
            random_control_present=bool(config.get("random_control_present", False)),
        ),
    )


def _has_cost_model(config: dict[str, Any]) -> bool:
    if config.get("cost_model"):
        return True
    return any(
        key in config
        for key in (
            "commission_bps",
            "slippage_bps",
            "spread_bps",
            "tax_bps",
            "commission_rate",
            "slippage",
            "stamp_tax",
            "transfer_fee",
        )
    )


def _strict_random_control_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "random_ic_mean": row.get("random_ic_mean"),
        "alpha_t_full": row.get("alpha_t_full"),
        "alpha_t_train": row.get("alpha_t_train"),
        "alpha_t_test": row.get("alpha_t_test"),
        "ic_mean": row.get("ic_mean"),
        "ir": row.get("ir"),
        "category": row.get("_category") or row.get("category"),
    }


def _issue_code(issue: QuantIssue | str) -> str:
    return issue.code if isinstance(issue, QuantIssue) else str(issue)
