from __future__ import annotations

from typing import Any

from src.alpha_quality.decision.cost_model import cost_exceeds_alpha
from src.alpha_quality.decision.model import (
    AlphaQualityDecisionContext,
    HardFailureCode,
    normalize_hard_failure,
)
from src.alpha_quality.model import AlphaQualityScorecard


LOOKAHEAD_TOKENS = (
    "future_",
    "future-return",
    "future return",
    "forward_return",
    "next_close",
    "next_day",
)


def scorecard_hard_failures(scorecard: AlphaQualityScorecard) -> set[HardFailureCode]:
    failures: set[HardFailureCode] = set()
    for value in scorecard.hard_failures:
        normalized = normalize_hard_failure(value)
        if normalized is not None:
            failures.add(normalized)
    return failures


def check_lookahead(scorecard: AlphaQualityScorecard) -> set[HardFailureCode]:
    failures = scorecard_hard_failures(scorecard)
    formula = scorecard.formula.lower()
    if any(token in formula for token in LOOKAHEAD_TOKENS):
        failures.add(HardFailureCode.LOOKAHEAD_DETECTED)
    return {HardFailureCode.LOOKAHEAD_DETECTED} & failures


def check_test_contamination(
    scorecard: AlphaQualityScorecard,
    context: AlphaQualityDecisionContext,
) -> set[HardFailureCode]:
    for entry in context.trial_entries:
        if _entry_candidate_id(entry) not in (None, scorecard.factor_id):
            continue
        if _entry_value(entry, "data_scope") == "final_test":
            return {HardFailureCode.TEST_SET_CONTAMINATED}
        if _entry_value(entry, "split_id") == "final_test":
            return {HardFailureCode.TEST_SET_CONTAMINATED}
    return set()


def check_reproducibility(scorecard: AlphaQualityScorecard) -> set[HardFailureCode]:
    if scorecard.scope == "final_quality_decision" and (
        not scorecard.data_snapshot_ref or not scorecard.trial_ledger_ref
    ):
        return {HardFailureCode.NON_REPRODUCIBLE}
    return set()


def check_pit_contract(
    context: AlphaQualityDecisionContext,
) -> set[HardFailureCode]:
    if context.survivorship_bias or not context.pit_contract_present:
        return {HardFailureCode.PIT_CONTRACT_MISSING}
    return set()


def check_cost_vs_execution_alpha(
    scorecard: AlphaQualityScorecard,
) -> set[HardFailureCode]:
    if cost_exceeds_alpha(scorecard.execution):
        return {HardFailureCode.COST_EXCEEDS_ALPHA}
    return set()


def check_execution_return_missing(
    scorecard: AlphaQualityScorecard,
    *,
    allow_missing: bool = False,
) -> set[HardFailureCode]:
    if allow_missing:
        return set()
    if scorecard.execution is None or not scorecard.execution.uses_execution_return:
        return {HardFailureCode.EXECUTION_RETURN_MISSING}
    return set()


def check_duplicate_alpha(
    scorecard: AlphaQualityScorecard,
    context: AlphaQualityDecisionContext,
) -> set[HardFailureCode]:
    failures = scorecard_hard_failures(scorecard)
    if context.duplicate_alpha or HardFailureCode.DUPLICATE_ALPHA in failures:
        return {HardFailureCode.DUPLICATE_ALPHA}
    return set()


def _entry_value(entry: Any, field: str) -> Any:
    if isinstance(entry, dict):
        return entry.get(field)
    return getattr(entry, field, None)


def _entry_candidate_id(entry: Any) -> str | None:
    value = _entry_value(entry, "candidate_id")
    return str(value) if value is not None else None
