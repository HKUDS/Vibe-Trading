"""A session's own model selection: storage, effective view and LLM construction.

A session may name ``{provider, model, reasoning_effort}`` under
``Session.config["model_selection"]``; without one it inherits the server's
settings unchanged. Each attempt builds its own client from an immutable
settings copy, so concurrent sessions never see each other's selection and the
process environment is never written.
"""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy

from pathlib import Path
from typing import Any, Mapping, Optional

from src.providers.selection import (
    SESSION_CONFIG_KEY,
    ModelSelection,
    ModelSelectionError,
    configured_selection,
    parse_model_selection,
    validate_model_selection,
)
from src.session.models import Session


def set_model_selection(session: Session, selection: Optional[ModelSelection]) -> None:
    """Store a validated selection on ``session``, or clear it with None.

    The caller validates the selection first (:func:`validate_model_selection`)
    and persists the session afterwards. A running attempt keeps the client it
    started with; the change applies from the next turn.

    Args:
        session: Session to change in place.
        selection: Validated selection, or None to inherit the server's settings.
    """
    if selection is None:
        session.config.pop(SESSION_CONFIG_KEY, None)
    else:
        session.config[SESSION_CONFIG_KEY] = selection.to_dict()


def effective_model_selection(session: Session) -> dict[str, Any]:
    """Describe the model the session's next turn will ask for.

    Args:
        session: Session to describe.

    Returns:
        ``provider`` / ``model`` / ``reasoning_effort`` plus ``source``:
        ``"session"`` for the session's own selection, ``"inherited"`` for the
        server's settings. A stored selection that no longer parses is
        reported with ``error`` instead of being replaced by the default.
    """
    stored = session.config.get(SESSION_CONFIG_KEY)
    if stored is None:
        return {"source": "inherited", **configured_selection().to_dict()}
    try:
        return {"source": "session", **parse_model_selection(stored).to_dict()}
    except ModelSelectionError as exc:
        return {"source": "session", "provider": None, "model": None,
                "reasoning_effort": None, "error": str(exc)}


def chat_llm_for_session(config: Optional[Mapping[str, Any]], *, policy: ToolPolicy) -> Any:
    """Build the chat client for one attempt of a session.

    Args:
        config: The session's config, as stored.

    Returns:
        A ``ChatLLM`` on the server's settings when the session has no
        selection, else one on the selection, re-validated now so a provider
        whose credentials were removed fails the turn instead of falling back.

    Raises:
        ModelSelectionError: The stored selection is no longer usable.
    """
    from src.providers import chat as chat_module

    stored = (config or {}).get(SESSION_CONFIG_KEY)
    if stored is None:
        return chat_module.ChatLLM(policy=policy)
    _selection, provider_config = validate_model_selection(stored)
    return chat_module.ChatLLM(policy=policy, snapshot=provider_config, selection="session")


def chat_llm_for_stored_session(sessions_dir: Path | str, session_id: str, *, policy: ToolPolicy) -> Any:
    """Build the chat client for a session read from a session store.

    Args:
        sessions_dir: Root of the session store.
        session_id: Session id; empty for a run that belongs to no session.

    Returns:
        The client :func:`chat_llm_for_session` builds for that session.
    """
    config = None
    if session_id:
        from src.session.store import SessionStore

        session = SessionStore(base_dir=Path(sessions_dir)).get_session(session_id)
        config = session.config if session is not None else None
    return chat_llm_for_session(config, policy=policy)


def unavailable_selection_result(error: ModelSelectionError) -> dict[str, Any]:
    """Result of a CLI turn whose session-selected model cannot be used.

    The turn fails visibly instead of falling back to the server's model or
    taking the REPL down with a traceback.

    Args:
        error: Why the stored selection was refused.

    Returns:
        A failed run result naming the error and how to recover.
    """
    message = (
        f"Session model unavailable: {error}. Run /model clear to use the "
        "server's model, or configure that provider."
    )
    return {"status": "failed", "reason": message, "content": message}
