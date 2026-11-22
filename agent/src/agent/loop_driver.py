"""Composable iteration driver for :class:`AgentLoop`."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.agent.context_compact import _attach_tool_call_thought_signatures, _context_collapse
from src.agent.context_budget import is_context_overflow
from src.agent.loop_compaction import estimate_tokens
from src.agent.tool_loading import request_definitions
from src.agent.loop_final import FinalAnswerHandler
from src.agent.loop_streaming import TurnStream
from src.providers.messages import repair_provider_messages
from src.agent.loop_state import TurnState
from src.agent.tuning import (
    _heartbeat_interval_s,
    _llm_timeout_seconds,
    _override,
    _reasoning_delta_min_interval_s,
    _stream_retry_backoff_s,
    _stream_retry_max_delay_s,
    _token_threshold,
    _wrap_up_nudge_remaining,
)
from src.providers.chat import ProviderStreamError, reported_model_source
from src.providers.content_filter import CONTENT_FILTER_SKIP_MESSAGE, MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS

logger = logging.getLogger(__name__)


class IterationDriver:
    """Drive bounded iterations and delegate each concern to a named step."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.final_answers = FinalAnswerHandler(owner)

    def run(self, state: TurnState) -> None:
        """Run research iterations until a final answer or stop condition."""
        while state.iteration < self.owner.max_iterations or state.final_answer_retry_pending:
            state.final_answer_retry = state.final_answer_retry_pending
            state.final_answer_retry_pending = False
            if self._prepare_iteration(state):
                break
            if self._request_response(state):
                break
            if state.response is None:
                continue
            if self._handle_response(state):
                break

    def _prepare_iteration(self, state: TurnState) -> bool:
        """Apply budgets, compaction, background results, and directives."""
        owner = self.owner
        owner._context_compactor.tool_schema_tokens = estimate_tokens(request_definitions(owner.registry))
        if owner._budget_stop_reason is not None or owner._cancel_event.is_set():
            if owner._cancel_event.is_set():
                state.trace.write({"type": "cancelled", "iter": owner._run_iteration + 1})
            return True
        state.iteration += 1
        owner._run_iteration += 1
        state.current_iter = owner._run_iteration
        notifs = owner._background_manager.drain_notifications()
        if notifs:
            text = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
            owner._inject(state.messages, f"<background-results>\n{text}\n</background-results>\n\n<system>Continue processing with the background results above.</system>")
        self._compact(state)
        if owner._cancel_event.is_set() or owner._budget_stop_reason is not None:
            return True
        self._write_directives(state)
        return False

    def _compact(self, state: TurnState) -> None:
        """Run the configured estimate or model-window compaction path."""
        owner = self.owner
        if _override("TOKEN_THRESHOLD") is not None:
            tokens = estimate_tokens(state.messages)
            if tokens > int(_token_threshold() * 0.5):
                owner._microcompact_and_unblock(state.messages, state.trace, state.iteration, preserve_tool_call_ids=owner._readonly_replay_visibility_pending)
                tokens = estimate_tokens(state.messages)
            if tokens > int(_token_threshold() * 0.7):
                before = json.loads(json.dumps(state.messages, default=str, ensure_ascii=False))
                _context_collapse(state.messages, preserve_tool_call_ids=owner._readonly_replay_visibility_pending)
                owner._record_compaction_layer(state.messages, 2, before)
                tokens = estimate_tokens(state.messages)
            if tokens > _token_threshold():
                decision = owner._run_hook("PreCompact", {"session_id": state.session_id, "iteration": state.current_iter, "prompt_tokens": tokens})
                if decision is None or not decision.denied:
                    owner._auto_compact(state.messages, state.run_dir, state.trace, iteration=state.current_iter)
        else:
            owner._compact_to_budget(state.messages, state.run_dir, state.trace, state.iteration, state.current_iter)

    def _write_directives(self, state: TurnState) -> None:
        """Add wrap-up and pending-write directives at their original points."""
        owner = self.owner
        remaining = _wrap_up_nudge_remaining()
        wrap_at = max(2, owner.max_iterations - remaining) if remaining > 0 else None
        if wrap_at is not None and state.iteration == wrap_at and 1 < state.iteration < owner.max_iterations:
            count = owner.max_iterations - state.iteration
            content = f"[SYSTEM] You have {count} iterations remaining out of {owner.max_iterations}. Wrap up your work now: finish any outstanding file writes or data updates that are part of your task FIRST, while tools are still available for a few more iterations. Do not start new analysis or re-verify data you already hold. Then provide your final answer as plain text; if your task was to update a file, state that it is done and where."
            directive = owner._pending_write_directive(state.user_message, state.run_started_wall)
            if directive:
                content += "\n\n" + directive
                state.trace.write({"type": "pending_write_directive", "iter": state.current_iter})
            owner._inject(state.messages, content)
        if state.iteration == owner.max_iterations - 1:
            directive = owner._pending_write_directive(state.user_message, state.run_started_wall)
            if directive:
                state.trace.write({"type": "pending_write_directive", "iter": state.current_iter})
                owner._inject(state.messages, f"<system>{directive}</system>")

    def _request_response(self, state: TurnState) -> bool:
        """Request one provider response with bounded retry handling."""
        owner = self.owner
        state.stream = TurnStream(emit=owner._emit, iteration=state.current_iter, heartbeat_interval=_heartbeat_interval_s, reasoning_interval=_reasoning_delta_min_interval_s)
        state.tool_defs = None if state.iteration >= owner.max_iterations else request_definitions(owner.registry)
        if state.iteration >= owner.max_iterations:
            state.trace.write({"type": "forced_text_only", "iter": state.current_iter})
        timeout = _llm_timeout_seconds()
        try:
            state.response = self._stream_request(state, timeout)
        except ProviderStreamError as exc:
            if not exc.retryable and not is_context_overflow(str(exc)):
                raise
            context_overflow = is_context_overflow(str(exc))
            if context_overflow:
                owner._recover_context_overflow(exc, state.messages, state.run_dir, state.trace, state.iteration, state.current_iter)
                delay = 0.0
            else:
                state.stream_failure_streak += 1
                delay = min(exc.retry_after_s, _stream_retry_max_delay_s()) if exc.retry_after_s is not None else _stream_retry_backoff_s(state.stream_failure_streak)
            state.stream.emit("item.delta", {"kind": "text.reset", "iter": state.current_iter, "reason": "context_overflow" if context_overflow else "provider_stream_retry", "provider": exc.provider, "model": exc.model, "retry_delay_s": delay})
            state.stream.reset_for_retry()
            owner._cancel_event.wait(delay)
            if owner._cancel_event.is_set() or owner._budget_stop_reason is not None:
                return True
            state.response = self._stream_request(state, timeout)
        else:
            state.stream_failure_streak = 0
        owner._consume_readonly_replay_visibility(state.messages, state.trace, state.current_iter)
        owner._last_activity_wall = time.time()
        usage = getattr(state.response, "usage_metadata", None)
        state.current_response_model = getattr(state.response, "response_model", None)
        owner._context_compactor.context_meter.observe(usage.get("context_input_tokens", usage.get("input_tokens")) if isinstance(usage, dict) else None, state.request_messages, tool_schema_tokens=estimate_tokens(state.tool_defs) if state.tool_defs else 0)
        if state.current_response_model:
            state.last_response_model = state.current_response_model
        owner._account_llm_usage(state.run_dir, usage, state.current_iter)
        if owner._cancel_event.is_set() or (owner._budget_stop_reason is not None and state.response.has_tool_calls):
            return True
        state.thinking_text = "".join(state.stream.thinking_chunks)
        self._record_thinking(state)
        if getattr(state.response, "content_filter_triggered", False):
            return self._skip_content_filter(state)
        state.consecutive_content_filter_count = 0
        return False

    def _stream_request(self, state: TurnState, timeout: float):
        """Send one provider request and charge failed-stream usage."""
        owner = self.owner
        state.request_messages = repair_provider_messages(state.messages)
        try:
            return owner.llm.stream_chat(state.request_messages, tools=state.tool_defs, on_text_chunk=state.stream.on_text, on_reasoning_chunk=state.stream.on_reasoning, on_waiting_chunk=state.stream.on_waiting, timeout=timeout if timeout > 0 else None, idle_timeout_s=timeout if timeout > 0 else None, should_cancel=owner._cancel_event.is_set)
        except ProviderStreamError as error:
            owner._account_llm_usage(state.run_dir, getattr(error, "usage_metadata", None), state.current_iter, purpose="failed_stream")
            raise

    def _record_thinking(self, state: TurnState) -> None:
        """Persist reasoning text only after the response phase is known."""
        if not state.thinking_text:
            return
        state.trace.write({"type": "thinking", "iter": state.current_iter, "content": state.thinking_text})

    def _skip_content_filter(self, state: TurnState) -> bool:
        """Skip filtered responses and trip the existing circuit breaker."""
        state.content_filter_count += 1
        state.consecutive_content_filter_count += 1
        if state.consecutive_content_filter_count >= MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS:
            state.trace.write({"type": "content_filter_circuit_breaker", "iter": state.current_iter, "count": state.content_filter_count})
            state.content_filter_circuit_breaker = True
            return True
        state.trace.write({"type": "content_filter_skipped", "iter": state.current_iter})
        self.owner._inject(state.messages, f"<system>{CONTENT_FILTER_SKIP_MESSAGE}</system>")
        state.response = None
        return False

    def _handle_response(self, state: TurnState) -> bool:
        """Release final text or execute the response's tool batch."""
        response = state.response
        finish_reason = getattr(response, "finish_reason", None)
        if finish_reason in {"length", "max_tokens"}:
            state.final_content = response.content or ""
            state.stream.finish(state.final_content)
            state.truncation_reason = f"provider output truncated ({finish_reason}); partial answer retained"
            self.owner._record_final_answer(state.final_content)
            return True
        if not response.has_tool_calls or state.final_answer_retry:
            return self.final_answers.handle(state) == "done"
        assistant = state.context.format_assistant_tool_calls(response.tool_calls, content=response.content, reasoning_content=response.reasoning_content or state.thinking_text or None, provider_items=getattr(response, "provider_items", None))
        _attach_tool_call_thought_signatures(assistant, response.tool_calls)
        self.owner._append_assistant(state.messages, assistant, phase="commentary")
        self.owner._active_model_id = state.current_response_model or self.owner._llm_runtime.configured_model
        self.owner._active_model_source = reported_model_source(self.owner._llm_runtime, state.current_response_model)
        state.compact_requested, state.focus_topic = self.owner._process_tool_calls(response.tool_calls, state.context, state.messages, state.trace, state.current_iter)
        if self.owner._waiting_user is not None:
            state.final_content = self.owner._waiting_user.get("prompt", "")
            options = self.owner._waiting_user.get("options") or []
            if options:
                state.final_content += "\n" + "\n".join(f"{i + 1}. {option}" for i, option in enumerate(options))
            self.owner._record_final_answer(state.final_content)
            return True
        self.owner._sync_thread_state()
        self._after_tools(state, response)
        return state.finished

    def _after_tools(self, state: TurnState, response: Any) -> None:
        """Apply pacing, no-progress, manual compaction, and queued input."""
        owner = self.owner
        state.no_commentary_rounds = 0 if response.content and response.content.strip() else state.no_commentary_rounds + 1
        if state.mid_turn_nudge_rounds > 0 and state.no_commentary_rounds >= state.mid_turn_nudge_rounds and self._has_successful_data_result(state.messages):
            owner._inject(state.messages, "<system>Evidence is already in hand. Answer the user's request now using the available evidence. Do not start extra analysis unless the user requested it.</system>")
            state.trace.write({"type": "mid_turn_nudge", "iter": state.current_iter, "no_commentary_rounds": state.no_commentary_rounds})
            state.no_commentary_rounds = 0
        if not owner._cancel_event.is_set() and owner._tool_progress.finish_iteration():
            state.final_content = owner._tool_progress.recovery_message()
            state.no_progress_reason = "no_progress: " + state.final_content
            state.trace.write({"type": "no_progress", "iter": state.current_iter, "iterations_without_progress": owner._tool_progress.stalled_iterations})
            state.stream.emit("item.delta", {"kind": "text.delta", "delta": state.final_content, "iter": state.current_iter, "phase": "final"})
            owner._record_final_answer(state.final_content)
            state.finished = True
            state.compact_requested = False
            state.focus_topic = ""
            return
        if state.compact_requested:
            owner._auto_compact(state.messages, state.run_dir, state.trace, focus_topic=state.focus_topic, iteration=state.current_iter)
        owner._take_queued_inputs(state.messages, state.trace, state.current_iter)

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
