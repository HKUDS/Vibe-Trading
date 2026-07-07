"""No-exec scorecard policy engine over ClaimSet and MethodologyFactSet."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from src.reliability.artifacts.store import ArtifactStore
from src.reliability.claims.model import ClaimSet, ResearchClaim
from src.reliability.quant.methodology_facts import MethodologyFactSet
from src.reliability.quant.scorecard import BacktestReliabilityScorecard
from src.reliability.quant.scorecard_explainer import ConclusionLevel, RuleAction, TriggeredRule, format_triggered_rule

SCHEMA_VERSION = "1.2.1"
POLICY_RULE_VERSION = "builtin-v1.2.1"

_CONCLUSION_RANK: dict[str, int] = {
    "not_reliable": 0,
    "exploratory": 1,
    "research_candidate": 2,
    "paper_trade_candidate": 3,
    "production_ready": 4,
}


class ScorecardPolicyRule(BaseModel):
    """Declarative policy rule bound to a fixed predicate name."""

    schema_version: str = SCHEMA_VERSION
    rule_id: str
    predicate_name: str
    action: RuleAction
    reason_code: str
    explanation_template: str
    conclusion_cap: ConclusionLevel | None = None
    built_in: bool = True


class PredicateInput(BaseModel):
    """Inputs available to scorecard policy predicates."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    scorecard: BacktestReliabilityScorecard
    claim_set: ClaimSet
    methodology_facts: MethodologyFactSet
    protocol: Any | None = None
    artifact_store: ArtifactStore


class PredicateMatch(BaseModel):
    """A predicate trigger with evidence and formatting context."""

    evidence_refs: list[str] = Field(default_factory=list)
    explanation_context: dict[str, Any] = Field(default_factory=dict)


class ScorecardPolicyResult(BaseModel):
    """Result of applying scorecard policy to a scorecard."""

    scorecard: BacktestReliabilityScorecard
    triggered_rules: list[TriggeredRule] = Field(default_factory=list)


Predicate = Callable[[PredicateInput], PredicateMatch | None]


def _pit_violation_hard_fail(inputs: PredicateInput) -> PredicateMatch | None:
    if inputs.methodology_facts.pit_safe is False:
        return PredicateMatch(
            evidence_refs=_fact_refs(inputs, "pit_safe"),
            explanation_context={"fact": "pit_safe=False"},
        )
    return None


def _tradable_claim_without_cost_model(inputs: PredicateInput) -> PredicateMatch | None:
    claims = _claims(inputs, "tradable")
    if claims and not inputs.methodology_facts.has_cost_model:
        return PredicateMatch(
            evidence_refs=_claim_refs(claims) + _fact_refs(inputs, "has_cost_model"),
            explanation_context={"claim_count": len(claims), "fact": "has_cost_model=False"},
        )
    return None


def _alpha_claim_without_benchmark(inputs: PredicateInput) -> PredicateMatch | None:
    claims = _claims(inputs, "alpha")
    if claims and not inputs.methodology_facts.has_benchmark:
        return PredicateMatch(
            evidence_refs=_claim_refs(claims) + _fact_refs(inputs, "has_benchmark"),
            explanation_context={"claim_count": len(claims), "fact": "has_benchmark=False"},
        )
    return None


def _generalization_claim_without_oos(inputs: PredicateInput) -> PredicateMatch | None:
    claims = _claims(inputs, "generalization")
    if claims and not inputs.methodology_facts.has_oos:
        return PredicateMatch(
            evidence_refs=_claim_refs(claims) + _fact_refs(inputs, "has_oos"),
            explanation_context={"claim_count": len(claims), "fact": "has_oos=False"},
        )
    return None


def _paper_gate_without_all_requirements(inputs: PredicateInput) -> PredicateMatch | None:
    claims = _claims(inputs, "paper_trade_candidate")
    if not claims:
        return None
    missing = _paper_gate_missing(inputs.methodology_facts)
    if missing:
        return PredicateMatch(
            evidence_refs=_claim_refs(claims) + _fact_refs(inputs, *missing),
            explanation_context={"missing": ", ".join(missing)},
        )
    return None


