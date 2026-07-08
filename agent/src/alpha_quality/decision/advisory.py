from __future__ import annotations

from src.alpha_quality.decision.model import AdvisoryCode
from src.alpha_quality.model import AlphaQualityScorecard


def check_recent_decay(scorecard: AlphaQualityScorecard) -> set[AdvisoryCode]:
    if "RECENT_DECAY" in scorecard.warnings:
        return {AdvisoryCode.RECENT_DECAY}
    return set()


def check_turnover(
    scorecard: AlphaQualityScorecard,
    *,
    turnover_warn_threshold: float = 1.0,
) -> set[AdvisoryCode]:
    execution = scorecard.execution
    if execution is None or execution.turnover_mean is None:
        return set()
    if execution.turnover_mean > turnover_warn_threshold:
        return {AdvisoryCode.HIGH_TURNOVER}
    return set()


def check_exposure(scorecard: AlphaQualityScorecard) -> set[AdvisoryCode]:
    if (
        "EXPOSURE_CONCENTRATION" in scorecard.warnings
        or "UNEXPLAINED_EXPOSURE" in scorecard.warnings
    ):
        return {AdvisoryCode.UNEXPLAINED_EXPOSURE}
    return set()


def check_multiple_testing_proxy(
    *,
    trial_count: int,
    selected_p_value: float | None,
    familywise_alpha: float = 0.05,
    large_trial_count: int = 50,
) -> set[AdvisoryCode]:
    if trial_count <= 1:
        return set()
    if selected_p_value is None:
        return {AdvisoryCode.HIGH_PBO_PROXY} if trial_count >= large_trial_count else set()
    if selected_p_value * trial_count > familywise_alpha:
        return {AdvisoryCode.HIGH_PBO_PROXY}
    if trial_count >= large_trial_count:
        return {AdvisoryCode.HIGH_PBO_PROXY}
    return set()


def check_deflated_sharpe_proxy(
    *,
    trial_count: int,
    observed_ir: float | None,
) -> set[AdvisoryCode]:
    if observed_ir is None:
        return set()
    if trial_count >= 50 and observed_ir < 0.25:
        return {AdvisoryCode.LOW_DEFLATED_SHARPE}
    return set()
