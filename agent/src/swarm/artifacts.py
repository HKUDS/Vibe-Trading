"""Task workspace paths and artifact lifecycle for swarm runs."""

import shutil
from pathlib import Path


def agent_artifact_dir(run_dir: Path, agent_id: str, task_id: str) -> Path:
    """Return the canonical artifacts directory for one task within a run."""
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


def node_thread(run_dir: Path, agent_id: str, task_id: str) -> Path:
    """Locate the canonical thread outside the model's task workspace."""
    workspace = agent_artifact_dir(run_dir, agent_id, task_id)
    return run_dir / "nodes" / workspace.parent.name / workspace.name / "thread.jsonl"


def clear_agent_artifacts(artifact_dir: Path) -> None:
    """Remove *artifact_dir* and everything in it, before a retry attempt."""
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)


def collect_artifacts(run_dir: Path, artifact_dir: Path) -> list[str]:
    """Collect regular artifacts as deterministic run-relative paths."""
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


def collect_node_artifacts(run_dir: Path, workspace: Path) -> list[str]:
    """Publish the task's deliverables while keeping runtime records private."""
    private = {"req.json", "state.json", "llm_usage.json", "run_manifest.json",
               "artifacts/identity_evidence.json"}
    relative = workspace.relative_to(run_dir)
    reserved = {str(relative / name) for name in private}
    return [path for path in collect_artifacts(run_dir, workspace) if path not in reserved]
