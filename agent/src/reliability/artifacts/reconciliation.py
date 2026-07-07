"""Rebuild derived evidence indexes from durable evidence sources."""

from __future__ import annotations

from src.governance.evidence_index import EvidenceIndexStore, RunEvidenceIndex
from src.governance.evidence_outbox import EvidenceOutbox
from src.reliability.artifacts.store import ArtifactStore


class EvidenceReconciler:
    """Repair RunEvidenceIndex from artifacts and pending outbox rows."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        index_store: EvidenceIndexStore,
        outbox: EvidenceOutbox | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.index_store = index_store
        self.outbox = outbox

    def rebuild_run(self, run_id: str) -> RunEvidenceIndex:
        index = RunEvidenceIndex(run_id=run_id)
        for record in self.artifact_store.list_records(run_id=run_id):
            if record.artifact_type != "policy_decision":
                continue
            payload = self.artifact_store.read_json(record.artifact_id) or {}
            _merge_policy_decision_artifact(index, record.artifact_id, payload)
        if self.outbox is not None:
            for entry in self.outbox.list_pending(run_id=run_id):
                _append_unique(index.policy_decision_ids, entry.decision_id)
                _append_unique(index.degraded_reasons, "outbox_pending")
        return self.index_store.write(index)


def _merge_policy_decision_artifact(index: RunEvidenceIndex, artifact_id: str, payload: dict) -> None:
    decision_id = payload.get("decision_id") or payload.get("policy_decision_id")
    identity = payload.get("evidence_identity") if isinstance(payload.get("evidence_identity"), dict) else {}
    _append_unique(index.policy_decision_ids, decision_id)
    _append_unique(index.policy_decision_artifact_refs, artifact_id)
    _append_unique(index.trace_event_refs, identity.get("trace_event_id"))
    _append_unique(index.ledger_event_hashes, identity.get("ledger_event_hash"))


def _append_unique(values: list[str], value: str | None) -> None:
    if value and value not in values:
        values.append(value)