def _best_trial_without_trial_count(inputs: PredicateInput) -> PredicateMatch | None:
    claims = _claims(inputs, "alpha", "generalization", "paper_trade_candidate", "production_ready")
    metrics = inputs.scorecard.metrics
    strong_result = bool(metrics.get("best_trial") or metrics.get("selected_trial") or metrics.get("sharpe"))
    if claims and strong_result and inputs.methodology_facts.trial_count is None:
        return PredicateMatch(
            evidence_refs=_claim_refs(claims) + _fact_refs(inputs, "trial_count"),
            explanation_context={"fact": "trial_count missing"},
        )
    return None


def _policy_deny_ignored(inputs: PredicateInput) -> PredicateMatch | None:
    facts = inputs.methodology_facts
    if facts.has_policy_denies and not inputs.scorecard.policy_decision_ids:
        return PredicateMatch(
            evidence_refs=list(facts.policy_deny_ids),
            explanation_context={"policy_deny_ids": ", ".join(facts.policy_deny_ids)},
        )
    return None


def _scorecard_override_attempt(inputs: PredicateInput) -> PredicateMatch | None:
    if inputs.scorecard.override_attempted:
        return PredicateMatch(
            evidence_refs=[inputs.scorecard.run_id],
            explanation_context={"run_id": inputs.scorecard.run_id},
        )
    return None


def _ashare_market_rules_incomplete(inputs: PredicateInput) -> PredicateMatch | None:
    claims = _claims(inputs, "tradable")
    market = (inputs.scorecard.market or "").lower()
    if claims and market in {"ashare", "a-share", "a_share"} and not inputs.methodology_facts.has_market_rule_coverage:
        return PredicateMatch(
            evidence_refs=_claim_refs(claims) + _fact_refs(inputs, "has_market_rule_coverage"),
            explanation_context={"market": inputs.scorecard.market or "ashare"},
        )
    return None


def _high_crowding_without_stress_test(inputs: PredicateInput) -> PredicateMatch | None:
    crowding = _numeric_metric(inputs.scorecard.metrics, "crowding")
    has_stress_test = bool(inputs.scorecard.metrics.get("has_stress_test"))
    if crowding is not None and crowding >= 0.8 and not has_stress_test:
        return PredicateMatch(
            evidence_refs=[inputs.scorecard.run_id],
            explanation_context={"crowding": crowding},
        )
    return None


def _negative_regime_ic_no_activation(inputs: PredicateInput) -> PredicateMatch | None:
    regime_ic = _numeric_metric(inputs.scorecard.metrics, "frequent_regime_ic")
    has_activation = bool(inputs.scorecard.metrics.get("conditional_activation"))
    if regime_ic is not None and regime_ic < 0 and not has_activation:
        return PredicateMatch(
            evidence_refs=[inputs.scorecard.run_id],
            explanation_context={"frequent_regime_ic": regime_ic},
        )
    return None


PREDICATE_REGISTRY: dict[str, Predicate] = {
    "pit_violation_hard_fail": _pit_violation_hard_fail,
    "tradable_claim_without_cost_model": _tradable_claim_without_cost_model,
    "alpha_claim_without_benchmark": _alpha_claim_without_benchmark,
    "generalization_claim_without_oos": _generalization_claim_without_oos,
    "paper_gate_without_all_requirements": _paper_gate_without_all_requirements,
    "best_trial_without_trial_count": _best_trial_without_trial_count,
    "policy_deny_ignored": _policy_deny_ignored,
    "scorecard_override_attempt": _scorecard_override_attempt,
    "ashare_market_rules_incomplete": _ashare_market_rules_incomplete,
    "high_crowding_without_stress_test": _high_crowding_without_stress_test,
    "negative_regime_ic_no_activation": _negative_regime_ic_no_activation,
}


