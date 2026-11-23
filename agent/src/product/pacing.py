"""Final-answer policy for the composed agent turn loop."""

from __future__ import annotations

import json
from typing import Any

from src.agent.tuning import _wrap_up_nudge_remaining
from src.kernel import events as vocabulary
from src.kernel.contracts import Continue, LLMResponse, Stop
from src.product.tool_results import _looks_like_tool_call_syntax

MAX_CONSECUTIVE_EMPTY_RESPONSE_SKIPS = 1


class TurnPacing:
    """Own forced-text retries, empty responses, and goal continuation."""

    manages_context = False

    def capture_interrupted_response(self, state) -> None:
        """Allow a task delivery policy to retain an interrupted draft."""

    def __init__(self, conversation, provider, llm, max_iterations, goals) -> None:
        self.conversation = conversation
        self.provider = provider
        self.llm = llm
        self.max_iterations = max_iterations
        self.goals = goals

    def handle(self, state: Any, response: LLMResponse) -> Continue | Stop:
        """Handle a response with no executable tool batch."""
        state.final_content = response.content or ""
        if not state.final_content and not response.has_tool_calls:
            if self._empty_response(state):
                return Continue.NEXT
        state.consecutive_empty_responses = 0
        if state.final_answer_retry and response.has_tool_calls:
            return self._syntax_retry(state)
        if _looks_like_tool_call_syntax(state.final_content):
            return self._syntax_retry(state)
        if self.goals.continue_goal(state, self.conversation):
            return Continue.NEXT
        self._release(state)
        return Stop("final_answer" if state.final_content else "empty_response")

    def _empty_response(self, state: Any) -> bool:
        """Nudge once after an empty completion."""
        state.empty_model_response_iter = state.iteration
        state.trace.write({
            "type": "empty_model_response",
            "iter": state.current_iter,
            "provider": self.provider,
            "model": getattr(self.llm, "model_name", None),
        })
        if state.consecutive_empty_responses >= MAX_CONSECUTIVE_EMPTY_RESPONSE_SKIPS:
            return False
        state.consecutive_empty_responses += 1
        self.conversation.inject(
            state.view.messages,
            "<system>Your previous response was empty (no text, no tool calls). Respond again with either your next tool call or your final plain-text answer.</system>",
        )
        return True

    def _syntax_retry(self, state: Any) -> Continue | Stop:
        """Withhold tool syntax and grant one bounded plain-text retry."""
        if state.stream.streamed_chars:
            state.stream.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.TEXT_RESET, "iter": state.current_iter, "reason": "tool_call_syntax_in_answer"})
        state.trace.write({"type": "tool_call_syntax_in_answer", "iter": state.current_iter})
        self.conversation.append_assistant(
            state.view.messages, {"role": "assistant", "content": state.final_content}, phase="commentary"
        )
        self.conversation.inject(
            state.view.messages,
            "<system>Your previous response was not released: it contained tool-call syntax even though tool calling is unavailable now. Provide the final answer as plain prose only, with no XML/DSML tags.</system>",
        )
        state.final_content = ""
        if state.iteration <= self.max_iterations:
            return Continue.FINAL_ANSWER if state.iteration == self.max_iterations else Continue.NEXT
        state.final_content = "My final response could not be delivered: it contained tool-call syntax instead of a plain-text answer. Please ask me to continue."
        state.released_fallback = True
        state.released_fallback_reason = "final answer withheld: it contained tool-call syntax on the forced-text iteration"
        state.stream.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.TEXT_DELTA, "delta": state.final_content, "iter": state.current_iter, "phase": "final"})
        self._release(state, stream_finish=False)
        return Stop("syntax_retry_exhausted")

    def _release(self, state: Any, *, stream_finish: bool = True) -> None:
        """Record and release the final answer."""
        if stream_finish:
            state.stream.finish(state.final_content)
        self.conversation.record_final_answer(state.final_content)

    def write_directives(self, state, writes) -> None:
        """Add wrap-up and pending-write directives at their original points."""
        remaining = _wrap_up_nudge_remaining()
        wrap_at = max(2, self.max_iterations - remaining) if remaining > 0 else None
        if wrap_at is not None and state.iteration == wrap_at and 1 < state.iteration < self.max_iterations:
            count = self.max_iterations - state.iteration
            content = f"[SYSTEM] You have {count} iterations remaining out of {self.max_iterations}. Wrap up your work now: finish any outstanding file writes or data updates that are part of your task FIRST, while tools are still available for a few more iterations. Do not start new analysis or re-verify data you already hold. Then provide your final answer as plain text; if your task was to update a file, state that it is done and where."
            directive = writes.pending(state.user_message, state.run_started_wall)
            if directive:
                content += "\n\n" + directive
                state.trace.write({"type": "pending_write_directive", "iter": state.current_iter})
            self.conversation.inject(state.view.messages, content)
        if state.iteration == self.max_iterations - 1:
            directive = writes.pending(state.user_message, state.run_started_wall)
            if directive:
                state.trace.write({"type": "pending_write_directive", "iter": state.current_iter})
                self.conversation.inject(state.view.messages, f"<system>{directive}</system>")

    def after_tools(self, state, response, progress, cancel) -> bool:
        """Return whether to stop after publishing a no-progress answer."""
        state.no_commentary_rounds = 0 if response.content and response.content.strip() else state.no_commentary_rounds + 1
        if state.mid_turn_nudge_rounds > 0 and state.no_commentary_rounds >= state.mid_turn_nudge_rounds and self._has_successful_data_result(state.view.messages):
            self.conversation.inject(state.view.messages, "<system>Evidence is already in hand. Answer the user's request now using the available evidence. Do not start extra analysis unless the user requested it.</system>")
            state.trace.write({"type": "mid_turn_nudge", "iter": state.current_iter, "no_commentary_rounds": state.no_commentary_rounds})
            state.no_commentary_rounds = 0
        if not cancel.is_set() and progress.finish_iteration():
            state.final_content = progress.recovery_message()
            state.no_progress_reason = "no_progress: " + state.final_content
            state.trace.write({"type": "no_progress", "iter": state.current_iter, "iterations_without_progress": progress.stalled_iterations})
            state.stream.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.TEXT_DELTA, "delta": state.final_content, "iter": state.current_iter, "phase": "final"})
            self.conversation.record_final_answer(state.final_content)
            return True
        return False

    @staticmethod
    def _has_successful_data_result(messages: list[dict[str, Any]]) -> bool:
        """Return whether a successful data tool result is visible."""
        names = {"get_market_data", "technical_indicators", "get_stock_profile", "get_fundamentals", "get_financial_statements", "get_options_chain", "news_search", "web_search", "backtest"}
        for message in messages:
            if message.get("role") != "tool" or message.get("name") not in names:
                continue
            try:
                payload = json.loads(message.get("content", ""))
            except (TypeError, ValueError):
                payload = None
            if isinstance(payload, dict) and (payload.get("ok") is False or payload.get("success") is False):
                continue
            return True
        return False
