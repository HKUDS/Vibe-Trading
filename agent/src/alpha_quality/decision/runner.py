from __future__ import annotations

from src.alpha_quality.decision.advisory import (
    check_deflated_sharpe_proxy,
    check_exposure,
    check_multiple_testing_proxy,
    check_recent_decay,
    check_turnover,
)
from src.alpha_quality.decision.decision import (
    cap_reasons,
    decide_quality,
    is_decision_raise,
)
from src.alpha_quality.decision.hard_fails import (
    check_cost_vs_execution_alpha,
    check_duplicate_alpha,
    check_execution_return_missing,
    check_lookahead,
    check_pit_contract,
    check_reproducibility,
    check_test_contamination,
    scorecard_hard_failures,
)
from src.alpha_quality.decision.model import (
    AdvisoryCode,
    AlphaQualityDecision,
    AlphaQualityDecisionContext,
    HardFailureCode,
)
from src.alpha_quality.model import AlphaQualityScorecard


class QualityDecisionRunner:
    def run(
        self,
        scorecard: AlphaQualityScorecard,
        context: AlphaQualityDecisionContext,
    ) -> AlphaQualityDecision:
        hard_failures = self._hard_failures(scorecard, context)
        warnings = self._warnings(scorecard, context)
        decision = decide_quality(
            hard_failures,
            total_quality_score=context.total_quality_score,
        )

        if context.caller_claimed_decision is not None and is_decision_raise(
            context.caller_claimed_decision,
            decision,
        ):
            hard_failures.add(HardFailureCode.SCORECARD_OVERRIDE_ATTEMPT)
            decision = decide_quality(
                hard_failures,
                total_quality_score=context.total_quality_score,
            )

        return AlphaQualityDecision(
            schema_version="alpha_quality_decision.v1",
            factor_id=scorecard.factor_id,
            decision=decision,
            hard_failures=sorted(hard_failures, key=lambda code: code.value),
            warnings=sorted(warnings, key=lambda code: code.value),
            cap_reasons=cap_reasons(hard_failures),
            total_quality_score=float(context.total_quality_score),
        )

    def _hard_failures(
        self,
        scorecard: AlphaQualityScorecard,
        context: AlphaQualityDecisionContext,
    ) -> set[HardFailureCode]:
        failures = scorecard_hard_failures(scorecard)
        failures |= check_lookahead(scorecard)
        failures |= check_test_contamination(scorecard, context)
        failures |= check_reproducibility(scorecard)
        failures |= check_pit_contract(context)
        failures |= check_cost_vs_execution_alpha(scorecard)
        failures |= check_execution_return_missing(
            scorecard,
            allow_missing=context.allow_missing_execution_return,
        )
        failures |= check_duplicate_alpha(scorecard, context)
        return failures

    def _warnings(
        self,
        scorecard: AlphaQualityScorecard,
        context: AlphaQualityDecisionContext,
    ) -> set[AdvisoryCode]:
        observed_ir = _extract_observed_ir(scorecard)
        warnings = check_recent_decay(scorecard)
        warnings |= check_turnover(scorecard)
        warnings |= check_exposure(scorecard)
        warnings |= check_multiple_testing_proxy(
            trial_count=context.trial_count,
            selected_p_value=context.selected_p_value,
        )
        warnings |= check_deflated_sharpe_proxy(
            trial_count=context.trial_count,
            observed_ir=observed_ir,
        )
        return warnings


def _extract_observed_ir(scorecard: AlphaQualityScorecard) -> float | None:
    if scorecard.predictive is None:
        return None
    values: list[float] = []
    for horizon in scorecard.predictive.by_horizon.values():
        for summary in horizon.by_split.values():
            if summary.rank_icir is not None:
                values.append(float(summary.rank_icir))
    if not values:
        return None
    return max(values)