DEFAULT_RULES: tuple[ScorecardPolicyRule, ...] = (
    ScorecardPolicyRule(
        rule_id="pit_violation_hard_fail",
        predicate_name="pit_violation_hard_fail",
        action="hard_fail",
        reason_code="PIT_VIOLATION",
        explanation_template="Point-in-time safety failed: {fact}.",
    ),
    ScorecardPolicyRule(
        rule_id="tradable_claim_without_cost_model",
        predicate_name="tradable_claim_without_cost_model",
        action="hard_fail",
        reason_code="TRADABLE_WITHOUT_COST_MODEL",
        explanation_template="{claim_count} tradable claim(s) require a cost model; {fact}.",
    ),
    ScorecardPolicyRule(
        rule_id="alpha_claim_without_benchmark",
        predicate_name="alpha_claim_without_benchmark",
        action="hard_fail",
        reason_code="ALPHA_WITHOUT_BENCHMARK",
        explanation_template="{claim_count} alpha claim(s) require a benchmark; {fact}.",
    ),
    ScorecardPolicyRule(
        rule_id="generalization_claim_without_oos",
        predicate_name="generalization_claim_without_oos",
        action="cap_conclusion",
        conclusion_cap="research_candidate",
        reason_code="GENERALIZATION_WITHOUT_OOS",
        explanation_template="{claim_count} generalization claim(s) require OOS evidence; {fact}.",
    ),
    ScorecardPolicyRule(
        rule_id="paper_gate_without_all_requirements",
        predicate_name="paper_gate_without_all_requirements",
        action="hard_fail",
        reason_code="PAPER_GATE_INCOMPLETE",
        explanation_template="Paper-trade candidate gate is incomplete: {missing}.",
    ),
    ScorecardPolicyRule(
        rule_id="best_trial_without_trial_count",
        predicate_name="best_trial_without_trial_count",
        action="hard_fail",
        reason_code="BEST_TRIAL_WITHOUT_TRIAL_COUNT",
        explanation_template="Strong result claim lacks trial disclosure: {fact}.",
    ),
    ScorecardPolicyRule(
        rule_id="policy_deny_ignored",
        predicate_name="policy_deny_ignored",
        action="hard_fail",
        reason_code="POLICY_DENY_IGNORED",
        explanation_template="Policy deny IDs are not represented in scorecard refs: {policy_deny_ids}.",
    ),
    ScorecardPolicyRule(
        rule_id="scorecard_override_attempt",
        predicate_name="scorecard_override_attempt",
        action="hard_fail",
        reason_code="SCORECARD_OVERRIDE_ATTEMPT",
        explanation_template="External text attempted to override scorecard conclusion for {run_id}.",
    ),
    ScorecardPolicyRule(
        rule_id="ashare_market_rules_incomplete",
        predicate_name="ashare_market_rules_incomplete",
        action="cap_conclusion",
        conclusion_cap="research_candidate",
        reason_code="ASHARE_MARKET_RULES_INCOMPLETE",
        explanation_template="{market} tradable claim lacks market rule coverage.",
    ),
    ScorecardPolicyRule(
        rule_id="high_crowding_without_stress_test",
        predicate_name="high_crowding_without_stress_test",
        action="cap_conclusion",
        conclusion_cap="research_candidate",
        reason_code="HIGH_CROWDING_WITHOUT_STRESS_TEST",
        explanation_template="High crowding score {crowding} lacks stress testing.",
    ),
    ScorecardPolicyRule(
        rule_id="negative_regime_ic_no_activation",
        predicate_name="negative_regime_ic_no_activation",
        action="cap_conclusion",
        conclusion_cap="research_candidate",
        reason_code="NEGATIVE_REGIME_IC_NO_ACTIVATION",
        explanation_template="Frequent-regime IC {frequent_regime_ic} lacks conditional activation.",
    ),
)


class ScorecardPolicyEngine:
    """Apply fixed-name scorecard policy predicates without dynamic code paths."""

    def __init__(self, rules: list[ScorecardPolicyRule]) -> None:
        _validate_rules(rules)
        self.rules = list(rules)

    @classmethod
    def default(cls) -> "ScorecardPolicyEngine":
        return cls([rule.model_copy(deep=True) for rule in DEFAULT_RULES])

    @classmethod
    def from_yaml(cls, path: Path | str) -> "ScorecardPolicyEngine":
        data = _read_policy_yaml(Path(path))
        rules_data = data.get("rules")
        if not isinstance(rules_data, list):
            raise ValueError("scorecard policy YAML must contain a rules list")
        rules = [ScorecardPolicyRule.model_validate(item) for item in rules_data]
        _validate_builtin_rules_not_weakened(rules)
        return cls(rules)

    def evaluate(self, inputs: PredicateInput) -> ScorecardPolicyResult:
        scorecard = inputs.scorecard.model_copy(deep=True)
        triggered: list[TriggeredRule] = []
        for rule in self.rules:
            match = PREDICATE_REGISTRY[rule.predicate_name](inputs)
            if match is None:
                continue
            triggered_rule = format_triggered_rule(
                rule=rule,
                explanation_context=match.explanation_context,
                evidence_refs=match.evidence_refs,
            )
            triggered.append(triggered_rule)
            _apply_trigger(scorecard, rule)
        scorecard.triggered_rules = triggered
        scorecard.policy_rule_version = POLICY_RULE_VERSION
        return ScorecardPolicyResult(scorecard=scorecard, triggered_rules=triggered)


