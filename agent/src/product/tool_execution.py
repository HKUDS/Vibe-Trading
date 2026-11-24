"""Prepare authorized tool batches with explicit identity dependencies."""
from __future__ import annotations

import json
import logging
from copy import copy
from dataclasses import dataclass
from itertools import groupby
from typing import Any

from src.agent.tools import ToolRegistry
from src.agent.tuning import _override
from src.kernel.contracts import BoundCall, ToolCallRequest
from src.kernel.tool_runner import execute_batch
from src.product.context import ContextBuilder
from src.product.data_window import UserDataWindow
from src.product.identity.ledger import IdentityLedger
from src.product.resources.memory import WorkspaceMemory
from src.tools._arguments import normalize_tool_run_dir
from src.tools.redaction import redact_payload

logger = logging.getLogger(__name__)


@dataclass
class ToolEnvironment:
    registry: ToolRegistry
    memory: WorkspaceMemory
    identity: IdentityLedger | None = None
    data_window: UserDataWindow | None = None
    session_id: str = ""


class ToolExecution:
    """Plan identity dependencies, refusals and ordered runs of authorized calls."""
    def __init__(self, env, replay, delivery, invocation, cancel_event, context_budget, prompt_tokens):
        self.env = env
        self.replay = replay
        self.delivery = delivery
        self.invocation = invocation
        self._cancel_event = cancel_event
        self._context_budget = context_budget
        self._prompt_tokens = prompt_tokens

    def _identity_dependency_query(self, tc: Any) -> str | None:
        """Read the opted-in dependency without issuing a refused consumer call."""
        if self.env.identity is None or self._cancel_event.is_set():
            return None
        tool = self.env.registry.get(tc.name)
        field = getattr(tool, "identity_argument", None)
        if not field or not self.replay._is_tool_readonly(tc.name) or self.env.registry.policy.denies(tc.name):
            return None
        if self.env.registry.get("search_symbol") is None:
            return None
        return self.env.identity.pending_resolution_query(tc.arguments, field)

    def _prepare_identity_dependencies(
        self, tool_calls, context, trace, iteration,
    ) -> dict[str, str]:
        """Resolve new dependencies through the ordinary bounded tool lifecycle."""
        outcomes = {}
        for tc in tool_calls:
            query = self._identity_dependency_query(tc)
            if query is None:
                continue
            dependency = ToolCallRequest(
                id=f"{tc.id}:identity", name="search_symbol", arguments={"query": query},
            )
            trace.write({
                "type": "identity_dependency", "iter": iteration,
                "parent_call_id": tc.id, "call_id": dependency.id,
                "tool": dependency.name, "query": query,
            })
            internal_messages = []
            # Record lookup results for display without adding an invented provider call ID.
            conversation = self.delivery.conversation
            previous_lists = conversation.dependency_lists
            conversation.dependency_lists = (*previous_lists, internal_messages)
            try:
                self.process(
                    [dependency], context, internal_messages, trace, iteration,
                )
            finally:
                conversation.dependency_lists = previous_lists
            if internal_messages:
                outcomes[tc.id] = internal_messages[-1]["content"]
        return outcomes

    def process(
        self,
        tool_calls: list,
        context: ContextBuilder,
        messages: list,
        trace: Any,
        iteration: int,
    ) -> tuple[bool, str]:
        """Pre-process tool calls: handle compact, filter duplicates, batch execute."""
        # Keep the explicit resolver’s provider call ID when moving it ahead of the read.
        tool_calls = list(tool_calls)
        window = self.env.data_window
        if window is not None:
            for index, tc in enumerate(tool_calls):
                if not getattr(self.env.registry.get(tc.name), "use_user_date_window", False):
                    continue
                arguments = window.normalize(tc.arguments)
                if arguments is not tc.arguments:
                    effective = copy(tc)
                    effective.arguments = arguments
                    tool_calls[index] = effective
                    trace.write({
                        "type": "data_window_normalized", "iter": iteration,
                        "call_id": tc.id, "tool": tc.name,
                        "original_start": tc.arguments.get("start_date"),
                        "original_end": tc.arguments.get("end_date"),
                        "effective_start": arguments["start_date"],
                        "effective_end": arguments["end_date"],
                    })
        for index, tc in enumerate(tool_calls):
            query = self._identity_dependency_query(tc)
            if query is None:
                continue
            for later in range(index + 1, len(tool_calls)):
                other = tool_calls[later]
                if other.name == "search_symbol" and str(other.arguments.get("query", "")).strip().casefold() == query.casefold():
                    tool_calls.insert(index, tool_calls.pop(later))
                    break

        # Each resolver commits its identity before the next tool segment.
        if len(tool_calls) > 1 and any(tc.name == "search_symbol" for tc in tool_calls):
            compact_requested, focus_topic = False, ""
            for is_resolver, group in groupby(tool_calls, key=lambda tc: tc.name == "search_symbol"):
                parts = ([tc] for tc in group) if is_resolver else (list(group),)
                for part in parts:
                    compact, focus = self.process(part, context, messages, trace, iteration)
                    compact_requested |= compact
                    focus_topic = focus or focus_topic
            return compact_requested, focus_topic

        # Do not pull an implicit prerequisite ahead of a prior mutation.
        for index, tc in enumerate(tool_calls):
            if self._identity_dependency_query(tc) is not None and any(
                not self.replay._is_tool_readonly(previous.name) for previous in tool_calls[:index]
            ):
                compact_a, focus_a = self.process(
                    tool_calls[:index], context, messages, trace, iteration,
                )
                compact_b, focus_b = self.process(
                    tool_calls[index:], context, messages, trace, iteration,
                )
                return compact_a or compact_b, focus_b or focus_a

        dependency_results = self._prepare_identity_dependencies(
            tool_calls, context, trace, iteration,
        )
        compact_requested = False
        focus_topic = ""
        execution_plan: list[tuple[Any, str | None]] = []
        batch_authorized_symbols = (
            set(self.env.identity.authorized_symbols)
            if self.env.identity is not None
            else set()
        )
        batch_identity_status = (
            self.env.identity.identity_status
            if self.env.identity is not None
            else "not_required"
        )

        if self._cancel_event.is_set():
            self.delivery.deliver_cancelled_calls(
                tool_calls, context, messages, trace, iteration
            )
            return compact_requested, focus_topic

        for tc in tool_calls:
            if tc.name == "compact" and (self.invocation.successful_reads is None or self.env.registry.get(tc.name) is not None):
                self.delivery.progress.note("compact", "compact")
                self.delivery._emit_tool_started(tc, {}, iteration)
                budget = None if _override("TOKEN_THRESHOLD") is not None else self._context_budget(messages)
                tokens = self._prompt_tokens(messages) if budget is not None else 0
                if budget is not None and tokens <= budget.micro_at:
                    # A small prompt still carries evidence the model would otherwise have to fetch again.
                    declined = json.dumps({
                        "status": "ok",
                        "skipped": True,
                        "message": (
                            f"Compaction not needed: the prompt is {tokens} tokens, "
                            f"under the {budget.micro_at}-token threshold. Earlier "
                            "tool results are still in context; keep using them."
                        ),
                    })
                    self.delivery._append_tool_result(messages, context, tc.id, "compact", declined, status="ok", elapsed_ms=0)
                    trace.write({"type": "compact_declined", "iter": iteration, "prompt_tokens": tokens})
                else:
                    compact_requested = True
                    focus_topic = tc.arguments.get("focus_topic", "")
                    self.delivery._append_tool_result(
                        messages, context, tc.id, "compact",
                        '{"status":"ok","message":"Compressing..."}', status="ok", elapsed_ms=0,
                    )
                    trace.write({"type": "compact_requested", "iter": iteration})
                self.delivery._emit_tool_completed(tc, "ok", 0, "")
                continue

            tool_def = self.env.registry.get(tc.name)
            repeatable = tool_def.repeatable if tool_def else False
            # Unserializable arguments share neither a cache key nor a failure block.
            dedup_key = self.replay._identical_call_key(tc.name, tc.arguments)
            if dedup_key is not None and self.delivery.progress.is_blocked(dedup_key):
                failed_result = json.dumps(
                    {
                        "status": "error",
                        "skipped": True,
                        "reason": "This exact call already failed repeatedly in this run. Change strategy or ask the user for help.",
                    }
                )
                self.delivery.deliver_blocked_call(
                    tc,
                    failed_result,
                    context,
                    messages,
                    trace,
                    iteration,
                )
                continue
            if (
                self.env.identity is not None and tc.name == "search_symbol"
                and getattr(tool_def, "reuse_session_identity", False)
            ):
                reused = (
                    None if self.env.registry.policy.denies(tc.name)
                    else self.env.identity.reusable_resolution(tc.arguments)
                )
                if reused is not None:
                    self.delivery._emit_tool_started(tc, tc.arguments, iteration)
                    trace.write({
                        "type": "identity_reused", "iter": iteration, "tool": tc.name,
                        "call_id": tc.id, "args": redact_payload(tc.arguments),
                    })
                    self.delivery.progress.note("reused", tc.name)
                    self.delivery._finalize_tool_result(
                        tc, reused, 0, context, messages, trace, iteration,
                        update_memory=False, update_identity=False,
                    )
                    continue
            if self.env.identity is not None:
                authorization = self.env.identity.authorize_tool_call(
                    tc.name,
                    tc.arguments,
                    batch_authorized_symbols=batch_authorized_symbols,
                    call_id=tc.id,
                    batch_identity_status=batch_identity_status,
                )
                if not authorization.allowed:
                    refused = authorization.error_payload(tc.name, self.env.identity.identity_summary())
                    if tc.id in dependency_results:
                        payload = json.loads(refused)
                        payload["identity_resolution"] = dependency_results[tc.id]
                        refused = json.dumps(payload, ensure_ascii=False)
                    execution_plan.append((tc, refused))
                    continue

            use_shared_cache = self.invocation.successful_reads is None
            if use_shared_cache and self.replay.deliver_cached(tc, tool_def, repeatable, dedup_key, context, messages, trace, iteration, self.delivery):
                continue

            execution_plan.append((tc, None))

        if not execution_plan:
            return compact_requested, focus_topic

        # Refusals bound execution segments so provider result ordering stays stable.
        authorized_segment: list[Any] = []

        def flush_authorized_segment() -> None:
            if not authorized_segment:
                return
            if self._cancel_event.is_set():
                self.delivery.deliver_cancelled_calls(authorized_segment, context, messages, trace, iteration)
            else:
                plan = []
                for tc in authorized_segment:
                    tool = self.env.registry.get(tc.name) if len(authorized_segment) > 1 else None
                    plan.append(self._bind(tc, context, messages, trace, iteration,
                                           parallel=bool(tool and tool.is_readonly and self.invocation.successful_reads is None)))
                execute_batch(plan, self._cancel_event.is_set)
            authorized_segment.clear()

        for tc, blocked_result in execution_plan:
            if blocked_result is None:
                authorized_segment.append(tc)
                continue
            flush_authorized_segment()
            self.delivery.deliver_blocked_call(
                tc,
                blocked_result,
                context,
                messages,
                trace,
                iteration,
            )
        flush_authorized_segment()

        return compact_requested, focus_topic

    def _bind(self, tc, context, messages, trace, iteration, *, parallel) -> BoundCall:
        def start(in_parallel: bool):
            args = normalize_tool_run_dir(tc.arguments, self.env.memory.run_dir)
            self.delivery._emit_tool_started(tc, args, iteration)
            trace.write({"type": "tool_execution", "iter": iteration, "tool": tc.name, "call_id": tc.id})
            if not in_parallel:
                logger.info("Tool call: %s(%s)", tc.name, list(args))
            return lambda: self.invocation._invoke_tool(tc.name, args, call_id=tc.id)

        def finish(result, elapsed_ms):
            self.delivery._finalize_tool_result(tc, result, elapsed_ms, context, messages, trace, iteration)

        def skip():
            self.delivery.deliver_cancelled_calls([tc], context, messages, trace, iteration)

        return BoundCall(start=start, finish=finish, skip=skip, parallel=parallel)
