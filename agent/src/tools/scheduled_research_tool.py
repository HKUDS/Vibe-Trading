"""Single read-only agent tool for scheduled research and proposals."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tools import BaseTool
from src.channels.targets import list_delivery_targets
from src.scheduled_research.playbooks import list_playbooks
from src.scheduled_research.proposals import propose_cancel, propose_create
from src.scheduled_research.service import default_store, public_job, scheduler_status


class ScheduledResearchTool(BaseTool):
    """Inspect scheduled research or prepare a user-confirmable mutation."""

    name = "scheduled_research"
    description = (
        "Inspect scheduled research and prepare create/cancel proposals. This is "
        "the only scheduled-research tool and is READ-ONLY: propose_create and "
        "propose_cancel never change jobs. A human must confirm the proposal in "
        "the current surface before it is committed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "list_jobs",
                    "get_job",
                    "list_playbooks",
                    "propose_create",
                    "propose_cancel",
                ],
            },
            "job_id": {"type": "string"},
            "draft": {
                "type": "object",
                "description": "Create draft; required for propose_create.",
                "properties": {
                    "title": {"type": "string"},
                    "source": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["prompt", "playbook"]},
                            "prompt": {"type": "string"},
                            "playbook_slug": {"type": "string"},
                            "variables": {"type": "object"},
                        },
                        "required": ["kind"],
                    },
                    "schedule": {
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string"},
                            "timezone": {"type": ["string", "null"]},
                        },
                        "required": ["expression"],
                    },
                    "end_at": {
                        "type": ["string", "integer", "null"],
                        "description": "RFC3339 timestamp with offset, or epoch milliseconds.",
                    },
                    "delivery": {
                        "type": "object",
                        "properties": {
                            "mode": {
                                "type": "string",
                                "enum": ["in_app", "origin", "configured"],
                            },
                            "target_ref": {"type": "string"},
                            "format": {
                                "type": ["string", "null"],
                                "enum": ["html", "pdf", None],
                                "description": "Email only; omit or null for plain text. Destination must be configured or from the origin session.",
                            },
                            "protect_pdf": {
                                "type": "boolean",
                                "description": "Encrypt a PDF Email report using the private channel password configured by the user; never supply the password in a draft.",
                            },
                        },
                        "required": ["mode"],
                    },
                },
                "required": ["title", "source", "schedule", "end_at", "delivery"],
            },
        },
        "required": ["action"],
    }
    repeatable = True
    is_readonly = True

    def __init__(self, default_session_id: str | None = None, **_kwargs: Any) -> None:
        self._default_session_id = default_session_id

    def execute(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action") or "").strip()
        session_id = (
            str(kwargs.get("session_id") or self._default_session_id or "").strip()
            or None
        )
        if action == "status":
            payload = scheduler_status()
            payload["delivery_targets"] = [
                target.public_dict() for target in list_delivery_targets()
            ]
        elif action == "list_jobs":
            payload = {
                "jobs": [
                    public_job(job) for job in default_store().list_jobs(limit=200)
                ]
            }
        elif action == "get_job":
            job_id = str(kwargs.get("job_id") or "").strip()
            job = default_store().get(job_id)
            if job is None:
                raise ValueError(f"scheduled research job {job_id!r} was not found")
            payload = public_job(job)
        elif action == "list_playbooks":
            payload = {"playbooks": [item.to_dict() for item in list_playbooks()]}
        elif action == "propose_create":
            draft = kwargs.get("draft")
            if not isinstance(draft, dict):
                raise ValueError("draft is required for propose_create")
            payload = propose_create(draft, session_id=session_id)
        elif action == "propose_cancel":
            job_id = str(kwargs.get("job_id") or "").strip()
            if not job_id:
                raise ValueError("job_id is required for propose_cancel")
            payload = propose_cancel(job_id, session_id=session_id)
        else:
            raise ValueError(f"unsupported scheduled_research action {action!r}")
        return json.dumps(payload, ensure_ascii=False)
