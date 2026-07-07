"""Best-effort policy decision recording with explicit partial outcomes."""

from __future__ import annotations

import re
from typing import Any

from src.governance.decisions import PolicyDecision, RecordedPolicyDecision
from src.governance.evidence_identity import (
    EvidenceIdentity,
    EvidenceWriteOutcome,
    compute_idempotency_key,
    decision_id_for_key,
    hash_params,
    policy_decision_artifact_id_for_key,
    trace_event_id_for_key,
)
from src.reliability.artifacts.store import ArtifactStore

_SECRET_KEY_RE = re.compile(r"(token|key|secret|password|credential|api|auth|broker)", re.IGNORECASE)
_REDACTED = "[REDACTED]"


class DecisionRecorder:
    """Prepare and persist policy decisions without affecting allow/deny."""

    def __init__(
        self,
        *,
        artifact_store: Any | None = None,
        trace_writer: Any | None = None,
        generated_by: str = "DecisionRecorder",
    ) -> None:
        self.artifact_store = artifact_store if artifact_store is not None else ArtifactStore()
        self.trace_writer = trace_writer
        self.generated_by = generated_by

    def prepare(
        self,
        decision: PolicyDecision,
        *,
        params: dict[str, Any],
        context: Any,
    ) -> RecordedPolicyDecision:
        """Build a stable recorded decision envelope without writing evidence."""
        params_hash = hash_params(params)
        idempotency_key = compute_idempotency_key(
            decision=decision,
            context=context,
            params_hash=params_hash,
        )
        decision_id = decision_id_for_key(idempotency_key)
        identity = EvidenceIdentity(
            decision_id=decision_id,
            run_id=getattr(context, "run_id", None),
            session_id=getattr(context, "session_id", None),
            trial_id=getattr(context, "trial_id", None),
            protocol_hash=getattr(context, "protocol_hash", None),
            idempotency_key=idempotency_key,
        )
        return RecordedPolicyDecision(
            decision_id=decision_id,
            tool_name=decision.tool_name,
            action=decision.action,
            status=_status_for_action(decision.action),
            mode=getattr(context, "mode", "observe"),
            surface=getattr(context, "surface", "unknown"),
            risk_level=decision.risk_level,
            reasons=list(decision.reasons),
            reason_codes=list(decision.reason_codes),
            required_checks=list(decision.required_checks),
            check_results=dict(decision.check_results),
            run_id=getattr(context, "run_id", None),
            session_id=getattr(context, "session_id", None),
            trial_id=getattr(context, "trial_id", None),
            protocol_hash=getattr(context, "protocol_hash", None),
            params_hash=params_hash,
            redacted_params_preview=_redact_params(params),
            evidence_identity=identity,
            created_at=decision.created_at,
            metadata={"policy_engine_version": decision.policy_engine_version, **decision.metadata},
        )

    def record_best_effort(self, envelope: RecordedPolicyDecision) -> EvidenceWriteOutcome:
        """Write trace/artifact evidence best-effort and never raise to callers."""
        errors: list[str] = []
        trace_event_id = trace_event_id_for_key(envelope.evidence_identity.idempotency_key)
        artifact_id = policy_decision_artifact_id_for_key(envelope.evidence_identity.idempotency_key)
        trace_written = False
        artifact_written = False

        if self.trace_writer is not None:
            try:
                trace_payload = self._trace_payload(envelope, trace_event_id)
                self.trace_writer.write(trace_payload)
                trace_written = True
                envelope.evidence_identity.trace_event_id = trace_event_id
            except Exception as exc:  # noqa: BLE001 - evidence write must not alter policy outcome.
                errors.append(f"trace: {exc}")

        if self.artifact_store is not None:
            try:
                existing = getattr(self.artifact_store, "get_record", lambda _artifact_id: None)(artifact_id)
                if existing is None:
                    record = self.artifact_store.write_json(
                        envelope.model_dump(mode="json", exclude={"write_outcome"}),
                        artifact_type="policy_decision",
                        generated_by=self.generated_by,
                        metadata={
                            "schema_version": envelope.schema_version,
                            "decision_id": envelope.decision_id,
                            "idempotency_key": envelope.evidence_identity.idempotency_key,
                            "run_id": envelope.run_id,
                            "surface": envelope.surface,
                            "risk_level": envelope.risk_level,
                        },
                        parent_artifacts=envelope.parent_artifacts,
                        schema_version=envelope.schema_version,
                        artifact_id=artifact_id,
                    )
                else:
                    record = existing
                if record is not None:
                    artifact_written = True
                    envelope.evidence_identity.policy_decision_artifact_id = record.artifact_id
                    if record.artifact_id not in envelope.evidence_refs:
                        envelope.evidence_refs.append(record.artifact_id)
            except Exception as exc:  # noqa: BLE001 - evidence write must not alter policy outcome.
                errors.append(f"artifact: {exc}")

        outcome = EvidenceWriteOutcome(
            decision_id=envelope.decision_id,
            trace_written=trace_written,
            artifact_written=artifact_written,
            trace_event_id=envelope.evidence_identity.trace_event_id,
            policy_decision_artifact_id=envelope.evidence_identity.policy_decision_artifact_id,
            errors=errors,
            status=_outcome_status(
                trace_written=trace_written,
                artifact_written=artifact_written,
                trace_attempted=self.trace_writer is not None,
                artifact_attempted=self.artifact_store is not None,
                errors=errors,
            ),
        )
        envelope.write_outcome = outcome
        return outcome

    def record_pre_execution_best_effort(self, envelope: RecordedPolicyDecision) -> EvidenceWriteOutcome:
        """Record an allow/warn decision before the inner tool executes."""
        return self.record_best_effort(envelope)

    def record_post_execution_best_effort(
        self,
        envelope: RecordedPolicyDecision,
        *,
        status: str,
        error: BaseException | None = None,
    ) -> EvidenceWriteOutcome:
        """Record the final execution status without changing policy outcome."""
        if status == "failed":
            envelope.status = "failed"
            if error is not None:
                envelope.metadata["execution_error"] = str(error)
        return self.record_best_effort(envelope)

    @staticmethod
    def _trace_payload(envelope: RecordedPolicyDecision, trace_event_id: str) -> dict[str, Any]:
        return {
            "type": "policy_decision",
            "trace_event_id": trace_event_id,
            "policy_decision_id": envelope.decision_id,
            "tool": envelope.tool_name,
            "action": envelope.action,
            "status": envelope.status,
            "mode": envelope.mode,
            "surface": envelope.surface,
            "risk_level": envelope.risk_level,
            "reason_codes": envelope.reason_codes,
            "evidence_identity": envelope.evidence_identity.model_dump(mode="json"),
        }


def _status_for_action(action: str) -> str:
    if action == "allow":
        return "allowed"
    if action == "warn":
        return "warned"
    return "denied"


def _outcome_status(
    *,
    trace_written: bool,
    artifact_written: bool,
    trace_attempted: bool,
    artifact_attempted: bool,
    errors: list[str],
) -> str:
    if not errors:
        return "complete"
    if trace_written and not artifact_written:
        return "partial_trace_only"
    if artifact_written and not trace_written:
        return "partial_artifact_only"
    if trace_attempted or artifact_attempted:
        return "write_failed"
    return "complete"


def _redact_params(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            redacted[key_text] = _REDACTED if _SECRET_KEY_RE.search(key_text) else _redact_params(item)
        return redacted
    if isinstance(value, list):
        return [_redact_params(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_params(item) for item in value]
    return value

