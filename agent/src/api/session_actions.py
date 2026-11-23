"""Session creation, model changes, message submission and cancellation."""

from __future__ import annotations



import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.goal_routes import _get_goal_store
from src.api.session_http import ModelSelectionResponse, SessionResponse, existing_session, model_selection_response
from src.session.input_rules import MAX_MESSAGE_CHARS
from src.session.pending_inputs import PendingInputLimitError
from src.session.models import SessionBusyError


logger = logging.getLogger(__name__)


# ============================================================================
# Web composer prompt wrappers
# ============================================================================
# Web chat creates the session with the raw prompt (``prompt.trim().slice(0, 50)``
# in frontend/src/pages/Agent.tsx) but POSTs a wrapped first message. These
# mirror frontend/src/lib/chatPrompt.ts (SWARM_PROMPT_PREFIX),
# frontend/src/lib/attachments.ts (the ``[Uploaded files: ...]`` envelope) and
# Agent.tsx (GOAL_KICKOFF_PREFIX), and are stripped the way ``toDisplayPrompt``
# strips them, so the auto-title route can tell a wrapped first prompt from a
# genuine manual rename.
_SWARM_PROMPT_PREFIX = (
    "[Swarm Team Mode] Use the swarm tool to assemble the best specialist team "
    "for this task. Auto-select the most appropriate preset.\n\n"
)
_GOAL_KICKOFF_PREFIX = "\n".join(
    [
        "Start working on this research goal now.",
        "Keep it research-only, use available tools when evidence is needed, "
        "add concrete evidence to the goal ledger, and keep going until the "
        "goal is complete, blocked, waiting for user input, or budget-limited.",
        "",
        "Goal: ",
    ]
)
_ATTACHMENTS_OPEN = "[Uploaded files: "
_ATTACHMENTS_CLOSE = "]\n\n"
_LEGACY_ATTACHMENT = re.compile(r"^\[Uploaded file: (.+), path: [^\n]*\]\n\n")


def _strip_prompt_wrappers(content: str) -> str:
    """Return the prompt the user typed, without the composer's envelopes."""
    unwrapped = False
    if content.startswith(_ATTACHMENTS_OPEN):
        close = content.find(_ATTACHMENTS_CLOSE, len(_ATTACHMENTS_OPEN))
        if close >= 0:
            try:
                payload = json.loads(content[len(_ATTACHMENTS_OPEN):close])
            except ValueError:
                payload = None  # Malformed envelopes stay verbatim.
            if isinstance(payload, list) and any(
                isinstance(item, dict) and isinstance(item.get("filename"), str)
                and item.get("filename")
                for item in payload
            ):
                content = content[close + len(_ATTACHMENTS_CLOSE):]
                unwrapped = True
    if not unwrapped:
        legacy = _LEGACY_ATTACHMENT.match(content)
        if legacy:
            content = content[legacy.end():]
    if content.startswith(_SWARM_PROMPT_PREFIX):
        content = content[len(_SWARM_PROMPT_PREFIX):]
    if content.startswith(_GOAL_KICKOFF_PREFIX):
        content = content[len(_GOAL_KICKOFF_PREFIX):]
    return content


class CreateSessionRequest(BaseModel):
    """Create session request body."""
    title: str = Field("", description="Session title")
    config: Optional[Dict[str, Any]] = Field(None, description="Session config")


class ForkSessionRequest(BaseModel):
    """Fork a session through a completed turn."""
    turn_id: str = Field(..., min_length=1)
    title: str = Field("", max_length=200)


class CompactSessionRequest(BaseModel):
    """Request a user-triggered context compaction."""
    focus: str = Field("", max_length=2000)


class SendMessageRequest(BaseModel):
    """Send an interactive research prompt."""
    content: str = Field(..., description="Research prompt", min_length=1, max_length=MAX_MESSAGE_CHARS)


class UpdateSessionRequest(BaseModel):
    """Session update fields."""
    title: Optional[str] = None


async def _validated_model_selection(raw: Any):
    """Validate a caller-written selection off the event loop, or raise 400."""
    from src.providers.selection import ModelSelectionError, validate_model_selection

    try:
        selection, _config = await asyncio.to_thread(validate_model_selection, raw)
    except ModelSelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return selection


