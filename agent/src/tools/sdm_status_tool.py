"""BaseTool wrapper for querying and updating strategy store artifact status."""

from __future__ import annotations

import json
from dataclasses import asdict

from src.strategy_store.models import is_four_eyes_violation
from typing import Any

from src.agent.tools import BaseTool
from src.strategy_store.decay import DecayEvaluator
from src.strategy_store.metrics import compute_decay_metrics, has_decay_inputs
from src.strategy_store.models import (
    ArtifactStatus,
    ArtifactType,
)
from src.strategy_store._shared import get_store as _get_store


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False)


def _error(exc: Exception) -> str:
    return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


def _artifact_to_dict(artifact: Any) -> dict[str, Any]:
    """Convert a frozen dataclass artifact to a JSON-safe dict."""
    d = asdict(artifact)
    # Enum values → strings for JSON serialization
    if "type" in d:
        d["type"] = d["type"].value if hasattr(d["type"], "value") else d["type"]
    if "status" in d:
        d["status"] = (
            d["status"].value if hasattr(d["status"], "value") else d["status"]
        )
    if "category" in d and d["category"] is not None:
        d["category"] = (
            d["category"].value
            if hasattr(d["category"], "value")
            else d["category"]
        )
    for enum_field in ("model_tier", "validation_status"):
        if d.get(enum_field) is not None and hasattr(d[enum_field], "value"):
            d[enum_field] = d[enum_field].value

    # Model-governance readout. Reported on every artifact, including the ones
    # carrying no governance data at all -- "this model is unregistered" is the
    # finding, and omitting the block when it is empty would hide it.
    governance = {
        "registered": any(
            d.get(f) for f in ("developer", "owner", "validator", "approver",
                               "intended_use", "limitations")
        ),
        "four_eyes_violation": is_four_eyes_violation(artifact),
    }
    if not governance["registered"]:
        governance["note"] = (
            "no owner, validator, approver, intended use or limitations recorded: "
            "this is an unregistered model under any model-risk policy"
        )
    elif governance["four_eyes_violation"]:
        governance["note"] = (
            f"developer and approver are the same person ({d.get('developer')!r}); "
            "the approval carries no independent review"
        )
    d["governance"] = governance
    return d


