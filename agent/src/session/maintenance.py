"""Fork completed conversation prefixes and compact a session on request."""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import Callable
from pathlib import Path

from src.session.models import Session, SessionBusyError
from src.session.runtime import SessionRuntime
from src.session.store import SessionStore


def fork_completed_turn(
    store: SessionStore, source_session_id: str, turn_id: str, title: str,
) -> Session:
    """Copy the canonical thread through a completed turn into an independent session."""
    source = store.get_session(source_session_id)
    if source is None:
        raise ValueError(f"Session {source_session_id} not found")
    source_items = store.thread_log(source_session_id).read()
    turn_items = [item for item in source_items if item.turn_id == turn_id]
    if not turn_items or not any(item.type == "turn_start" for item in turn_items):
        raise ValueError(f"Turn {turn_id} not found in session {source_session_id}")
    end = next((item for item in turn_items if item.type == "turn_end"), None)
    if end is None:
        raise SessionBusyError("Cannot fork from a turn that is still running")
    if end.get("status") != "completed":
        raise ValueError(f"Turn {turn_id} is not completed")
    copied = [item for item in source_items if item.seq <= end.seq]
    fork = Session(
        title=title or f"{source.title or source_session_id} (fork)",
        config=copy.deepcopy(source.config),
        owner=source.owner,
        forked_from_session_id=source_session_id,
        forked_from_turn_id=turn_id,
    )
    store.create_session(fork)
    target_log = store.thread_log(fork.session_id)
    workspace_dir = str(target_log.path.parent / "workspace")
    try:
        for item in copied:
            payload = copy.deepcopy(item.data)
            if item.type == "state":
                payload["workspace_dir"] = workspace_dir
                payload["workspace"] = workspace_dir
            target_log.append(item.type, item.turn_id, **payload)
    except BaseException:
        store.delete_session(fork.session_id)
        raise
    return fork


async def compact_history(
    session: Session, focus: str, *, runtime_for: Callable[[str], SessionRuntime], runs_dir: Path,
):
    """Run manual compaction through a recorder with the session's selected model."""
    from src.agent.runtime import AgentRuntime
    from src.product.resources.memory import WorkspaceMemory
    from src.agent.tools import ToolRegistry
    from src.session.model_selection import chat_llm_for_session
    from src.session.runtime import TurnRecorder

    llm = chat_llm_for_session(session.config)
    compact_id = f"compact-{uuid.uuid4().hex[:12]}"
    runtime = runtime_for(session.session_id)
    snapshot = getattr(llm, "runtime_snapshot", None)
    provider = getattr(snapshot, "provider", None)
    model = getattr(snapshot, "configured_model", None)
    history, history_seqs, user_history = runtime.replay_history(provider=provider, model=model)
    if not history:
        await llm.aclose()
        raise ValueError("Session has no conversation history to compact")
    recorder = TurnRecorder(
        runtime,
        compact_id,
        history,
        history_seqs,
        user_history,
        provider=provider,
        model=model,
    )
    run_dir = runs_dir / "compactions" / compact_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trace = recorder
    messages = [{"role": "system", "content": ""}, *history]
    agent = AgentRuntime(
        registry=ToolRegistry(),
        llm=llm,
        memory=WorkspaceMemory(session_workspace=str(runtime.workspace_path)),
        thread_recorder=recorder,
    )
    agent.memory.run_dir = str(run_dir)
    agent._conversation.turn_messages = messages
    try:
        await asyncio.to_thread(
            agent._context_compactor.auto_compact,
            messages,
            run_dir,
            trace,
            focus.strip()[:2000],
            0,
        )
    finally:
        recorder.close()
        await llm.aclose()
    compacted = next(
        (
            item for item in reversed(runtime.thread.read())
            if item.turn_id == compact_id and item.type == "compaction"
        ),
        None,
    )
    if compacted is None:
        raise ValueError("Conversation is too short to compact")
    return compacted
