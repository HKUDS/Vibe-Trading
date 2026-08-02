"""BaseTool wrapper for batch decay monitoring scan across active artifacts."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.strategy_store.decay import DecayEvaluator
from src.strategy_store.metrics import compute_decay_metrics, has_decay_inputs
from src.strategy_store.models import (
    ArtifactStatus,
    ArtifactType,
    DecaySnapshot,
)
from src.strategy_store._shared import get_store as _get_store


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False)


def _error(exc: Exception) -> str:
    return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


class SdmDecayScanTool(BaseTool):
    """Run decay monitoring scan on active factors/strategies."""

    name = "sdm_decay_scan"
    description = (
        "Run decay monitoring scan on active factors/strategies. "
        "Evaluates rolling IC vs baseline for each active artifact and "
        "reports decay signals."
    )
    is_readonly = False
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "universe": {
                "type": "string",
                "description": "Filter by universe",
            },
            "artifact_type": {
                "type": "string",
                "enum": ["factor", "strategy"],
                "description": "Filter by type",
            },
            "dry_run": {
                "type": "boolean",
                "description": "Report without applying transitions",
                "default": False,
            },
        },
        "required": [],
    }

    def execute(self, **kwargs: Any) -> str:
        """Scan active artifacts for decay and return a summary."""
        try:
            store = _get_store()
            evaluator = DecayEvaluator()

            universe = kwargs.get("universe")
            type_filter = None
            if kwargs.get("artifact_type"):
                type_filter = ArtifactType(kwargs["artifact_type"])
            dry_run = bool(kwargs.get("dry_run", False))

            # Collect ACTIVE and MONITORING artifacts
            active = store.list_artifacts(
                type=type_filter,
                status=ArtifactStatus.ACTIVE,
                universe=universe,
            )
            monitoring = store.list_artifacts(
                type=type_filter,
                status=ArtifactStatus.MONITORING,
                universe=universe,
            )

            targets = list(active) + list(monitoring)

            counts = {
                "total_scanned": 0,
                "healthy": 0,
                "warning": 0,
                "decayed": 0,
                "critical": 0,
                "insufficient_data": 0,
            }
            transitions_applied: list[dict[str, Any]] = []
            per_artifact: list[dict[str, Any]] = []

            for artifact in targets:
                counts["total_scanned"] += 1
                bench_history = list(store.get_bench_history(artifact.id, limit=20))

                if len(bench_history) < 3:
                    counts["insufficient_data"] += 1
                    per_artifact.append(
                        {
                            "artifact_id": artifact.id,
                            "name": artifact.name,
                            "signal": "insufficient_data",
                            "bench_count": len(bench_history),
                        }
                    )
                    continue

                metrics = compute_decay_metrics(bench_history)

                if not has_decay_inputs(metrics):
                    counts["insufficient_data"] += 1
                    per_artifact.append(
                        {
                            "artifact_id": artifact.id,
                            "name": artifact.name,
                            "signal": "insufficient_data",
                            "bench_count": len(bench_history),
                        }
                    )
                    continue

                signal = evaluator.evaluate_decay(
                    ic_ratio=metrics["ic_ratio"],
                    ir=metrics["rolling_ir"],
                    ic_positive_ratio=metrics["ic_positive_ratio"],
                    sharpe=metrics["rolling_sharpe"],
                )

                # Count by signal
                signal_key = signal.value
                if signal_key in counts:
                    counts[signal_key] += 1

                # Determine transition
                decay_history = list(store.get_decay_history(artifact.id, limit=10))
                prior_signals = [s.decay_signal for s in reversed(decay_history) if s.decay_signal is not None]
                recommended = evaluator.should_transition(artifact.status, prior_signals + [signal])

                # Count consecutive non-healthy signals for snapshot
                consecutive_warnings = 0
                for s in reversed(prior_signals + [signal]):
                    if s.value != "healthy":
                        consecutive_warnings += 1
                    else:
                        break

                # Apply transition if not dry_run
                transition_info: dict[str, Any] | None = None
                if recommended and not dry_run:
                    updated = store.update_status(
                        artifact.id,
                        recommended,
                        reason=f"Decay scan: {signal.value} signal triggered transition",
                    )
                    if updated is not None:
                        transition_info = {
                            "from": artifact.status.value,
                            "to": recommended.value,
                        }
                        transitions_applied.append(
                            {
                                "artifact_id": artifact.id,
                                "name": artifact.name,
                                **transition_info,
                            }
                        )

                # Record decay snapshot
                if not dry_run:
                    snapshot = DecaySnapshot(
                        artifact_id=artifact.id,
                        rolling_ic_mean=metrics["rolling_ic_mean"],
                        rolling_ir=metrics["rolling_ir"],
                        baseline_ic_mean=metrics["baseline_ic_mean"],
                        ic_ratio=metrics["ic_ratio"],
                        decay_signal=signal,
                        consecutive_warnings=consecutive_warnings,
                        detail=json.dumps(metrics, ensure_ascii=False),
                    )
                    store.record_decay_snapshot(snapshot)

                entry: dict[str, Any] = {
                    "artifact_id": artifact.id,
                    "name": artifact.name,
                    "current_status": artifact.status.value,
                    "signal": signal.value,
                    "metrics": metrics,
                }
                if transition_info:
                    entry["transition"] = transition_info
                elif recommended and dry_run:
                    entry["recommended_transition"] = recommended.value

                per_artifact.append(entry)

            return _ok(
                {
                    "summary": counts,
                    "transitions_applied": len(transitions_applied),
                    "dry_run": dry_run,
                    "artifacts": per_artifact,
                }
            )
        except Exception as exc:
            return _error(exc)
