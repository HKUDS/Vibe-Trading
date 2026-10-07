"""Domain service shared by HTTP, tools, CLI and IM surfaces."""

from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime
from typing import Any, Mapping

from src.channels.targets import resolve_delivery_target
from src.scheduled_research.executor import next_due, scheduler_enabled_from_env
from src.scheduled_research.models import (
    JobStatus,
    ScheduledResearchJob,
    is_interval_schedule,
    validate_schedule,
    validate_timezone,
    validate_timezone_shape,
)
from src.scheduled_research.playbooks import get_playbook
from src.scheduled_research.store import ScheduledResearchJobStore


def public_job(job: ScheduledResearchJob) -> dict[str, Any]:
    """Return the user-facing job shape without raw channel destination ids."""
    state = job.status.value
    if job.status in {JobStatus.PENDING, JobStatus.COMPLETED}:
        state = "active"
    return {
        "id": job.id,
        "title": job.title or job.id,
        "state": state,
        "source": {
            "kind": job.source_type,
            "playbook_slug": job.playbook_slug,
            "prompt": job.prompt if job.source_type == "prompt" else None,
        },
        "schedule": {
            "expression": job.schedule,
            "timezone": job.timezone,
            "next_run_at": None if job.status is JobStatus.EXPIRED else job.next_run_at,
            "end_at": job.end_at,
        },
        "delivery": {
            "channel": job.delivery_channel,
            "target_ref": job.delivery_target_ref,
            "target_label": job.delivery_target_label,
            "format": job.delivery_format,
            "status": job.delivery.status.value,
            "attempts": job.delivery.attempts,
            "provider_message_id": job.delivery.provider_message_id,
            "error": job.delivery.error,
        },
        "last_run_at": job.last_run_at,
        "last_error": job.last_error,
    }


def scheduler_status() -> dict[str, Any]:
    """Return configuration and runtime state without starting the scheduler."""
    enabled = scheduler_enabled_from_env()
    running = False
    host = sys.modules.get("api_server") or sys.modules.get("agent.api_server")
    executor = getattr(host, "_scheduled_research_executor", None) if host else None
    if executor is None:
        try:
            from src.api import scheduled_routes

            executor = scheduled_routes._scheduled_research_executor
        except Exception:
            executor = None
    if executor is not None:
        running = bool(executor.is_running)
    return {"enabled": enabled, "running": running, "executable": enabled and running}


def _parse_end_at(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("end_at must be RFC3339 text or epoch milliseconds")
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        raise ValueError("end_at must be RFC3339 text or epoch milliseconds")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("end_at must be a valid RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("end_at must include an explicit timezone offset")
    return int(parsed.timestamp() * 1000)


def _origin_target(session_id: str | None) -> tuple[str, str, str | None, str]:
    if not session_id:
        raise ValueError("origin delivery requires the originating session")
    host = sys.modules.get("api_server") or sys.modules.get("agent.api_server")
    service = (
        host._get_session_service()
        if host and hasattr(host, "_get_session_service")
        else None
    )
    session = service.get_session(session_id) if service else None
    config = getattr(session, "config", None) or {}
    channel = config.get("channel")
    target = config.get("channel_chat_id")
    if not isinstance(channel, str) or not isinstance(target, str):
        raise ValueError("the originating session is not an IM conversation")
    return channel, target, None, "当前会话"


def build_job_from_draft(
    draft: Mapping[str, Any],
    *,
    session_id: str | None = None,
    now_ms: int | None = None,
) -> ScheduledResearchJob:
    """Validate the public draft and build a persisted-model job."""
    now = int(time.time() * 1000) if now_ms is None else now_ms
    title = str(draft.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")
    source = draft.get("source")
    schedule_spec = draft.get("schedule")
    delivery_spec = draft.get("delivery") or {"mode": "in_app"}
    if not isinstance(source, Mapping) or not isinstance(schedule_spec, Mapping):
        raise ValueError("source and schedule must be objects")
    if not isinstance(delivery_spec, Mapping):
        raise ValueError("delivery must be an object")

    source_type = str(source.get("kind") or "prompt")
    playbook_slug = None
    config: dict[str, Any] = {}
    if source_type == "prompt":
        prompt = str(source.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("source.prompt is required")
    elif source_type == "playbook":
        playbook_slug = str(source.get("playbook_slug") or "").strip()
        if not playbook_slug:
            raise ValueError("source.playbook_slug is required")
        playbook = get_playbook(playbook_slug)
        variables = source.get("variables") or {}
        if not isinstance(variables, Mapping):
            raise ValueError("source.variables must be an object")
        prompt = playbook.render(variables)
        config["playbook"] = playbook_slug
    else:
        raise ValueError("source.kind must be 'prompt' or 'playbook'")

    expression = str(schedule_spec.get("expression") or "").strip()
    timezone = schedule_spec.get("timezone")
    validate_schedule(expression)
    if is_interval_schedule(expression):
        validate_timezone_shape(timezone)
    else:
        validate_timezone(timezone)
    next_run_at = now
    if timezone is not None and not is_interval_schedule(expression):
        next_run_at = next_due(expression, now, timezone)

    end_at = _parse_end_at(draft.get("end_at"))
    if end_at is not None and end_at <= now:
        raise ValueError("end_at must be in the future")
    if end_at is not None and next_run_at > end_at:
        raise ValueError("the first scheduled run occurs after end_at")

    mode = str(delivery_spec.get("mode") or "in_app")
    delivery_channel = delivery_target = target_ref = target_label = None
    if mode == "configured":
        target_ref = str(delivery_spec.get("target_ref") or "").strip()
        if not target_ref:
            raise ValueError("delivery.target_ref is required for configured delivery")
        target = resolve_delivery_target(target_ref)
        delivery_channel, delivery_target = target.channel, target.target
        target_label = target.label
    elif mode == "origin":
        delivery_channel, delivery_target, target_ref, target_label = _origin_target(
            session_id
        )
    elif mode != "in_app":
        raise ValueError("delivery.mode must be 'in_app', 'origin', or 'configured'")

    delivery_format = delivery_spec.get("format")
    if delivery_format not in (None, "html", "pdf"):
        raise ValueError("delivery.format must be 'html', 'pdf', or null")
    if delivery_format is not None and delivery_channel != "email":
        raise ValueError("delivery.format is supported only for email delivery")

    return ScheduledResearchJob(
        id=str(draft.get("id") or f"sr-{uuid.uuid4().hex[:12]}"),
        title=title,
        prompt=prompt,
        source_type=source_type,
        playbook_slug=playbook_slug,
        schedule=expression,
        timezone=timezone,
        next_run_at=next_run_at,
        end_at=end_at,
        status=JobStatus.PENDING,
        created_at=now,
        config=config,
        delivery_channel=delivery_channel,
        delivery_target=delivery_target,
        delivery_target_ref=target_ref,
        delivery_target_label=target_label,
        delivery_format=delivery_format,
    )


def default_store() -> ScheduledResearchJobStore:
    """Return the API singleton when available so every surface shares state."""
    try:
        from src.api.scheduled_routes import _get_scheduled_research_store

        return _get_scheduled_research_store()
    except Exception:
        return ScheduledResearchJobStore()
