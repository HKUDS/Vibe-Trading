"""Scheduled research HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_scheduled_routes(app, ...)``.
"""

from __future__ import annotations

import logging
import re
import sys as _sys
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.config.accessor import get_env_config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SCHEDULED_RESEARCH_SCHEDULER_ENV = "VIBE_TRADING_ENABLE_SCHEDULER"
_SCHEDULED_RESEARCH_TRUE_VALUES = {"1", "true", "yes", "on"}

# Mirrors ``_SAFE_PATH_PARAM_RE`` in src/api/helpers.py, which the delete route
# enforces on the job id. Kept in sync so a job can never be created under an
# id the delete route refuses.
_SAFE_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_scheduled_research_store: Any = None
_scheduled_research_executor: Any = None


def _scheduled_research_scheduler_enabled() -> bool:
    """Return whether scheduled research execution is enabled."""
    return get_env_config().agent_tuning.vibe_trading_enable_scheduler


def _get_scheduled_research_store():
    """Return the singleton ScheduledResearchJobStore, creating it on first call."""
    global _scheduled_research_store
    if _scheduled_research_store is None:
        from src.scheduled_research.store import ScheduledResearchJobStore

        _scheduled_research_store = ScheduledResearchJobStore()
    return _scheduled_research_store


async def _dispatch_scheduled_research_job(job) -> None:
    """Enqueue one scheduled research job through the session runtime.

    ``send_message`` queues the agent attempt and returns once accepted; it
    does not wait for that agent run to reach a terminal status. The executor's
    ``COMPLETED`` state for this dispatch path means "successfully enqueued."
    """
    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    svc = host._get_session_service()
    if not svc:
        raise RuntimeError("Session runtime not enabled")
    # Pass a copy so the session runtime's internal config writes (e.g.
    # include_shell_tools) do not mutate the persisted scheduled-run config.
    session = svc.create_session(
        title=f"scheduled-research:{job.id}", config=dict(job.config)
    )
    logger.info(
        "dispatching scheduled research job %s via session %s",
        job.id,
        session.session_id,
    )
    await svc.send_message(session.session_id, job.prompt)


def _get_scheduled_research_executor():
    """Return the singleton scheduled research executor."""
    global _scheduled_research_executor
    if _scheduled_research_executor is None:
        from src.scheduled_research.executor import ScheduledResearchExecutor

        _scheduled_research_executor = ScheduledResearchExecutor(
            _get_scheduled_research_store(),
            _dispatch_scheduled_research_job,
            enabled=_scheduled_research_scheduler_enabled(),
        )
    return _scheduled_research_executor


def _start_scheduled_research_executor() -> None:
    """Start scheduled research execution when explicitly enabled."""
    if not _scheduled_research_scheduler_enabled():
        return
    _get_scheduled_research_executor().start()


async def _stop_scheduled_research_executor() -> None:
    """Stop scheduled research execution if it was started."""
    executor = _scheduled_research_executor
    if executor is not None:
        await executor.stop()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CreateScheduledRunRequest(BaseModel):
    """Request body for POST /scheduled-runs."""

    id: Optional[str] = Field(
        None,
        description=(
            "Job id; auto-generated UUID when omitted. Must match the id rule "
            "the delete route enforces: letters, digits, '_' and '-', 1-128 "
            "characters."
        ),
    )
    prompt: str = Field(
        ..., min_length=1, description="Research prompt or backtest description"
    )
    schedule: str = Field(
        ..., min_length=1, description="Interval-ms or 5-field cron expression"
    )
    next_run_at: Optional[int] = Field(
        None, description="Epoch-ms for next run; defaults to now"
    )
    config: Dict[str, Any] = Field(
        default_factory=dict, description="Optional backtest parameters"
    )
    timezone: Optional[str] = Field(
        None,
        description=(
            "IANA timezone key the cron schedule is evaluated in "
            "(e.g. 'Pacific/Auckland'); null = UTC, the pre-existing "
            "semantics. Ignored by interval schedules."
        ),
    )


class PlaybookResponse(BaseModel):
    """Catalogue record for one research playbook template.

    ``body`` is the raw instruction text with ``{{placeholders}}`` unresolved.
    It is populated only by the single-template endpoint; the list endpoint
    leaves it null so a catalogue response stays small.
    """

    slug: str
    name: str
    description: str
    suggested_schedule: str
    suggested_timezone: Optional[str] = None
    markets: List[str] = Field(default_factory=list)
    data_capabilities: List[str] = Field(default_factory=list)
    variables: Dict[str, str] = Field(default_factory=dict)
    body: Optional[str] = None


