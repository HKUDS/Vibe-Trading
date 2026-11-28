"""Per-conversation LLM session identity."""

from __future__ import annotations

from contextvars import ContextVar, Token

_LLM_SESSION_ID: ContextVar[str] = ContextVar("vibe_llm_session_id", default="")


def bind_llm_session_id(session_id: str | None) -> Token[str]:
    """Bind ``session_id`` as the active LLM session in the current context.

    Args:
        session_id: Vibe session ID. Empty, whitespace-only, or None clears the binding.

    Returns:
        Token to pass to reset_llm_session_id when the run ends.
    """
    return _LLM_SESSION_ID.set((session_id or "").strip())


def reset_llm_session_id(token: Token[str]) -> None:
    """Restore the binding that was active before :func:`bind_llm_session_id`.

    Args:
        token: Token returned by bind_llm_session_id in the current context.
    """
    _LLM_SESSION_ID.reset(token)


def current_llm_session_id() -> str:
    """Read the active LLM session ID.

    Returns:
        The bound session ID, or an empty string outside a bound run.
    """
    return _LLM_SESSION_ID.get()
