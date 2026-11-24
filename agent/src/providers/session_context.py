"""Per-conversation LLM session identity."""

from __future__ import annotations

from contextvars import ContextVar, Token

_LLM_SESSION_ID: ContextVar[str] = ContextVar("vibe_llm_session_id", default="")


def bind_llm_session_id(session_id: str | None) -> Token[str]:
    """Bind ``session_id`` as the active LLM session in the current context."""
    return _LLM_SESSION_ID.set((session_id or "").strip())


def reset_llm_session_id(token: Token[str]) -> None:
    """Restore the binding that was active before :func:`bind_llm_session_id`."""
    _LLM_SESSION_ID.reset(token)


def current_llm_session_id() -> str:
    """Return the active LLM session id, or ``""`` outside a bound run."""
    return _LLM_SESSION_ID.get()
