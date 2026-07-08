from __future__ import annotations

from src.alpha_quality.decision.advisory import (
    check_multiple_testing_proxy,
    check_turnover,
)
from src.alpha_quality.decision.model import AdvisoryCode
from src.alpha_quality.model import AlphaQualityScorecard, ExecutionMetrics


def test_multiple_testing_proxy_uses_high_pbo_proxy_name() -> None:
    warnings = check_multiple_testing_proxy(trial_count=100, selected_p_value=0.001)

    assert warnings == {AdvisoryCode.HIGH_PBO_PROXY}
    assert all("PBO" in warning.value for warning in warnings)
    assert "TRUE_PBO" not in {warning.value for warning in warnings}


def test_high_turnover_is_advisory_not_hard_failure() -> None:
    scorecard = AlphaQualityScorecard(
        factor_id="candidate",
        execution=ExecutionMetrics(uses_execution_return=True, return_mean=0.02, turnover_mean=1.6),
    )

    assert check_turnover(scorecard) == {AdvisoryCode.HIGH_TURNOVER}
