from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import HTTPException

from src.api.helpers import RUNS_DIR, SESSIONS_DIR

logger = logging.getLogger(__name__)

# ============================================================================
# Module-level singleton variables
# ============================================================================

_session_service = None
_goal_store = None
_channel_runtime = None
_channel_bus = None
_channel_manager = None
_swarm_runtime = None
_scheduled_research_store: Optional["ScheduledResearchJobStore"] = None
_scheduled_research_executor: Optional["ScheduledResearchExecutor"] = None

# ============================================================================
# Scheduled research constants
# ============================================================================

_SCHEDULED_RESEARCH_SCHEDULER_ENV = "VIBE_TRADING_ENABLE_SCHEDULER"
_SCHEDULED_RESEARCH_TRUE_VALUES = {"1", "true", "yes", "on"}


# ============================================================================
# Session service
# ============================================================================


def _get_session_service():
    """Lazy-init session service when ENABLE_SESSION_RUNTIME=true."""
    global _session_service
    if _session_service is not None:
        return _session_service

    if os.getenv("ENABLE_SESSION_RUNTIME", "true").lower() != "true":
        return None

    import asyncio
    from src.session.store import SessionStore
    from src.session.events import EventBus
    from src.session.service import SessionService

    store = SessionStore(base_dir=SESSIONS_DIR)
    event_bus = EventBus()

    try:
        loop = asyncio.get_event_loop()
        event_bus.set_loop(loop)
    except RuntimeError:
        pass

    _session_service = SessionService(
        store=store,
        event_bus=event_bus,
        runs_dir=RUNS_DIR,
    )
    return _session_service


# ============================================================================
# Channel runtime
# ============================================================================


def _get_channel_runtime():
    """Lazy-init IM channel runtime without starting platform adapters."""
    global _channel_runtime, _channel_bus, _channel_manager
    if _channel_runtime is not None:
        return _channel_runtime

    from src.channels.bus.queue import MessageBus
    from src.channels.config import load_channels_config
    from src.channels.manager import ChannelManager
    from src.channels.runtime import ChannelRuntime

    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")

    _channel_bus = MessageBus()
    config = load_channels_config()
    _channel_manager = ChannelManager(config, _channel_bus, session_service=svc)
    _channel_runtime = ChannelRuntime(
        bus=_channel_bus,
        session_service=svc,
        manager=_channel_manager,
    )
    return _channel_runtime


async def _start_channel_runtime():
    """Start the IM channel runtime."""
    runtime = _get_channel_runtime()
    await runtime.start(start_manager=True)
    return runtime


async def _stop_channel_runtime() -> None:
    """Stop the IM channel runtime if it was initialized."""
    if _channel_runtime is None:
        return
    await _channel_runtime.stop()


# ============================================================================
# Goal store
# ============================================================================


def _get_goal_store():
    """Return the shared finance goal store."""
    global _goal_store
    if _goal_store is None:
        from src.goal import GoalStore

        _goal_store = GoalStore()
    return _goal_store


def _get_existing_session_or_404(session_id: str):
    svc = _get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    session = svc.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return svc, session


# ============================================================================
# Swarm runtime
# ============================================================================


def _get_swarm_runtime():
    """Lazy-init SwarmRuntime singleton."""
    global _swarm_runtime
    if _swarm_runtime is not None:
        return _swarm_runtime
    from src.config import load_swarm_agent_config
    from src.swarm.store import SwarmStore
    from src.swarm.runtime import SwarmRuntime
    swarm_dir = Path(__file__).resolve().parent.parent.parent / ".swarm" / "runs"
    store = SwarmStore(base_dir=swarm_dir)
    # Boot-time / operator-trusted: REST API callers cannot influence the
    # config path. See docs/2026-05-25_swarm_mcp_tools_roadmap.md.
    agent_config = load_swarm_agent_config()
    _swarm_runtime = SwarmRuntime(store=store, agent_config=agent_config)
    return _swarm_runtime


# ============================================================================
# Scheduled research
# ============================================================================


def _get_scheduled_research_store() -> "ScheduledResearchJobStore":
    """Return the singleton ScheduledResearchJobStore, creating it on first call."""
    global _scheduled_research_store
    if _scheduled_research_store is None:
        from src.scheduled_research.store import ScheduledResearchJobStore

        _scheduled_research_store = ScheduledResearchJobStore()
    return _scheduled_research_store


def _scheduled_research_scheduler_enabled() -> bool:
    """Return whether scheduled research execution is enabled."""
    return os.getenv(_SCHEDULED_RESEARCH_SCHEDULER_ENV, "").strip().lower() in _SCHEDULED_RESEARCH_TRUE_VALUES


async def _dispatch_scheduled_research_job(job: "ScheduledResearchJob") -> None:
    """Enqueue one scheduled research job through the session runtime.

    ``send_message`` queues the agent attempt and returns once accepted; it
    does not wait for that agent run to reach a terminal status. The executor's
    ``COMPLETED`` state for this dispatch path means "successfully enqueued."
    """
    svc = _get_session_service()
    if not svc:
        raise RuntimeError("Session runtime not enabled")
    # Pass a copy so the session runtime's internal config writes (e.g.
    # include_shell_tools) do not mutate the persisted scheduled-run config.
    session = svc.create_session(title=f"scheduled-research:{job.id}", config=dict(job.config))
    logger.info("dispatching scheduled research job %s via session %s", job.id, session.session_id)
    await svc.send_message(session.session_id, job.prompt)


def _get_scheduled_research_executor() -> "ScheduledResearchExecutor":
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
