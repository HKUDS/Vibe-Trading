"""Shared scheduling kernel (scheduler unification).

This package is the single home of the scheduling machinery every scheduler
in the repo can adopt:

* :mod:`src.scheduling.triggers` — pure, clock-injected trigger grammar
  (interval-ms + 5-field cron + IANA timezones with the DST gap-skip /
  fold=0 policy) and next-run math, plus the ``once`` trigger kind absorbed
  from the live runtime scheduler (consumed by its kernel-backed façade).
* :mod:`src.scheduling.types` — the shared vocabulary: ``ExecutorKind`` with
  its closed runtime domain, and the kernel callback type aliases.
* :mod:`src.scheduling.kernel` — ``SchedulerKernel``: the generic tick loop
  with ``asyncio.Event`` wakeup, bounded exponential backoff, an injectable
  clock, the ``on_tick`` seam for domain logic and an optional
  ``sleep_hint_fn`` seam for adaptive-sleep consumers (together consumed by
  the scheduled-research executor and the live runtime scheduler).
* :mod:`src.scheduling.registry` — the internal-callable allowlist: an
  explicit module-level dict mapping literal registry keys to zero-arg
  sync/async callables, with exact-key resolution only (no dynamic import,
  no string parsing, no shell) and deferred domain imports.
* :mod:`src.scheduling.system_jobs` — protected system jobs: the
  ``SystemJobSpec`` surface (``system:`` id prefix, ``source_type="system"``,
  ``executor_kind="internal"``, registry-key callable, per-spec enablement
  predicate) and ``ensure_system_jobs`` — the idempotent startup
  seed/repair pass (tamper correction, status reset, schedule-trust
  boundary, repair-replay, flag-off halt) called from the lifespan before
  the executor starts.
"""

from src.scheduling.kernel import (
    DEFAULT_MAX_CONSECUTIVE_FAILURES,
    DEFAULT_RETRY_BASE_DELAY_MS,
    DEFAULT_RETRY_MAX_DELAY_MS,
    DEFAULT_TICK_INTERVAL_MS,
    DEFAULT_TASK_NAME,
    SchedulerKernel,
)
from src.scheduling.registry import (
    InternalCallableError,
    InternalRunnable,
    is_registered,
    list_internal,
    register_internal,
    resolve_internal,
)
from src.scheduling.triggers import (
    CRON_BOUNDS,
    CRON_SEARCH_LIMIT_DAYS,
    DEFAULT_TRIGGER_INTERVAL_MS,
    ONCE_SPEC,
    day_matches,
    is_interval_schedule,
    local_wall_time_to_epoch_ms,
    next_cron_due,
    next_due,
    next_once_due,
    parse_cron_field,
    trigger_interval_ms,
    validate_schedule,
    validate_timezone,
    validate_timezone_shape,
)
from src.scheduling.types import (
    EXECUTOR_KINDS,
    ExecutorKind,
    NowFn,
    OnTickFn,
    SleepHintFn,
    is_executor_kind,
)

__all__ = [
    "CRON_BOUNDS",
    "CRON_SEARCH_LIMIT_DAYS",
    "DEFAULT_MAX_CONSECUTIVE_FAILURES",
    "DEFAULT_RETRY_BASE_DELAY_MS",
    "DEFAULT_RETRY_MAX_DELAY_MS",
    "DEFAULT_TASK_NAME",
    "DEFAULT_TICK_INTERVAL_MS",
    "DEFAULT_TRIGGER_INTERVAL_MS",
    "EXECUTOR_KINDS",
    "ONCE_SPEC",
    "ExecutorKind",
    "InternalCallableError",
    "InternalRunnable",
    "NowFn",
    "OnTickFn",
    "SchedulerKernel",
    "SleepHintFn",
    "day_matches",
    "is_executor_kind",
    "is_interval_schedule",
    "is_registered",
    "list_internal",
    "local_wall_time_to_epoch_ms",
    "next_cron_due",
    "next_due",
    "next_once_due",
    "parse_cron_field",
    "register_internal",
    "resolve_internal",
    "trigger_interval_ms",
    "validate_schedule",
    "validate_timezone",
    "validate_timezone_shape",
    # Lazily resolved (PEP 562) — see the comment below.
    "EnabledPredicate",
    "EnsureSystemJobsReport",
    "JOB_ID_RULE_MESSAGE",
    "SAFE_JOB_ID_RE",
    "SYSTEM_JOB_ID_PREFIX",
    "SpecGate",
    "SystemJobSpec",
    "ensure_system_jobs",
    "is_safe_job_id",
    "is_system_job_id",
    "system_job_specs",
]

# --- lazy re-export: src.scheduling.system_jobs (PEP 562) -------------------
# system_jobs imports src.scheduled_research.models/store, and models itself
# imports src.scheduling.triggers — an eager import here would make that
# re-enter this partially initialized __init__ (circular ImportError) whenever
# src.scheduled_research is imported before src.scheduling. Deferring the
# import to first attribute access keeps the export surface identical
# (``from src.scheduling import ensure_system_jobs`` and friends all work)
# while breaking the import-time cycle in every import order.
_SYSTEM_JOBS_EXPORTS = frozenset(
    {
        "JOB_ID_RULE_MESSAGE",
        "SAFE_JOB_ID_RE",
        "SYSTEM_JOB_ID_PREFIX",
        "EnabledPredicate",
        "EnsureSystemJobsReport",
        "SpecGate",
        "SystemJobSpec",
        "ensure_system_jobs",
        "is_safe_job_id",
        "is_system_job_id",
        "system_job_specs",
    }
)


def __getattr__(name: str):
    """Lazily resolve the system-jobs exports (see the comment above)."""
    if name in _SYSTEM_JOBS_EXPORTS:
        from src.scheduling import system_jobs

        return getattr(system_jobs, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
