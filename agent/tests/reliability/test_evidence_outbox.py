"""Tests for v1.2.1 durable evidence outbox."""

from __future__ import annotations

from pathlib import Path

from src.governance.decisions import PolicyDecision
from src.governance.decision_recorder import DecisionRecorder
from src.governance.evidence_outbox import EvidenceOutbox
from src.governance.runtime import RuntimeContext


def test_outbox_append_list_and_mark_reconciled(tmp_path: Path) -> None:
    outbox = EvidenceOutbox(tmp_path / "evidence_outbox.sqlite")
    recorder = DecisionRecorder(artifact_store=None)
    envelope = recorder.prepare(
        PolicyDecision(
            tool_name="fake_shell",
            action="deny",
            risk_level="R5_SHELL",
            reasons=["blocked"],
            reason_codes=["R5_DENIED"],
        ),
        params={"api_key": "sk-test-secret-value-abcdefghijklmnopqrstuvwxyz", "safe": "visible"},
        context=RuntimeContext(mode="warn", surface="remote_api", run_id="run_outbox"),
    )

    outbox.append(envelope, errors=["artifact: unavailable"])
    pending = outbox.list_pending(run_id="run_outbox")

    assert len(pending) == 1
    assert pending[0].decision_id == envelope.decision_id
    assert pending[0].run_id == "run_outbox"
    assert pending[0].status == "pending"
    dumped = pending[0].payload
    assert dumped["redacted_params_preview"]["api_key"] == "[REDACTED]"
    assert "sk-test-secret-value" not in str(dumped)

    outbox.mark_reconciled(envelope.evidence_identity.idempotency_key)

    assert outbox.list_pending(run_id="run_outbox") == []


def test_outbox_upserts_same_idempotency_key(tmp_path: Path) -> None:
    outbox = EvidenceOutbox(tmp_path / "evidence_outbox.sqlite")
    recorder = DecisionRecorder(artifact_store=None)
    context = RuntimeContext(mode="warn", surface="remote_api", run_id="run_outbox")
    decision = PolicyDecision(
        tool_name="fake_shell",
        action="deny",
        risk_level="R5_SHELL",
        reasons=["blocked"],
        reason_codes=["R5_DENIED"],
    )
    envelope = recorder.prepare(decision, params={"cmd": "echo hi"}, context=context)

    outbox.append(envelope, errors=["first"])
    outbox.append(envelope, errors=["second"])

    pending = outbox.list_pending()
    assert len(pending) == 1
    assert pending[0].errors == ["second"]