class SdmStatusTool(BaseTool):
    """Query or update factor/strategy status in the strategy store."""

    name = "sdm_status"
    description = (
        "Query or update factor/strategy status in the strategy store. "
        "Actions: list, detail, disable, enable, decay_check."
    )
    is_readonly = False
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "detail", "disable", "enable", "decay_check"],
                "description": "Action to perform",
            },
            "artifact_id": {
                "type": "string",
                "description": "Artifact ID (required for detail/disable/enable/decay_check)",
            },
            "artifact_type": {
                "type": "string",
                "enum": ["factor", "strategy"],
                "description": "Filter by type (list only)",
            },
            "status_filter": {
                "type": "string",
                "description": "Filter by status (list only)",
            },
            "universe_filter": {
                "type": "string",
                "description": "Filter by universe (list only)",
            },
            "reason": {
                "type": "string",
                "description": "Reason for disable",
            },
        },
        "required": ["action"],
    }

    def execute(self, **kwargs: Any) -> str:
        """Route by action and return the result as JSON."""
        try:
            store = _get_store()
            action = str(kwargs["action"])

            if action == "list":
                return self._handle_list(store, kwargs)
            if action == "detail":
                return self._handle_detail(store, kwargs)
            if action == "disable":
                return self._handle_disable(store, kwargs)
            if action == "enable":
                return self._handle_enable(store, kwargs)
            if action == "decay_check":
                return self._handle_decay_check(store, kwargs)

            return _error(ValueError(f"Unknown action: {action}"))
        except Exception as exc:
            return _error(exc)

    def _handle_list(
        self, store: Any, kwargs: dict[str, Any]
    ) -> str:
        """List artifacts with optional filters."""
        type_filter = None
        if kwargs.get("artifact_type"):
            type_filter = ArtifactType(kwargs["artifact_type"])

        status_filter = None
        if kwargs.get("status_filter"):
            status_filter = ArtifactStatus(kwargs["status_filter"])

        artifacts = store.list_artifacts(
            type=type_filter,
            status=status_filter,
            universe=kwargs.get("universe_filter"),
        )
        return _ok({
            "count": len(artifacts),
            "artifacts": [_artifact_to_dict(a) for a in artifacts],
        })

    def _handle_detail(
        self, store: Any, kwargs: dict[str, Any]
    ) -> str:
        """Get full detail for a single artifact."""
        artifact_id = str(kwargs.get("artifact_id", ""))
        if not artifact_id:
            return _error(ValueError("artifact_id is required for detail"))

        artifact = store.get_artifact(artifact_id)
        if artifact is None:
            return _error(ValueError(f"Artifact not found: {artifact_id}"))

        bench_history = store.get_bench_history(artifact_id, limit=50)
        decay_history = store.get_decay_history(artifact_id, limit=20)

        return _ok({
            "artifact": _artifact_to_dict(artifact),
            "bench_history": [asdict(r) for r in bench_history],
            "decay_history": [asdict(s) for s in decay_history],
        })

    def _handle_disable(
        self, store: Any, kwargs: dict[str, Any]
    ) -> str:
        """Disable an artifact."""
        artifact_id = str(kwargs.get("artifact_id", ""))
        if not artifact_id:
            return _error(ValueError("artifact_id is required for disable"))

        updated = store.update_status(
            artifact_id,
            ArtifactStatus.DISABLED,
            reason=kwargs.get("reason"),
        )
        if updated is None:
            return _error(ValueError(f"Artifact not found: {artifact_id}"))

        return _ok({"artifact": _artifact_to_dict(updated)})

    def _handle_enable(
        self, store: Any, kwargs: dict[str, Any]
    ) -> str:
        """Re-enable a disabled artifact."""
        artifact_id = str(kwargs.get("artifact_id", ""))
        if not artifact_id:
            return _error(ValueError("artifact_id is required for enable"))

        updated = store.update_status(artifact_id, ArtifactStatus.ACTIVE)
        if updated is None:
            return _error(ValueError(f"Artifact not found: {artifact_id}"))

        return _ok({"artifact": _artifact_to_dict(updated)})

    def _handle_decay_check(
        self, store: Any, kwargs: dict[str, Any]
    ) -> str:
        """Evaluate decay state for an artifact."""
        artifact_id = str(kwargs.get("artifact_id", ""))
        if not artifact_id:
            return _error(ValueError("artifact_id is required for decay_check"))

        artifact = store.get_artifact(artifact_id)
        if artifact is None:
            return _error(ValueError(f"Artifact not found: {artifact_id}"))

        bench_history = list(store.get_bench_history(artifact_id, limit=10))
        if len(bench_history) < 3:
            return _ok({
                "artifact_id": artifact_id,
                "signal": "insufficient_data",
                "message": f"Need at least 3 bench results, have {len(bench_history)}",
            })

        metrics = compute_decay_metrics(bench_history)
        if not has_decay_inputs(metrics):
            return _ok({
                "artifact_id": artifact_id,
                "signal": "insufficient_data",
                "message": (
                    f"{len(bench_history)} bench results but no evaluable "
                    "metric (need ic_mean or sharpe values)"
                ),
            })
        evaluator = DecayEvaluator()

        signal = evaluator.evaluate_decay(
            ic_ratio=metrics["ic_ratio"],
            ir=metrics["rolling_ir"],
            ic_positive_ratio=metrics["ic_positive_ratio"],
            sharpe=metrics["rolling_sharpe"],
        )

        # Get prior decay signals from history
        decay_history = list(store.get_decay_history(artifact_id, limit=10))
        prior_signals = [
            s.decay_signal for s in reversed(decay_history)
            if s.decay_signal is not None
        ]

        recommended_transition = evaluator.should_transition(
            artifact.status, prior_signals + [signal]
        )

        return _ok({
            "artifact_id": artifact_id,
            "current_status": artifact.status.value,
            "signal": signal.value,
            "recommended_transition": (
                recommended_transition.value if recommended_transition else None
            ),
            "metrics": metrics,
        })
