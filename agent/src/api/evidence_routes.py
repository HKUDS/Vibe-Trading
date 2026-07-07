"""Read-only evidence closure API routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException

from src.governance.evidence_index import EvidenceIndexStore
from src.governance.evidence_outbox import EvidenceOutbox
from src.reliability.artifacts.graph import ArtifactGraph
from src.reliability.artifacts.store import ArtifactStore
from src.reliability.artifacts.verifier import EvidenceVerifier
from src.reliability.redaction import redact_secrets


def register_evidence_routes(
    app: FastAPI,
    *,
    auth_dependency=None,
    artifact_store_factory: Callable[[], ArtifactStore] | None = None,
    index_store_factory: Callable[[], EvidenceIndexStore] | None = None,
    outbox_factory: Callable[[], EvidenceOutbox] | None = None,
) -> None:
    """Register v1.2.1 read-only evidence routes."""
    dependencies = [Depends(auth_dependency)] if auth_dependency is not None else []
    artifact_store_factory = artifact_store_factory or ArtifactStore
    index_store_factory = index_store_factory or EvidenceIndexStore
    outbox_factory = outbox_factory or EvidenceOutbox

    @app.get("/research/evidence/{run_id}", dependencies=dependencies)
    async def get_research_evidence(run_id: str):
        index = index_store_factory().get(run_id)
        if index is None:
            report = EvidenceVerifier(
                artifact_store=artifact_store_factory(),
                index_store=index_store_factory(),
                outbox=outbox_factory(),
            ).verify(run_id)
            return {
                "schema_version": "1.2.1",
                "run_id": run_id,
                "index": None,
                "degraded": report.degraded,
                "degraded_reasons": report.degraded_reasons,
                "verified_from": report.verified_from,
            }
        return index.model_dump(mode="json")

    @app.get("/research/evidence/{run_id}/verify", dependencies=dependencies)
    async def verify_research_evidence(run_id: str):
        report = EvidenceVerifier(
            artifact_store=artifact_store_factory(),
            index_store=index_store_factory(),
            outbox=outbox_factory(),
        ).verify(run_id)
        return report.model_dump(mode="json")

    @app.get("/research/artifacts/{artifact_id}/lineage", dependencies=dependencies)
    async def get_artifact_lineage(artifact_id: str):
        lineage = ArtifactGraph(artifact_store_factory()).lineage(artifact_id)
        if not lineage.get("found"):
            raise HTTPException(status_code=404, detail="artifact not found")
        return lineage

    @app.get("/governance/policy-decisions", dependencies=dependencies)
    async def list_policy_decisions(run_id: str):
        artifact_store = artifact_store_factory()
        index = index_store_factory().get(run_id)
        records = artifact_store.list_records(run_id=run_id, artifact_type="policy_decision")
        if _should_return_legacy_policy_decisions(index=index, records=records):
            legacy_decisions: list[dict[str, Any]] = []
            for record in records:
                payload = artifact_store.read_json(record.artifact_id) or {}
                legacy_decisions.append(redact_secrets(payload))
            return {"schema_version": "1.0.0", "decisions": legacy_decisions}

        decisions: list[dict[str, Any]] = []
        decision_ids: list[str] = list(index.policy_decision_ids) if index is not None else []
        for record in records:
            payload = artifact_store.read_json(record.artifact_id) or {}
            decision_id = _first_text(payload.get("decision_id"), record.metadata.get("decision_id"))
            if decision_id:
                _append_unique(decision_ids, decision_id)
            decisions.append(_policy_decision_snapshot(payload, artifact_id=record.artifact_id))
        decisions.sort(key=lambda item: str(item.get("decision_id") or ""))
        decision_ids = [decision_id for decision_id in decision_ids if decision_id]
        return {
            "schema_version": "1.2.1",
            "run_id": run_id,
            "decision_ids": decision_ids,
            "decisions": decisions,
        }

    @app.get("/research/claims/{run_id}", dependencies=dependencies)
    async def get_research_claims(run_id: str):
        artifact_store = artifact_store_factory()
        index = index_store_factory().get(run_id)
        record = _latest_record_for_run(
            artifact_store,
            run_id=run_id,
            artifact_type="claim_set",
            preferred_refs=index.claim_set_artifact_refs if index is not None else [],
        )
        payload = artifact_store.read_json(record.artifact_id) if record is not None else None
        claims = payload.get("claims") if isinstance(payload, dict) else []
        claim_ids = [
            claim.get("claim_id")
            for claim in claims
            if isinstance(claim, dict) and isinstance(claim.get("claim_id"), str)
        ]
        return {
            "schema_version": "1.2.1",
            "run_id": run_id,
            "artifact_ref": record.artifact_id if record is not None else None,
            "claim_ids": claim_ids,
            "claim_set": _redact_secret_values(payload) if isinstance(payload, dict) else None,
        }

    @app.get("/research/methodology-facts/{run_id}", dependencies=dependencies)
    async def get_methodology_facts(run_id: str):
        artifact_store = artifact_store_factory()
        index = index_store_factory().get(run_id)
        record = _latest_record_for_run(
            artifact_store,
            run_id=run_id,
            artifact_type="methodology_facts",
            preferred_refs=index.methodology_fact_artifact_refs if index is not None else [],
        )
        payload = artifact_store.read_json(record.artifact_id) if record is not None else None
        return {
            "schema_version": "1.2.1",
            "run_id": run_id,
            "artifact_ref": record.artifact_id if record is not None else None,
            "methodology_facts": _redact_secret_values(payload) if isinstance(payload, dict) else None,
        }


def _should_return_legacy_policy_decisions(*, index: Any, records: list[Any]) -> bool:
    """Preserve the pre-v1.2.1 policy-decision API for v1.0 artifacts."""
    return bool(records) and index is None and all(record.schema_version == "1.0.0" for record in records)


def _policy_decision_snapshot(payload: dict[str, Any], *, artifact_id: str) -> dict[str, Any]:
    identity = payload.get("evidence_identity") if isinstance(payload.get("evidence_identity"), dict) else {}
    return {
        "decision_id": _first_text(payload.get("decision_id")),
        "tool_name": _first_text(payload.get("tool_name")),
        "action": _first_text(payload.get("action")),
        "status": _first_text(payload.get("status")),
        "mode": _first_text(payload.get("mode")),
        "surface": _first_text(payload.get("surface")),
        "risk_level": _first_text(payload.get("risk_level")),
        "reason_codes": [str(item) for item in payload.get("reason_codes") or []],
        "evidence_refs": [artifact_id],
        "trace_event_id": _first_text(identity.get("trace_event_id")),
        "ledger_event_hash": _first_text(identity.get("ledger_event_hash")),
    }


def _latest_record_for_run(
    artifact_store: ArtifactStore,
    *,
    run_id: str,
    artifact_type: str,
    preferred_refs: list[str],
):
    for artifact_id in reversed(preferred_refs):
        record = artifact_store.get_record(artifact_id)
        if record is not None and record.metadata.get("run_id") == run_id and record.artifact_type == artifact_type:
            return record
    records = artifact_store.list_records(run_id=run_id, artifact_type=artifact_type)  # type: ignore[arg-type]
    return records[-1] if records else None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _redact_secret_values(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in ("secret", "token", "api_key", "apikey", "password", "credential", "authorization")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_secret_values(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secret_values(item) for item in value]
    if isinstance(value, str) and value.lower().startswith(("sk-", "bearer ")):
        return "[REDACTED]"
    return value
