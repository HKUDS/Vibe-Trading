from __future__ import annotations

from pathlib import Path

import pytest

from src.evals.agent_eval.case_schema import load_case, load_cases
from src.evals.agent_eval.runner import AgentEvalRunner
from src.evals.agent_eval.scorer import score_trace


CASES_DIR = Path(__file__).parent / "cases"


def _run(case_id: str):
    case = load_case(CASES_DIR / f"{case_id}.yaml")
    result = AgentEvalRunner(stub_dir=Path(__file__).parent / "stubs").run_case(case)
    return case, result, score_trace(case, result.trace)


def test_remote_api_shell_case_fails_without_deny() -> None:
    case = load_case(CASES_DIR / "remote_api_shell_denied.yaml")
    trace = [{"type": "tool_call", "tool_name": "bash"}, {"type": "final", "status": "allowed"}]

    result = score_trace(case, trace)

    assert result.passed is False
    assert any("deny" in failure for failure in result.failures)


def test_future_data_case_requires_pit_warning_or_rejection() -> None:
    case = load_case(CASES_DIR / "deny_future_data_backtest.yaml")
    trace = [{"type": "tool_call", "tool_name": "backtest"}, {"type": "final", "status": "allowed"}]

    result = score_trace(case, trace)

    assert result.passed is False
    assert any("PIT_FUTURE_DATA" in failure for failure in result.failures)


def test_scorecard_override_case_rejects_llm_upgrade() -> None:
    case, result, scoring = _run("scorecard_not_llm_overridden")

    assert result.status == case.expected.final_status
    assert scoring.passed is True
    assert any(event.get("code") == "QUANT_SCORECARD_LLM_OVERRIDE_ATTEMPT" for event in result.trace)


@pytest.mark.parametrize("case", load_cases(CASES_DIR), ids=lambda c: c.id)
def test_initial_policy_security_quant_cases_pass(case) -> None:
    result = AgentEvalRunner(stub_dir=Path(__file__).parent / "stubs").run_case(case)
    scoring = score_trace(case, result.trace)

    assert scoring.passed, scoring.failures
