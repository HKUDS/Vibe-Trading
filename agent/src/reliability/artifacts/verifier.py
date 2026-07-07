"""Independent evidence closure verifier for v1.2.1."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.agent.trace import TraceWriter
from src.governance.evidence_index import EvidenceIndexStore, RunEvidenceIndex
from src.governance.evidence_outbox import EvidenceOutbox
from src.reliability.artifacts.store import ArtifactStore

VerifiedSource = Literal["trace", "artifact", "ledger", "index", "outbox", "card", "scorecard"]


class EvidenceClosureReport(BaseModel):
    """Verification result for a run evidence chain."""

    schema_version: str = "1.2.1"
    run_id: str
    passed: bool
    degraded: bool = False
    verified_from: list[VerifiedSource] = Field(default_factory=list)
    missing_refs: list[str] = Field(default_factory=list)
    dangling_refs: list[str] = Field(default_factory=list)
    inconsistent_ids: list[str] = Field(default_factory=list)
    partial_decisions: list[str] = Field(default_factory=list)
    outbox_pending: list[str] = Field(default_factory=list)
    secret_leak_warnings: list[str] = Field(default_factory=list)
    lineage_errors: list[str] = Field(default_factory=list)
    hard_failure_inconsistencies: list[str] = Field(default_factory=list)
    claim_gate_inconsistencies: list[str] = Field(default_factory=list)
    required_refs_present: dict[str, bool] = Field(default_factory=dict)
    degraded_reasons: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceVerifier:
    """Verify evidence without treating the index as the sole truth source."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        index_store: EvidenceIndexStore | None = None,
        outbox: EvidenceOutbox | None = None,
        trace_dir: Path | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.index_store = index_store
        self.outbox = outbox
        self.trace_dir = trace_dir

    def verify(self, run_id: str) -> EvidenceClosureReport:
        verified_from: list[VerifiedSource] = []
        degraded_reasons: list[str] = []
        missing_refs: list[str] = []
        dangling_refs: list[str] = []
        inconsistent_ids: list[str] = []
        partial_decisions: list[str] = []
        outbox_pending: list[str] = []
        secret_leak_warnings: list[str] = []
        hard_failure_inconsistencies: list[str] = []
        scorecard_hard_failures: list[str] | None = None
        card_hard_failures: list[str] | None = None

        index = self.index_store.get(run_id) if self.index_store is not None else None
        original_index_decision_ids: set[str] = set()
        if index is not None:
            verified_from.append("index")
            original_index_decision_ids = set(index.policy_decision_ids)
        else:
            index = RunEvidenceIndex(run_id=run_id)
            degraded_reasons.append("index_missing_rebuilt_from_artifacts")

        artifact_records = self.artifact_store.list_records(run_id=run_id)
        artifact_payloads: dict[str, dict] = {}
        for record in artifact_records:
            verified_from = _add_source(verified_from, "artifact")
            payload = self.artifact_store.read_json(record.artifact_id) or {}
            artifact_payloads[record.artifact_id] = payload
            secret_leak_warnings.extend(_secret_paths(payload, root=f"artifact:{record.artifact_id}"))
            if record.artifact_type == "policy_decision":
                _merge_artifact_into_index(index, record.artifact_id, payload)
            elif record.artifact_type == "scorecard":
                verified_from = _add_source(verified_from, "scorecard")
                scorecard_hard_failures = _string_list(payload.get("hard_failures"))
            elif record.artifact_type == "research_card":
                verified_from = _add_source(verified_from, "card")
                card_hard_failures = _string_list(payload.get("hard_failures"))

        trace_decision_ids: set[str] = set()
        trace_event_ids: set[str] = set()
        if self.trace_dir is not None:
            entries = TraceWriter.read(self.trace_dir)
            for entry in entries:
                if entry.get("type") != "policy_decision":
                    continue
                verified_from = _add_source(verified_from, "trace")
                decision_id = entry.get("policy_decision_id")
                trace_event_id = entry.get("trace_event_id")
                if isinstance(decision_id, str):
                    trace_decision_ids.add(decision_id)
                    _append_unique(index.policy_decision_ids, decision_id)
                if isinstance(trace_event_id, str):
                    trace_event_ids.add(trace_event_id)
                    _append_unique(index.trace_event_refs, trace_event_id)

        artifact_ids = {record.artifact_id for record in artifact_records}
        for ref in index.policy_decision_artifact_refs:
            if ref not in artifact_ids:
                dangling_refs.append(ref)

        artifact_decision_ids = {
            payload.get("decision_id")
            for payload in artifact_payloads.values()
            if isinstance(payload.get("decision_id"), str)
        }
        if original_index_decision_ids and artifact_decision_ids:
            for decision_id in artifact_decision_ids - original_index_decision_ids:
                inconsistent_ids.append(decision_id)
            for decision_id in original_index_decision_ids - artifact_decision_ids:
                inconsistent_ids.append(decision_id)

        pending = self.outbox.list_pending(run_id=run_id) if self.outbox is not None else []
        for entry in pending:
            verified_from = _add_source(verified_from, "outbox")
            outbox_pending.append(entry.decision_id)
            degraded_reasons.append("outbox_pending")

        required_refs_present = {
            "policy_decision_ids": bool(index.policy_decision_ids),
            "policy_decision_artifact_refs": bool(index.policy_decision_artifact_refs),
            "trace_event_refs": bool(index.trace_event_refs),
        }
        if index.policy_decision_ids:
            if not index.policy_decision_artifact_refs:
                missing_refs.append("policy_decision_artifact_refs")
            if trace_event_ids and not index.trace_event_refs:
                missing_refs.append("trace_event_refs")

        if scorecard_hard_failures is not None and card_hard_failures is not None:
            if scorecard_hard_failures != card_hard_failures:
                hard_failure_inconsistencies.append("research_card hard_failures != scorecard hard_failures")

        degraded = bool(degraded_reasons or partial_decisions)
        passed = not (
            missing_refs
            or dangling_refs
            or inconsistent_ids
            or outbox_pending
            or hard_failure_inconsistencies
        )
        return EvidenceClosureReport(
            run_id=run_id,
            passed=passed,
            degraded=degraded,
            verified_from=verified_from,
            missing_refs=sorted(set(missing_refs)),
            dangling_refs=sorted(set(dangling_refs)),
            inconsistent_ids=sorted(set(inconsistent_ids)),
            partial_decisions=sorted(set(partial_decisions)),
            outbox_pending=sorted(set(outbox_pending)),
            secret_leak_warnings=sorted(set(secret_leak_warnings)),
            hard_failure_inconsistencies=sorted(set(hard_failure_inconsistencies)),
            required_refs_present=required_refs_present,
            degraded_reasons=sorted(set(degraded_reasons)),
        )


def _merge_artifact_into_index(index: RunEvidenceIndex, artifact_id: str, payload: dict) -> None:
    _append_unique(index.policy_decision_ids, payload.get("decision_id"))
    _append_unique(index.policy_decision_artifact_refs, artifact_id)
    identity = payload.get("evidence_identity") if isinstance(payload.get("evidence_identity"), dict) else {}
    _append_unique(index.trace_event_refs, identity.get("trace_event_id"))
    _append_unique(index.ledger_event_hashes, identity.get("ledger_event_hash"))


def _secret_paths(value: object, *, root: str) -> list[str]:
    warnings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{root}.{key}"
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in ("secret", "token", "api_key", "apikey", "password", "credential", "broker", "authorization")):
                warnings.append(path)
            else:
                warnings.extend(_secret_paths(item, root=path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            warnings.extend(_secret_paths(item, root=f"{root}[{index}]"))
    return warnings


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)


def _add_source(values: list[VerifiedSource], value: VerifiedSource) -> list[VerifiedSource]:
    if value not in values:
        values.append(value)
    return values
