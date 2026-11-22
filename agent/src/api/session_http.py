"""Shared HTTP session response types and lookup semantics."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field


class ModelSelectionResponse(BaseModel):
    """The model a session's next turn asks for, and where that choice comes from."""
    session_id: str
    source: str = Field(..., description="'session' (its own selection) or 'inherited' (server settings)")
    provider: Optional[str] = None
    model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    error: Optional[str] = Field(None, description="Why a stored selection is unreadable")
    turn_running: bool = False
    applies_from: str = Field("next_turn", description="A change never reaches a turn already running")


class SessionResponse(BaseModel):
    """Session record."""
    session_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    last_attempt_id: Optional[str] = None
    forked_from_session_id: Optional[str] = None
    forked_from_turn_id: Optional[str] = None


def existing_session(host, session_id: str):
    """Return (service, session) or raise 404."""
    svc = host._get_session_service()
    if not svc:
        raise HTTPException(status_code=501, detail="Session runtime not enabled")
    session = svc.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return svc, session


def model_selection_response(svc, session) -> ModelSelectionResponse:
    from src.session.model_selection import effective_model_selection

    attempt = (
        svc.store.get_attempt(session.session_id, session.last_attempt_id)
        if session.last_attempt_id else None
    )
    attempt_status = getattr(attempt.status, "value", attempt.status) if attempt else None
    return ModelSelectionResponse(
        session_id=session.session_id,
        # A pending attempt already holds the session it was sent with.
        turn_running=attempt_status in {"pending", "running"},
        **effective_model_selection(session),
    )
