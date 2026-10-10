"""Durable confirmation proposals for scheduled-research mutations."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Mapping

from src.config.paths import get_runtime_root
from src.scheduled_research.service import (
    build_job_from_draft,
    default_store,
    public_job,
    scheduler_status,
)

_ID_RE = re.compile(r"^srp_[0-9a-f]{32}$")
_TTL_MS = 15 * 60 * 1000
_LOCK = threading.Lock()


class ProposalError(ValueError):
    pass


def _path(proposal_id: str) -> Path:
    if not _ID_RE.fullmatch(proposal_id):
        raise ProposalError("invalid scheduled research proposal id")
    return (
        get_runtime_root() / "scheduled_research" / "proposals" / f"{proposal_id}.json"
    )


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(
                    (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
                )
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise
    os.chmod(path, 0o600)


def _read(proposal_id: str) -> dict[str, Any]:
    path = _path(proposal_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalError(f"proposal {proposal_id!r} is unknown") from exc
    if not isinstance(payload, dict):
        raise ProposalError("proposal record is malformed")
    return payload


def public_proposal(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "scheduled_research.proposal",
        "proposal_id": payload["proposal_id"],
        "operation": payload["operation"],
        "status": payload["status"],
        "expires_at": payload["expires_at"],
        "job": payload.get("job"),
        "job_id": payload.get("job_id"),
        "committed_job_id": payload.get("committed_job_id"),
    }


def propose_create(
    draft: Mapping[str, Any], *, session_id: str | None = None
) -> dict[str, Any]:
    job = build_job_from_draft(draft, session_id=session_id)
    now = int(time.time() * 1000)
    payload = {
        "proposal_id": f"srp_{uuid.uuid4().hex}",
        "operation": "create",
        "status": "pending",
        "session_id": session_id,
        "created_at": now,
        "expires_at": now + _TTL_MS,
        "job": public_job(job),
        "internal_job": job.to_dict(),
    }
    _write(_path(payload["proposal_id"]), payload)
    return public_proposal(payload)


def propose_cancel(job_id: str, *, session_id: str | None = None) -> dict[str, Any]:
    job = default_store().get(job_id)
    if job is None:
        raise ProposalError(f"scheduled research job {job_id!r} was not found")
    now = int(time.time() * 1000)
    payload = {
        "proposal_id": f"srp_{uuid.uuid4().hex}",
        "operation": "cancel",
        "status": "pending",
        "session_id": session_id,
        "created_at": now,
        "expires_at": now + _TTL_MS,
        "job_id": job_id,
        "job": public_job(job),
    }
    _write(_path(payload["proposal_id"]), payload)
    return public_proposal(payload)


def load_proposal(proposal_id: str) -> dict[str, Any]:
    return public_proposal(_read(proposal_id))


def latest_pending_for_session(session_id: str) -> dict[str, Any] | None:
    """Return the newest pending proposal bound to one conversation."""
    directory = get_runtime_root() / "scheduled_research" / "proposals"
    if not directory.exists():
        return None
    newest: dict[str, Any] | None = None
    for path in directory.glob("srp_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if (
            payload.get("session_id") != session_id
            or payload.get("status") != "pending"
        ):
            continue
        if newest is None or int(payload.get("created_at") or 0) > int(
            newest.get("created_at") or 0
        ):
            newest = payload
    return public_proposal(newest) if newest is not None else None


def commit_proposal(proposal_id: str) -> dict[str, Any]:
    with _LOCK:
        payload = _read(proposal_id)
        if payload.get("status") == "committed":
            return public_proposal(payload)
        if payload.get("status") != "pending":
            raise ProposalError(f"proposal is {payload.get('status')}")
        if int(payload.get("expires_at") or 0) < int(time.time() * 1000):
            payload["status"] = "expired"
            _write(_path(proposal_id), payload)
            raise ProposalError("proposal has expired")
        runtime = scheduler_status()
        if not runtime["executable"]:
            raise ProposalError(
                "scheduled research executor is not enabled and running"
            )

        store = default_store()
        if payload["operation"] == "create":
            from src.scheduled_research.models import ScheduledResearchJob

            job = ScheduledResearchJob.from_dict(payload["internal_job"])
            if job.protect_pdf:
                from src.scheduled_research.service import email_pdf_password_configured

                if not email_pdf_password_configured():
                    raise ProposalError("PDF protection requested but no PDF password is configured")
            store.upsert(job)
            payload["committed_job_id"] = job.id
        elif payload["operation"] == "cancel":
            if not store.delete(payload["job_id"]):
                raise ProposalError("scheduled research job no longer exists")
            payload["committed_job_id"] = payload["job_id"]
        else:
            raise ProposalError("unsupported proposal operation")
        payload["status"] = "committed"
        payload["committed_at"] = int(time.time() * 1000)
        _write(_path(proposal_id), payload)
        return public_proposal(payload)


def discard_proposal(proposal_id: str) -> dict[str, Any]:
    with _LOCK:
        payload = _read(proposal_id)
        if payload.get("status") == "pending":
            payload["status"] = "discarded"
            _write(_path(proposal_id), payload)
        return public_proposal(payload)
