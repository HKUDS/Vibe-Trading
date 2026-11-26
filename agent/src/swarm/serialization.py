"""Shared serialization helpers for the swarm read boundaries."""

from __future__ import annotations

from typing import Any

from src.tools.redaction import redact_internal_paths


def serialize_task(task: Any) -> dict:
    """Project a SwarmTask into its public per-task dict.

    Args:
        task: Swarm task to expose to a reader.

    Returns:
        Public task fields including status, summary, iteration count, redacted error, timestamps,
        dependency lists, the task's tool narrowing (None inherits the agent's) and its input
        bindings.
    """
    status = task.status.value if hasattr(task.status, "value") else str(task.status)
    return {
        "id": task.id,
        "agent_id": task.agent_id,
        "status": status,
        "summary": task.summary,
        "iterations": getattr(task, "worker_iterations", 0),
        "error": redact_internal_paths(getattr(task, "error", None)) or None,
        "started_at": getattr(task, "started_at", None),
        "completed_at": getattr(task, "completed_at", None),
        "depends_on": list(getattr(task, "depends_on", []) or []),
        "blocked_by": list(getattr(task, "blocked_by", []) or []),
        "tools": getattr(task, "tools", None),
        "input_from": dict(getattr(task, "input_from", {}) or {}),
    }


def run_level_error(run: Any) -> str | None:
    """Format the first recorded task error for the run-level error field.

    Args:
        run: Run whose tasks are inspected in order.

    Returns:
        Task and agent IDs followed by the redacted error, or None if no task carries an error.
    """
    for task in getattr(run, "tasks", None) or []:
        err = getattr(task, "error", None)
        if err:
            return f"{task.id}/{task.agent_id}: {redact_internal_paths(err)}"
    return None
