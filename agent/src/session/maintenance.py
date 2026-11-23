"""Compact a session on request using its selected model."""

from __future__ import annotations

from src.product.tool_policy import ToolPolicy

import asyncio
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack
from pathlib import Path

from src.session.models import Session
from src.session.runtime import SessionRuntime


async def compact_history(
    session: Session, focus: str, *, runtime_for: Callable[[str], SessionRuntime], runs_dir: Path,
    compact: Callable, policy: ToolPolicy,
):
    """Run manual compaction through a recorder with the session's selected model."""
    from src.session.model_selection import chat_llm_for_session
    from src.session.runtime import TurnRecorder

    llm = chat_llm_for_session(session.config, policy=policy)
    async with AsyncExitStack() as resources:
        resources.push_async_callback(llm.aclose)
        compact_id = f"compact-{uuid.uuid4().hex[:12]}"
        runtime = runtime_for(session.session_id)
        snapshot = getattr(llm, "runtime_snapshot", None)
        provider = getattr(snapshot, "provider", None)
        model = getattr(snapshot, "configured_model", None)
        history, history_seqs, user_history = runtime.replay_history(provider=provider, model=model)
        if not history:
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
        resources.callback(recorder.close)
        run_dir = runs_dir / "compactions" / compact_id
        run_dir.mkdir(parents=True, exist_ok=True)
        messages = [{"role": "system", "content": ""}, *history]
        await asyncio.to_thread(compact, llm, runtime, recorder, messages, run_dir, focus.strip()[:2000])
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
