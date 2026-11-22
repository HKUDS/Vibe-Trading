"""Product and provider operations bound to the turn scheduler."""

from __future__ import annotations

from src.agent.loop_state import TurnState
from src.agent.loop_streaming import TurnStream
from src.agent.tuning import (
    _heartbeat_interval_s,
    _reasoning_delta_min_interval_s,
)
from src.kernel.contracts import Continue, Iteration, LLMResponse, LoopContext, Stop
from src.kernel.events import EventSink
from src.product.tool_loading import request_definitions
from src.providers.response import reported_model_source
from src.providers.content_filter import CONTENT_FILTER_SKIP_MESSAGE, MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS
from src.providers.messages import attach_tool_call_thought_signatures


class IterationSteps:
    """Prepare a turn, request a response, and apply tool results in the host."""

    def __init__(
        self, *, state: TurnState, requests, activity, goals, tools, compactor,
        conversation, writes, usage, background, pacing,
    ) -> None:
        self.requests = requests
        self.state = state
        self.activity = activity
        self.goals = goals
        self.tools = tools
        self.compactor = compactor
        self.conversation = conversation
        self.writes = writes
        self.usage = usage
        self.background = background
        self.pacing = pacing

    def on_cancel(self) -> None:
        self.state.trace.write({"type": "cancelled", "iter": self.activity.iteration + 1})

    def before_iteration(self, view: LoopContext) -> Stop | None:
        view.tools = request_definitions(self.tools.env.registry)
        self.compactor.update_tool_schemas(view.tools)
        if self.goals.stop_reason is not None:
            return Stop(self.goals.stop_reason)
        return None

    def prepare_request(self, view: LoopContext, iteration: Iteration) -> Stop | None:
        """Compact, deliver background results and select the tools for this request."""
        state = self.state
        state.iteration = iteration.number
        state.final_answer_retry = iteration.final_answer_retry
        self.activity.iteration += 1
        state.current_iter = self.activity.iteration
        notifs = self.background.drain_notifications()
        if notifs:
            text = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs)
            self.conversation.inject(state.view.messages, f"<background-results>\n{text}\n</background-results>\n\n<system>Continue processing with the background results above.</system>")
        self.compactor.compact_if_needed(
            state.view.messages, state.run_dir, state.trace, state.iteration, state.current_iter,
            session_id=state.session_id,
        )
        if self.activity.cancel.is_set() or self.goals.stop_reason is not None:
            return Stop(self.goals.stop_reason or "cancelled")
        self.pacing.write_directives(state, self.writes)
        if iteration.text_only:
            state.trace.write({"type": "forced_text_only", "iter": state.current_iter})
            view.tools = None
        else:
            view.tools = request_definitions(self.tools.env.registry)
        return None

    def request(self, view: LoopContext, emit: EventSink) -> LLMResponse | Continue | Stop:
        """Request one response, preserving stream accounting and filtering."""
        state = self.state
        state.stream = TurnStream(
            emit=emit, iteration=state.current_iter, heartbeat_interval=_heartbeat_interval_s,
            reasoning_interval=_reasoning_delta_min_interval_s,
        )
        result = self.requests.send(
            view.messages, view.tools, state.stream, run_dir=state.run_dir, trace=state.trace,
            iteration=state.iteration, current_iter=state.current_iter,
        )
        if result is None:
            return Stop(self.goals.stop_reason or "cancelled")
        response, request_messages = result
        self.tools.replay._consume_readonly_replay_visibility(state.view.messages, state.trace, state.current_iter)
        self.activity.touch()
        usage = getattr(response, "usage_metadata", None)
        state.current_response_model = getattr(response, "response_model", None)
        self.compactor.observe_request(usage, request_messages, view.tools)
        if state.current_response_model:
            state.last_response_model = state.current_response_model
        self.usage.record(state.run_dir, usage, state.current_iter)
        if self.activity.cancel.is_set() or (self.goals.stop_reason is not None and response.has_tool_calls):
            return Stop(self.goals.stop_reason or "cancelled")
        state.thinking_text = "".join(state.stream.thinking_chunks)
        self._record_thinking(state)
        if getattr(response, "content_filter_triggered", False):
            return self._skip_content_filter(state)
        state.consecutive_content_filter_count = 0
        return Continue.NEXT if response is None else response

    def _record_thinking(self, state: TurnState) -> None:
        """Persist reasoning text only after the response phase is known."""
        if not state.thinking_text:
            return
        state.trace.write({"type": "thinking", "iter": state.current_iter, "content": state.thinking_text})

    def _skip_content_filter(self, state: TurnState) -> Continue | Stop:
        """Skip filtered responses and trip the existing circuit breaker."""
        state.content_filter_count += 1
        state.consecutive_content_filter_count += 1
        if state.consecutive_content_filter_count >= MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS:
            state.trace.write({"type": "content_filter_circuit_breaker", "iter": state.current_iter, "count": state.content_filter_count})
            state.content_filter_circuit_breaker = True
            return Stop("content_filter")
        state.trace.write({"type": "content_filter_skipped", "iter": state.current_iter})
        self.conversation.inject(state.view.messages, f"<system>{CONTENT_FILTER_SKIP_MESSAGE}</system>")
        return Continue.NEXT

    def record_partial(self, response: LLMResponse, finish_reason: str) -> None:
        """Retain a truncated answer and its original terminal reason."""
        state = self.state
        state.final_content = response.content or ""
        state.stream.finish(state.final_content)
        state.truncation_reason = f"provider output truncated ({finish_reason}); partial answer retained"
        self.conversation.record_final_answer(state.final_content)

    def run_tools(self, response: LLMResponse) -> Continue | Stop:
        """Record the assistant item and process its bound tool batch."""
        state = self.state
        assistant = state.context.format_assistant_tool_calls(response.tool_calls, content=response.content, reasoning_content=response.reasoning_content or state.thinking_text or None, provider_items=getattr(response, "provider_items", None))
        attach_tool_call_thought_signatures(assistant, response.tool_calls)
        self.conversation.append_assistant(state.view.messages, assistant, phase="commentary")
        self.writes.active_model_id = state.current_response_model or state.view.model.configured_model
        self.writes.active_model_source = reported_model_source(state.view.model, state.current_response_model)
        state.compact_requested, state.focus_topic = self.tools.process(response.tool_calls, state.context, state.view.messages, state.trace, state.current_iter)
        if self.tools.delivery.waiting_user is not None:
            state.final_content = self.tools.delivery.waiting_user.get("prompt", "")
            options = self.tools.delivery.waiting_user.get("options") or []
            if options:
                state.final_content += "\n" + "\n".join(f"{i + 1}. {option}" for i, option in enumerate(options))
            self.conversation.record_final_answer(state.final_content)
            return Stop("waiting_user")
        self.conversation.sync_state(self.tools.env)
        if self.pacing.after_tools(state, response, self.tools.delivery.progress, self.activity.cancel):
            return Stop("no_progress")

        if state.compact_requested:
            self.compactor.auto_compact(state.view.messages, state.run_dir, state.trace, focus_topic=state.focus_topic, iteration=state.current_iter)
        return Continue.NEXT

    def poll_inputs(self) -> None:
        self.conversation.take_queued_inputs(
            self.state.view.messages, cancelled=self.activity.cancel.is_set(),
            budget_spent=self.goals.stop_reason is not None,
        )
