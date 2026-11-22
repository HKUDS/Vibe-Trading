"""Conversation-thread and queued-input state for :class:`AgentLoop`."""

from __future__ import annotations

from typing import Any


class ConversationState:
    """Own the durable thread sink and messages delivered during a turn."""

    def __init__(self, thread: Any = None, queued_inputs: Any = None) -> None:
        self.thread = thread
        self.queued_inputs = queued_inputs

    def records_into(self, messages: list, turn_messages: list | None) -> bool:
        """Return whether an appended message belongs to the durable turn."""
        if self.thread is None:
            return False
        return messages is turn_messages

    def inject(self, messages: list, content: str, turn_messages: list | None) -> None:
        """Append a loop-authored message and record it."""
        message = {"role": "user", "content": content}
        messages.append(message)
        if self.records_into(messages, turn_messages):
            self.thread.inject(message)

    def append_assistant(
        self, messages: list, message: dict[str, Any], *, phase: str, turn_messages: list | None
    ) -> None:
        """Append a model response and record it."""
        messages.append(message)
        if self.records_into(messages, turn_messages):
            self.thread.assistant(message, phase=phase)

    def record_final_answer(self, content: str) -> None:
        """Record the released answer as a final assistant item."""
        if self.thread is not None and content:
            self.thread.assistant({"role": "assistant", "content": content}, phase="final")

    def sync_state(self, owner: Any) -> None:
        """Persist workspace, identity, and loaded-tool state."""
        if self.thread is None:
            return
        snapshot: dict[str, Any] = {
            "workspace": owner.memory.run_dir,
            "workspace_dir": owner.memory.session_workspace,
        }
        if owner._identity is not None:
            snapshot["identity"] = owner._identity.export_state()
        exposed_names = getattr(owner.registry, "exposed_names", None)
        if callable(exposed_names):
            snapshot["loaded_tools"] = exposed_names()
        self.thread.state(snapshot)

    def end_turn(self, owner: Any) -> None:
        """Flush usage and the final state snapshot."""
        if self.thread is None:
            return
        self.thread.usage = dict(owner._llm_usage_summary.get("totals") or {})
        self.sync_state(owner)

    def take_queued_inputs(self, messages: list, trace: Any, current_iter: int, owner: Any) -> None:
        """Deliver pending user messages at the safe model-call boundary."""
        if (
            self.queued_inputs is None
            or owner._cancel_event.is_set()
            or owner._budget_stop_reason is not None
        ):
            return
        for index, message in enumerate(self.queued_inputs.deliver(), start=1):
            messages.append(message)
            trace.write_text_entry(
                {"type": "message", "iter": current_iter, "role": "user", "queued": True},
                field="content",
                value=message.get("content") or "",
                offload_kind=f"queued-user-message-{current_iter}-{index}",
            )
