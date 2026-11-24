"""Shared serialization helpers for the swarm read boundaries."""

from __future__ import annotations

from typing import Any

from src.tools.redaction import redact_internal_paths


def serialize_task(task: Any) -> dict:
    """Project a SwarmTask into its public per-task dict."""
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
    }


def run_level_error(run: Any) -> str | None:
    """First failed task's error, for a top-level ``error`` field."""
    for task in getattr(run, "tasks", None) or []:
        err = getattr(task, "error", None)
        if err:
            return f"{task.id}/{task.agent_id}: {redact_internal_paths(err)}"
    return None
