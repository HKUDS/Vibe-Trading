"""Swarm DAG orchestration runtime."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy

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
from functools import partial
from pathlib import Path
from typing import Callable

from src.config.accessor import get_env_config
from src.config.schema import AgentConfig
from src.providers.settings import _ensure_dotenv
from src.providers.llm import uses_responses_api
from src.session.thread import ThreadLog
from src.session.thread_schema import ThreadItemError
from src.swarm import grounding
from src.swarm.artifacts import agent_artifact_dir, clear_agent_artifacts, collect_node_artifacts, node_thread
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
from src.swarm.node import (
    UNKNOWN_TOOL_OUTCOME, UsageMeasure, _CancellationSignal, run_node, unknown_outcome,
)

logger = logging.getLogger(__name__)


# Index in-flight runs by ID so another runtime can cancel them after the launching tool returns.
_ACTIVE_RUNS: dict[str, tuple[str, Callable[[], bool]]] = {}
_ACTIVE_RUNS_LOCK = threading.Lock()


def register_active_run(run_id: str, session_id: str, cancel: Callable[[], bool]) -> None:
    """Index a freshly started run under the session that owns it."""
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS[run_id] = (session_id, cancel)


def unregister_active_run(run_id: str) -> None:
    """Drop a run from the index once it is terminal or no longer ours."""
    with _ACTIVE_RUNS_LOCK:
        _ACTIVE_RUNS.pop(run_id, None)


def cancel_indexed_run(run_id: str) -> bool:
    """Signal one indexed run regardless of which runtime started it."""
    with _ACTIVE_RUNS_LOCK:
        entry = _ACTIVE_RUNS.pop(run_id, None)
    if entry is None:
        return False
    try:
        return bool(entry[1]())
    except Exception:
        logger.warning("Swarm cancel callback failed for run %s", run_id, exc_info=True)
        return False


def active_run_ids(session_id: str) -> list[str]:
    """Return the run ids currently indexed for ``session_id``."""
    with _ACTIVE_RUNS_LOCK:
        return [rid for rid, (sid, _) in _ACTIVE_RUNS.items() if sid == session_id]


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
    """Return an equal-jitter exponential delay for a worker-level retry."""
    delay_ceiling = _worker_retry_delay_ceiling_s(retry_number)
    return random.uniform(delay_ceiling / 2, delay_ceiling)


def _worker_retry_budget_s(max_retries: int) -> float:
    """Return the maximum cumulative backoff included in a task deadline."""
    return sum(
        _worker_retry_delay_ceiling_s(retry_number)
        for retry_number in range(1, max_retries + 1)
    )


_LAYER_STOP_POLL_S = 0.05
_LAYER_DEADLINE_ERROR = "Worker exceeded layer deadline of "
_UNKNOWN_OUTCOME = (
    ". Its outcome is unknown. Check task artifacts and any external side effects before retrying."
)


class _LayerStop:
    def __init__(self, run_cancel: threading.Event) -> None:
        self._run_cancel = run_cancel
        self._expired = threading.Event()

    def expire(self) -> None:
        self._expired.set()

    def accepts_events(self) -> bool:
        return not self._expired.is_set()

    def is_set(self) -> bool:
        return self._run_cancel.is_set() or self._expired.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            interval = _LAYER_STOP_POLL_S
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self.is_set()
                interval = min(interval, remaining)
            if self._run_cancel.wait(interval):
                return True
        return True


def _wait_for_worker_retry(
    delay_s: float,
    cancel_event: _CancellationSignal | None,
) -> bool:
    """Wait before a retry and return whether cancellation interrupted it."""
    if cancel_event is not None:
        return cancel_event.wait(delay_s)
    time.sleep(delay_s)
    return False


def _merge_token_source(current: str | None, incoming: str | None) -> str | None:
    """Merge two usage-provenance labels conservatively."""
    if incoming is None:
        return current
    if current is None or incoming == "estimated":
        return incoming
    return current


class _RunUsage:
    """Combine node calls and serialize usage with run snapshots."""

    def __init__(self, run: SwarmRun, store: SwarmStore, parent: Callable[[dict], None] | None):
        self.run = run
        self.store = store
        self.parent = parent
        self._lock = threading.Lock()
        self._reported: set[str] = set()
        self._finalized = False

    def record(self, task_id: str, measured: UsageMeasure, raw: dict) -> None:
        with self._lock:
            self._reported.add(task_id)
            self._add(measured)
            if self._finalized:
                self.store.update_run(self.run)
        if self.parent is not None:
            self.parent(raw)

    def settle(self, task_id: str, result: WorkerResult) -> None:
        with self._lock:
            if task_id not in self._reported:
                self._add(result)

    def persist(self, *, final: bool = False) -> None:
        with self._lock:
            self.store.update_run(self.run)
            self._finalized = final

    def _add(self, usage: UsageMeasure | WorkerResult) -> None:
        self.run.total_input_tokens += usage.input_tokens
        self.run.total_output_tokens += usage.output_tokens
        self.run.cache_read_tokens += usage.cache_read_tokens
        self.run.cache_creation_tokens += usage.cache_creation_tokens
        self.run.token_source = _merge_token_source(self.run.token_source, usage.token_source)


def _rehome_artifact_paths(
    artifact_paths: list[str],
    source_run_dir: Path,
    target_run_dir: Path,
) -> list[str]:
    """Copy a kept task's run-relative artifacts into *target_run_dir*."""
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
            # Check containment before mkdir so symlinked parents cannot write outside the run.
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
    """Return whether an agent's defining configuration differs between runs."""
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
    """Return whether a task's semantic definition differs between runs."""
    if (
        prev_run.user_vars != new_run.user_vars
        or prev.agent_id != new.agent_id
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
    """Swarm DAG orchestration engine."""

    def __init__(
        self,
        store: SwarmStore,
        max_workers: int = 4,
        agent_config: AgentConfig | None = None,
        *,
        policy: ToolPolicy,
    ) -> None:
        """Initialize SwarmRuntime."""
        self.policy = policy
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
        *,
        session_id: str | None = None,
        record_usage: Callable[[dict], None] | None = None,
    ) -> SwarmRun:
        """Start a swarm run."""
        if resume_from is not None:
            prior_dir = self._store.run_dir(resume_from.id)
            for task in resume_from.tasks:
                # The deadline diagnostic is already persisted on historical runs.
                error = task.error or ""
                if error.startswith(_LAYER_DEADLINE_ERROR) and error.endswith(_UNKNOWN_OUTCOME):
                    raise ValueError(f"Cannot resume task {task.id}: {error}")
                path = node_thread(prior_dir, task.agent_id, task.id)
                try:
                    unresolved = path.is_file() and unknown_outcome(ThreadLog(path).read(strict=True))
                except (OSError, ThreadItemError):
                    unresolved = True
                if error == UNKNOWN_TOOL_OUTCOME or unresolved:
                    raise ValueError(f"Cannot resume task {task.id}: {UNKNOWN_TOOL_OUTCOME}")
            if not (prior_dir / "nodes").is_dir():
                raise ValueError("Cannot resume a swarm run created before the AgentRuntime cutover. Start a new run explicitly.")

        _ensure_dotenv()
        # Allow for task timeouts and heartbeats when deciding whether an active run is stale.
        try:
            reaped = self._store.reap_stale_running_runs()
            if reaped:
                logger.info("Reaped %d stale swarm run(s): %s", len(reaped), reaped)
        except Exception:
            logger.warning("Stale-run reaper failed", exc_info=True)

        run = build_run_from_preset(preset_name, user_vars)
        validate_dag(run.tasks)

        # Pin the provider settings used at launch for cost audits, including environment overrides.
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
        (self._store.run_dir(run.id) / "nodes").mkdir(exist_ok=True)

        cancel_event = threading.Event()
        thread = threading.Thread(
            target=self._run_with_cleanup,
            args=(run, cancel_event, include_shell_tools, resume_from, record_usage),
            name=f"swarm-{run.id}",
            daemon=True,
        )
        with self._lock:
            self._cancel_events[run.id] = cancel_event
            if live_callback is not None:
                self._live_callbacks[run.id] = live_callback
        if session_id is not None:
            # Register before the run can finish, regardless of how long the tool waits.
            register_active_run(run.id, session_id, lambda: self.cancel_run(run.id))
        try:
            thread.start()
        except RuntimeError:
            self._forget_run(run.id)
            raise

        return run

    def _forget_run(self, run_id: str) -> None:
        with self._lock:
            self._cancel_events.pop(run_id, None)
            self._live_callbacks.pop(run_id, None)
        unregister_active_run(run_id)

    def _run_with_cleanup(
        self,
        run: SwarmRun,
        cancel_event: threading.Event,
        include_shell_tools: bool,
        resume_from: SwarmRun | None,
        record_usage: Callable[[dict], None] | None = None,
    ) -> None:
        cancel_request = self._store.run_dir(run.id) / "cancel.request"
        finished = threading.Event()

        def watch_cancel_request() -> None:
            while not finished.is_set():
                if not cancel_request.is_symlink() and cancel_request.is_file():
                    cancel_event.set()
                    return
                finished.wait(0.2)

        watcher = threading.Thread(target=watch_cancel_request, name=f"swarm-cancel-{run.id}", daemon=True)
        watcher.start()
        try:
            self._execute_run(run, cancel_event, include_shell_tools, resume_from, record_usage)
        finally:
            finished.set()
            watcher.join()
            self._forget_run(run.id)

    def cancel_run(self, run_id: str) -> bool:
        """Signal cancellation for a running swarm."""
        with self._lock:
            cancel_event = self._cancel_events.get(run_id)
        if cancel_event is None:
            return False
        cancel_event.set()
        return True

    def _emit_event(
        self, run_id: str, event: SwarmEvent, *, accept: Callable[[], bool] | None = None,
    ) -> None:
        """Persist an event and forward it if the source is still active."""
        if accept is not None and not accept():
            return
        try:
            if accept is None:
                self._store.append_event(run_id, event)
            elif not self._store.append_event_if(run_id, event, accept):
                return
        except Exception:
            logger.warning("Failed to persist event for run %s", run_id, exc_info=True)
        with self._lock:
            cb = self._live_callbacks.get(run_id)
        if cb is not None and (accept is None or accept()):
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
        """Create a SwarmEvent with current timestamp."""
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
        record_usage: Callable[[dict], None] | None = None,
    ) -> None:
        """Schedule the DAG by layer in the run’s background thread."""
        run_id = run.id
        run_dir = self._store.run_dir(run_id)
        usage = _RunUsage(run, self._store, record_usage)

        # Rediscover MCP tools because operator configuration can change between runs.
        invalidate_mcp_specs_cache()

        run.status = RunStatus.running
        self._store.update_run(run)
        self._emit_event(run_id, self._make_event("run_started"))

        if resume_from is not None and run.user_vars == resume_from.user_vars:
            # Continue the same research snapshot, rather than mix fresh prices
            # with retained upstream reports and invalidate saved context.
            run.grounding_data = resume_from.grounding_data
        else:
            self._prefetch_grounding_data(run)

        task_store = TaskStore(run_dir)
        for task in run.tasks:
            task_store.save_task(task)

        agent_map: dict[str, SwarmAgentSpec] = {a.id: a for a in run.agents}

        # Share one grounding snapshot among all workers.
        grounding_block = grounding.format_grounding_block(run.grounding_data or {})

        layers = topological_layers(run.tasks)
        all_succeeded = True

        try:
            # Finalize overlay failures and sync kept tasks before cancellation can relabel them.
            if resume_from is not None:
                self._apply_resume_overlay(run, run_dir, task_store, resume_from)
                run.tasks = task_store.load_all()

            for layer_idx, layer_task_ids in enumerate(layers):
                if cancel_event.is_set():
                    logger.info("Run %s cancelled at layer %d", run_id, layer_idx)
                    self._cancel_remaining_tasks(task_store, run.tasks)
                    all_succeeded = False
                    break

                self._emit_event(
                    run_id,
                    self._make_event(
                        "layer_started",
                        data={"layer": layer_idx, "tasks": layer_task_ids},
                    ),
                )

                layer_results = self._execute_layer(
                    run=run,
                    task_store=task_store,
                    agent_map=agent_map,
                    layer_task_ids=layer_task_ids,
                    run_dir=run_dir,
                    cancel_event=cancel_event,
                    include_shell_tools=include_shell_tools,
                    grounding_block=grounding_block,
                    usage=usage,
                )

                for tid, result in layer_results.items():
                    usage.settle(tid, result)

                    completed = result.status == "completed"
                    cancelled = result.status == "cancelled"
                    error = None
                    update = {
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "summary": result.summary,
                        "artifacts": result.artifact_paths,
                        "worker_iterations": result.iterations,
                    }
                    if completed:
                        status = TaskStatus.completed
                    elif cancelled:
                        status = TaskStatus.cancelled
                    else:
                        status = TaskStatus.failed
                        error = redact_internal_paths(result.error)
                        update["error"] = error or f"worker did not complete (status={result.status})"

                    task_store.update_status(tid, status, **update)
                    if completed:
                        resolve_dependencies(run_dir / "tasks", tid)
                    else:
                        all_succeeded = False
                    data = ({"error": error} if status == TaskStatus.failed
                            else {"status": result.status, "iterations": result.iterations})
                    data.update({name: getattr(result, name) for name in UsageMeasure._fields})
                    self._emit_event(
                        run_id, self._make_event(f"task_{status.value}", task_id=tid, data=data),
                    )

                # Retained completed tasks also have no new layer result.
                for tid in layer_task_ids:
                    if tid not in layer_results and task_store.load_task(tid).status != TaskStatus.completed:
                        all_succeeded = False

                # Publish task statuses once per layer for run readers without per-task writes.
                self._sync_run_tasks_snapshot(run, task_store, usage)

        except Exception as exc:
            logger.error("Run %s failed with exception", run_id, exc_info=True)
            all_succeeded = False
            self._emit_event(
                run_id,
                self._make_event("run_error", data={"error": redact_internal_paths(str(exc))}),
            )

        final_status = (
            RunStatus.cancelled if cancel_event.is_set() else RunStatus.completed if all_succeeded else RunStatus.failed
        )
        run.status = final_status
        run.completed_at = datetime.now(timezone.utc).isoformat()

        run.tasks = task_store.load_all()

        from src.swarm.delivery import refresh_report
        refresh_report(run, layers[-1] if layers else [])

        usage.persist(final=True)
        self._emit_event(run_id, self._make_event("run_completed", data={"status": final_status.value, "report_is_partial": run.report_is_partial, "final_report": run.final_report}))

    def _sync_run_tasks_snapshot(self, run: SwarmRun, task_store: TaskStore, usage: _RunUsage) -> None:
        """Mirror live ``tasks/*.json`` back into ``run.json`` at a safe point."""
        try:
            run.tasks = task_store.load_all()
            usage.persist()
        except Exception:
            logger.warning("Layer-boundary run.json sync failed", exc_info=True)

    def _apply_resume_overlay(
        self,
        run: SwarmRun,
        run_dir: Path,
        task_store: TaskStore,
        resume_from: SwarmRun,
    ) -> None:
        """Carry completed tasks from *resume_from* into *run* before execution."""
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

        # Invalidate retained results transitively when an upstream task reruns.
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
            self._copy_node_thread(prev_run_dir, run_dir, task)
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
        # Resume unfinished tasks only when their inputs and definitions still match.
        for task in run.tasks:
            prev = prev_by_id.get(task.id)
            if prev is None or task.id in to_keep or prev.status == TaskStatus.completed:
                continue
            if any(dep not in to_keep for dep in task.depends_on):
                continue
            if _task_definition_changed(prev, task, prev_agents, new_agents, resume_from, run):
                continue
            if not self._copy_node_thread(prev_run_dir, run_dir, task):
                continue
            workspace = agent_artifact_dir(prev_run_dir, task.agent_id, task.id)
            paths = collect_node_artifacts(prev_run_dir, workspace)
            artifacts = _rehome_artifact_paths(paths, prev_run_dir, run_dir)
            task_store.update_status(task.id, TaskStatus.pending, summary=prev.summary, artifacts=artifacts)
        if kept:
            logger.info(
                "Run %s resumed from %s: kept %d completed task(s)",
                run.id,
                resume_from.id,
                kept,
            )

    @staticmethod
    def _copy_node_thread(source: Path, target: Path, task: SwarmTask) -> bool:
        original = node_thread(source, task.agent_id, task.id)
        if not original.is_file():
            return False
        destination = node_thread(target, task.agent_id, task.id)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
        return True

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

        # Emit heartbeats during grounding so the stale-run sweep leaves a healthy fetch alone.
        from src.kernel.progress import HeartbeatTimer

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
        run_dir: Path,
        cancel_event: threading.Event,
        include_shell_tools: bool = False,
        grounding_block: str = "",
        usage: _RunUsage | None = None,
    ) -> dict[str, WorkerResult]:
        """Execute all tasks in a single layer in parallel, with retry on failure."""
        results: dict[str, WorkerResult] = {}
        layer_stop = _LayerStop(cancel_event)

        def _event_callback(event: SwarmEvent) -> None:
            self._emit_event(run.id, event, accept=layer_stop.accepts_events)

        # Don't wait on work that could still be blocked in I/O after expiry.
        executor = ThreadPoolExecutor(max_workers=self._max_workers)
        futures: dict[Future[WorkerResult], str] = {}
        layer_budget = 0  # seconds — max per-task (retries × timeout) across layer
        try:
            for tid in layer_task_ids:
                task = task_store.load_task(tid)

                if task.status == TaskStatus.completed:
                    continue

                # Research can use incomplete evidence, with its status explicit.
                # Only dependencies that have not reached a terminal state wait.
                blocked_upstreams: list[tuple[str, str]] = []
                for dep_id in task.depends_on:
                    try:
                        dep_task = task_store.load_task(dep_id)
                    except FileNotFoundError:
                        blocked_upstreams.append((dep_id, "missing"))
                        continue
                    if dep_task.status not in {TaskStatus.completed, TaskStatus.failed, TaskStatus.cancelled}:
                        blocked_upstreams.append((dep_id, dep_task.status.value))

                if blocked_upstreams:
                    reason = ", ".join(f"{d}={s}" for d, s in blocked_upstreams)
                    blocked_by_ids = [d for d, _ in blocked_upstreams]
                    task_store.update_status(
                        tid,
                        TaskStatus.blocked,
                        error=f"Waiting for upstream result ({reason})",
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

                task_store.update_status(
                    tid,
                    TaskStatus.in_progress,
                    started_at=datetime.now(timezone.utc).isoformat(),
                    blocked_by=[],
                )
                self._emit_event(
                    run.id,
                    self._make_event("task_started", agent_id=agent_spec.id, task_id=tid),
                )

                # Name missing inputs so the downstream model does not invent their results.
                upstream: dict[str, str] = {}
                for context_key, source_task_id in task.input_from.items():
                    source = task_store.load_task(source_task_id)
                    if source.status == TaskStatus.completed:
                        upstream[context_key] = source.summary or ""
                    else:
                        upstream[context_key] = (
                            f"Upstream {source_task_id} is {source.status.value}. "
                            f"{source.error or 'The requested work is incomplete.'}\n"
                            "Use the available material below; identify missing inputs "
                            "and do not treat this as a completed analysis.\n\n"
                            + (source.summary or "No result was produced.")
                        )

                future = executor.submit(
                    self._run_node_with_retries,
                    agent_spec=agent_spec,
                    task=task,
                    upstream_summaries=upstream,
                    user_vars=run.user_vars,
                    run_dir=run_dir,
                    event_callback=_event_callback,
                    run_id=run.id,
                    include_shell_tools=include_shell_tools,
                    grounding_block=grounding_block,
                    cancel_event=layer_stop,
                    **({"record_usage": partial(usage.record, tid)} if usage is not None else {}),
                )
                futures[future] = tid
                per_task_budget = (
                    agent_spec.timeout_seconds * (agent_spec.max_retries + 1)
                    + _worker_retry_budget_s(agent_spec.max_retries)
                )
                layer_budget = max(layer_budget, per_task_budget)

            # Bound layer waits because blocked worker I/O can bypass in-loop timeouts (issue #42).
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
                layer_stop.expire()
                for pending, tid in futures.items():
                    if tid in results:
                        continue
                    cancelled_before_start = pending.cancel()
                    logger.error(
                        "Worker for task %s exceeded layer deadline (%ds)",
                        tid,
                        layer_deadline,
                    )
                    error = f"{_LAYER_DEADLINE_ERROR}{layer_deadline}s"
                    if not cancelled_before_start:
                        error += _UNKNOWN_OUTCOME
                    results[tid] = WorkerResult(
                        status="timeout",
                        summary="",
                        error=error,
                    )
        except KeyboardInterrupt:
            cancel_event.set()
            logger.warning("Swarm layer interrupted — cancelling pending workers")
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        return results

    def _run_node_with_retries(
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
        cancel_event: _CancellationSignal | None = None,
        record_usage: Callable[[UsageMeasure, dict], None] | None = None,
    ) -> WorkerResult:
        """Run a worker with automatic retry on failure."""
        max_retries = agent_spec.max_retries
        totals = dict.fromkeys(UsageMeasure._fields[:-1], 0)
        token_source = None
        result: WorkerResult | None = None

        def stop_requested() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        def cancelled_result() -> WorkerResult:
            if result is None:
                return WorkerResult(status="cancelled", summary="")
            return result.model_copy(update={
                **totals, "token_source": token_source, "status": WorkerStatus.cancelled,
            })

        successful_reads: dict[tuple[str, str], str] = {}
        thread_path = node_thread(run_dir, agent_spec.id, task.id)
        # Each task owns its artifact directory, so only retries need to clear it.
        for attempt in range(max_retries + 1):
            if stop_requested():
                return cancelled_result()
            if attempt > 0:
                retry_delay_s = _worker_retry_delay_s(attempt)
                retry_event = self._make_event(
                    "task_retry",
                    agent_id=agent_spec.id,
                    task_id=task.id,
                    data={
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "previous_error": result.error if result else None,
                        "retry_delay_s": retry_delay_s,
                    },
                )
                if event_callback is None:
                    self._emit_event(run_id, retry_event)
                else:
                    event_callback(retry_event)
                logger.info(
                    "Retrying task %s in %.2fs (attempt %d/%d)",
                    task.id,
                    retry_delay_s,
                    attempt + 1,
                    max_retries + 1,
                )
                if _wait_for_worker_retry(retry_delay_s, cancel_event) or stop_requested():
                    return cancelled_result()
                # Checkpointed retries continue the saved conversation and files.
                artifact_dir = agent_artifact_dir(run_dir, agent_spec.id, task.id)
                if not thread_path.is_file():
                    if stop_requested():
                        return cancelled_result()
                    clear_agent_artifacts(artifact_dir)
                    successful_reads.clear()

            if stop_requested():
                return cancelled_result()
            result = run_node(
                policy=self.policy,
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
                resume=thread_path.is_file(),
                successful_reads=successful_reads,
                **({"record_usage": record_usage} if record_usage is not None else {}),
            )

            for field in totals:
                totals[field] += getattr(result, field)
            token_source = _merge_token_source(token_source, result.token_source)
            if result.status != "failed" or result.error == UNKNOWN_TOOL_OUTCOME:
                break

        if result is not None:
            result = result.model_copy(update={**totals, "token_source": token_source})
        return result  # type: ignore[return-value]

    def _cancel_remaining_tasks(
        self,
        task_store: TaskStore,
        all_tasks: list[SwarmTask],
    ) -> None:
        """Mark all non-completed tasks as cancelled."""
        for task in all_tasks:
            if task.status not in (TaskStatus.completed, TaskStatus.failed):
                try:
                    task_store.update_status(task.id, TaskStatus.cancelled)
                except Exception:
                    logger.warning("Failed to cancel task %s", task.id, exc_info=True)
