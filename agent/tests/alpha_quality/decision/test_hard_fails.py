from __future__ import annotations

from src.alpha_quality.decision.hard_fails import (
    check_execution_return_missing,
    check_lookahead,
)
from src.alpha_quality.decision.model import HardFailureCode
from src.alpha_quality.model import AlphaQualityScorecard, ExecutionMetrics


def _scorecard(
    *,
    formula: str = "rank(close)",
    execution: ExecutionMetrics | None = None,
) -> AlphaQualityScorecard:
    return AlphaQualityScorecard(
        factor_id="candidate",
        formula=formula,
        factor_definition_hash="sha256:factor",
        scope="final_quality_decision",
        horizons=[1],
        execution=execution
        if execution is not None
        else ExecutionMetrics(uses_execution_return=True, return_mean=0.01),
        data_snapshot_ref="snapshot:fixture",
        trial_ledger_ref="ledger:fixture",
    )


def test_lookahead_formula_is_exact_hard_failure_code() -> None:
    failures = check_lookahead(_scorecard(formula="rank(future_return)"))

    assert failures == {HardFailureCode.LOOKAHEAD_DETECTED}


def test_missing_execution_return_is_exact_hard_failure_code() -> None:
    failures = check_execution_return_missing(
        _scorecard(execution=ExecutionMetrics(uses_execution_return=False))
    )

    assert failures == {HardFailureCode.EXECUTION_RETURN_MISSING}
