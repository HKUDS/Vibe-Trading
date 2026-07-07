"""Shared helpers for deterministic IRR-AGL v1.2.1 demos."""

from __future__ import annotations

import json
import os
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from src.api.evidence_routes import register_evidence_routes
from src.agent.trace import TraceWriter
from src.governance.evidence_index import EvidenceIndexStore
from src.governance.evidence_outbox import EvidenceOutbox
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.artifacts.verifier import EvidenceClosureReport, EvidenceVerifier
from src.research_card.builder import ResearchCardEvidenceArtifacts, build_research_card_evidence_artifacts

BUILDER_NAME = "src.research_card.builder.build_research_card_evidence_artifacts"
VERIFIER_NAME = "src.reliability.artifacts.verifier.EvidenceVerifier"


@dataclass
class DemoContext:
    """Local evidence sinks for a deterministic demo run."""

    demo_name: str
    root: Path
    artifact_store: ArtifactStore
    index_store: EvidenceIndexStore
    outbox: EvidenceOutbox
    trace_dir: Path


@dataclass
class BuiltEvidence:
    """Production-builder output plus the final post-card verifier report."""

    artifacts: ResearchCardEvidenceArtifacts
    report: EvidenceClosureReport


def prepare_demo_context(output_dir: Path | str | None, demo_name: str) -> DemoContext:
    """Prepare isolated local stores for one demo invocation."""
    ensure_demo_modes()
    root = Path(output_dir) if output_dir is not None else Path(tempfile.mkdtemp(prefix=f"{demo_name}_"))
    if root.name != demo_name:
        root = root / demo_name
    root.mkdir(parents=True, exist_ok=True)
    return DemoContext(
        demo_name=demo_name,
        root=root,
        artifact_store=ArtifactStore(root / "artifacts"),
        index_store=EvidenceIndexStore(root / "evidence_index.sqlite"),
        outbox=EvidenceOutbox(root / "evidence_outbox.sqlite"),
        trace_dir=root / "trace",
    )


def ensure_demo_modes() -> None:
    """Force deterministic local evidence writes for demo scripts."""
    os.environ["VIBE_TRADING_RELIABILITY_MODE"] = "observe"
    os.environ["VIBE_TRADING_EVIDENCE_INDEX_ENABLED"] = "1"
    if os.getenv("VIBE_TRADING_GOVERNANCE_MODE", "observe").strip().lower() == "off":
        os.environ["VIBE_TRADING_GOVERNANCE_MODE"] = "observe"


def trace_writer(context: DemoContext) -> TraceWriter:
    """Create a trace writer under the demo output directory."""
    return TraceWriter(context.trace_dir)


def record_data_audit(context: DemoContext, run_id: str, payload: dict[str, Any]) -> str:
    """Persist the demo data-audit input and expose it through the evidence index."""
    record = context.artifact_store.write_json(
        payload,
        artifact_type="data_audit",
        generated_by=f"{context.demo_name}.fixture",
        metadata={"run_id": run_id},
        schema_version="1.2.1",
    )
    if record is None:
        raise RuntimeError("data audit artifact was not written")
    index = context.index_store.get_or_create(run_id)
    if record.artifact_id not in index.data_audit_artifact_refs:
        index.data_audit_artifact_refs.append(record.artifact_id)
    context.index_store.write(index)
    return record.artifact_id


def record_trial_events(context: DemoContext, run_id: str, events: list[dict[str, Any]]) -> list[str]:
    """Persist deterministic trial events without constructing the final card."""
    artifact_ids: list[str] = []
    for event in events:
        record = context.artifact_store.write_json(
            {"schema_version": "1.2.1", "run_id": run_id, **event},
            artifact_type="trial_event",
            generated_by=f"{context.demo_name}.fixture",
            metadata={"run_id": run_id, "trial_id": str(event.get("trial_id") or "")},
            schema_version="1.2.1",
        )
        if record is None:
            raise RuntimeError("trial event artifact was not written")
        artifact_ids.append(record.artifact_id)
    return artifact_ids


def build_card_evidence(
    context: DemoContext,
    *,
    research_card: dict[str, Any],
    protocol: dict[str, Any] | None = None,
    data_audit: dict[str, Any] | None = None,
    scorecard: dict[str, Any] | None = None,
    trial_ledger: dict[str, Any] | None = None,
    policy_decision_ids: list[str] | None = None,
) -> BuiltEvidence:
    """Build final card evidence with production builders and verify after export."""
    artifacts = build_research_card_evidence_artifacts(
        research_card,
        artifact_store=context.artifact_store,
        evidence_index=context.index_store,
        protocol=protocol,
        data_audit=data_audit,
        scorecard=scorecard,
        trial_ledger=trial_ledger,
        policy_decision_ids=policy_decision_ids,
        evidence_outbox=context.outbox,
    )
    report = EvidenceVerifier(
        artifact_store=context.artifact_store,
        index_store=context.index_store,
        outbox=context.outbox,
        trace_dir=context.trace_dir,
    ).verify(artifacts.run_id)
    return BuiltEvidence(artifacts=artifacts, report=report)


def policy_decision_ids_via_api(context: DemoContext, run_id: str) -> list[str]:
    """Read policy decision IDs through the production read-only API route."""
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Using `httpx` with `starlette.testclient` is deprecated.*",
            category=Warning,
        )
        from fastapi.testclient import TestClient

    app = FastAPI()
    register_evidence_routes(
        app,
        artifact_store_factory=lambda: context.artifact_store,
        index_store_factory=lambda: context.index_store,
        outbox_factory=lambda: context.outbox,
    )
    response = TestClient(app).get(f"/governance/policy-decisions?run_id={run_id}")
    response.raise_for_status()
    payload = response.json()
    return [str(decision_id) for decision_id in payload.get("decision_ids") or []]


def write_demo_summary(context: DemoContext, result: dict[str, Any]) -> None:
    """Persist a compact run summary that is not a final evidence artifact."""
    path = context.root / "demo-summary.json"
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def json_main(result: dict[str, Any]) -> None:
    """Print a deterministic JSON result for CLI usage."""
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
