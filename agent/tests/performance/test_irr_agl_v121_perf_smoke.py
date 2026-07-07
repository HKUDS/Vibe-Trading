"""Phase 10 performance smoke tests for v1.2.1 evidence paths."""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.governance.decision_recorder import DecisionRecorder
from src.governance.decisions import PolicyDecision
from src.governance.evidence_index import EvidenceIndexStore
from src.governance.runtime import RuntimeContext
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.artifacts.verifier import EvidenceVerifier
from src.reliability.claims.extractor import build_claim_set_from_research_card


class FakeArtifactStore:
    """In-memory artifact store for DecisionRecorder fake-store timing."""

    def __init__(self) -> None:
        self.records: dict[str, SimpleNamespace] = {}

    def get_record(self, artifact_id: str):
        return self.records.get(artifact_id)

    def write_json(self, payload, *, artifact_id: str, **kwargs):
        del payload, kwargs
        record = SimpleNamespace(artifact_id=artifact_id)
        self.records[artifact_id] = record
        return record


def _p99_ms(values: list[float]) -> float:
    return statistics.quantiles(values, n=100, method="inclusive")[98]


def test_decision_recorder_fake_store_p99_under_15ms() -> None:
    recorder = DecisionRecorder(artifact_store=FakeArtifactStore(), generated_by="perf_smoke")
    samples: list[float] = []
    for index in range(250):
        decision = PolicyDecision(
            tool_name="fake_shell",
            action="deny",
            risk_level="R5_SHELL",
            reasons=["blocked"],
            reason_codes=["R5_DENIED"],
        )
        context = RuntimeContext(mode="warn", surface="remote_api", run_id=f"run_perf_{index}")
        start = time.perf_counter()
        envelope = recorder.prepare(decision, params={"command": "echo denied", "i": index}, context=context)
        recorder.record_best_effort(envelope)
        samples.append((time.perf_counter() - start) * 1000)

    assert _p99_ms(samples) < 15


def test_evidence_verifier_complete_fixture_under_200ms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    run_id = "run_perf_verify"
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    index_store = EvidenceIndexStore(tmp_path / "evidence_index.sqlite")
    artifact_store.write_json(
        {
            "schema_version": "1.2.1",
            "run_id": run_id,
            "conclusion_level": "exploratory",
            "hard_failures": [],
        },
        artifact_type="scorecard",
        generated_by="perf_smoke",
        metadata={"run_id": run_id},
        schema_version="1.2.1",
        artifact_id="art_perf_scorecard",
    )
    artifact_store.write_json(
        {
            "schema_version": "1.2.1",
            "run_id": run_id,
            "conclusion_level": "exploratory",
            "hard_failures": [],
        },
        artifact_type="research_card",
        generated_by="perf_smoke",
        metadata={"run_id": run_id},
        schema_version="1.2.1",
        artifact_id="art_perf_card",
    )
    index = index_store.get_or_create(run_id)
    index.scorecard_artifact_refs = ["art_perf_scorecard"]
    index.research_card_artifact_refs = ["art_perf_card"]
    index_store.write(index)

    start = time.perf_counter()
    report = EvidenceVerifier(artifact_store=artifact_store, index_store=index_store).verify(run_id)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert report.passed is True
    assert elapsed_ms < 200


def test_claimset_deterministic_extraction_under_50ms() -> None:
    start = time.perf_counter()
    claim_set = build_claim_set_from_research_card(
        {
            "run_id": "run_perf_claims",
            "conclusion_level": "research_candidate",
            "structured_claims": [
                {
                    "claim_type": "generalization",
                    "claim_text": "The result generalizes across the declared split.",
                    "source_ref": "perf.structured_claims[0]",
                }
            ],
        }
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert claim_set.claims
    assert elapsed_ms < 50
