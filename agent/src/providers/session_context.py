"""Per-conversation LLM session identity.

Some relays require a stable per-conversation identifier on every request.
OpenCode Go rejects calls that lack ``x-opencode-session`` (HTTP 400
``MissingSessionID``) because it uses the id for routing and prompt caching.

The agent loop binds the active Vibe session id here for the duration of a
run; provider adapters read it at request time. A ``ContextVar`` keeps the
binding thread- and task-local, so concurrent sessions never see each other's
id and nothing has to be threaded through every LangChain call site.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

_LLM_SESSION_ID: ContextVar[str] = ContextVar("vibe_llm_session_id", default="")


def bind_llm_session_id(session_id: str | None) -> Token[str]:
    """Bind ``session_id`` as the active LLM session in the current context.

    Args:
        session_id: Vibe session id; empty or ``None`` clears the binding.

    Returns:
        Token to pass to :func:`reset_llm_session_id` when the run ends.
    """
    return _LLM_SESSION_ID.set((session_id or "").strip())


def reset_llm_session_id(token: Token[str]) -> None:
    """Restore the binding that was active before :func:`bind_llm_session_id`."""
    _LLM_SESSION_ID.reset(token)


def current_llm_session_id() -> str:
    """Return the active LLM session id, or ``""`` outside a bound run."""
    return _LLM_SESSION_ID.get()
