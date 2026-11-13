"""Persist research context for retries and explicit continuation, never replay tools."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)
FILENAME = "checkpoint.json"


def context_key(initial_messages: list[dict]) -> str:
    """Bind a checkpoint to the research instructions and supplied evidence."""
    initial = [dict(message) for message in initial_messages]
    initial[0]["content"] = initial[0]["content"].split("## Current Date & Time", 1)[0]
    return hashlib.sha256(json.dumps(initial, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(artifact_dir: Path, *, key: str, messages: list[dict], last_content: str, run_dir: Path) -> None:
    """Atomically retain context, including calls whose result is still unknown."""
    payload = {
        "version": 1,
        "key": key,
        "messages": messages,
        "last_content": last_content,
        "run_dir": str(run_dir.resolve()),
    }
    path = artifact_dir / FILENAME
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        logger.warning("Could not persist worker checkpoint in %s", artifact_dir, exc_info=True)


def restore(artifact_dir: Path, *, key: str, system: dict, run_dir: Path) -> tuple[list[dict], str] | None:
    """Restore compatible context; unknown tool outcomes are disclosed, not executed.

    Args:
        artifact_dir: This worker's private artifact directory.
        key: Fingerprint of current instructions, task and upstream evidence.
        system: Fresh system message, including the current timestamp.
        run_dir: Current run root for re-homed artifact references.

    Returns:
        Conversation and last partial text, or None when no compatible state exists.
    """
    try:
        data = json.loads((artifact_dir / FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("key") != key:
        return None
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages or any(not isinstance(m, dict) for m in messages):
        return None
    old_root = data.get("run_dir")

    def rehome(value):
        if isinstance(value, str) and isinstance(old_root, str) and old_root:
            return value.replace(old_root, str(run_dir.resolve()))
        if isinstance(value, list):
            return [rehome(item) for item in value]
        if isinstance(value, dict):
            return {name: rehome(item) for name, item in value.items()}
        return value

    messages = rehome(messages)
    system = rehome(system)
    messages[0] = system
    # Checkpoints can be captured while a tool is in flight. Complete the wire
    # protocol with an explicit unknown outcome, without resubmitting the call.
    pending = {}
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("id"):
                    pending[call["id"]] = (call.get("function") or {}).get("name", "tool")
        elif message.get("role") == "tool":
            pending.pop(message.get("tool_call_id"), None)
    for call_id, name in pending.items():
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": json.dumps(
                    {
                        "status": "error",
                        "error_code": "interrupted_tool_result",
                        "message": "Execution outcome was not recorded. Inspect existing artifacts/state before retrying; do not assume a mutating call failed.",
                    }
                ),
            }
        )
    last_content = str(data.get("last_content") or "")
    if isinstance(old_root, str) and old_root:
        last_content = last_content.replace(old_root, str(run_dir.resolve()))
    if last_content and not any(m.get("role") == "assistant" and m.get("content") == last_content for m in messages):
        messages.append({"role": "assistant", "content": last_content})
    messages.append(
        {
            "role": "user",
            "content": "Continue the interrupted task from the saved work. Reuse available observations and files; finish the remaining request. The prior response was incomplete.",
        }
    )
    return messages, last_content
