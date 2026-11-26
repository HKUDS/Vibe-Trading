"""Swarm multi-agent system — Task persistence and DAG algorithms."""

from __future__ import annotations

import threading
import uuid
from collections import Counter, defaultdict, deque
from pathlib import Path

from src.swarm.models import SwarmTask, TaskStatus


class TaskStore:
    """Store task records under the current run's tasks directory.

    Args:
        run_dir: Root directory of the current run.
    """

    def __init__(self, run_dir: Path) -> None:
        """Initialize TaskStore."""
        self.run_dir = run_dir
        self._tasks_dir = run_dir / "tasks"
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _task_path(self, task_id: str) -> Path:
        """Return the file path for a task."""
        return self._tasks_dir / f"task-{task_id}.json"

    def save_task(self, task: SwarmTask) -> None:
        """Save or overwrite task state.

        Args:
            task: Current task record to persist under its ID.
        """
        path = self._task_path(task.id)
        # Use a unique temp file so concurrent writers cannot consume each other’s writes (#1536).
        tmp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        with self._lock:
            tmp_path.write_text(task.model_dump_json(indent=2), encoding="utf-8")
            tmp_path.replace(path)

    def load_task(self, task_id: str) -> SwarmTask:
        """Load a task by ID.

        Args:
            task_id: ID of the task to load.

        Returns:
            Task state from its persisted JSON record.

        Raises:
            FileNotFoundError: If the task file does not exist.
        """
        path = self._task_path(task_id)
        if not path.exists():
            raise FileNotFoundError(f"Task not found: {path.name}")
        return SwarmTask.model_validate_json(path.read_text(encoding="utf-8"))

    def load_all(self) -> list[SwarmTask]:
        """Load all tasks for the current run.

        Returns:
            Task records in filename order.
        """
        tasks: list[SwarmTask] = []
        for path in sorted(self._tasks_dir.glob("task-*.json")):
            tasks.append(
                SwarmTask.model_validate_json(path.read_text(encoding="utf-8"))
            )
        return tasks

    def update_status(
        self, task_id: str, status: TaskStatus, **kwargs: str | int | list[str] | None
    ) -> SwarmTask:
        """Update task status and additional fields.

        Args:
            task_id: ID of the task to update.
            status: New task status.
            **kwargs: Optional updates to known task fields such as summary, error, completed_at, or
                artifacts. Unknown fields are ignored.

        Returns:
            Validated task record saved to disk.
        """
        task = self.load_task(task_id)
        updated_data = task.model_dump()
        updated_data["status"] = status
        for key, value in kwargs.items():
            if key in updated_data:
                updated_data[key] = value
        updated_task = SwarmTask.model_validate(updated_data)
        self.save_task(updated_task)
        return updated_task


def resolve_dependencies(tasks_dir: Path, completed_task_id: str) -> list[str]:
    """Remove a completed task ID from blocked_by in all downstream tasks.

    Args:
        tasks_dir: Path to the tasks directory.
        completed_task_id: ID of the just-completed task.

    Returns:
        IDs of blocked tasks moved to pending after their last dependency was removed.
    """
    newly_unblocked: list[str] = []

    for path in tasks_dir.glob("task-*.json"):
        task = SwarmTask.model_validate_json(path.read_text(encoding="utf-8"))
        if completed_task_id not in task.blocked_by:
            continue

        new_blocked_by = [tid for tid in task.blocked_by if tid != completed_task_id]
        updated_data = task.model_dump()
        updated_data["blocked_by"] = new_blocked_by

        if not new_blocked_by and task.status == TaskStatus.blocked:
            updated_data["status"] = TaskStatus.pending
            newly_unblocked.append(task.id)

        updated_task = SwarmTask.model_validate(updated_data)
        tmp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(updated_task.model_dump_json(indent=2), encoding="utf-8")
        tmp_path.replace(path)

    return newly_unblocked


def validate_dag(tasks: list[SwarmTask]) -> None:
    """Validate task IDs, dependency references, cycles and upstream data bindings.

    Args:
        tasks: Tasks and their declared dependencies.

    Raises:
        ValueError: If a task ID repeats, a dependency is unknown, a cycle is detected (the
            message includes the cycle path), or an input_from source is not an ancestor through
            depends_on.
    """
    graph: dict[str, list[str]] = {t.id: list(t.depends_on) for t in tasks}
    all_ids = {t.id for t in tasks}
    if len(all_ids) != len(tasks):
        duplicates = sorted(tid for tid, count in Counter(t.id for t in tasks).items() if count > 1)
        raise ValueError(f"Duplicate task ID(s) in DAG: {', '.join(duplicates)}")

    for task in tasks:
        for dep in task.depends_on:
            if dep not in all_ids:
                raise ValueError(
                    f"Task '{task.id}' depends on unknown task '{dep}'"
                )

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {tid: WHITE for tid in all_ids}
    path: list[str] = []

    def dfs(node: str) -> None:
        """DFS traversal to detect back edges."""
        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, []):
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                raise ValueError(
                    f"Cycle detected in task DAG: {' -> '.join(cycle)}"
                )
            if color[neighbor] == WHITE:
                dfs(neighbor)

        path.pop()
        color[node] = BLACK

    for tid in all_ids:
        if color[tid] == WHITE:
            dfs(tid)

    # Scheduling and resume invalidation follow depends_on, so a data source must be an ancestor
    # there; otherwise its result is read while it runs or kept after it re-executes.
    for task in tasks:
        ancestors: set[str] = set()
        pending = list(task.depends_on)
        while pending:
            source = pending.pop()
            if source not in ancestors:
                ancestors.add(source)
                pending.extend(graph[source])
        for key, source in task.input_from.items():
            if source not in ancestors:
                raise ValueError(
                    f"Task '{task.id}' input_from '{key}' references '{source}', "
                    "which is not upstream in the DAG; declare its depends_on path"
                )


def topological_layers(tasks: list[SwarmTask]) -> list[list[str]]:
    """Group the task DAG into layers that can run in parallel.

    Args:
        tasks: Tasks with valid dependency references.

    Returns:
        List of layers in execution order, each containing task IDs that can run in parallel.

    Raises:
        ValueError: If topological sorting cannot process every task.
    """
    in_degree: dict[str, int] = {t.id: 0 for t in tasks}
    dependents: dict[str, list[str]] = defaultdict(list)

    for task in tasks:
        in_degree[task.id] = len(task.depends_on)
        for dep in task.depends_on:
            dependents[dep].append(task.id)

    queue: deque[str] = deque(
        tid for tid, deg in in_degree.items() if deg == 0
    )

    layers: list[list[str]] = []
    processed = 0

    while queue:
        layer: list[str] = list(queue)
        queue.clear()
        layers.append(layer)
        processed += len(layer)

        for tid in layer:
            for downstream in dependents[tid]:
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)

    if processed != len(tasks):
        raise ValueError(
            f"DAG contains a cycle: processed {processed}/{len(tasks)} tasks"
        )

    return layers
