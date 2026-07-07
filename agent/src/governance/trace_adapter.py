"""Trace adapter for policy decisions."""

from __future__ import annotations

from typing import Any

from src.governance.decisions import PolicyDecision


class DecisionRecorder:
    """Collect and optionally emit governance records to an existing trace."""

    def __init__(self, trace_writer: Any | None = None) -> None:
        self.trace_writer = trace_writer
        self.decisions: list[PolicyDecision] = []
        self.records: list[dict[str, Any]] = []

    def set_trace_writer(self, trace_writer: Any | None) -> None:
        self.trace_writer = trace_writer

    def record(self, decision: PolicyDecision, *, manifest: object | None = None) -> None:
        del manifest
        self.decisions.append(decision)
        record: dict[str, Any] = {
            "type": "policy_decision",
            "decision": decision.model_dump(mode="json"),
        }
        self.records.append(record)
        if self.trace_writer is not None and hasattr(self.trace_writer, "write"):
            self.trace_writer.write(record)

    def record_denied(self, decision: PolicyDecision, *, trace_status: str, shadow: bool) -> None:
        record = {
            "type": "policy_denied",
            "status": trace_status,
            "shadow": shadow,
            "decision_id": decision.decision_id,
            "tool_name": decision.tool_name,
            "rule_id": decision.rule_id,
        }
        self.records.append(record)
        if self.trace_writer is not None and hasattr(self.trace_writer, "write"):
            self.trace_writer.write(record)