def _validate_rules(rules: list[ScorecardPolicyRule]) -> None:
    seen: set[str] = set()
    for rule in rules:
        if rule.rule_id in seen:
            raise ValueError(f"duplicate scorecard policy rule_id: {rule.rule_id}")
        seen.add(rule.rule_id)
        if rule.predicate_name not in PREDICATE_REGISTRY:
            raise ValueError(f"unknown scorecard policy predicate: {rule.predicate_name}")
        if rule.action == "cap_conclusion" and rule.conclusion_cap is None:
            raise ValueError(f"cap rule {rule.rule_id} must define conclusion_cap")


def _validate_builtin_rules_not_weakened(rules: list[ScorecardPolicyRule]) -> None:
    if os.getenv("VIBE_TRADING_TEST_ALLOW_WEAKER_SCORECARD_POLICY", "").strip().lower() in {"1", "true", "yes"}:
        return
    defaults = {rule.rule_id: rule for rule in DEFAULT_RULES}
    loaded = {rule.rule_id: rule for rule in rules}
    missing = sorted(set(defaults) - set(loaded))
    if missing:
        raise ValueError(f"scorecard policy missing built-in rules: {', '.join(missing)}")
    for rule_id, default in defaults.items():
        candidate = loaded[rule_id]
        if default.action == "hard_fail" and candidate.action != "hard_fail":
            raise ValueError(f"scorecard policy weakens built-in hard gate: {rule_id}")
        if candidate.predicate_name != default.predicate_name:
            raise ValueError(f"scorecard policy changes built-in predicate: {rule_id}")


def _read_policy_yaml(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("Invalid scorecard policy YAML") from exc
    if not isinstance(loaded, Mapping):
        raise ValueError("Invalid scorecard policy YAML")
    return dict(loaded)


def _apply_trigger(scorecard: BacktestReliabilityScorecard, rule: ScorecardPolicyRule) -> None:
    if rule.action == "hard_fail":
        if rule.rule_id not in scorecard.hard_failures:
            scorecard.hard_failures.append(rule.rule_id)
        scorecard.conclusion_level = "not_reliable"
        return
    if rule.action == "cap_conclusion" and rule.conclusion_cap is not None:
        scorecard.conclusion_level = _min_conclusion(scorecard.conclusion_level, rule.conclusion_cap)
        if rule.reason_code not in scorecard.warnings:
            scorecard.warnings.append(rule.reason_code)
        return
    if rule.reason_code not in scorecard.warnings:
        scorecard.warnings.append(rule.reason_code)


def _min_conclusion(current: ConclusionLevel, cap: ConclusionLevel) -> ConclusionLevel:
    return cap if _CONCLUSION_RANK[current] > _CONCLUSION_RANK[cap] else current


def _claims(inputs: PredicateInput, *claim_types: str) -> list[ResearchClaim]:
    return [
        claim
        for claim in inputs.claim_set.claims
        if claim.requires_gate and claim.claim_type in claim_types
    ]


def _claim_refs(claims: list[ResearchClaim]) -> list[str]:
    refs: list[str] = []
    for claim in claims:
        _append_unique(refs, claim.claim_id)
        for ref in claim.evidence_refs:
            _append_unique(refs, ref)
    return refs


def _fact_refs(inputs: PredicateInput, *field_names: str) -> list[str]:
    refs = [f"methodology_facts:{field_name}" for field_name in field_names]
    for ref in inputs.methodology_facts.generated_from_artifacts:
        _append_unique(refs, ref)
    return refs


def _paper_gate_missing(facts: MethodologyFactSet) -> list[str]:
    missing: list[str] = []
    checks = {
        "has_cost_model": facts.has_cost_model,
        "has_benchmark": facts.has_benchmark,
        "has_oos": facts.has_oos,
        "has_execution_timeline": facts.has_execution_timeline,
        "has_capacity_test": facts.has_capacity_test,
        "has_market_rule_coverage": facts.has_market_rule_coverage,
    }
    for field_name, present in checks.items():
        if not present:
            missing.append(field_name)
    if facts.pit_safe is False:
        missing.append("pit_safe")
    return missing


def _numeric_metric(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
