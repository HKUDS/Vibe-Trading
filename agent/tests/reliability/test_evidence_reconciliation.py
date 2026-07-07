"""Tests for rebuilding RunEvidenceIndex from durable evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.governance.decisions import PolicyDecision
from src.governance.decision_recorder import DecisionRecorder
from src.governance.evidence_index import EvidenceIndexStore
from src.governance.runtime import RuntimeContext
from src.reliability.artifacts.reconciliation import EvidenceReconciler
from src.reliability.artifacts.store import ArtifactStore


def test_index_separates_decision_ids_and_artifact_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    index_store = EvidenceIndexStore(tmp_path / "evidence_index.sqlite")
    recorder = DecisionRecorder(
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        evidence_index=index_store,
    )
    envelope = recorder.prepare(
        PolicyDecision(
            tool_name="fake_shell",
            action="deny",
            risk_level="R5_SHELL",
            reasons=["blocked"],
            reason_codes=["R5_DENIED"],
        ),
        params={"cmd": "echo hi"},
        context=RuntimeContext(mode="warn", surface="remote_api", run_id="run_index"),
    )

    recorder.record_best_effort(envelope)
    index = index_store.get("run_index")

    assert index is not None
    assert index.policy_decision_ids == [envelope.decision_id]
    assert index.policy_decision_artifact_refs == [
        envelope.evidence_identity.policy_decision_artifact_id
    ]
    assert envelope.decision_id not in index.policy_decision_artifact_refs
    assert envelope.evidence_identity.policy_decision_artifact_id not in index.policy_decision_ids


def test_reconciliation_repairs_index_from_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    recorder = DecisionRecorder(artifact_store=artifact_store)
    envelope = recorder.prepare(
        PolicyDecision(
            tool_name="fake_shell",
            action="deny",
            risk_level="R5_SHELL",
            reasons=["blocked"],
            reason_codes=["R5_DENIED"],
        ),
        params={"cmd": "echo hi"},
        context=RuntimeContext(mode="warn", surface="remote_api", run_id="run_repair"),
    )
    recorder.record_best_effort(envelope)
    index_store = EvidenceIndexStore(tmp_path / "evidence_index.sqlite")

    repaired = EvidenceReconciler(
        artifact_store=artifact_store,
        index_store=index_store,
    ).rebuild_run("run_repair")

    assert repaired.run_id == "run_repair"
    assert repaired.policy_decision_ids == [envelope.decision_id]
    assert repaired.policy_decision_artifact_refs == [
        envelope.evidence_identity.policy_decision_artifact_id
    ]
    loaded = index_store.get("run_repair")
    assert loaded is not None
    assert loaded.policy_decision_ids == [envelope.decision_id]

