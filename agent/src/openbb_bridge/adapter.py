"""Core adapter bridging OpenBB Workspace ``/v1/query`` to Vibe-Trading.

The :class:`OpenBBQueryAdapter` is responsible for:

* creating one **ephemeral** Vibe-Trading session per ``/v1/query`` request and
  replaying the full history the request carried into it;
* injecting workspace context (explicit context items, widget metadata,
  dashboard info) into the user's message;
* triggering the Vibe-Trading ``AgentLoop`` via ``SessionService.send_message``;
* consuming the session event bus and translating each event into OpenBB SSE
  objects until the underlying attempt completes or fails.

Why a fresh session per request: ``openbb_ai.models.QueryRequest`` carries no
conversation / thread identifier (verified against openbb-ai 2.1.0 — its fields
are ``messages``, ``context``, ``widgets``, ``urls``, ``api_keys``,
``force_web_search``, ``timezone``, ``workspace_state``, ``workspace_options``,
``tools``), and OpenBB's contract is explicitly stateless with the whole history
resupplied every turn. Any server-side identity would therefore have to be
derived from message *content*, which collides across unrelated conversations
(two chats opening with "hello" would share one session and leak history into
each other). Deriving nothing and replaying the supplied history instead keeps
conversations isolated by construction.

The adapter never mutates Vibe-Trading's core components; it only orchestrates
their public API.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, List, Optional

from openbb_ai.helpers import message_chunk, reasoning_step

from src.session.models import Message

from .context_injector import WorkspaceContextInjector
from .event_mapper import SSEEventMapper

logger = logging.getLogger("openbb_bridge")

# Roles as used by OpenBB Workspace messages (``openbb_ai.models.RoleEnum`` is a
# str-enum, so plain string comparison is exact).
_ROLE_HUMAN = "human"
_ROLE_AI = "ai"

# OpenBB role -> Vibe-Trading role for history replay. ``tool`` messages are not
# replayed as turns; their payload is folded into the context prefix instead.
_ROLE_TO_VIBE = {_ROLE_HUMAN: "user", _ROLE_AI: "assistant"}

_TERMINAL_EVENTS = {"attempt.completed", "attempt.failed", "attempt.cancelled"}

# Session titles surface in the Vibe-Trading UI; keep them short but identifiable.
_TITLE_MAX_CHARS = 48


class OpenBBQueryAdapter:
    """Adapt an OpenBB ``QueryRequest`` onto the Vibe-Trading agent."""

    def __init__(
        self,
        session_service: Any,
        context_injector: Optional[WorkspaceContextInjector] = None,
        event_mapper: Optional[SSEEventMapper] = None,
    ) -> None:
        """Bind the adapter to a session service.

        Args:
            session_service: The ``SessionService`` instance driving the agent.
            context_injector: Optional injector override; a default is built when
                omitted.
            event_mapper: Optional event mapper override; a default is built when
                omitted.
        """
        self.session_service = session_service
        self.context_injector = context_injector or WorkspaceContextInjector()
        self.event_mapper = event_mapper or SSEEventMapper()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def handle_query(self, request: Any) -> AsyncGenerator[Any, None]:
        """Yield ``openbb_ai`` SSE objects for an OpenBB ``QueryRequest``.

        Args:
            request: The parsed ``openbb_ai.models.QueryRequest``.

        Yields:
            ``openbb_ai`` SSE objects (message chunks and reasoning steps).
        """
        user_message = self._extract_last_human_message(request)

        if not user_message or not self._should_execute(request):
            yield reasoning_step(
                message="Waiting for user input.",
                event_type="INFO",
            )
            return

        session_id = self._create_ephemeral_session(user_message)
        self._replay_history(session_id, request)

        enriched = self.context_injector.inject(request, user_message)

        try:
            result = await self.session_service.send_message(session_id, enriched)
        except Exception as exc:
            logger.error("Failed to dispatch message to Vibe-Trading: %s", exc)
            yield reasoning_step(
                message=f"Failed to start the agent: {exc}",
                event_type="ERROR",
            )
            yield message_chunk(text=f"Sorry, the agent could not be started: {exc}")
            return

        attempt_id = result.get("attempt_id")
        try:
            async for sse in self._consume_events(session_id, attempt_id):
                yield sse
        finally:
            # The session stays on disk for auditing, but nothing will ever
            # reconnect to this one-shot stream — drop its in-memory replay
            # buffer so a long-lived server does not accumulate one buffer per
            # Workspace turn.
            self.session_service.event_bus.clear(session_id)

    # ------------------------------------------------------------------
    # Event consumption
    # ------------------------------------------------------------------
    async def _consume_events(
        self, session_id: str, attempt_id: Optional[str]
    ) -> AsyncGenerator[Any, None]:
        """Translate session-bus events into OpenBB SSE objects until terminal.

        Args:
            session_id: The ephemeral session being streamed.
            attempt_id: The attempt this request started, used to ignore
                stragglers.

        Yields:
            ``openbb_ai`` SSE objects.
        """
        saw_text = False
        async for event in self.session_service.event_bus.subscribe(session_id):
            event_type = event.event_type
            data = event.data or {}

            if event_type == "heartbeat":
                continue

            ev_attempt = data.get("attempt_id")
            if attempt_id and ev_attempt and ev_attempt != attempt_id:
                continue

            if event_type == "text_delta" and data.get("delta"):
                saw_text = True

            for sse in self.event_mapper.map(event_type, data):
                yield sse

            if event_type in _TERMINAL_EVENTS and (
                not attempt_id or ev_attempt == attempt_id
            ):
                async for sse in self._finalize(event_type, data, saw_text):
                    yield sse
                break

    async def _finalize(
        self, event_type: str, data: dict, saw_text: bool
    ) -> AsyncGenerator[Any, None]:
        """Emit any closing summary / error after the attempt terminates.

        Args:
            event_type: The terminal event type.
            data: The terminal event payload.
            saw_text: Whether any answer text was already streamed.

        Yields:
            ``openbb_ai`` SSE objects.
        """
        if event_type == "attempt.failed":
            error = data.get("error") or "The agent run failed."
            yield reasoning_step(message=f"Run failed: {error}", event_type="ERROR")
            if not saw_text:
                yield message_chunk(text=f"The agent run failed: {error}")
            return

        if event_type == "attempt.cancelled":
            # A stop is terminal too; without this the stream would keep
            # emitting heartbeats until the client gave up.
            yield reasoning_step(message="Run cancelled.", event_type="WARNING")
            if not saw_text:
                yield message_chunk(text="The agent run was cancelled.")
            return

        # attempt.completed: only send the summary if nothing was streamed.
        if not saw_text:
            summary = data.get("summary") or ""
            if summary:
                yield message_chunk(text=summary)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def _create_ephemeral_session(self, user_message: str) -> str:
        """Create a one-shot session for a single OpenBB request.

        Args:
            user_message: The question being asked, used for a readable title.

        Returns:
            The new session's id.
        """
        title = user_message.strip().replace("\n", " ")[:_TITLE_MAX_CHARS]
        session = self.session_service.create_session(
            title=f"OpenBB Workspace: {title}" if title else "OpenBB Workspace"
        )
        logger.info("OpenBB request -> ephemeral Vibe session %s", session.session_id)
        return session.session_id

    def _replay_history(self, session_id: str, request: Any) -> None:
        """Persist the history OpenBB supplied into the ephemeral session.

        Every message preceding the final human message is replayed so the agent
        sees the whole conversation. The final human message is dispatched
        separately via ``send_message`` so it is the turn that triggers the loop.

        Writes go straight to the store rather than through
        ``SessionService.send_message``: a ``user``-role send would start a
        second attempt, and indexing one-shot replayed turns would pollute
        cross-session search with duplicates of the Workspace transcript.

        Args:
            session_id: The ephemeral session to seed.
            request: The parsed ``QueryRequest``.
        """
        messages = self._get_messages(request)
        if not messages:
            return

        last_human_idx = self._last_human_index(messages)
        prior = messages[:last_human_idx] if last_human_idx is not None else messages

        replayed = 0
        for message in prior:
            vibe_role = _ROLE_TO_VIBE.get(getattr(message, "role", None))
            if vibe_role is None:
                continue  # tool messages are folded into the context prefix
            content = self._message_text(message)
            if not content:
                continue
            try:
                self.session_service.store.append_message(
                    Message(session_id=session_id, role=vibe_role, content=content)
                )
                replayed += 1
            except Exception as exc:
                logger.warning("Failed to replay history message: %s", exc)

        if replayed:
            logger.info(
                "Replayed %d supplied message(s) into session %s", replayed, session_id
            )

    # ------------------------------------------------------------------
    # Request parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_messages(request: Any) -> List[Any]:
        """Return the request's message list, or an empty list."""
        return getattr(request, "messages", None) or []

    @classmethod
    def _extract_last_human_message(cls, request: Any) -> str:
        """Return the text of the most recent human message, or ``""``."""
        messages = cls._get_messages(request)
        for message in reversed(messages):
            if getattr(message, "role", None) == _ROLE_HUMAN:
                return cls._message_text(message)
        return ""

    @classmethod
    def _should_execute(cls, request: Any) -> bool:
        """Return whether the most recent message is from the human."""
        messages = cls._get_messages(request)
        if not messages:
            return False
        return getattr(messages[-1], "role", None) == _ROLE_HUMAN

    @classmethod
    def _last_human_index(cls, messages: List[Any]) -> Optional[int]:
        """Return the index of the last human message, or ``None``."""
        for idx in range(len(messages) - 1, -1, -1):
            if getattr(messages[idx], "role", None) == _ROLE_HUMAN:
                return idx
        return None

    @staticmethod
    def _message_text(message: Any) -> str:
        """Extract plain text from an OpenBB message of any supported shape.

        Args:
            message: An ``LlmClientMessage``-like object or mapping.

        Returns:
            The message's textual content, or ``""`` when there is none.
        """
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        if isinstance(content, str):
            return content
        # Function-call content or other structured payloads: stringify safely.
        if content is None:
            return ""
        return str(content)
