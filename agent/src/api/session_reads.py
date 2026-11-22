"""Session reads, thread paging and server-sent events."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.session_http import ModelSelectionResponse, SessionResponse, existing_session, model_selection_response
from src.session.events import display_page


logger = logging.getLogger(__name__)


class MessageResponse(BaseModel):
    """Stored chat message."""
    message_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    linked_attempt_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ThreadPageResponse(BaseModel):
    """One page of a session's conversation thread, as display items."""
    session_id: str
    items: List[Dict[str, Any]]
    has_more: bool
    cursor: int = Field(..., description="Highest seq in the thread; pass it as the event stream's cursor to continue live")


# Upper bound on one page of the thread endpoint.
MAX_THREAD_PAGE = 500


_PROPOSAL_TOOL_NAME = "propose_mandate_profiles"
_PROPOSAL_ID_RE = re.compile(r'"proposal_id"\s*:\s*"(mp_[0-9a-f]{32})"')
_SCHEDULED_PROPOSAL_TOOL_NAME = "scheduled_research"
_SCHEDULED_PROPOSAL_ID_RE = re.compile(
    r'"proposal_id"\s*:\s*"(srp_[0-9a-f]{32})"'
)


def _load_full_proposal(proposal_id: str) -> Optional[Dict[str, Any]]:
    """Reload a persisted mandate proposal by id, broker-agnostic."""
    try:
        from src.live.paths import live_root

        for proposal_path in live_root().glob(f"*/proposals/{proposal_id}.json"):
            try:
                data = json.loads(proposal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("type") == "mandate.proposal":
                return data
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("mandate.proposal reload failed for %s", proposal_id, exc_info=True)
    return None


def _mandate_proposal_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a mandate.proposal SSE frame from a propose-tool tool_result."""
    data = getattr(event, "data", None)
    if (
        not isinstance(data, dict)
        or getattr(event, "event_type", None) != "item.completed"
        or data.get("kind") not in {"tool.completed", "tool.failed"}
    ):
        return None
    item = data.get("item") if isinstance(data.get("item"), dict) else {}
    if item.get("name") != _PROPOSAL_TOOL_NAME or item.get("status") != "ok":
        return None
    match = _PROPOSAL_ID_RE.search(str(item.get("content") or ""))
    if not match:
        return None
    proposal = _load_full_proposal(match.group(1))
    if proposal is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="mandate.proposal",
        data=proposal,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()


def _scheduled_proposal_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a deterministic scheduled-research confirmation SSE frame."""
    data = getattr(event, "data", None)
    if (
        not isinstance(data, dict)
        or getattr(event, "event_type", None) != "item.completed"
        or data.get("kind") not in {"tool.completed", "tool.failed"}
    ):
        return None
    item = data.get("item") if isinstance(data.get("item"), dict) else {}
    if item.get("name") != _SCHEDULED_PROPOSAL_TOOL_NAME or item.get("status") != "ok":
        return None
    match = _SCHEDULED_PROPOSAL_ID_RE.search(str(item.get("content") or ""))
    if not match:
        return None
    try:
        from src.scheduled_research.proposals import load_proposal

        proposal = load_proposal(match.group(1))
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("scheduled proposal reload failed", exc_info=True)
        return None
    from src.session.events import SSEEvent

    return SSEEvent(
        event_type="scheduled_research.proposal",
        data=proposal,
        session_id=getattr(event, "session_id", "") or "",
    ).to_sse()


_LIVE_ACTION_ID_RE = re.compile(r'"audit_id"\s*:\s*"(la_[0-9a-zA-Z]+)"')


def _load_live_action_record(audit_id: str) -> Optional[Dict[str, Any]]:
    """Reload a redacted live-action record from the ledger by audit_id."""
    try:
        from src.live.paths import live_root

        ledger = live_root() / "audit.jsonl"
        if not ledger.exists():
            return None
        for line in reversed(ledger.read_text(encoding="utf-8").splitlines()):
            if audit_id not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("audit_id") == audit_id:
                return record
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("live.action reload failed for %s", audit_id, exc_info=True)
    return None


def _live_action_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a live.action SSE frame from an order-guard tool_result."""
    data = getattr(event, "data", None)
    if (
        not isinstance(data, dict)
        or getattr(event, "event_type", None) != "item.completed"
        or data.get("kind") not in {"tool.completed", "tool.failed"}
    ):
        return None
    item = data.get("item") if isinstance(data.get("item"), dict) else {}
    preview = str(item.get("content") or "")
    if '"live_action"' not in preview:
        return None
    match = _LIVE_ACTION_ID_RE.search(preview)
    if not match:
        return None
    record = _load_live_action_record(match.group(1))
    if record is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="live.action",
        data=record,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()


def register_session_reads(app: FastAPI, host) -> None:
    """Register reads with the host authentication dependencies."""
    @app.get("/sessions", response_model=List[SessionResponse], dependencies=[Depends(host.require_auth)])
    async def list_sessions(limit: int = Query(50, ge=1, le=200)):
        """List sessions."""
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        sessions = svc.list_sessions(limit=limit)
        return [
            SessionResponse(
                session_id=s.session_id,
                title=s.title,
                status=s.status.value,
                created_at=s.created_at,
                updated_at=s.updated_at,
                last_attempt_id=s.last_attempt_id,
                forked_from_session_id=s.forked_from_session_id,
                forked_from_turn_id=s.forked_from_turn_id,
            )
            for s in sessions
        ]

    @app.get("/sessions/{session_id}", response_model=SessionResponse, dependencies=[Depends(host.require_auth)])
    async def get_session(session_id: str):
        """Get one session by id."""
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return SessionResponse(
            session_id=session.session_id,
            title=session.title,
            status=session.status.value,
            created_at=session.created_at,
            updated_at=session.updated_at,
            last_attempt_id=session.last_attempt_id,
            forked_from_session_id=session.forked_from_session_id,
            forked_from_turn_id=session.forked_from_turn_id,
        )

    @app.get(
        "/sessions/{session_id}/model",
        response_model=ModelSelectionResponse,
        dependencies=[Depends(host.require_auth)],
    )
    async def get_session_model(session_id: str):
        """Return the model the session's next turn asks for."""
        host._validate_path_param(session_id, "session_id")
        svc, session = existing_session(host, session_id)
        return model_selection_response(svc, session)

    @app.get("/sessions/{session_id}/pending-inputs", dependencies=[Depends(host.require_auth)])
    async def list_pending_inputs(session_id: str):
        """List the messages waiting to join a session's conversation, oldest first."""
        host._validate_path_param(session_id, "session_id")
        svc, _ = existing_session(host, session_id)
        return {"session_id": session_id, "items": svc.list_pending_inputs(session_id)}

    @app.get("/sessions/{session_id}/messages", response_model=List[MessageResponse], dependencies=[Depends(host.require_auth)])
    async def get_messages(session_id: str, limit: int = Query(100, ge=1, le=1000)):
        """List messages for a session."""
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        messages = svc.get_messages(session_id, limit=limit)
        return [
            MessageResponse(
                message_id=m.message_id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                linked_attempt_id=m.linked_attempt_id,
                metadata=m.metadata if m.metadata else None,
            )
            for m in messages
        ]

    @app.get(
        "/sessions/{session_id}/thread",
        response_model=ThreadPageResponse,
        dependencies=[Depends(host.require_auth)],
    )
    async def get_thread(
        session_id: str,
        after: int = Query(0, ge=0, description="Return items with seq greater than this"),
        before: Optional[int] = Query(None, ge=1, description="Return the newest items with seq below this"),
        limit: int = Query(200, ge=1, le=MAX_THREAD_PAGE),
    ):
        """Return a session's thread as display items, paged by seq.

        The items are what ``thread.jsonl`` records, in the client view of
        ``display_item``: tool results as delivered (redacted), tool-call
        arguments redacted, and no model-only envelopes or state records.
        Pre-thread sessions are migrated on first access, so this route uses
        the same canonical log for archived and newly recorded sessions.
        """
        host._validate_path_param(session_id, "session_id")
        svc, _session = existing_session(host, session_id)
        items = await asyncio.to_thread(svc.store.thread_log(session_id).read)
        page = display_page(items, after=after, before=before, limit=limit)
        return ThreadPageResponse(session_id=session_id, **page)

    @app.get("/sessions/{session_id}/events", dependencies=[Depends(host.require_event_stream_auth)])
    async def session_events(
        session_id: str,
        request: Request,
        last_event_id: Optional[str] = Query(None, alias="Last-Event-ID"),
        replay: Optional[str] = Query(None),
        cursor: Optional[int] = Query(None, ge=0),
    ):
        """SSE stream for the durable item and run event vocabulary.

        The thread sequence is the only resume cursor. A durable
        ``Last-Event-ID`` such as ``item-42`` is converted to the same cursor,
        and completed items are replayed from ``thread.jsonl``.
        """
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        header_id = request.headers.get("Last-Event-ID")
        event_id = header_id or last_event_id
        replay_active = (replay or "").lower() == "active"
        replay_all = False
        running_attempt = None
        if replay_active and not event_id and session.last_attempt_id:
            attempt = svc.store.get_attempt(session_id, session.last_attempt_id)
            attempt_status = getattr(attempt.status, "value", attempt.status) if attempt else None
            replay_all = attempt_status == "running"
            if replay_all:
                running_attempt = attempt

        async def event_generator():
            async for event in svc.thread_events.stream(
                session_id,
                cursor=cursor,
                last_event_id=event_id,
                replay_all=replay_all,
                active_turn_id=running_attempt.attempt_id if running_attempt is not None else None,
            ):
                if await request.is_disconnected():
                    break
                yield event.to_sse()
                relayed = _mandate_proposal_frame_from_tool_result(event)
                if relayed is not None:
                    yield relayed
                scheduled_relay = _scheduled_proposal_frame_from_tool_result(event)
                if scheduled_relay is not None:
                    yield scheduled_relay
                live_action = _live_action_frame_from_tool_result(event)
                if live_action is not None:
                    yield live_action

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
