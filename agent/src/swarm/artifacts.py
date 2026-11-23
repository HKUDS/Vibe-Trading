"""Task workspace paths and artifact lifecycle for swarm runs."""

import shutil
from pathlib import Path


def agent_artifact_dir(run_dir: Path, agent_id: str, task_id: str) -> Path:
    """Return the canonical artifacts directory for one task within a run.

    The single source of truth for this path — shared with the retry loop
    in ``runtime.py`` so the two can never compute it differently and drift
    apart.  The guard belongs here rather than only in
    ``clear_agent_artifacts`` because this path is also used by ``run_worker``
    for ``mkdir``; validating the shared constructor protects both directory
    creation and recursive cleanup from the same path escape.

    Keyed by ``(agent_id, task_id)`` rather than ``agent_id`` alone: a preset
    where one agent handles multiple tasks (sequentially or, across workers,
    concurrently) must not have those tasks share a directory. Sharing meant
    a later task's read of the directory could pick up an earlier task's
    still-there files, and clearing the shared directory before a later task
    could delete an earlier, concurrently-running task's in-flight output.
    A directory scoped to one task never has either problem, and earlier
    tasks' artifacts simply stay in place under their own task_id once the
    agent moves on, instead of being deleted.

    Args:
        run_dir: Root directory for the swarm run.
        agent_id: Single safe path segment identifying the agent.
        task_id: Single safe path segment identifying the task.

    Raises:
        ValueError: If ``agent_id`` or ``task_id`` is not a single safe path
            segment, or the resolved artifact directory is not exactly two
            levels below the resolved ``run_dir/artifacts`` directory.
    """
    artifact_root = run_dir / "artifacts"

    def _check(label: str, value: str) -> None:
        if (
            not isinstance(value, str)
            or not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
        ):
            raise ValueError(
                f"Invalid swarm {label} {value!r}: expected one safe path segment"
            )

    _check("agent id", agent_id)
    _check("task id", task_id)

    artifact_dir = artifact_root / agent_id / task_id
    resolved_root = artifact_root.resolve()
    resolved_dir = artifact_dir.resolve()
    try:
        relative = resolved_dir.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(
            f"Invalid swarm agent/task id {agent_id!r}/{task_id!r}: artifact "
            "path escapes the run artifacts directory"
        ) from exc
    if relative.parts != (agent_id, task_id):
        raise ValueError(
            f"Invalid swarm agent/task id {agent_id!r}/{task_id!r}: artifact "
            "path must preserve its agent and task below the run artifacts directory"
        )
    return artifact_dir


def clear_agent_artifacts(artifact_dir: Path) -> None:
    """Remove *artifact_dir* and everything in it, before a retry attempt.

    A retry re-invokes :func:`run_worker` against the same ``artifact_dir``.
    Without this, a failed attempt's ``report.md`` (or any other file a tool
    wrote) would still be sitting there when the retried attempt reads the
    directory back via ``_resolve_summary``/``_report_written``/
    ``collect_artifacts``, silently substituting stale content for the new
    attempt's real result.

    Raises on failure rather than swallowing it: proceeding with a retry
    while known-stale artifacts remain would recreate the exact bug this
    exists to prevent. ``run_worker`` recreates the directory itself
    (``mkdir(parents=True, exist_ok=True)``) on its next invocation.
    """
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)


def collect_artifacts(run_dir: Path, artifact_dir: Path) -> list[str]:
    """Collect regular artifacts as deterministic run-relative paths.

    Args:
        run_dir: Root directory for the swarm run.
        artifact_dir: Path to artifacts/{agent_id}/{task_id}/ directory.

    Returns:
        Sorted POSIX-style paths relative to the swarm run directory. Symlinks
        and files that resolve outside the agent artifact directory are omitted.
    """
    if not artifact_dir.exists():
        return []

    run_dir = run_dir.resolve()
    artifact_root = artifact_dir.resolve()
    if not artifact_root.is_relative_to(run_dir):
        return []

    artifacts: list[str] = []
    for path in artifact_dir.rglob("*"):
        try:
            if path.is_symlink():
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(artifact_root) or not resolved.is_file():
                continue
            artifacts.append(resolved.relative_to(run_dir).as_posix())
        except (OSError, RuntimeError, ValueError):
            # A concurrently removed file, symlink loop, or containment
            # failure is not a durable artifact and must not escape the run.
            continue
    return sorted(artifacts)
