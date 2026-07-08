from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from src.alpha_foundry.reports.model import AlphaGenesisReport
from src.alpha_quality.decision.model import AlphaQualityDecision
from src.alpha_quality.model import AlphaQualityScorecard
from src.research_ledger.hash_utils import json_safe, redact_secrets


DEFAULT_LIMITATIONS = [
    "research-only evidence package",
    "requires independent review before any capital allocation",
]
DEFAULT_NON_GOALS = [
    "not live trading advice",
    "not production-ready",
]


def build_alpha_genesis_report(
    *,
    report_id: str,
    candidate_id: str | None = None,
    parent_seed_id: str | None = None,
    formula_hash: str | None = None,
    scorecard: AlphaQualityScorecard | None = None,
    decision: AlphaQualityDecision | None = None,
    trial_entries: list[Any] | None = None,
    data_snapshot: dict[str, Any] | None = None,
    novelty_metrics: dict[str, Any] | None = None,
    synergy_metrics: dict[str, Any] | None = None,
    robustness_metrics: dict[str, Any] | None = None,
    source_config: dict[str, Any] | None = None,
    limitations: list[str] | None = None,
    non_goals: list[str] | None = None,
) -> AlphaGenesisReport:
    trial_entries = trial_entries or []
    data_snapshot = data_snapshot or {}
    resolved_candidate_id = candidate_id or (scorecard.factor_id if scorecard else report_id)

    return AlphaGenesisReport(
        report_id=report_id,
        candidate_id=resolved_candidate_id,
        parent_seed_id=parent_seed_id,
        formula=scorecard.formula if scorecard else None,
        formula_hash=formula_hash,
        factor_definition_hash=scorecard.factor_definition_hash if scorecard else None,
        data_snapshot_hash=(
            str(data_snapshot.get("snapshot_hash"))
            if data_snapshot.get("snapshot_hash") is not None
            else (scorecard.data_snapshot_ref if scorecard else None)
        ),
        pit_contract_present=_optional_bool(data_snapshot.get("pit_contract_present")),
        survivorship_bias=_optional_bool(data_snapshot.get("survivorship_bias")),
        split_config=_scorecard_split_config(scorecard),
        data_scope=scorecard.scope if scorecard else "research",
        predictive_metrics=_predictive_metrics(scorecard),
        robustness_metrics=robustness_metrics or {},
        tradability_metrics=_tradability_metrics(scorecard),
        novelty_metrics=novelty_metrics or {},
        synergy_metrics=synergy_metrics or {},
        hard_failures=_decision_codes(decision.hard_failures if decision else []),
        warnings=_decision_codes(decision.warnings if decision else []),
        decision=decision.decision.value if decision else "research_only",
        cap_reasons=_decision_codes(decision.cap_reasons if decision else []),
        trial_count=len(trial_entries),
        trial_group_id=_trial_group_id(trial_entries),
        limitations=list(limitations or DEFAULT_LIMITATIONS),
        non_goals=list(non_goals or DEFAULT_NON_GOALS),
        metadata=redact_secrets(
            {
                "source_config": source_config or {},
                "scorecard_ref": scorecard.trial_ledger_ref if scorecard else None,
            }
        ),
    )


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _decision_codes(values: list[Any]) -> list[str]:
    codes: list[str] = []
    for value in values:
        if hasattr(value, "value"):
            codes.append(str(value.value))
        else:
            codes.append(str(value))
    return codes


def _scorecard_split_config(scorecard: AlphaQualityScorecard | None) -> dict[str, Any]:
    if scorecard is None:
        return {}
    return {"scope": scorecard.scope, "horizons": list(scorecard.horizons)}


def _predictive_metrics(scorecard: AlphaQualityScorecard | None) -> dict[str, Any]:
    if scorecard is None or scorecard.predictive is None:
        return {}
    return _json_model(scorecard.predictive)


def _tradability_metrics(scorecard: AlphaQualityScorecard | None) -> dict[str, Any]:
    if scorecard is None:
        return {}
    payload: dict[str, Any] = {}
    if scorecard.coverage is not None:
        payload["coverage"] = _json_model(scorecard.coverage)
    if scorecard.execution is not None:
        payload["execution"] = _json_model(scorecard.execution)
    return payload


def _json_model(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return json_safe(value)
    return {"value": json_safe(value)}


def _trial_group_id(entries: list[Any]) -> str | None:
    if not entries:
        return None
    first = entries[0]
    if isinstance(first, dict):
        value = first.get("trial_group_id")
    else:
        value = getattr(first, "trial_group_id", None)
    return str(value) if value is not None else None
