"""Conversation-thread and queued-input state for :class:`AgentRuntime`."""

from __future__ import annotations

from typing import Any


class ConversationState:
    """Own the durable thread sink and messages delivered during a turn."""

    def __init__(self, thread: Any = None, queued_inputs: Any = None) -> None:
        self.thread = thread
        self.queued_inputs = queued_inputs
        self.turn_messages = None
        self.dependency_lists = ()

    def records_into(self, messages: list) -> bool:
        """Return whether an appended message belongs to the durable turn."""
        if self.thread is None:
            return False
        return messages is self.turn_messages or any(messages is batch for batch in self.dependency_lists)

    def inject(self, messages: list, content: str) -> None:
        """Append a loop-authored message and record it."""
        message = {"role": "user", "content": content}
        messages.append(message)
        if self.records_into(messages):
            self.thread.inject(message)

    def append_assistant(
        self, messages: list, message: dict[str, Any], *, phase: str
    ) -> None:
        """Append a model response and record it."""
        messages.append(message)
        if self.records_into(messages):
            self.thread.assistant(message, phase=phase)

    def record_final_answer(self, content: str) -> None:
        """Record the released answer as a final assistant item."""
        if self.thread is not None and content:
            self.thread.assistant({"role": "assistant", "content": content}, phase="final")

    def sync_state(self, env) -> None:
        """Persist workspace, identity, and loaded-tool state."""
        if self.thread is None:
            return
        snapshot: dict[str, Any] = {
            "workspace": env.memory.run_dir,
            "workspace_dir": env.memory.session_workspace,
        }
        if env.identity is not None:
            snapshot["identity"] = env.identity.export_state()
        exposed_names = getattr(env.registry, "exposed_names", None)
        if callable(exposed_names):
            snapshot["loaded_tools"] = exposed_names()
        self.thread.state(snapshot)

    def end_turn(self, env, usage) -> None:
        """Flush usage and the final state snapshot."""
        if self.thread is None:
            return
        self.thread.usage = dict(usage.get("totals") or {})
        self.sync_state(env)

    def take_queued_inputs(self, messages: list, *, cancelled: bool, budget_spent: bool) -> None:
        """Deliver pending user messages at the safe model-call boundary."""
        if (
            self.queued_inputs is None
            or cancelled
            or budget_spent
        ):
            return
        messages.extend(self.queued_inputs.deliver())
