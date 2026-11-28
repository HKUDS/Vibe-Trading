"""Store session model selection and resolve it at the next turn."""

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

    Args:
        session: Session whose configuration is updated.
        selection: Validated model selection, or None to clear the override.
    """
    if selection is None:
        session.config.pop(SESSION_CONFIG_KEY, None)
    else:
        session.config[SESSION_CONFIG_KEY] = selection.to_dict()


def effective_model_selection(session: Session) -> dict[str, Any]:
    """Describe the model the session's next turn will ask for.

    Args:
        session: Session whose model override, if any, is inspected.

    Returns:
        Selection fields and their source. An invalid stored override includes an error and null
        selection fields.
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
        config: Optional session config containing a stored model override.
        policy: Tool policy passed to the chat client.

    Returns:
        A client bound to the validated session model or the configured default.
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
        sessions_dir: Root of the persisted session store.
        session_id: Session ID to look up. An empty ID uses the configured default.
        policy: Tool policy passed to the chat client.

    Returns:
        A client using the stored session override when present, otherwise the configured default.
    """
    config = None
    if session_id:
        from src.session.store import SessionStore

        session = SessionStore(base_dir=Path(sessions_dir)).get_session(session_id)
        config = session.config if session is not None else None
    return chat_llm_for_session(config, policy=policy)


def unavailable_selection_result(error: ModelSelectionError) -> dict[str, Any]:
    """Result of a CLI turn whose session-selected model cannot be used.

    Args:
        error: Validation error explaining why the selected model is unavailable.

    Returns:
        A failed turn result with the same explanatory message as its reason and content.
    """
    message = (
        f"Session model unavailable: {error}. Run /model clear to use the "
        "server's model, or configure that provider."
    )
    return {"status": "failed", "reason": message, "content": message}
