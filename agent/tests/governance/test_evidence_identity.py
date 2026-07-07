"""Tests for v1.2.1 governance evidence identity semantics."""

from __future__ import annotations

from datetime import datetime, timezone

from src.governance.decisions import PolicyDecision
from src.governance.evidence_identity import (
    EvidenceIdentity,
    EvidenceWriteOutcome,
    compute_idempotency_key,
    hash_params,
)
from src.governance.runtime import RuntimeContext


def test_evidence_identity_distinguishes_decision_and_artifact_ids() -> None:
    identity = EvidenceIdentity(
        decision_id="dec_123",
        policy_decision_artifact_id="art_456",
        trace_event_id="trace_789",
        ledger_event_hash="ledger_abc",
        run_id="run_1",
        idempotency_key="idem_1",
    )

    assert identity.schema_version == "1.2.1"
    assert identity.decision_id == "dec_123"
    assert identity.policy_decision_artifact_id == "art_456"
    assert identity.decision_id != identity.policy_decision_artifact_id
    assert identity.trace_event_id == "trace_789"
    assert identity.ledger_event_hash == "ledger_abc"


def test_idempotency_key_stable_for_same_decision() -> None:
    context = RuntimeContext(
        mode="warn",
        surface="remote_api",
        run_id="run_1",
        session_id="session_1",
        trial_id="trial_1",
        protocol_hash="protocol_1",
    )
    decision = PolicyDecision(
        tool_name="fake_shell",
        action="deny",
        risk_level="R5_SHELL",
        reasons=["remote shell denied"],
        reason_codes=["R5_REMOTE_SHELL_DENIED"],
        policy_engine_version="engine-test",
    )

    key1 = compute_idempotency_key(
        decision=decision,
        context=context,
        params_hash=hash_params({"b": 2, "a": 1}),
    )
    key2 = compute_idempotency_key(
        decision=decision,
        context=context,
        params_hash=hash_params({"a": 1, "b": 2}),
    )

    assert len(key1) == 64
    assert key1 == key2


def test_evidence_write_outcome_partial_status_is_explicit() -> None:
    outcome = EvidenceWriteOutcome(
        decision_id="dec_123",
        artifact_written=True,
        policy_decision_artifact_id="art_456",
        errors=["trace: unavailable"],
        status="partial_artifact_only",
    )

    dumped = outcome.model_dump(mode="json")

    assert dumped["schema_version"] == "1.2.1"
    assert dumped["decision_id"] == "dec_123"
    assert dumped["trace_written"] is False
    assert dumped["artifact_written"] is True
    assert dumped["status"] == "partial_artifact_only"


def test_policy_decision_defaults_are_schema_versioned() -> None:
    decision = PolicyDecision(
        tool_name="fake_shell",
        action="deny",
        risk_level="R5_SHELL",
        reasons=["remote shell denied"],
        created_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
    )

    assert decision.schema_version == "1.2.1"
    assert decision.reason_codes == []
    assert decision.policy_engine_version