class CreateRunFromPlaybookRequest(BaseModel):
    """Request body for POST /scheduled-runs/playbooks/{slug}.

    Every field is optional: posting ``{}`` schedules the template on its own
    suggested cadence with its declared variable defaults.
    """

    id: Optional[str] = Field(
        None, description="Job id; defaults to a slug-prefixed generated id"
    )
    schedule: Optional[str] = Field(
        None,
        min_length=1,
        description=(
            "Schedule override (interval-ms or 5-field cron); defaults to the "
            "template's suggested_schedule"
        ),
    )
    timezone: Optional[str] = Field(
        None,
        description=(
            "IANA timezone override. Omit the field to keep the template's "
            "suggested_timezone; send null explicitly to force UTC."
        ),
    )
    variables: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Overrides for the template's declared variables. An undeclared "
            "name is rejected rather than silently ignored."
        ),
    )
    config: Dict[str, Any] = Field(
        default_factory=dict, description="Session config forwarded to the agent run"
    )
    next_run_at: Optional[int] = Field(
        None, description="Explicit first-fire epoch-ms, bypassing the default rule"
    )


class ScheduledRunResponse(BaseModel):
    """API response for a single scheduled job."""

    id: str
    prompt: str
    schedule: str
    next_run_at: int
    status: str
    created_at: int
    last_run_at: Optional[int] = None
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    failure_kind: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    timezone: Optional[str] = None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_scheduled_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the scheduled routes onto ``app``.

    Resolves ``require_auth`` from the host ``api_server`` module via
    ``sys.modules`` when not passed explicitly.
    """
    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")

    if host is None:
        raise RuntimeError(
            "register_scheduled_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_auth is None:
        require_auth = host.require_auth

    def _host_validate_path_param(value: str, kind: str) -> None:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        h._validate_path_param(value, kind)

    # --- Routes ---

    @app.post(
        "/scheduled-runs",
        response_model=ScheduledRunResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def create_scheduled_run(
        request: CreateScheduledRunRequest,
    ) -> ScheduledRunResponse:
        """Create (or replace) a scheduled research job.

        The job is persisted immediately. No execution is triggered.
        """
        from src.scheduled_research.models import (
            JobStatus,
            ScheduledResearchJob,
            is_interval_schedule,
            validate_schedule,
            validate_timezone,
            validate_timezone_shape,
        )

        from src.scheduled_research.executor import next_due

        # A job whose id the delete route rejects can never be cancelled
        # through the API, so the id is held to that same rule at creation
        # rather than at first attempted delete.
        if request.id is not None and not _SAFE_JOB_ID_RE.fullmatch(request.id):
            raise HTTPException(
                status_code=422,
                detail=(
                    "job id must be 1-128 characters of letters, digits, "
                    "'_' or '-'"
                ),
            )

        try:
            validate_schedule(request.schedule)
            # Interval schedules ignore the timezone, and the executor
            # deliberately skips resolving it for them so an interval job keeps
            # advancing on a host whose timezone database lacks the key. The
            # create path follows the same rule: only a cron schedule, whose
            # evaluation actually needs the zone, resolves it. Both forms still
            # reject a blank value.
            if is_interval_schedule(request.schedule):
                validate_timezone_shape(request.timezone)
            else:
                validate_timezone(request.timezone)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        now_ms = int(time.time() * 1000)
        next_run_at = request.next_run_at
        if next_run_at is None:
            next_run_at = now_ms
            if request.timezone is not None and not is_interval_schedule(request.schedule):
                # A timezone-carrying cron job's contract is the authored wall
                # clock, so its first fire is the first authored occurrence —
                # not the creation moment. Interval jobs and timezone-less
                # jobs keep the pre-existing immediate-first-fire default.
                try:
                    next_run_at = next_due(request.schedule, now_ms, request.timezone)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc

        job = ScheduledResearchJob(
            id=request.id or str(uuid.uuid4()),
            prompt=request.prompt,
            schedule=request.schedule,
            next_run_at=next_run_at,
            status=JobStatus.PENDING,
            created_at=now_ms,
            config=request.config,
            timezone=request.timezone,
        )
        _get_scheduled_research_store().upsert(job)
        return ScheduledRunResponse(**job.to_dict())

    @app.get(
        "/scheduled-runs",
        response_model=List[ScheduledRunResponse],
        dependencies=[Depends(require_auth)],
    )
    async def list_scheduled_runs(
        status_filter: Optional[str] = Query(None, alias="status"),
        limit: int = Query(50, ge=1, le=200),
    ) -> List[ScheduledRunResponse]:
        """List scheduled research jobs, optionally filtered by status."""
        jobs = _get_scheduled_research_store().list_jobs(
            status=status_filter, limit=limit
        )
        return [ScheduledRunResponse(**j.to_dict()) for j in jobs]

    @app.delete(
        "/scheduled-runs/{job_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_auth)],
    )
    async def delete_scheduled_run(job_id: str) -> None:
        """Cancel (delete) a scheduled research job by id."""
        _host_validate_path_param(job_id, "job_id")
        removed = _get_scheduled_research_store().delete(job_id)
        if not removed:
            raise HTTPException(
                status_code=404, detail=f"scheduled run {job_id} not found"
            )

    # --- Playbook templates ---
    #
    # Mounted under /scheduled-runs because a template is only useful as the
    # source of a scheduled run. ``{job_id}`` never matches across a "/", so
    # these paths cannot collide with the CRUD routes above. Every one carries
    # the same ``require_auth`` dependency: there is deliberately no unguarded
    # way to enumerate the catalogue or create a job from it.

    @app.get(
        "/scheduled-runs/playbooks",
        response_model=List[PlaybookResponse],
        dependencies=[Depends(require_auth)],
    )
    async def list_research_playbooks() -> List[PlaybookResponse]:
        """List the available research playbook templates, without bodies."""
        from src.scheduled_research.playbooks import PlaybookError, list_playbooks

        try:
            playbooks = list_playbooks()
        except (PlaybookError, OSError) as exc:
            # A malformed file is surfaced, not skipped: a user template the
            # loader refuses must be visible as a broken template rather than
            # vanish from the catalogue.
            raise HTTPException(
                status_code=500, detail=f"playbook catalogue is unreadable: {exc}"
            ) from exc
        return [PlaybookResponse(**pb.to_dict()) for pb in playbooks]

    @app.get(
        "/scheduled-runs/playbooks/{slug}",
        response_model=PlaybookResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_research_playbook(slug: str) -> PlaybookResponse:
        """Read one research playbook template, including its instruction body."""
        from src.scheduled_research.playbooks import (
            PlaybookError,
            PlaybookNotFoundError,
            get_playbook,
        )

        _host_validate_path_param(slug, "slug")
        try:
            playbook = get_playbook(slug)
        except PlaybookNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (PlaybookError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return PlaybookResponse(**playbook.to_dict(include_body=True))

    @app.post(
        "/scheduled-runs/playbooks/{slug}",
        response_model=ScheduledRunResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def create_scheduled_run_from_playbook(
        slug: str,
        request: CreateRunFromPlaybookRequest,
    ) -> ScheduledRunResponse:
        """Create a scheduled research job from a template.

        The template body becomes ``job.prompt`` verbatim — the natural-language
        data requirements are never rewritten into tool calls here; routing
        stays the agent's job at run time.

        Schedule and timezone are validated by ``ResearchPlaybook.to_job``,
        which calls the same ``validate_schedule`` / ``validate_timezone`` the
        plain ``POST /scheduled-runs`` path uses, so the two entry points can
        never accept different schedule grammars.
        """
        from src.scheduled_research.playbooks import (
            PlaybookError,
            PlaybookNotFoundError,
            get_playbook,
        )

        _host_validate_path_param(slug, "slug")
        # Unlike POST /scheduled-runs this checks the caller-supplied id up
        # front: an id outside the safe pattern would persist fine but could
        # never be removed through DELETE /scheduled-runs/{job_id}, which
        # rejects it with 400.
        if request.id is not None:
            _host_validate_path_param(request.id, "id")

        try:
            playbook = get_playbook(slug)
        except PlaybookNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (PlaybookError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        kwargs: Dict[str, Any] = {}
        # An omitted timezone keeps the template's suggestion; an explicit null
        # means UTC. Pydantic collapses both to ``None``, so the distinction has
        # to come from the fields the caller actually sent.
        if "timezone" in request.model_fields_set:
            kwargs["timezone"] = request.timezone

        try:
            job = playbook.to_job(
                job_id=request.id,
                schedule=request.schedule,
                variables=request.variables,
                config=request.config,
                next_run_at=request.next_run_at,
                **kwargs,
            )
        except ValueError as exc:
            # Covers PlaybookError (undeclared/oversized variable) and the
            # schedule / timezone / cron-window failures, all ValueError.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        _get_scheduled_research_store().upsert(job)
        return ScheduledRunResponse(**job.to_dict())
