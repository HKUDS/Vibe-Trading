"""Product and provider operations bound to the turn scheduler."""

from __future__ import annotations

import json
import logging

from src.agent.context_budget import estimate_tokens, is_context_overflow
from src.agent.context_compact import _attach_tool_call_thought_signatures, _context_collapse
from src.agent.loop_state import TurnState
from src.agent.loop_streaming import TurnStream
from src.agent.tuning import (
    _heartbeat_interval_s,
    _llm_timeout_seconds,
    _override,
    _reasoning_delta_min_interval_s,
    _stream_retry_backoff_s,
    _stream_retry_max_delay_s,
    _token_threshold,
)
from src.kernel import events as vocabulary
from src.kernel.contracts import LLMResponse, LoopDecision
from src.product.tool_loading import request_definitions
from src.providers.chat import ProviderStreamError, reported_model_source
from src.providers.content_filter import CONTENT_FILTER_SKIP_MESSAGE, MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS
from src.providers.messages import repair_provider_messages

logger = logging.getLogger(__name__)


class IterationSteps:
    """Prepare a turn, request a response, and apply tool results in the host."""

    def __init__(
        self, *, llm, runtime, max_iterations, activity, goals, tools, compactor,
        conversation, writes, usage, background, emit, hook, pacing,
    ) -> None:
        self.llm = llm
        self.runtime = runtime
        self.max_iterations = max_iterations
        self.activity = activity
        self.goals = goals
        self.tools = tools
        self.compactor = compactor
        self.conversation = conversation
        self.writes = writes
        self.usage = usage
        self.background = background
        self.emit = emit
        self.hook = hook
        self.pacing = pacing

    def prepare_iteration(self, state: TurnState) -> LoopDecision:
        """Apply budgets, compaction, background results, and directives."""
        self.compactor.tool_schema_tokens = estimate_tokens(request_definitions(self.tools.env.registry))
        if self.goals.stop_reason is not None or self.activity.cancel.is_set():
            if self.activity.cancel.is_set():
                state.trace.write({"type": "cancelled", "iter": self.activity.iteration + 1})
            return LoopDecision.STOP
        state.iteration += 1
        self.activity.iteration += 1
        state.current_iter = self.activity.iteration
        notifs = self.background.drain_notifications()
        if notifs:
            text = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
            self.conversation.inject(state.messages, f"<background-results>\n{text}\n</background-results>\n\n<system>Continue processing with the background results above.</system>")
        self._compact(state)
        if self.activity.cancel.is_set() or self.goals.stop_reason is not None:
            return LoopDecision.STOP
        self.pacing.write_directives(state, self.writes)
        return LoopDecision.CONTINUE

    def _compact(self, state: TurnState) -> None:
        """Run the configured estimate or model-window compaction path."""
        if _override("TOKEN_THRESHOLD") is not None:
            tokens = estimate_tokens(state.messages)
            if tokens > int(_token_threshold() * 0.5):
                self.compactor._microcompact_and_unblock(state.messages, state.trace, state.iteration, preserve_tool_call_ids=self.tools.replay._readonly_replay_visibility_pending)
                tokens = estimate_tokens(state.messages)
            if tokens > int(_token_threshold() * 0.7):
                before = json.loads(json.dumps(state.messages, default=str, ensure_ascii=False))
                _context_collapse(state.messages, preserve_tool_call_ids=self.tools.replay._readonly_replay_visibility_pending)
                self.compactor._record_compaction_layer(state.messages, 2, before)
                tokens = estimate_tokens(state.messages)
            if tokens > _token_threshold():
                decision = self.hook("PreCompact", {"session_id": state.session_id, "iteration": state.current_iter, "prompt_tokens": tokens})
                if decision is None or not decision.denied:
                    self.compactor.auto_compact(state.messages, state.run_dir, state.trace, iteration=state.current_iter)
        else:
            self.compactor._compact_to_budget(state.messages, state.run_dir, state.trace, state.iteration, state.current_iter)

    def request(self, state: TurnState) -> LLMResponse | LoopDecision:
        """Request one provider response with bounded retry handling."""
        state.stream = TurnStream(emit=self.emit, iteration=state.current_iter, heartbeat_interval=_heartbeat_interval_s, reasoning_interval=_reasoning_delta_min_interval_s)
        state.tool_defs = None if state.iteration >= self.max_iterations else request_definitions(self.tools.env.registry)
        if state.iteration >= self.max_iterations:
            state.trace.write({"type": "forced_text_only", "iter": state.current_iter})
        timeout = _llm_timeout_seconds()
        try:
            response = self._stream_request(state, timeout)
        except ProviderStreamError as exc:
            if not exc.retryable and not is_context_overflow(str(exc)):
                raise
            context_overflow = is_context_overflow(str(exc))
            if context_overflow:
                self.compactor._recover_context_overflow(exc, state.messages, state.run_dir, state.trace, state.iteration, state.current_iter)
                delay = 0.0
            else:
                state.stream_failure_streak += 1
                delay = min(exc.retry_after_s, _stream_retry_max_delay_s()) if exc.retry_after_s is not None else _stream_retry_backoff_s(state.stream_failure_streak)
            state.stream.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.TEXT_RESET, "iter": state.current_iter, "reason": "context_overflow" if context_overflow else "provider_stream_retry", "provider": exc.provider, "model": exc.model, "retry_delay_s": delay})
            state.stream.reset_for_retry()
            self.activity.cancel.wait(delay)
            if self.activity.cancel.is_set() or self.goals.stop_reason is not None:
                return LoopDecision.STOP
            response = self._stream_request(state, timeout)
        else:
            state.stream_failure_streak = 0
        self.tools.replay._consume_readonly_replay_visibility(state.messages, state.trace, state.current_iter)
        self.activity.touch()
        usage = getattr(response, "usage_metadata", None)
        state.current_response_model = getattr(response, "response_model", None)
        self.compactor.context_meter.observe(usage.get("context_input_tokens", usage.get("input_tokens")) if isinstance(usage, dict) else None, state.request_messages, tool_schema_tokens=estimate_tokens(state.tool_defs) if state.tool_defs else 0)
        if state.current_response_model:
            state.last_response_model = state.current_response_model
        self.usage.record(state.run_dir, usage, state.current_iter)
        if self.activity.cancel.is_set() or (self.goals.stop_reason is not None and response.has_tool_calls):
            return LoopDecision.STOP
        state.thinking_text = "".join(state.stream.thinking_chunks)
        self._record_thinking(state)
        if getattr(response, "content_filter_triggered", False):
            return self._skip_content_filter(state)
        state.consecutive_content_filter_count = 0
        return LoopDecision.CONTINUE if response is None else response

    def _stream_request(self, state: TurnState, timeout: float) -> LLMResponse:
        """Send one provider request and charge failed-stream usage."""
        state.request_messages = repair_provider_messages(state.messages)
        try:
            return self.llm.stream_chat(state.request_messages, tools=state.tool_defs, on_text_chunk=state.stream.on_text, on_reasoning_chunk=state.stream.on_reasoning, on_waiting_chunk=state.stream.on_waiting, timeout=timeout if timeout > 0 else None, idle_timeout_s=timeout if timeout > 0 else None, should_cancel=self.activity.cancel.is_set)
        except ProviderStreamError as error:
            self.usage.record(state.run_dir, getattr(error, "usage_metadata", None), state.current_iter, purpose="failed_stream")
            raise

    def _record_thinking(self, state: TurnState) -> None:
        """Persist reasoning text only after the response phase is known."""
        if not state.thinking_text:
            return
        state.trace.write({"type": "thinking", "iter": state.current_iter, "content": state.thinking_text})

    def _skip_content_filter(self, state: TurnState) -> LoopDecision:
        """Skip filtered responses and trip the existing circuit breaker."""
        state.content_filter_count += 1
        state.consecutive_content_filter_count += 1
        if state.consecutive_content_filter_count >= MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS:
            state.trace.write({"type": "content_filter_circuit_breaker", "iter": state.current_iter, "count": state.content_filter_count})
            state.content_filter_circuit_breaker = True
            return LoopDecision.STOP
        state.trace.write({"type": "content_filter_skipped", "iter": state.current_iter})
        self.conversation.inject(state.messages, f"<system>{CONTENT_FILTER_SKIP_MESSAGE}</system>")
        return LoopDecision.CONTINUE

    def record_partial(self, state: TurnState, response: LLMResponse, finish_reason: str) -> None:
        """Retain a truncated answer and its original terminal reason."""
        state.final_content = response.content or ""
        state.stream.finish(state.final_content)
        state.truncation_reason = f"provider output truncated ({finish_reason}); partial answer retained"
        self.conversation.record_final_answer(state.final_content)

    def run_tools(self, state: TurnState, response: LLMResponse) -> LoopDecision:
        """Record the assistant item and process its bound tool batch."""
        assistant = state.context.format_assistant_tool_calls(response.tool_calls, content=response.content, reasoning_content=response.reasoning_content or state.thinking_text or None, provider_items=getattr(response, "provider_items", None))
        _attach_tool_call_thought_signatures(assistant, response.tool_calls)
        self.conversation.append_assistant(state.messages, assistant, phase="commentary")
        self.writes.active_model_id = state.current_response_model or self.runtime.configured_model
        self.writes.active_model_source = reported_model_source(self.runtime, state.current_response_model)
        state.compact_requested, state.focus_topic = self.tools.process(response.tool_calls, state.context, state.messages, state.trace, state.current_iter)
        if self.tools.delivery.waiting_user is not None:
            state.final_content = self.tools.delivery.waiting_user.get("prompt", "")
            options = self.tools.delivery.waiting_user.get("options") or []
            if options:
                state.final_content += "\n" + "\n".join(f"{i + 1}. {option}" for i, option in enumerate(options))
            self.conversation.record_final_answer(state.final_content)
            return LoopDecision.STOP
        self.conversation.sync_state(self.tools.env)
        if self.pacing.after_tools(state, response, self.tools.delivery.progress, self.activity.cancel):
            return LoopDecision.STOP

        if state.compact_requested:
            self.compactor.auto_compact(state.messages, state.run_dir, state.trace, focus_topic=state.focus_topic, iteration=state.current_iter)
        self.conversation.take_queued_inputs(state.messages, cancelled=self.activity.cancel.is_set(), budget_spent=self.goals.stop_reason is not None)
        return LoopDecision.CONTINUE
