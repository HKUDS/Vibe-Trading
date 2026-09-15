"""Swarm DAG orchestration runtime.

Core orchestrator: schedules workers by topological layer, parallel within each
layer and serial between layers. Execution runs in a background daemon thread
with cancellation and event callback support.
"""

from __future__ import annotations

import logging
import random
import shutil
import threading
import time
from concurrent.futures import (
    Future,
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.config.accessor import get_env_config
from src.config.schema import AgentConfig
from src.providers.llm import _ensure_dotenv, uses_responses_api
from src.swarm import grounding
from src.swarm.models import (
    RunStatus,
    SwarmAgentSpec,
    SwarmEvent,
    SwarmRun,
    SwarmTask,
    TaskStatus,
    WorkerResult,
    WorkerStatus,
    public_model_metadata,
    public_provider_metadata,
    public_reasoning_effort,
)
from src.swarm.presets import build_run_from_preset
from src.swarm.store import SwarmStore
from src.swarm.task_store import (
    TaskStore,
    resolve_dependencies,
    topological_layers,
    validate_dag,
)
from src.tools.mcp import invalidate_mcp_specs_cache
from src.tools.redaction import redact_internal_paths
from src.swarm.worker import agent_artifact_dir, clear_agent_artifacts, run_worker

logger = logging.getLogger(__name__)


def _worker_retry_delay_ceiling_s(retry_number: int) -> float:
    """Return the capped exponential ceiling for a one-based retry number."""
    if retry_number < 1:
        raise ValueError("retry_number must be at least 1")

    config = get_env_config().swarm
    base_delay = config.swarm_worker_retry_base_delay_s
    max_delay = config.swarm_worker_retry_max_delay_s
    exponent = min(retry_number - 1, 62)
    return min(base_delay * (2**exponent), max_delay)


def _worker_retry_delay_s(retry_number: int) -> float:
    """Return an equal-jitter exponential delay for a worker-level retry.

    Equal jitter keeps half of the exponential delay while spreading
    concurrent swarm workers across the remaining half of the window.
    """
    delay_ceiling = _worker_retry_delay_ceiling_s(retry_number)
    return random.uniform(delay_ceiling / 2, delay_ceiling)


def _worker_retry_budget_s(max_retries: int) -> float:
    """Return the maximum cumulative backoff included in a task deadline."""
    return sum(
        _worker_retry_delay_ceiling_s(retry_number)
        for retry_number in range(1, max_retries + 1)
    )


def _wait_for_worker_retry(
    delay_s: float,
    cancel_event: threading.Event | None,
) -> bool:
    """Wait before a retry and return whether cancellation interrupted it."""
    if cancel_event is not None:
        return cancel_event.wait(delay_s)
    time.sleep(delay_s)
    return False


def _rehome_artifact_paths(
    artifact_paths: list[str],
    source_run_dir: Path,
    target_run_dir: Path,
) -> list[str]:
    """Copy a kept task's run-relative artifacts into *target_run_dir*.

    Workers persist artifacts as POSIX paths relative to the run directory
    (``artifacts/<agent>/<file>``; see ``worker._collect_artifacts``). A
    resumed run must not reference the old run's directory — the old run
    stays as a record and may be deleted later.

    The stored artifact list is on-disk state that may be stale or tampered,
    so every entry is validated before use:
    - Only paths under the ``artifacts/`` subtree are accepted, resolved to a
      real path on BOTH sides: ``artifacts/../run.json`` normalizes into the
      run root (control-file clobber) and a symlinked component such as
      ``artifacts/analyst -> tasks`` redirects the copy onto task files. The
      resolved source and resolved destination must each land inside BOTH the
      run directory and its ``artifacts/`` subtree — the run-root bound stops a
      symlinked ``artifacts/`` dir (e.g. ``artifacts -> /outside``) from
      redefining the safe boundary, the subtree bound stops redirection onto
      control/task files. Anything else (``run.json``, ``events.jsonl``,
      ``tasks/*.json``, absolute paths, ``..``, symlink redirection) is a
      control-file or path-traversal vector and is dropped — re-homing a kept
      artifact must never clobber the new run's own state files or write
      outside the run.
    - Missing files are dropped rather than re-homed.

    Returns:
        New run-relative artifact paths, preserving the input order.
    """
    rehomed: list[str] = []
    source_root = source_run_dir.resolve()
    target_root = target_run_dir.resolve()
    source_artifacts = (source_root / "artifacts").resolve()
    target_artifacts = (target_root / "artifacts").resolve()
    for raw in artifact_paths or []:
        rel = Path(raw)
        parts = rel.parts
        if rel.is_absolute() or not parts or len(parts) < 2 or parts[0] != "artifacts":
            logger.warning("Resume: dropping non-artifact path %r", raw)
            continue
        if ".." in parts:
            logger.warning(
                "Resume: dropping artifact path escaping artifacts/: %r", raw
            )
            continue
        src = source_run_dir / rel
        try:
            resolved_src = src.resolve()
            if not (
                resolved_src.is_relative_to(source_root)
                and resolved_src.is_relative_to(source_artifacts)
            ):
                logger.warning(
                    "Resume: dropping artifact escaping source run: %r", raw
                )
                continue
        except (OSError, RuntimeError, ValueError):
            continue
        if not src.is_file():
            continue
        dst = target_run_dir / rel
        try:
            # Validate containment BEFORE mkdir: creating parent dirs through a
            # symlinked component (e.g. artifacts -> /outside) would already
            # write outside the run dir.
            resolved_dst = dst.resolve(strict=False)
            if not (
                resolved_dst.is_relative_to(target_root)
                and resolved_dst.is_relative_to(target_artifacts)
            ):
                logger.warning(
                    "Resume: dropping artifact whose destination escapes the run dir: %r",
                    raw,
                )
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        except OSError:
            logger.warning("Resume: failed to re-home artifact %s", rel, exc_info=True)
            continue
        rehomed.append(rel.as_posix())
    return rehomed


def _agent_spec_changed(prev: SwarmAgentSpec, new: SwarmAgentSpec) -> bool:
    """Return whether an agent's defining configuration differs between runs.

    Only the fields that determine what/with-what the agent produces are
    compared: role, system prompt, tool/skill whitelists, model choice,
    retry budget, and timeout. A kept task result is only valid if the agent
    that produced it still means the same thing.
    """
    return (
        prev.role != new.role
        or prev.system_prompt != new.system_prompt
        or prev.tools != new.tools
        or prev.skills != new.skills
        or prev.model_name != new.model_name
        or prev.max_retries != new.max_retries
        or prev.max_iterations != new.max_iterations
        or prev.timeout_seconds != new.timeout_seconds
    )


def _task_definition_changed(
    prev: SwarmTask,
    new: SwarmTask,
    prev_agents: dict[str, SwarmAgentSpec],
    new_agents: dict[str, SwarmAgentSpec],
    prev_run: SwarmRun,
    new_run: SwarmRun,
) -> bool:
    """Return whether a task's semantic definition differs between runs.

    Compares both the fields that define *what the task is* — the agent that
    executes it, the prompt template, and the DAG wiring (``depends_on`` and
    ``input_from``) — and the agent spec that executes it (see
    ``_agent_spec_changed``). Runtime state (status, summary, blocked_by,
    completed_at, …) is deliberately excluded.

    When neither the old nor the new agent pins ``model_name`` (bundled presets
    leave it unset), the task runs on the run-level default captured in
    ``SwarmRun.model`` / ``.provider`` — so a global model/provider swap
    between the original run and the replay also invalidates kept results.
    Per-agent overrides are compared by ``_agent_spec_changed`` already.

    A replayed run must keep a completed task only when the task, its agent,
    and the effective model that produced it still mean the same thing —
    otherwise the kept result is stale with respect to the current run.
    """
    if (
        prev.agent_id != new.agent_id
        or prev.prompt_template != new.prompt_template
        or prev.depends_on != new.depends_on
        or prev.input_from != new.input_from
    ):
        return True
    prev_agent = prev_agents.get(prev.agent_id)
    new_agent = new_agents.get(new.agent_id)
    if prev_agent is None or new_agent is None:
        # Agent vanished from or appeared in the preset — treat as changed.
        return prev_agent is not new_agent
    if _agent_spec_changed(prev_agent, new_agent):
        return True
    if prev_agent.model_name is None and new_agent.model_name is None:
        # Both defer to the run-level default model/provider.
        return prev_run.model != new_run.model or prev_run.provider != new_run.provider
    return False


class SwarmRuntime:
    """Swarm DAG orchestration engine.

    Manages the full lifecycle of a swarm run: creation, scheduling, execution,
    and cancellation. Each run executes in an independent background daemon thread;
    tasks within a layer run in parallel via ThreadPoolExecutor.

    Attributes:
        _store: SwarmStore persistence layer.
        _max_workers: Maximum concurrent workers in ThreadPoolExecutor.
    """

    def __init__(
        self,
        store: SwarmStore,
        max_workers: int = 4,
        agent_config: AgentConfig | None = None,
    ) -> None:
        """Initialize SwarmRuntime.

        Args:
            store: SwarmStore instance for run persistence.
            max_workers: Maximum concurrent worker threads.
            agent_config: Optional resolved agent config carrying remote MCP
                server definitions. Boot-time / operator-trusted; never derived
                from a swarm caller. Forwarded to every worker on every run so
                the worker can assemble a registry that includes remote MCP
                tools. ``None`` (the default) preserves the current
                local-tool-only behavior byte-for-byte.
        """
        self._store = store
        self._max_workers = max_workers
        self._agent_config = agent_config
        self._cancel_events: dict[str, threading.Event] = {}
        self._live_callbacks: dict[str, Callable] = {}
        self._lock = threading.Lock()

    def start_run(
        self,
        preset_name: str,
        user_vars: dict[str, str],
        live_callback: Callable | None = None,
        include_shell_tools: bool = False,
        resume_from: SwarmRun | None = None,
    ) -> SwarmRun:
        """Start a swarm run. Returns immediately, execution happens in background.

        Args:
            preset_name: YAML preset name to execute.
            user_vars: User-provided variables for prompt templates.
            live_callback: Optional callback invoked for each event in real-time.
            include_shell_tools: Whether workers may register shell tools.
            resume_from: Optional prior ``failed`` / ``cancelled`` run to resume.
                Its completed tasks (and their artifacts) are carried into the
                new run as-is; every other task re-executes. ``None`` (default)
                starts a fully fresh run.

        Returns:
            The created SwarmRun instance (status=pending initially).

        Raises:
            FileNotFoundError: If preset does not exist.
            ValueError: If DAG validation fails.
        """
        _ensure_dotenv()
        # Reap any previously running runs whose host process died without
        # finalizing them. Threshold is computed per-run from agent timeouts +
        # heartbeat interval (see SwarmStore.compute_stale_threshold), so a
        # legitimately slow long-running task is not killed.
        try:
            reaped = self._store.reap_stale_running_runs()
            if reaped:
                logger.info("Reaped %d stale swarm run(s): %s", len(reaped), reaped)
        except Exception:
            logger.warning("Stale-run reaper failed", exc_info=True)

        run = build_run_from_preset(preset_name, user_vars)
        validate_dag(run.tasks)

        # Capture which provider/model the run was launched against so the
        # serialized run.json carries enough context for cost audits and
        # post-hoc debugging. Read directly from the same env vars the
        # provider layer uses (src/providers/llm.py:136,195) — that way an
        # override applied via os.environ still shows up. Per-agent overrides
        # remain visible on SwarmAgentSpec.model_name.
        _cfg = get_env_config()
        run.provider = public_provider_metadata(_cfg.llm.langchain_provider.lower())
        run.model = public_model_metadata(_cfg.llm.langchain_model_name)
        run.reasoning_effort = public_reasoning_effort(_cfg.llm.langchain_reasoning_effort)
        run.use_responses_api = uses_responses_api(
            _cfg.llm.langchain_provider,
            _cfg.llm.langchain_use_responses_api,
            _cfg.llm.vibe_trading_deepseek_adapter,
        )

        self._store.create_run(run)

        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[run.id] = cancel_event
            if live_callback is not None:
                self._live_callbacks[run.id] = live_callback

        thread = threading.Thread(
            target=self._execute_run,
            args=(run, cancel_event, include_shell_tools, resume_from),
            name=f"swarm-{run.id}",
            daemon=True,
        )
        thread.start()

        return run

    def cancel_run(self, run_id: str) -> bool:
        """Signal cancellation for a running swarm.

        Args:
            run_id: ID of the run to cancel.

        Returns:
            True if cancellation was signalled, False if run not found.
        """
        with self._lock:
            cancel_event = self._cancel_events.get(run_id)
        if cancel_event is None:
            return False
        cancel_event.set()
        return True

    def _emit_event(self, run_id: str, event: SwarmEvent) -> None:
        """Persist an event and forward to live callback if registered.

        Args:
            run_id: Run identifier.
            event: Event to persist.
        """
        try:
            self._store.append_event(run_id, event)
        except Exception:
            logger.warning("Failed to persist event for run %s", run_id, exc_info=True)
        with self._lock:
            cb = self._live_callbacks.get(run_id)
        if cb is not None:
            try:
                cb(event)
            except Exception:
                logger.warning("Live callback failed for run %s", run_id, exc_info=True)

    def _make_event(
        self,
        event_type: str,
        agent_id: str | None = None,
        task_id: str | None = None,
        data: dict | None = None,
    ) -> SwarmEvent:
        """Create a SwarmEvent with current timestamp.

        Args:
            event_type: Event type string.
            agent_id: Optional agent identifier.
            task_id: Optional task identifier.
            data: Optional additional data.

        Returns:
            SwarmEvent instance.
        """
        return SwarmEvent(
            type=event_type,
            agent_id=agent_id,
            task_id=task_id,
            data=data or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _execute_run(
        self,
        run: SwarmRun,
        cancel_event: threading.Event,
        include_shell_tools: bool = False,
        resume_from: SwarmRun | None = None,
    ) -> None:
        """Core orchestration loop (runs in background thread).

        Steps:
            1. Update run status to running
            2. Initialize TaskStore, save all tasks
            3. Compute topological layers
            4. For each layer:
               a. Check cancellation
               b. Submit all tasks to ThreadPoolExecutor
               c. Collect results, resolve dependencies, update store
            5. Update run status to completed/failed

        Args:
            run: SwarmRun to execute.
            cancel_event: Threading event for cancellation signalling.
            include_shell_tools: Whether workers may register shell tools.
            resume_from: Optional prior run whose completed tasks are kept
                (see :meth:`_apply_resume_overlay`). ``None`` executes fresh.
        """
        run_id = run.id
        run_dir = self._store.run_dir(run_id)

        # Ensure fresh MCP tool discovery for this run — prior run's cached
        # specs may be stale if operator edited mcp_servers config between runs.
        invalidate_mcp_specs_cache()

        # Mark as running
        run.status = RunStatus.running
        self._store.update_run(run)
        self._emit_event(run_id, self._make_event("run_started"))

        self._prefetch_grounding_data(run)

        # Initialize task store
        task_store = TaskStore(run_dir)
        for task in run.tasks:
            task_store.save_task(task)

        # Build agent lookup
        agent_map: dict[str, SwarmAgentSpec] = {a.id: a for a in run.agents}

        # Render the grounding block once and pass it to every worker on
        # this run. The block is empty when no symbols were detected, in
        # which case workers see no extra section.
        grounding_block = grounding.format_grounding_block(run.grounding_data or {})

        # Compute execution layers
        layers = topological_layers(run.tasks)
        task_summaries: dict[str, str] = {}
        all_succeeded = True

        try:
            # The overlay runs inside the try so a failure here finalizes the
            # run (run_error event + failed status) instead of leaving a
            # zombie "running" run on disk. run.tasks is re-synced from the
            # store afterwards: _cancel_remaining_tasks and the final snapshot
            # read in-memory task state, which must see kept tasks as
            # completed — otherwise a cancellation in the pre-layer window
            # would relabel them cancelled.
            if resume_from is not None:
                self._apply_resume_overlay(run, run_dir, task_store, resume_from, task_summaries)
                run.tasks = task_store.load_all()

            for layer_idx, layer_task_ids in enumerate(layers):
                # Check cancellation between layers
                if cancel_event.is_set():
                    logger.info("Run %s cancelled at layer %d", run_id, layer_idx)
                    self._cancel_remaining_tasks(task_store, layer_task_ids, run.tasks)
                    all_succeeded = False
                    break

                self._emit_event(
                    run_id,
                    self._make_event(
                        "layer_started",
                        data={"layer": layer_idx, "tasks": layer_task_ids},
                    ),
                )

                # Execute all tasks in this layer in parallel
                layer_results = self._execute_layer(
                    run=run,
                    task_store=task_store,
                    agent_map=agent_map,
                    layer_task_ids=layer_task_ids,
                    task_summaries=task_summaries,
                    run_dir=run_dir,
                    cancel_event=cancel_event,
                    include_shell_tools=include_shell_tools,
                    grounding_block=grounding_block,
                )

                # Process results
                for tid, result in layer_results.items():
                    # Accumulate token counts to run totals
                    run.total_input_tokens += result.input_tokens
                    run.total_output_tokens += result.output_tokens

                    if result.status == "completed":
                        task_summaries[tid] = result.summary
                        now_iso = datetime.now(timezone.utc).isoformat()
                        task_store.update_status(
                            tid,
                            TaskStatus.completed,
                            summary=result.summary,
                            completed_at=now_iso,
                            artifacts=result.artifact_paths,
                            worker_iterations=result.iterations,
                        )
                        resolve_dependencies(run_dir / "tasks", tid)
                        self._emit_event(
                            run_id,
                            self._make_event(
                                "task_completed",
                                task_id=tid,
                                data={
                                    "status": result.status,
                                    "iterations": result.iterations,
                                    "input_tokens": result.input_tokens,
                                    "output_tokens": result.output_tokens,
                                },
                            ),
                        )
                    elif result.status == "cancelled":
                        # The worker stopped because cancel_run() was
                        # signalled mid-flight; that is a user stop, not a
                        # worker error. Persist it as cancelled — the same
                        # terminal state _cancel_remaining_tasks gives tasks
                        # that never started — so the dashboard, the run
                        # summary and a later resume all see one consistent
                        # story instead of a spurious "worker did not
                        # complete" failure.
                        all_succeeded = False
                        task_store.update_status(
                            tid,
                            TaskStatus.cancelled,
                            summary=result.summary,
                            completed_at=datetime.now(timezone.utc).isoformat(),
                            artifacts=result.artifact_paths,
                            worker_iterations=result.iterations,
                        )
                        self._emit_event(
                            run_id,
                            self._make_event(
                                "task_cancelled",
                                task_id=tid,
                                data={
                                    "status": result.status,
                                    "iterations": result.iterations,
                                    "input_tokens": result.input_tokens,
                                    "output_tokens": result.output_tokens,
                                },
                            ),
                        )
                    else:
                        all_succeeded = False
                        task_store.update_status(
                            tid,
                            TaskStatus.failed,
                            error=redact_internal_paths(result.error)
                            or f"worker did not complete (status={result.status})",
                            completed_at=datetime.now(timezone.utc).isoformat(),
                            worker_iterations=result.iterations,
                        )
                        self._emit_event(
                            run_id,
                            self._make_event(
                                "task_failed",
                                task_id=tid,
                                data={
                                    "error": redact_internal_paths(result.error),
                                    "input_tokens": result.input_tokens,
                                    "output_tokens": result.output_tokens,
                                },
                            ),
                        )

                # Tasks blocked by a failed upstream are never dispatched and
                # therefore not present in layer_results — they were already
                # marked TaskStatus.blocked in _execute_layer and emitted
                # task_blocked. Account for them in run-level status so the
                # run is marked failed, not silently completed. Tasks kept
                # completed by a resume overlay are equally absent from
                # layer_results but are not failures.
                for tid in layer_task_ids:
                    if tid in layer_results:
                        continue
                    if task_store.load_task(tid).status == TaskStatus.completed:
                        continue
                    all_succeeded = False

                # Snapshot run.json at the layer boundary so list_runs and any
                # client that reads run.json directly sees fresh task statuses
                # without per-task I/O spam. One write per layer is cheap.
                self._sync_run_tasks_snapshot(run, task_store)

        except Exception as exc:
            logger.error("Run %s failed with exception", run_id, exc_info=True)
            all_succeeded = False
            self._emit_event(
                run_id,
                self._make_event("run_error", data={"error": redact_internal_paths(str(exc))}),
            )

        # Finalize run
        final_status = (
            RunStatus.cancelled if cancel_event.is_set() else RunStatus.completed if all_succeeded else RunStatus.failed
        )
        run.status = final_status
        run.completed_at = datetime.now(timezone.utc).isoformat()

        # Sync tasks back to run model
        run.tasks = task_store.load_all()

        # Set final report from aggregation task (last task) if available
        if task_summaries:
            last_layer = layers[-1] if layers else []
            for tid in last_layer:
                if tid in task_summaries:
                    run.final_report = task_summaries[tid]
                    break

        self._store.update_run(run)
        self._emit_event(run_id, self._make_event("run_completed", data={"status": final_status.value}))

        # Cleanup cancel event and live callback
        with self._lock:
            self._cancel_events.pop(run_id, None)
            self._live_callbacks.pop(run_id, None)

    def _sync_run_tasks_snapshot(self, run: SwarmRun, task_store: TaskStore) -> None:
        """Mirror live ``tasks/*.json`` back into ``run.json`` at a safe point.

        Called at layer boundaries only — not per-task — to keep run.json a
        useful coarse snapshot for ``list_runs`` and CLI/Web callers that
        don't hydrate per request. Failures are logged but never fatal: the
        per-task files are still the live source of truth.
        """
        try:
            run.tasks = task_store.load_all()
            self._store.update_run(run)
        except Exception:
            logger.warning("Layer-boundary run.json sync failed", exc_info=True)

    def _apply_resume_overlay(
        self,
        run: SwarmRun,
        run_dir: Path,
        task_store: TaskStore,
        resume_from: SwarmRun,
        task_summaries: dict[str, str],
    ) -> None:
        """Carry completed tasks from *resume_from* into *run* before execution.

        DAG semantics guarantee a completed task never depends on a failed one,
        so "keep everything completed, reset everything else" is the core of
        the failed/cancelled-subgraph re-execution #1157 asks for. Two
        exceptions, both enforced here:
        - A completed task is NOT kept when its definition changed since the
          original run — the task's own defining fields (agent, prompt
          template, DAG wiring) or the agent spec that executes it (role,
          system prompt, tools, skills, model, retries, timeout) — because a
          kept result must still mean the same thing.
        - A completed task is NOT kept when any of its transitive upstreams
          re-executes, because its kept summary was produced from the upstream's
          old output and would be stale relative to the fresh upstream output
          flowing into it (and unchanged dependents cascade the same way).
        Kept tasks are re-marked ``completed`` with their original
        summary/artifacts (artifacts re-homed into this run's directory so the
        new run is self-contained), kept ids are resolved out of downstream
        ``blocked_by`` edges, and their summaries are seeded into
        ``task_summaries`` so ``input_from`` context flows to re-executed
        dependents. Tasks with no counterpart in the original run (added to the
        preset since) run fresh.

        Degradation: a wholly missing or unreadable prior task store falls back
        to a fully fresh run (logged, never fatal). Individual tasks absent
        from an otherwise-readable store (e.g. preset evolution that removed
        them) simply have no kept counterpart and re-execute — that is not a
        store failure, so it does not trigger the fresh-run fallback.
        """
        prev_run_dir = self._store.run_dir(resume_from.id)
        if not prev_run_dir.exists():
            logger.warning(
                "Resume: run %s directory missing — replaying fresh",
                resume_from.id,
            )
            return
        try:
            prev_store = TaskStore(prev_run_dir)
            prev_by_id = {task.id: task for task in prev_store.load_all()}
        except Exception:
            logger.warning(
                "Resume: could not read task store of run %s — replaying fresh",
                resume_from.id,
                exc_info=True,
            )
            return

        prev_agents = {a.id: a for a in resume_from.agents}
        new_agents = {a.id: a for a in run.agents}

        # Phase 1: candidates = completed tasks whose own definition is unchanged.
        to_keep: set[str] = set()
        for task in run.tasks:
            prev = prev_by_id.get(task.id)
            if prev is None or prev.status != TaskStatus.completed:
                continue
            if _task_definition_changed(prev, task, prev_agents, new_agents, resume_from, run):
                logger.info(
                    "Resume: task %s definition changed since run %s — re-executing",
                    task.id,
                    resume_from.id,
                )
                continue
            to_keep.add(task.id)

        # Phase 2: a kept result is only valid if every transitive upstream is
        # also kept — a dependent whose upstream re-executes must itself
        # re-execute, or its kept summary would be stale with respect to the
        # fresh upstream output flowing into it. Iterate to fixpoint (DAGs are
        # small; worst case is quadratic).
        invalidated = True
        while invalidated:
            invalidated = False
            for task in run.tasks:
                if task.id not in to_keep:
                    continue
                for dep in task.depends_on:
                    if dep not in to_keep:
                        to_keep.discard(task.id)
                        logger.info(
                            "Resume: task %s invalidated — upstream %s re-executes",
                            task.id,
                            dep,
                        )
                        invalidated = True
                        break

        # Phase 3: apply the keep for the survivors.
        kept = 0
        for task in run.tasks:
            if task.id not in to_keep:
                continue
            prev = prev_by_id[task.id]
            artifact_paths = _rehome_artifact_paths(prev.artifacts, prev_run_dir, run_dir)
            task_store.update_status(
                task.id,
                TaskStatus.completed,
                summary=prev.summary,
                completed_at=prev.completed_at,
                artifacts=artifact_paths,
                worker_iterations=prev.worker_iterations,
                blocked_by=[],
            )
            resolve_dependencies(run_dir / "tasks", task.id)
            # Mirror _execute_run's live seeding (unconditional key): a kept
            # task must contribute its input_from key to re-executed dependents
            # even when the stored summary is empty or None.
            task_summaries[task.id] = prev.summary or ""
            kept += 1
            self._emit_event(
                run.id,
                self._make_event(
                    "task_resumed",
                    agent_id=task.agent_id,
                    task_id=task.id,
                    data={
                        "source_run_id": resume_from.id,
                        "completed_at": prev.completed_at,
                    },
                ),
            )
        if kept:
            logger.info(
                "Run %s resumed from %s: kept %d completed task(s)",
                run.id,
                resume_from.id,
                kept,
            )

    def _prefetch_grounding_data(self, run: SwarmRun) -> None:
        """Fetch run-level grounding data without blocking ``start_run``."""
        symbols = grounding.extract_symbols_from_user_vars(run.user_vars)
        if not symbols:
            return

        symbol_limit = grounding.max_grounding_symbols()
        if len(symbols) > symbol_limit:
            logger.warning(
                "grounding: limiting run %s symbols from %d to %d",
                run.id,
                len(symbols),
                symbol_limit,
            )
            symbols = symbols[:symbol_limit]

        # Multi-symbol grounding fetch can take 30s+ on slow loaders. Wrap it
        # in a heartbeat so events.jsonl gets fresh entries during the fetch
        # — without this, the stale-run reaper would false-positive-mark a
        # healthy fresh run that's just waiting on OHLCV API calls.
        from src.agent.progress import HeartbeatTimer

        def _on_grounding_heartbeat(payload: dict) -> None:
            self._emit_event(
                run.id,
                self._make_event(
                    "run_heartbeat",
                    data={**payload, "phase": "grounding"},
                ),
            )

        interval = get_env_config().swarm.swarm_heartbeat_interval_s

        try:
            with HeartbeatTimer(
                tool_name=f"grounding:{len(symbols)}symbols",
                interval=interval,
                emit=_on_grounding_heartbeat,
            ):
                fetched = grounding.fetch_grounding_data(symbols)
        except Exception:
            logger.warning(
                "grounding: pre-fetch failed for run %s symbols=%s",
                run.id,
                symbols,
                exc_info=True,
            )
            return

        if fetched:
            run.grounding_data = fetched
            self._store.update_run(run)

    def _execute_layer(
        self,
        run: SwarmRun,
        task_store: TaskStore,
        agent_map: dict[str, SwarmAgentSpec],
        layer_task_ids: list[str],
        task_summaries: dict[str, str],
        run_dir: Path,
        cancel_event: threading.Event,
        include_shell_tools: bool = False,
        grounding_block: str = "",
    ) -> dict[str, WorkerResult]:
        """Execute all tasks in a single layer in parallel, with retry on failure.

        Each task is retried up to agent_spec.max_retries times if the worker
        returns status="failed". A "task_retry" event is emitted before each retry.

        Args:
            run: The SwarmRun being executed.
            task_store: TaskStore for task persistence.
            agent_map: Agent specs keyed by agent_id.
            layer_task_ids: Task IDs in this layer.
            task_summaries: Accumulated task summaries from previous layers.
            run_dir: Run directory path.
            cancel_event: Cancellation event.
            include_shell_tools: Whether workers may register shell tools.
            grounding_block: Pre-rendered "Ground Truth" markdown for workers.

        Returns:
            Mapping of task_id -> WorkerResult for all tasks in this layer.
        """
        results: dict[str, WorkerResult] = {}

        def _event_callback(event: SwarmEvent) -> None:
            self._emit_event(run.id, event)

        # Manual executor lifecycle (not `with`) so KeyboardInterrupt and
        # the layer deadline don't block main on `shutdown(wait=True)` —
        # `wait=False + cancel_futures=True` lets pending work drop and
        # the CLI return immediately. Running workers finish naturally.
        executor = ThreadPoolExecutor(max_workers=self._max_workers)
        futures: dict[Future[WorkerResult], str] = {}
        layer_budget = 0  # seconds — max per-task (retries × timeout) across layer
        try:
            for tid in layer_task_ids:
                task = task_store.load_task(tid)

                # Replay support: a task kept completed by the resume overlay
                # must not be re-dispatched — its summary and artifacts were
                # carried into this run and its summary seeded into
                # task_summaries before layers started.
                if task.status == TaskStatus.completed:
                    continue

                # Dependency-aware gating: without this check, a failed upstream
                # silently produces an empty task_summaries entry (the worker
                # upstream loop below only copies summaries that exist) and the
                # downstream worker runs with no upstream context. For an
                # investment-committee preset where portfolio_manager
                # depends_on=["task-risk"], a failed risk_officer would let PM
                # produce a "decision" with no risk input — which is
                # safety-critical. Mark blocked and skip dispatch; same-layer
                # peers with no shared upstream are unaffected.
                blocked_upstreams: list[tuple[str, str]] = []
                for dep_id in task.depends_on:
                    try:
                        dep_task = task_store.load_task(dep_id)
                    except FileNotFoundError:
                        blocked_upstreams.append((dep_id, "missing"))
                        continue
                    if dep_task.status != TaskStatus.completed:
                        blocked_upstreams.append((dep_id, dep_task.status.value))

                if blocked_upstreams:
                    reason = ", ".join(f"{d}={s}" for d, s in blocked_upstreams)
                    blocked_by_ids = [d for d, _ in blocked_upstreams]
                    task_store.update_status(
                        tid,
                        TaskStatus.blocked,
                        error=f"Blocked: upstream not completed ({reason})",
                        blocked_by=blocked_by_ids,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                    )
                    self._emit_event(
                        run.id,
                        self._make_event(
                            "task_blocked",
                            agent_id=task.agent_id,
                            task_id=tid,
                            data={"blocked_by": blocked_by_ids, "reason": reason},
                        ),
                    )
                    continue

                agent_spec = agent_map.get(task.agent_id)
                if agent_spec is None:
                    results[tid] = WorkerResult(
                        status="failed",
                        summary="",
                        error=f"Agent '{task.agent_id}' not found in preset",
                    )
                    continue

                # Mark task as in_progress
                task_store.update_status(
                    tid,
                    TaskStatus.in_progress,
                    started_at=datetime.now(timezone.utc).isoformat(),
                )
                self._emit_event(
                    run.id,
                    self._make_event("task_started", agent_id=agent_spec.id, task_id=tid),
                )

                # Build upstream summaries from input_from mapping
                upstream: dict[str, str] = {}
                for context_key, source_task_id in task.input_from.items():
                    if source_task_id in task_summaries:
                        upstream[context_key] = task_summaries[source_task_id]

                future = executor.submit(
                    self._run_worker_with_retries,
                    agent_spec=agent_spec,
                    task=task,
                    upstream_summaries=upstream,
                    user_vars=run.user_vars,
                    run_dir=run_dir,
                    event_callback=_event_callback,
                    run_id=run.id,
                    include_shell_tools=include_shell_tools,
                    grounding_block=grounding_block,
                    cancel_event=cancel_event,
                )
                futures[future] = tid
                per_task_budget = (
                    agent_spec.timeout_seconds * (agent_spec.max_retries + 1)
                    + _worker_retry_budget_s(agent_spec.max_retries)
                )
                layer_budget = max(layer_budget, per_task_budget)

            # Collect results with a hard layer-level deadline — defends against
            # worker threads stuck in C extensions / blocked I/O that bypass the
            # in-loop timeout check (issue #42).
            deadline_buffer = 60
            layer_deadline = layer_budget + deadline_buffer if layer_budget else None

            try:
                for future in as_completed(futures, timeout=layer_deadline):
                    tid = futures[future]
                    try:
                        results[tid] = future.result()
                    except Exception as exc:
                        logger.error("Worker for task %s raised exception", tid, exc_info=True)
                        results[tid] = WorkerResult(
                            status="failed",
                            summary="",
                            error=str(exc),
                        )
            except FuturesTimeoutError:
                for pending, tid in futures.items():
                    if tid in results:
                        continue
                    pending.cancel()
                    logger.error(
                        "Worker for task %s exceeded layer deadline (%ds)",
                        tid,
                        layer_deadline,
                    )
                    results[tid] = WorkerResult(
                        status="timeout",
                        summary="",
                        error=f"Worker exceeded layer deadline of {layer_deadline}s",
                    )
        except KeyboardInterrupt:
            cancel_event.set()
            logger.warning("Swarm layer interrupted — cancelling pending workers")
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return results

    def _run_worker_with_retries(
        self,
        agent_spec: SwarmAgentSpec,
        task: SwarmTask,
        upstream_summaries: dict[str, str],
        user_vars: dict[str, str],
        run_dir: Path,
        event_callback: Callable[[SwarmEvent], None] | None,
        run_id: str,
        include_shell_tools: bool = False,
        grounding_block: str = "",
        cancel_event: threading.Event | None = None,
    ) -> WorkerResult:
        """Run a worker with automatic retry on failure.

        Retries up to agent_spec.max_retries times. Emits a "task_retry" event
        before each retry attempt. Token counts are accumulated across all
        attempts.

        Args:
            agent_spec: Agent role specification.
            task: The task to execute.
            upstream_summaries: Summaries from upstream tasks.
            user_vars: User-provided template variables.
            run_dir: Run directory path.
            event_callback: Optional event callback.
            run_id: Run identifier for event emission.
            include_shell_tools: Whether the worker may register shell tools.
            grounding_block: Pre-rendered "Ground Truth" markdown spliced
                into the worker's system prompt. Empty string when no
                symbols were extracted from user_vars.
            cancel_event: Optional cancellation signal from cancel_run().
                Forwarded to run_worker() so a signalled cancellation reaches
                an already-dispatched worker. A "cancelled" result is never
                retried (see the status check below).

        Returns:
            WorkerResult from the last attempt.
        """
        max_retries = agent_spec.max_retries
        cumulative_input_tokens = 0
        cumulative_output_tokens = 0
        result: WorkerResult | None = None

        # agent_artifact_dir is keyed by agent_id alone, so a preset where
        # one agent handles multiple sequential tasks reuses the same
        # directory across tasks. Clear it before this task's first attempt
        # too, not just before a retry: otherwise a prior task's report.md
        # (or any other tool-written file) is still there when this task's
        # own _resolve_summary/_report_written/_collect_artifacts read the
        # directory back, silently attributing it to this task instead.
        clear_agent_artifacts(agent_artifact_dir(run_dir, agent_spec.id))

        for attempt in range(max_retries + 1):
            if attempt > 0:
                retry_delay_s = _worker_retry_delay_s(attempt)
                self._emit_event(
                    run_id,
                    self._make_event(
                        "task_retry",
                        agent_id=agent_spec.id,
                        task_id=task.id,
                        data={
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "previous_error": result.error if result else None,
                            "retry_delay_s": retry_delay_s,
                        },
                    ),
                )
                logger.info(
                    "Retrying task %s in %.2fs (attempt %d/%d)",
                    task.id,
                    retry_delay_s,
                    attempt + 1,
                    max_retries + 1,
                )
                if _wait_for_worker_retry(retry_delay_s, cancel_event):
                    return result.model_copy(
                        update={
                            "status": WorkerStatus.cancelled,
                            "summary": f"Cancelled before retrying task {task.id}",
                            "error": None,
                            "input_tokens": cumulative_input_tokens,
                            "output_tokens": cumulative_output_tokens,
                        }
                    )
                # A retry re-invokes run_worker against the same artifact
                # directory. Without clearing it first, a failed attempt's
                # report.md (or any other tool-written file) would still be
                # there when the retried attempt reads the directory back,
                # silently substituting stale content for the new attempt's
                # real result.
                clear_agent_artifacts(agent_artifact_dir(run_dir, agent_spec.id))

            result = run_worker(
                agent_spec=agent_spec,
                task=task,
                upstream_summaries=upstream_summaries,
                user_vars=user_vars,
                run_dir=run_dir,
                event_callback=event_callback,
                include_shell_tools=include_shell_tools,
                grounding_block=grounding_block,
                agent_config=self._agent_config,
                cancel_event=cancel_event,
            )

            cumulative_input_tokens += result.input_tokens
            cumulative_output_tokens += result.output_tokens

            if result.status != "failed":
                # Success (or timeout/token_limit/completed) — no more retries
                result = result.model_copy(
                    update={
                        "input_tokens": cumulative_input_tokens,
                        "output_tokens": cumulative_output_tokens,
                    }
                )
                return result

        # All retries exhausted, return the last failed result with cumulative tokens
        if result is not None:
            result = result.model_copy(
                update={
                    "input_tokens": cumulative_input_tokens,
                    "output_tokens": cumulative_output_tokens,
                }
            )
        return result  # type: ignore[return-value]

    def _cancel_remaining_tasks(
        self,
        task_store: TaskStore,
        current_layer_ids: list[str],
        all_tasks: list[SwarmTask],
    ) -> None:
        """Mark all non-completed tasks as cancelled.

        Args:
            task_store: TaskStore for persistence.
            current_layer_ids: Task IDs in the current (interrupted) layer.
            all_tasks: All tasks in the run.
        """
        for task in all_tasks:
            if task.status not in (TaskStatus.completed, TaskStatus.failed):
                try:
                    task_store.update_status(task.id, TaskStatus.cancelled)
                except Exception:
                    logger.warning("Failed to cancel task %s", task.id, exc_info=True)
