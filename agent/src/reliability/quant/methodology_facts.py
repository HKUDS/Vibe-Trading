"""Methodology fact extraction for v1.2.1 scorecard policy inputs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = "1.2.1"


class MethodologyFactSet(BaseModel):
    """Structured methodology facts used by later scorecard policy gates."""

    schema_version: str = SCHEMA_VERSION
    run_id: str
    protocol_hash: str | None = None
    has_registered_protocol: bool = False
    trial_count: int | None = None
    has_data_audit: bool = False
    pit_safe: bool | None = None
    has_cost_model: bool = False
    has_benchmark: bool = False
    has_oos: bool = False
    oos_method: str | None = None
    walk_forward_effective_folds: int | None = None
    has_execution_timeline: bool = False
    execution_timestamps_present: list[str] = Field(default_factory=list)
    has_capacity_test: bool = False
    adv_caps_tested: list[float] = Field(default_factory=list)
    has_market_rule_coverage: bool = False
    market_rule_warnings: list[str] = Field(default_factory=list)
    has_policy_denies: bool = False
    policy_deny_ids: list[str] = Field(default_factory=list)
    generated_from_artifacts: list[str] = Field(default_factory=list)

    @field_validator("trial_count")
    @classmethod
    def _trial_count_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("trial_count must be non-negative")
        return value

    def to_diagnostics_readiness_report(self):
        """Map methodology facts to optional quant diagnostics readiness."""
        from src.reliability.quant.diagnostics import DiagnosticsReadinessReport

        return DiagnosticsReadinessReport.from_methodology_facts(self)


def build_methodology_fact_set(
    *,
    run_id: str,
    protocol: Any | None = None,
    data_audit: Any | None = None,
    scorecard: Any | None = None,
    trial_ledger: Any | None = None,
    research_card: Any | None = None,
    policy_decision_ids: list[str] | None = None,
    generated_from_artifacts: list[str] | None = None,
    protocol_hash: str | None = None,
) -> MethodologyFactSet:
    """Derive methodology facts from structured run artifacts."""
    protocol_map = _as_mapping(protocol)
    data_audit_map = _as_mapping(data_audit)
    scorecard_map = _as_mapping(scorecard)
    trial_ledger_map = _as_mapping(trial_ledger)
    research_card_map = _as_mapping(research_card)
    fact_sources = _artifact_refs(
        generated_from_artifacts,
        protocol_map,
        data_audit_map,
        scorecard_map,
        research_card_map,
    )
    deny_ids = list(policy_decision_ids or _as_list(research_card_map.get("policy_deny_ids")))
    split_policy = _as_mapping(protocol_map.get("split_policy"))
    capacity = _first_mapping(
        research_card_map.get("capacity_test"),
        research_card_map.get("capacity"),
        scorecard_map.get("capacity_test"),
        scorecard_map.get("capacity"),
    )
    timeline = _first_mapping(
        research_card_map.get("execution_timeline"),
        scorecard_map.get("execution_timeline"),
    )

    return MethodologyFactSet(
        run_id=run_id,
        protocol_hash=protocol_hash or _first_text(protocol_map.get("protocol_hash"), research_card_map.get("protocol_hash")),
        has_registered_protocol=_is_registered(protocol_map),
        trial_count=_trial_count(trial_ledger_map, research_card_map, scorecard_map),
        has_data_audit=bool(data_audit_map),
        pit_safe=_pit_safe(data_audit_map),
        has_cost_model=_has_cost_model(protocol_map, research_card_map, scorecard_map),
        has_benchmark=_has_benchmark(protocol_map, research_card_map, scorecard_map),
        has_oos=_has_oos(split_policy, research_card_map, scorecard_map),
        oos_method=_first_text(split_policy.get("method"), research_card_map.get("oos_method"), scorecard_map.get("oos_method")),
        walk_forward_effective_folds=_first_int(
            split_policy.get("walk_forward_effective_folds"),
            split_policy.get("effective_folds"),
            scorecard_map.get("walk_forward_effective_folds"),
        ),
        has_execution_timeline=bool(timeline),
        execution_timestamps_present=[key for key, value in timeline.items() if value],
        has_capacity_test=bool(capacity),
        adv_caps_tested=[float(value) for value in _as_list(capacity.get("adv_caps_tested")) if _is_number(value)],
        has_market_rule_coverage=_has_market_rule_coverage(protocol_map, research_card_map, scorecard_map),
        market_rule_warnings=[str(value) for value in _as_list(research_card_map.get("market_rule_warnings"))],
        has_policy_denies=bool(deny_ids),
        policy_deny_ids=[str(value) for value in deny_ids],
        generated_from_artifacts=fact_sources,
    )


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _trial_count(*sources: dict[str, Any]) -> int | None:
    for source in sources:
        explicit = _first_int(source.get("trial_count"), source.get("n_trials"))
        if explicit is not None:
            return explicit
    ledger = sources[0] if sources else {}
    trials = _as_list(ledger.get("trials"))
    if trials:
        return len(trials)
    events = _as_list(ledger.get("events"))
    if events:
        return len(
            [
                event
                for event in events
                if not isinstance(event, Mapping)
                or str(event.get("event_type") or event.get("type") or event.get("kind") or "trial").lower()
                in {"trial", "trial_event", "backtest_trial"}
            ]
        )
    return None


def _pit_safe(data_audit: dict[str, Any]) -> bool | None:
    if not data_audit:
        return None
    if data_audit.get("pit_safe") is False or data_audit.get("point_in_time_safe") is False:
        return False
    if _as_list(data_audit.get("pit_violations")):
        return False
    if data_audit.get("pit_safe") is True or data_audit.get("point_in_time_safe") is True:
        return True
    return True


def _has_cost_model(*sources: dict[str, Any]) -> bool:
    for source in sources:
        if source.get("has_cost_model") is True:
            return True
        if _truthy_mapping_or_text(source.get("cost_model")):
            return True
    return False


def _has_benchmark(protocol: dict[str, Any], research_card: dict[str, Any], scorecard: dict[str, Any]) -> bool:
    benchmark_policy = _as_mapping(protocol.get("benchmark_policy"))
    if _first_text(benchmark_policy.get("primary"), benchmark_policy.get("benchmark")):
        return True
    return any(
        _truthy_mapping_or_text(source.get("benchmark")) or source.get("has_benchmark") is True
        for source in (research_card, scorecard)
    )


def _has_oos(split_policy: dict[str, Any], research_card: dict[str, Any], scorecard: dict[str, Any]) -> bool:
    method = str(split_policy.get("method") or "").lower()
    if method in {"oos", "walk_forward", "train_test", "rolling_oos"}:
        return True
    if split_policy.get("test_start") and split_policy.get("test_end"):
        return True
    return any(source.get("has_oos") is True or _truthy_mapping_or_text(source.get("oos")) for source in (research_card, scorecard))


def _has_market_rule_coverage(*sources: dict[str, Any]) -> bool:
    for source in sources:
        if source.get("has_market_rule_coverage") is True:
            return True
        if _truthy_mapping_or_text(source.get("market_rule_coverage")) or _truthy_mapping_or_text(source.get("market_rules")):
            return True
    return False


def _is_registered(protocol: dict[str, Any]) -> bool:
    return bool(protocol.get("registered") is True or str(protocol.get("status") or "").lower() == "registered")


def _artifact_refs(explicit: list[str] | None, *sources: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for ref in explicit or []:
        _append_unique(refs, str(ref))
    for source in sources:
        _append_unique(refs, _first_text(source.get("artifact_id"), source.get("artifact_ref")))
    return refs


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        mapped = _as_mapping(value)
        if mapped:
            return mapped
    return {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
    return None


def _truthy_mapping_or_text(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _is_number(value: Any) -> bool:
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)
