"""Conversation-thread and queued-input state for :class:`AgentRuntime`."""

from __future__ import annotations

from typing import Any


class ConversationState:
    """Own the durable thread sink and messages delivered during a turn.

    Args:
        thread: Optional durable recorder for this turn.
        queued_inputs: Optional source of user messages queued during execution.
    """

    def __init__(self, thread: Any = None, queued_inputs: Any = None) -> None:
        self.thread = thread
        self.queued_inputs = queued_inputs
        self.turn_messages = None
        self.delta: list[dict[str, Any]] = []
        self.dependency_lists = ()

    def records_into(self, messages: list) -> bool:
        """Check whether appending to a message list should update the durable turn.

        Args:
            messages: Destination list, checked by object identity.

        Returns:
            True if a recorder exists and the list is the turn or one of its dependency batches.
        """
        if self.thread is None:
            return False
        return messages is self.turn_messages or any(messages is batch for batch in self.dependency_lists)

    def append(self, messages: list, message: dict[str, Any]) -> None:
        """Collect model-visible additions independently of in-place compaction.

        Args:
            messages: Destination list, whose additions are copied into the delta for the active turn.
            message: Model message to append.
        """
        messages.append(message)
        if messages is self.turn_messages:
            self.delta.append(dict(message))

    def inject(self, messages: list, content: str) -> None:
        """Append a loop-authored message and record it.

        Args:
            messages: Destination list, which determines whether to write a durable item.
            content: Text to inject with the user role.
        """
        message = {"role": "user", "content": content}
        self.append(messages, message)
        if self.records_into(messages):
            self.thread.inject(message)

    def append_assistant(
        self, messages: list, message: dict[str, Any], *, phase: str
    ) -> None:
        """Append a model response and record it.

        Args:
            messages: Destination list, which determines whether to write a durable item.
            message: Assistant message, which may include tool calls.
            phase: Phase label written to the durable assistant item.
        """
        self.append(messages, message)
        if self.records_into(messages):
            self.thread.assistant(message, phase=phase)

    def record_final_answer(self, content: str) -> None:
        """Record the released answer as a final assistant item.

        Args:
            content: Released answer text. Empty text is ignored.
        """
        if content:
            message = {"role": "assistant", "content": content}
            self.delta.append(message)
            if self.thread is not None:
                self.thread.assistant(message, phase="final")

    def sync_state(self, env) -> None:
        """Persist workspace, identity, and loaded-tool state.

        Args:
            env: Tool environment supplying the current workspace, ledger, and registry.
        """
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
        """Flush usage and the final state snapshot.

        Args:
            env: Tool environment supplying the state snapshot.
            usage: Usage totals to copy into the turn recorder.
        """
        if self.thread is None:
            return
        self.thread.usage = dict(usage)
        self.sync_state(env)

    def take_queued_inputs(self, messages: list, *, cancelled: bool, budget_spent: bool) -> None:
        """Deliver pending user messages at the safe model-call boundary.

        Args:
            messages: Destination for delivered messages.
            cancelled: Whether run cancellation prevents delivery.
            budget_spent: Whether a goal stopping condition prevents delivery.
        """
        if (
            self.queued_inputs is None
            or cancelled
            or budget_spent
        ):
            return
        for message in self.queued_inputs.deliver():
            self.append(messages, message)
