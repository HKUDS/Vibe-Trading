from __future__ import annotations

from src.evals.agent_eval.case_schema import AgentEvalCase
from src.evals.agent_eval.golden_trace import assert_golden_trace_equal
from src.evals.agent_eval.scorer import score_trace


def _case(**expected_updates) -> AgentEvalCase:
    expected = {
        "must_call": ["backtest"],
        "must_not_call": ["trading_place_order"],
        "must_warn_codes": ["PIT_FUTURE_DATA"],
        "must_deny_codes": ["P20"],
        "must_not_claim": ["tradable"],
        "required_trace_events": ["policy_decision", "data_audit"],
        "required_artifacts": ["data_audit"],
        "final_status": "denied",
    }
    expected.update(expected_updates)
    return AgentEvalCase.model_validate(
        {
            "id": "case",
            "prompt": "prompt",
            "setup": {},
            "expected": expected,
            "tags": ["test"],
            "timeout_seconds": 5,
        }
    )


def test_scorer_accepts_expected_trace() -> None:
    trace = [
        {"type": "tool_call", "tool_name": "backtest"},
        {"type": "policy_decision", "tool_name": "bash", "surface": "remote_api", "action": "deny", "code": "P20"},
        {"type": "warning", "code": "PIT_FUTURE_DATA"},
        {"type": "data_audit", "data_audit_id": "audit_1"},
        {"type": "artifact", "artifact_type": "data_audit", "artifact_id": "art_1"},
        {"type": "final", "status": "denied", "claims": []},
    ]

    result = score_trace(_case(), trace)

    assert result.passed is True
    assert result.failures == []


def test_scorer_detects_missing_policy_decision() -> None:
    result = score_trace(_case(), [{"type": "final", "status": "denied", "claims": []}])

    assert result.passed is False
    assert any("policy_decision" in failure for failure in result.failures)


def test_scorer_detects_hidden_hard_failure() -> None:
    result = score_trace(
        _case(must_deny_codes=[]),
        [
            {"type": "hard_failure", "code": "QUANT_NO_COST_MODEL_TRADABLE_CLAIM", "hidden": True},
            {"type": "final", "status": "denied", "claims": []},
        ],
    )

    assert result.passed is False
    assert any("hidden hard_failure" in failure for failure in result.failures)


def test_golden_trace_ignores_allowed_dynamic_fields() -> None:
    expected = [
        {
            "type": "policy_decision",
            "tool_name": "bash",
            "surface": "remote_api",
            "action": "deny",
            "status": "denied",
            "created_at": "2026-01-01T00:00:00Z",
            "decision_id": "pd_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "duration_ms": 1,
            "artifact_hash": "artifact://sha256/" + "a" * 64,
        }
    ]
    actual = [
        {
            "type": "policy_decision",
            "tool_name": "bash",
            "surface": "remote_api",
            "action": "deny",
            "status": "denied",
            "created_at": "2027-02-02T00:00:00Z",
            "decision_id": "pd_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "duration_ms": 99,
            "artifact_hash": "artifact://sha256/" + "b" * 64,
        }
    ]

    assert_golden_trace_equal(expected, actual)
