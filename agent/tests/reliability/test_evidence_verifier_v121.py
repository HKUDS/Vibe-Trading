"""Tests for v1.2.1 evidence closure verification."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.agent.trace import TraceWriter
from src.governance.decisions import PolicyDecision
from src.governance.decision_recorder import DecisionRecorder
from src.governance.evidence_index import EvidenceIndexStore
from src.governance.evidence_outbox import EvidenceOutbox
from src.governance.runtime import RuntimeContext
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.artifacts.verifier import EvidenceVerifier


def _record_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str,
    trace: bool = True,
    index: bool = True,
) -> tuple[ArtifactStore, EvidenceIndexStore | None, EvidenceOutbox, object]:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    index_store = EvidenceIndexStore(tmp_path / "evidence_index.sqlite") if index else None
    outbox = EvidenceOutbox(tmp_path / "evidence_outbox.sqlite")
    recorder = DecisionRecorder(
        artifact_store=artifact_store,
        trace_writer=TraceWriter(tmp_path / "trace") if trace else None,
        evidence_index=index_store,
        evidence_outbox=outbox,
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
        context=RuntimeContext(mode="warn", surface="remote_api", run_id=run_id),
    )
    recorder.record_best_effort(envelope)
    return artifact_store, index_store, outbox, envelope


def test_missing_index_rebuilds_from_artifact_store_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_store, _index_store, outbox, envelope = _record_decision(
        tmp_path,
        monkeypatch,
        run_id="run_missing_index",
        trace=True,
        index=False,
    )

    report = EvidenceVerifier(
        artifact_store=artifact_store,
        index_store=EvidenceIndexStore(tmp_path / "missing_index.sqlite"),
        outbox=outbox,
        trace_dir=tmp_path / "trace",
    ).verify("run_missing_index")

    assert report.passed is True
    assert report.degraded is True
    assert "artifact" in report.verified_from
    assert "index_missing_rebuilt_from_artifacts" in report.degraded_reasons
    assert report.required_refs_present["policy_decision_artifact_refs"] is True
    assert envelope.decision_id not in report.missing_refs


def test_dangling_artifact_ref_detected(tmp_path: Path) -> None:
    index_store = EvidenceIndexStore(tmp_path / "evidence_index.sqlite")
    index = index_store.get_or_create("run_dangling")
    index.policy_decision_ids.append("pd_missing")
    index.policy_decision_artifact_refs.append("art_missing")
    index_store.write(index)

    report = EvidenceVerifier(
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        index_store=index_store,
    ).verify("run_dangling")

    assert report.passed is False
    assert "art_missing" in report.dangling_refs


def test_inconsistent_decision_id_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_store, index_store, _outbox, envelope = _record_decision(
        tmp_path,
        monkeypatch,
        run_id="run_inconsistent",
        trace=False,
        index=True,
    )
    assert index_store is not None
    index = index_store.get("run_inconsistent")
    assert index is not None
    index.policy_decision_ids = ["pd_other"]
    index_store.write(index)

    report = EvidenceVerifier(
        artifact_store=artifact_store,
        index_store=index_store,
    ).verify("run_inconsistent")

    assert report.passed is False
    assert envelope.decision_id in report.inconsistent_ids


def test_outbox_pending_appears_in_evidence_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
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
        params={"cmd": "echo hi"},
        context=RuntimeContext(mode="warn", surface="remote_api", run_id="run_outbox_pending"),
    )
    outbox.append(envelope, errors=["artifact: unavailable"])

    report = EvidenceVerifier(
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        outbox=outbox,
    ).verify("run_outbox_pending")

    assert report.passed is False
    assert report.degraded is True
    assert envelope.decision_id in report.outbox_pending
    assert "outbox" in report.verified_from


def test_secret_scan_redacts_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    artifact_store.write_json(
        {
            "schema_version": "1.2.1",
            "run_id": "run_secret",
            "nested": {"api_key": "sk-test-secret-value-abcdefghijklmnopqrstuvwxyz"},
        },
        artifact_type="policy_decision",
        generated_by="pytest",
        metadata={"run_id": "run_secret", "decision_id": "pd_secret"},
        schema_version="1.2.1",
        artifact_id="art_secret",
    )

    report = EvidenceVerifier(artifact_store=artifact_store).verify("run_secret")

    assert report.secret_leak_warnings
    warning_text = " ".join(report.secret_leak_warnings)
    assert "api_key" in warning_text
    assert "sk-test-secret-value" not in warning_text


def test_scorecard_card_hard_failure_mismatch_fails_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    artifact_store.write_json(
        {"schema_version": "1.2.1", "run_id": "run_hard_fail", "hard_failures": ["pit_violation"]},
        artifact_type="scorecard",
        generated_by="pytest",
        metadata={"run_id": "run_hard_fail"},
        schema_version="1.2.1",
        artifact_id="art_scorecard",
    )
    artifact_store.write_json(
        {"schema_version": "1.2.1", "run_id": "run_hard_fail", "hard_failures": []},
        artifact_type="research_card",
        generated_by="pytest",
        metadata={"run_id": "run_hard_fail"},
        schema_version="1.2.1",
        artifact_id="art_card",
    )

    report = EvidenceVerifier(artifact_store=artifact_store).verify("run_hard_fail")

    assert report.passed is False
    assert report.hard_failure_inconsistencies == ["research_card hard_failures != scorecard hard_failures"]


def test_api_routes_are_get_only() -> None:
    import api_server

    evidence_paths = {
        "/research/evidence/{run_id}",
        "/research/evidence/{run_id}/verify",
        "/research/artifacts/{artifact_id}/lineage",
    }
    routes = {route.path: route.methods for route in api_server.app.routes if route.path in evidence_paths}

    assert set(routes) == evidence_paths
    assert all(methods == {"GET"} for methods in routes.values())

    client = TestClient(api_server.app)
    response = client.post("/research/evidence/run_x")
    assert response.status_code == 405