async def _validated_session_config(config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Hold a model selection written at creation to the same rules as PUT."""
    from src.providers.selection import SESSION_CONFIG_KEY

    if not config or SESSION_CONFIG_KEY not in config:
        return config
    checked = {key: value for key, value in config.items() if key != SESSION_CONFIG_KEY}
    if config[SESSION_CONFIG_KEY] is not None:
        selection = await _validated_model_selection(config[SESSION_CONFIG_KEY])
        checked[SESSION_CONFIG_KEY] = selection.to_dict()
    return checked


def register_session_submissions(app: FastAPI, host) -> None:
    """Register POSTs that precede the reads at the same paths for HTTP 405 handling."""
    @app.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
    async def create_session(
        request: CreateSessionRequest,
        principal=Depends(host.require_auth),
    ):
        """Create a chat session.

        The authenticated principal is recorded as the session owner. Under the
        shared-key and loopback auth modes that principal is not attributable to
        a named human -- it carries ``attributable=False`` and must not be read
        as an identity. Recording it anyway is still worth doing: it captures
        HOW the session was authorised, which is the part that becomes an
        identity once an identity provider is wired in.
        """
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        config = await _validated_session_config(request.config)
        session = svc.create_session(
            title=request.title, config=config, owner=principal
        )
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

    @app.post("/sessions/{session_id}/messages", dependencies=[Depends(host.require_auth)])
    async def send_message(session_id: str, payload: SendMessageRequest, http_request: Request):
        """Send a user message and start the agent loop (natural language strategy).

        A session whose turn is running accepts the message too: it waits and
        joins that turn after its current tool batch, or starts the next turn.
        That answer is HTTP 202 with ``status: "queued"``, ``input_id``,
        ``position`` and the ``attempt_id`` of the turn that will take it. The
        same validation and size limit apply either way.
        """
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        try:
            result = await svc.send_message(
                session_id=session_id,
                content=payload.content,
                include_shell_tools=host._shell_tools_enabled_for_request(http_request, policy=svc.policy),
                queue_if_busy=True,
            )
        except (SessionBusyError, PendingInputLimitError) as exc:
            # Must precede ValueError-style handling and stay distinct from 404:
            # the session exists, it is shutting down or its queue is full.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        if result.get("status") == "queued":
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=result)
        return result


def register_session_actions(app: FastAPI, host) -> None:
    """Register actions with the host authentication dependencies."""
    @app.post(
        "/sessions/{session_id}/fork",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(host.require_auth)],
    )
    async def fork_session(session_id: str, request: ForkSessionRequest):
        """Create an independent conversation copied through one turn."""
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        try:
            session = svc.fork_session(
                session_id, request.turn_id, title=request.title.strip()
            )
        except SessionBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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

    @app.delete("/sessions/{session_id}", dependencies=[Depends(host.require_auth)])
    async def delete_session(session_id: str):
        """Delete a session."""
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        try:
            deleted = svc.delete_session(session_id)
        except SessionBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        _get_goal_store().delete_session_goals(session_id)
        return {"status": "deleted", "session_id": session_id}

    @app.patch("/sessions/{session_id}", dependencies=[Depends(host.require_auth)])
    async def update_session(session_id: str, req: UpdateSessionRequest):
        """Update session fields (e.g. title)."""
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        if req.title is not None:
            session.title = req.title
        session.updated_at = datetime.now(timezone.utc).isoformat()
        svc.update_session(session)
        return {"status": "updated", "session_id": session_id}

    @app.put(
        "/sessions/{session_id}/model",
        response_model=ModelSelectionResponse,
        dependencies=[Depends(host.require_auth)],
    )
    async def set_session_model(session_id: str, payload: Dict[str, Any]):
        """Select one of the server's configured providers and a model for this session.

        Accepts only ``provider``, ``model`` and ``reasoning_effort``; endpoints,
        keys and headers always come from the server's settings. A turn that is
        already running keeps its model; the selection applies from the next turn.
        """
        from src.session.model_selection import set_model_selection

        host._validate_path_param(session_id, "session_id")
        existing_session(host, session_id)
        selection = await _validated_model_selection(payload)
        svc, session = existing_session(host, session_id)
        set_model_selection(session, selection)
        session.updated_at = datetime.now(timezone.utc).isoformat()
        svc.update_session(session)
        return model_selection_response(svc, session)

    @app.delete(
        "/sessions/{session_id}/model",
        response_model=ModelSelectionResponse,
        dependencies=[Depends(host.require_auth)],
    )
    async def clear_session_model(session_id: str):
        """Clear the session's selection so its next turn uses the server's settings."""
        from src.session.model_selection import set_model_selection

        host._validate_path_param(session_id, "session_id")
        svc, session = existing_session(host, session_id)
        set_model_selection(session, None)
        session.updated_at = datetime.now(timezone.utc).isoformat()
        svc.update_session(session)
        return model_selection_response(svc, session)

    @app.post("/sessions/{session_id}/title/auto", dependencies=[Depends(host.require_auth)])
    async def auto_title_session(session_id: str):
        """Summarize the first exchange into a short LLM-generated title.

        Never clobbers a manual rename: only rewrites when the current title
        is empty or still the auto-set first-prompt prefix from create time.
        """
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        messages = svc.get_messages(session_id, limit=6)
        first_user = next(
            (m for m in messages if m.role == "user" and (m.content or "").strip()), None
        )
        if first_user is None:
            raise HTTPException(status_code=409, detail="Session has no user message to summarize")

        current = (session.title or "").strip()
        auto_prefix = _strip_prompt_wrappers(first_user.content).strip()[:50].strip()
        if current and current != auto_prefix:
            return {"status": "kept", "session_id": session_id, "title": current}

        first_assistant = next(
            (m for m in messages if m.role == "assistant" and (m.content or "").strip()), None
        )
        excerpt = f"User: {first_user.content.strip()[:600]}"
        if first_assistant:
            excerpt += f"\nAssistant: {first_assistant.content.strip()[:600]}"
        prompt = (
            "Write a session title for the conversation below: at most 8 words "
            "(or 16 CJK characters), in the same language as the user's message, "
            "no quotes, no trailing punctuation. Reply with the title only.\n\n"
            + excerpt
        )

        def _generate() -> str:
            from src.providers.chat import ChatLLM

            llm = ChatLLM(policy=svc.policy)
            try:
                response = llm.chat([{"role": "user", "content": prompt}], timeout=30)
                return (getattr(response, "content", "") or "").strip()
            finally:
                llm.close()

        try:
            raw = await asyncio.to_thread(_generate)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"title generation failed: {exc}")

        title = raw.splitlines()[0].strip().strip("\"'“”「」『』").strip() if raw else ""
        chars = list(title)
        if len(chars) > 40:
            title = "".join(chars[:40])
        if not title:
            raise HTTPException(status_code=502, detail="empty title from model")

        # Generation yields to other requests. Reload their persisted metadata
        # and recheck a manual rename before this synchronous commit section.
        session = svc.store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        current = (session.title or "").strip()
        if current and current != auto_prefix:
            return {"status": "kept", "session_id": session_id, "title": current}

        session.title = title
        session.updated_at = datetime.now(timezone.utc).isoformat()
        svc.update_session(session)
        return {"status": "updated", "session_id": session_id, "title": title}

    @app.post("/sessions/{session_id}/compact", dependencies=[Depends(host.require_auth)])
    async def compact_session(
        session_id: str, request: Optional[CompactSessionRequest] = None
    ):
        """Compact replayed session history when no turn or queue is active."""
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        try:
            return await svc.compact_session(session_id, request.focus if request else "")
        except SessionBusyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            if "not found" in str(exc).lower():
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.delete("/sessions/{session_id}/pending-inputs/{input_id}", dependencies=[Depends(host.require_auth)])
    async def discard_pending_input(session_id: str, input_id: str):
        """Discard a waiting message before any turn takes it."""
        host._validate_path_param(session_id, "session_id")
        host._validate_path_param(input_id, "input_id")
        svc, _ = existing_session(host, session_id)
        removed = svc.discard_pending_input(session_id, input_id)
        if removed is None:
            raise HTTPException(
                status_code=404,
                detail=f"No waiting message {input_id} in session {session_id}",
            )
        return {"status": "discarded", "session_id": session_id, "input": removed}

    @app.post("/sessions/{session_id}/cancel", dependencies=[Depends(host.require_auth)])
    async def cancel_session(session_id: str):
        """Cancel the in-flight agent loop for this session."""
        host._validate_path_param(session_id, "session_id")
        svc = host._get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        cancelled = svc.cancel_current(session_id)
        # A stop keeps the messages queued behind it; say which are waiting.
        pending = svc.list_pending_inputs(session_id)
        body: Dict[str, Any] = {"status": "cancelled" if cancelled else "no_active_loop"}
        if pending:
            body["pending_inputs"] = pending
        return body
