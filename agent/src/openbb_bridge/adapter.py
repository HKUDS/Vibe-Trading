"""Core adapter bridging OpenBB Workspace ``/v1/query`` to Vibe-Trading.

The :class:`OpenBBQueryAdapter` is responsible for:

* deriving a stable ``conversation_id`` from an OpenBB ``QueryRequest`` and
  mapping it onto a Vibe-Trading ``session_id`` (1:1, in-memory);
* injecting widget / dashboard context into the user's message;
* triggering the Vibe-Trading ``AgentLoop`` via ``SessionService.send_message``;
* consuming the session event bus and translating each event into OpenBB SSE
  objects until the underlying attempt completes or fails.

The adapter never mutates Vibe-Trading's core components; it only orchestrates
their public API.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, AsyncGenerator, List, Optional, Tuple

from openbb_ai.helpers import message_chunk, reasoning_step

from src.session.models import Message

from .context_injector import WidgetContextInjector
from .event_mapper import SSEEventMapper
from .models import SessionMapping

logger = logging.getLogger("openbb_bridge")

# Roles as used by OpenBB Workspace messages.
_ROLE_HUMAN = "human"
_ROLE_AI = "ai"

# OpenBB role -> Vibe-Trading role for history seeding.
_ROLE_TO_VIBE = {_ROLE_HUMAN: "user", _ROLE_AI: "assistant"}

_TERMINAL_EVENTS = {"attempt.completed", "attempt.failed"}


class OpenBBQueryAdapter:
    """Adapt an OpenBB ``QueryRequest`` onto the Vibe-Trading agent."""

    def __init__(
        self,
        session_service: Any,
        context_injector: Optional[WidgetContextInjector] = None,
        event_mapper: Optional[SSEEventMapper] = None,
    ) -> None:
        self.session_service = session_service
        self.context_injector = context_injector or WidgetContextInjector()
        self.event_mapper = event_mapper or SSEEventMapper()
        self._session_map: dict[str, SessionMapping] = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def handle_query(self, request: Any) -> AsyncGenerator[Any, None]:
        """Yield ``openbb_ai`` SSE objects for an OpenBB ``QueryRequest``."""
        user_message = self._extract_last_human_message(request)

        if not user_message or not self._should_execute(request):
            yield reasoning_step(
                message="Waiting for user input.",
                event_type="INFO",
            )
            return

        conversation_id = self._extract_conversation_id(request)
        session_id, is_new = self._resolve_session(conversation_id)

        if is_new:
            self._seed_history(session_id, request)

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
        async for sse in self._consume_events(session_id, attempt_id):
            yield sse

    # ------------------------------------------------------------------
    # Event consumption
    # ------------------------------------------------------------------
    async def _consume_events(
        self, session_id: str, attempt_id: Optional[str]
    ) -> AsyncGenerator[Any, None]:
        saw_text = False
        async for event in self.session_service.event_bus.subscribe(session_id):
            event_type = event.event_type
            data = event.data or {}

            if event_type == "heartbeat":
                continue

            # In a reused session, ignore stragglers from other attempts.
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
        """Emit any closing summary / error after the attempt terminates."""
        if event_type == "attempt.failed":
            error = data.get("error") or "The agent run failed."
            yield reasoning_step(message=f"Run failed: {error}", event_type="ERROR")
            if not saw_text:
                yield message_chunk(text=f"The agent run failed: {error}")
            return

        # attempt.completed: only send the summary if nothing was streamed.
        if not saw_text:
            summary = data.get("summary") or ""
            if summary:
                yield message_chunk(text=summary)

    # ------------------------------------------------------------------
    # Session mapping
    # ------------------------------------------------------------------
    def _resolve_session(self, conversation_id: str) -> Tuple[str, bool]:
        """Return ``(session_id, is_new)`` for a conversation id."""
        mapping = self._session_map.get(conversation_id)
        if mapping is not None:
            existing = self.session_service.get_session(mapping.session_id)
            if existing is not None:
                return mapping.session_id, False
            # Session was deleted underneath us; fall through and recreate.
            self._session_map.pop(conversation_id, None)

        session = self.session_service.create_session(
            title=f"OpenBB Workspace {conversation_id[:8]}"
        )
        self._session_map[conversation_id] = SessionMapping(
            conversation_id=conversation_id,
            session_id=session.session_id,
        )
        logger.info(
            "Mapped OpenBB conversation %s -> Vibe session %s",
            conversation_id,
            session.session_id,
        )
        return session.session_id, True

    def _seed_history(self, session_id: str, request: Any) -> None:
        """Persist prior OpenBB turns into a freshly created session.

        Only messages preceding the final human message are seeded. The final
        human message is dispatched separately via ``send_message`` so it
        triggers the agent loop.
        """
        messages = self._get_messages(request)
        if not messages:
            return

        last_human_idx = self._last_human_index(messages)
        prior = messages[:last_human_idx] if last_human_idx is not None else messages

        seeded = 0
        for message in prior:
            role = getattr(message, "role", None)
            vibe_role = _ROLE_TO_VIBE.get(role)
            if vibe_role is None:
                continue  # skip tool messages / unknown roles
            content = self._message_text(message)
            if not content:
                continue
            try:
                self.session_service.store.append_message(
                    Message(session_id=session_id, role=vibe_role, content=content)
                )
                seeded += 1
            except Exception as exc:
                logger.warning("Failed to seed history message: %s", exc)

        if seeded:
            logger.info("Seeded %d prior message(s) into session %s", seeded, session_id)

    # ------------------------------------------------------------------
    # Request parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get_messages(request: Any) -> List[Any]:
        return getattr(request, "messages", None) or []

    @classmethod
    def _extract_conversation_id(cls, request: Any) -> str:
        """Derive a stable conversation id from the first message content.

        OpenBB ``QueryRequest`` carries no explicit conversation identifier, so
        we hash the first message's textual content, which is stable for the
        lifetime of a conversation.
        """
        messages = cls._get_messages(request)
        if messages:
            first_text = cls._message_text(messages[0])
            if first_text:
                return hashlib.sha256(first_text.encode("utf-8")).hexdigest()[:16]
        return "default"

    @classmethod
    def _extract_last_human_message(cls, request: Any) -> str:
        messages = cls._get_messages(request)
        for message in reversed(messages):
            if getattr(message, "role", None) == _ROLE_HUMAN:
                return cls._message_text(message)
        return ""

    @classmethod
    def _should_execute(cls, request: Any) -> bool:
        """Only run when the most recent message is from the human."""
        messages = cls._get_messages(request)
        if not messages:
            return False
        return getattr(messages[-1], "role", None) == _ROLE_HUMAN

    @classmethod
    def _last_human_index(cls, messages: List[Any]) -> Optional[int]:
        for idx in range(len(messages) - 1, -1, -1):
            if getattr(messages[idx], "role", None) == _ROLE_HUMAN:
                return idx
        return None

    @staticmethod
    def _message_text(message: Any) -> str:
        """Extract plain text from an OpenBB message of any supported shape."""
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
        if isinstance(content, str):
            return content
        # Function-call content or other structured payloads: stringify safely.
        if content is None:
            return ""
        return str(content)
