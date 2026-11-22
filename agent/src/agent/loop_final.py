"""Final-answer policy for the composed agent turn loop."""

from __future__ import annotations

import logging
from typing import Any

from src.agent.tool_results import _looks_like_tool_call_syntax
from src.agent.tuning import _goal_max_continuations
from src.goal.context import format_goal_continuation_prompt, goal_needs_continuation, goal_progress_tuple

logger = logging.getLogger(__name__)
MAX_CONSECUTIVE_EMPTY_RESPONSE_SKIPS = 1


class FinalAnswerHandler:
    """Own forced-text retries, empty responses, and goal continuation."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def handle(self, state: Any) -> str:
        """Handle a response with no executable tool batch."""
        response = state.response
        if response.has_tool_calls and not state.final_answer_retry:
            return "tools"
        state.final_content = response.content or ""
        if not state.final_content and not response.has_tool_calls:
            if self._empty_response(state):
                return "continue"
        state.consecutive_empty_responses = 0
        if state.final_answer_retry and response.has_tool_calls:
            return self._syntax_retry(state)
        if _looks_like_tool_call_syntax(state.final_content):
            return self._syntax_retry(state)
        if self._continue_goal(state):
            return "continue"
        self._release(state)
        return "done"

    def _empty_response(self, state: Any) -> bool:
        """Nudge once after an empty completion."""
        state.empty_model_response_iter = state.iteration
        state.trace.write({
            "type": "empty_model_response",
            "iter": state.current_iter,
            "provider": self.owner._llm_runtime.provider,
            "model": getattr(self.owner.llm, "model_name", None),
        })
        if state.consecutive_empty_responses >= MAX_CONSECUTIVE_EMPTY_RESPONSE_SKIPS:
            return False
        state.consecutive_empty_responses += 1
        self.owner._inject(
            state.messages,
            "<system>Your previous response was empty (no text, no tool calls). Respond again with either your next tool call or your final plain-text answer.</system>",
        )
        return True

    def _syntax_retry(self, state: Any) -> str:
        """Withhold tool syntax and grant one bounded plain-text retry."""
        if state.stream.streamed_chars:
            self.owner._emit("stream_reset", {"iter": state.current_iter, "reason": "tool_call_syntax_in_answer"})
        state.trace.write({"type": "tool_call_syntax_in_answer", "iter": state.current_iter})
        self.owner._append_assistant(
            state.messages, {"role": "assistant", "content": state.final_content}, phase="commentary"
        )
        self.owner._inject(
            state.messages,
            "<system>Your previous response was not released: it contained tool-call syntax even though tool calling is unavailable now. Provide the final answer as plain prose only, with no XML/DSML tags.</system>",
        )
        state.final_content = ""
        if state.iteration <= self.owner.max_iterations:
            state.final_answer_retry_pending = state.iteration == self.owner.max_iterations
            return "continue"
        state.final_content = "My final response could not be delivered: it contained tool-call syntax instead of a plain-text answer. Please ask me to continue."
        self.owner._released_fallback = True
        self.owner._released_fallback_reason = "final answer withheld: it contained tool-call syntax on the forced-text iteration"
        self.owner._emit("text_delta", {"delta": state.final_content, "iter": state.current_iter, "phase": "final"})
        self._release(state, stream_finish=False)
        return "done"

    def _continue_goal(self, state: Any) -> bool:
        """Continue an active goal only when progress and budget allow it."""
        if state.final_answer_retry or not state.active_goal_id or not state.session_id:
            return False
        maximum = _goal_max_continuations()
        if maximum <= 0:
            return False
        try:
            if state.goal_store is None:
                from src.goal import GoalStore
                state.goal_store = GoalStore()
            snapshot = state.goal_store.get_goal_snapshot(state.active_goal_id)
            if not snapshot or not goal_needs_continuation(snapshot):
                return False
        except Exception as exc:
            logger.debug("Goal continuation check skipped: %s", exc)
            return False
        progress = goal_progress_tuple(snapshot)
        no_new_progress = state.goal_last_progress is not None and progress <= state.goal_last_progress
        if state.goal_continuations >= maximum or (no_new_progress and state.goal_continuations > 0):
            state.trace.write({"type": "goal_continuation_suppressed", "iter": state.current_iter, "goal_id": state.active_goal_id, "progress": progress, "continuations": state.goal_continuations})
            return False
        state.trace.write({"type": "goal_intermediate_answer", "iter": state.current_iter, "goal_id": state.active_goal_id, "progress": progress, "content": state.final_content})
        self.owner._append_assistant(state.messages, {"role": "assistant", "content": state.final_content}, phase="commentary")
        self.owner._inject(state.messages, format_goal_continuation_prompt(snapshot, previous_answer=state.final_content))
        state.goal_last_progress = progress
        state.goal_continuations += 1
        return True

    def _release(self, state: Any, *, stream_finish: bool = True) -> None:
        """Record and release the final answer."""
        if stream_finish:
            state.stream.finish(state.final_content)
        self.owner._record_final_answer(state.final_content)
