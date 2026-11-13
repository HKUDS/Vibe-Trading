"""Tool-call lifecycle extracted verbatim from AgentLoop (#1624).

Owns authorization, deduplication/replay, ordered read/write batches, bounded
readonly execution and result recording. The mixin uses the existing loop's
run-scoped state and callback methods; it creates no second state owner.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import queue
import threading
import time as _time
from typing import Any, Dict, Mapping

from src.agent.context import ContextBuilder
from src.agent.context_compact import _replay_context_result, _result_data_gone
from src.agent.progress import HeartbeatTimer, ProgressEvent, _set_emitter
from src.agent.trace import TraceWriter
from src.agent.tuning import _heartbeat_interval_s, _override, _tool_timeout_seconds
from src.agent.tool_results import (
    _archive_backtest_result, _failure_code, _is_tool_success, _normalize_tool_run_dir,
)
from src.agent.result_artifacts import deliver_tool_result
from src.tools.redaction import redact_payload, redact_tool_result

logger = logging.getLogger("src.agent.loop")

# Compaction recovery is a bounded reliability aid, not an alternate research
# loop: a run restores at most this many lost readonly payloads from its replay
# cache. Past the cap a lost call runs again as it does without replay, so the
# model is never told to use a result it can no longer see, and a loop of
# identical re-runs still ends at the no-progress limit.
MAX_READONLY_REPLAY_RECOVERIES = 6


def _format_timeout(seconds: float) -> str:
    """Return a human-readable timeout label."""
    if seconds < 1:
        return f"{seconds:.2f}s"
    return f"{seconds:.0f}s"



class ToolCallLifecycle:
    """Run tools against the AgentLoop owner state; no independent lifecycle."""

    def _process_tool_calls(
        self,
        tool_calls: list,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> tuple[bool, str]:
        """Pre-process tool calls: handle compact, filter duplicates, batch execute.

        Args:
            tool_calls: Raw tool calls from LLM response.
            context: ContextBuilder for formatting messages.
            messages: Conversation messages (appended in place).
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration number.

        Returns:
            Tuple of (compact_requested, focus_topic).
        """
        # A resolver is a real data dependency. Execute it at a boundary so
        # subsequent reads see its result rather than a stale pre-turn snapshot.
        if len(tool_calls) > 1 and any(tc.name == "search_symbol" for tc in tool_calls):
            compact_requested, focus_topic = False, ""
            segment = []
            for tc in tool_calls:
                if tc.name == "search_symbol":
                    for part in (segment, [tc]):
                        if part:
                            compact, focus = self._process_tool_calls(
                                part, context, messages, trace, react_trace, iteration,
                            )
                            compact_requested |= compact
                            focus_topic = focus or focus_topic
                    segment = []
                else:
                    segment.append(tc)
            if segment:
                compact, focus = self._process_tool_calls(
                    segment, context, messages, trace, react_trace, iteration,
                )
                compact_requested |= compact
                focus_topic = focus or focus_topic
            return compact_requested, focus_topic

        compact_requested = False
        focus_topic = ""
        execution_plan: list[tuple[Any, str | None]] = []
        batch_authorized_symbols = (
            set(self._identity.authorized_symbols)
            if self._identity is not None
            else set()
        )
        batch_identity_status = (
            self._identity.identity_status
            if self._identity is not None
            else "not_required"
        )

        # Cancelled before this turn's tools ran — skip execution entirely.
        if self._cancel_event.is_set():
            return compact_requested, focus_topic

        for tc in tool_calls:
            # Layer 4: compact tool — mark then defer execution
            if tc.name == "compact":
                self._tool_progress.note("compact", "compact")
                self._emit(
                    "tool_call",
                    {"tool": "compact", "arguments": {}, "iter": iteration, "call_id": tc.id},
                )
                budget = None if _override("TOKEN_THRESHOLD") is not None else self._context_budget(messages)
                tokens = self._prompt_tokens(messages) if budget is not None else 0
                if budget is not None and tokens <= budget.micro_at:
                    # Summarising a prompt this small only destroys evidence the
                    # model will then fetch again: decline, and say why.
                    declined = json.dumps({
                        "status": "ok",
                        "skipped": True,
                        "message": (
                            f"Compaction not needed: the prompt is {tokens} tokens, "
                            f"under the {budget.micro_at}-token threshold. Earlier "
                            "tool results are still in context; keep using them."
                        ),
                    })
                    messages.append(context.format_tool_result(tc.id, "compact", declined))
                    trace.write({"type": "compact_declined", "iter": iteration, "prompt_tokens": tokens})
                else:
                    compact_requested = True
                    focus_topic = tc.arguments.get("focus_topic", "")
                    messages.append(context.format_tool_result(tc.id, "compact", '{"status":"ok","message":"Compressing..."}'))
                    trace.write({"type": "compact_requested", "iter": iteration})
                self._emit(
                    "tool_result",
                    {"tool": "compact", "status": "ok", "elapsed_ms": 0, "call_id": tc.id},
                )
                continue

            tool_def = self.registry.get(tc.name)
            is_repeatable = tool_def.repeatable if tool_def else False
            # A None key means the arguments could not be canonicalised. The
            # deterministic cache treats that as 'never cache'; the blocking
            # gate must likewise treat it as 'never block', otherwise every
            # un-serialisable call would collapse into a single identity and
            # the second one would be skipped without ever running.
            dedup_key = self._identical_call_key(tc.name, tc.arguments)
            if dedup_key is not None and self._tool_progress.is_blocked(dedup_key):
                failed_result = json.dumps(
                    {
                        "status": "error",
                        "skipped": True,
                        "reason": "This exact call already failed repeatedly in this run. Change strategy or ask the user for help.",
                    }
                )
                self._record_blocked_tool_call(
                    tc,
                    failed_result,
                    context,
                    messages,
                    trace,
                    react_trace,
                    iteration,
                )
                continue
            if self._identity is not None:
                authorization = self._identity.authorize_tool_call(
                    tc.name,
                    tc.arguments,
                    batch_authorized_symbols=batch_authorized_symbols,
                    call_id=tc.id,
                    batch_identity_status=batch_identity_status,
                )
                if not authorization.allowed:
                    execution_plan.append(
                        (
                            tc,
                            authorization.error_payload(
                                tc.name,
                                self._identity.identity_summary(),
                            ),
                        )
                    )
                    continue

            # A successful readonly call whose visible result was removed by
            # micro/auto-compaction can be replayed from this run's memory. This
            # extends the existing deterministic-cache pattern without declaring
            # mutable web resources deterministic. Fresh/no-cache calls bypass
            # this path, while repeatable calls must explicitly opt in.
            if (
                dedup_key is not None
                and dedup_key in self._readonly_replay_ready
                and self._readonly_replay_recoveries < MAX_READONLY_REPLAY_RECOVERIES
                and self._readonly_replay_allowed(tool_def, tc.arguments)
                and dedup_key in self._readonly_replay_cache
            ):
                cached = self._readonly_replay_cache[dedup_key]
                restored = _replay_context_result(cached)
                messages.append(
                    context.format_tool_result(
                        tc.id, tc.name, deliver_tool_result(restored, self.memory.run_dir, self.registry)
                    )
                )
                self._readonly_replay_visibility_pending.add(tc.id)
                self._successful_call_keys[tc.id] = dedup_key
                self._called_ok.add(dedup_key)
                self._readonly_replay_ready.discard(dedup_key)
                self._readonly_replay_recoveries += 1
                # A repeatable tool would otherwise re-fetch on the very next
                # identical call; the restored payload is visible now, so that
                # call is refused until compaction removes it again.
                if getattr(tool_def, "repeatable", False):
                    self._readonly_replay_protected.add(dedup_key)
                # Restoring data that compaction removed is forward progress for
                # the working context, but not a new external observation.
                self._tool_progress.mark_context_restored()
                trace.write({
                    "type": "tool_result_replayed",
                    "iter": iteration,
                    "tool": tc.name,
                    "call_id": tc.id,
                    "recovery_count": self._readonly_replay_recoveries,
                    "recovery_limit": MAX_READONLY_REPLAY_RECOVERIES,
                })
                react_trace.append({"type": "tool_result_replayed", "tool": tc.name})
                self._tool_progress.note("replayed", tc.name)
                self._emit(
                    "tool_result",
                    {
                        "tool": tc.name,
                        "status": "ok",
                        "elapsed_ms": 0,
                        "preview": redact_tool_result(cached)[:200],
                        "call_id": tc.id,
                        "cached": True,
                        "replayed": True,
                    },
                )
                continue

            if (
                dedup_key is not None
                and dedup_key in self._called_ok
                and (
                    not is_repeatable
                    or dedup_key in self._readonly_replay_protected
                )
            ):
                logger.warning(f"Blocked duplicate call: {tc.name} (already succeeded)")
                replay_restored = dedup_key in self._readonly_replay_protected
                reason = (
                    f"{tc.name} was just restored from the run-scoped replay cache after "
                    "compaction. The payload is already visible in context; use that "
                    "result and continue the analysis instead of requesting the same "
                    "call again."
                    if replay_restored
                    else f"{tc.name} already completed successfully. Use the previous result."
                )
                skip_msg = json.dumps({"skipped": True, "reason": reason})
                messages.append(context.format_tool_result(tc.id, tc.name, skip_msg))
                trace.write({"type": "tool_skipped", "iter": iteration, "tool": tc.name})
                self._tool_progress.note("skipped", tc.name)
                react_trace.append({"type": "tool_skipped", "tool": tc.name})
                continue

            # Deterministic tools (e.g. financial_rigor calc) return the same
            # result for the same args. Checked AFTER authorization above so a
            # cached repeat can never bypass the identity gate. After auto-compact cleared earlier
            # tool outputs, the model used to re-run identical expressions
            # 5-9x each (2026-08-20 INTC run) to re-verify numbers it could
            # no longer see. Serve an identical prior call from cache instead.
            if tool_def is not None and getattr(tool_def, "deterministic", False):
                cache_key = self._identical_call_key(tc.name, tc.arguments)
                if cache_key is not None and cache_key in self._called_identical:
                    cached = self._called_identical[cache_key]
                    messages.append(context.format_tool_result(tc.id, tc.name, deliver_tool_result(cached, self.memory.run_dir, self.registry)))
                    self._successful_call_keys[tc.id] = cache_key
                    self._called_ok.add(cache_key)
                    trace.write({
                        "type": "tool_result_cached",
                        "iter": iteration,
                        "tool": tc.name,
                        "call_id": tc.id,
                    })
                    react_trace.append({"type": "tool_result_cached", "tool": tc.name})
                    self._tool_progress.note("cached", tc.name)
                    self._emit(
                        "tool_result",
                        {
                            "tool": tc.name,
                            "status": "ok",
                            "elapsed_ms": 0,
                            "preview": cached[:200],
                            "call_id": tc.id,
                            "cached": True,
                        },
                    )
                    continue

            execution_plan.append((tc, None))

        if not execution_plan:
            return compact_requested, focus_topic

        # Preserve provider tool-result ordering. A synthetic blocked result
        # acts as a batch boundary, while adjacent authorized calls retain the
        # existing readonly-parallel/write-serial scheduler.
        authorized_segment: list[Any] = []

        def flush_authorized_segment() -> None:
            if not authorized_segment:
                return
            if len(authorized_segment) == 1:
                self._execute_single(
                    authorized_segment[0],
                    context,
                    messages,
                    trace,
                    react_trace,
                    iteration,
                )
            else:
                self._batch_execute(
                    authorized_segment,
                    context,
                    messages,
                    trace,
                    react_trace,
                    iteration,
                )
            authorized_segment.clear()

        for tc, blocked_result in execution_plan:
            if blocked_result is None:
                authorized_segment.append(tc)
                continue
            flush_authorized_segment()
            self._record_blocked_tool_call(
                tc,
                blocked_result,
                context,
                messages,
                trace,
                react_trace,
                iteration,
            )
        flush_authorized_segment()

        return compact_requested, focus_topic

    def _record_blocked_tool_call(
        self,
        tc: Any,
        result: str,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> None:
        """Record a blocked call without invoking its implementation.

        Args:
            tc: Provider tool-call object.
            result: Structured identity-gate error payload.
            context: Context builder.
            messages: Conversation messages.
            trace: Persistent trace writer.
            react_trace: Compact returned trace.
            iteration: Current iteration.
        """
        self._tool_progress.note("blocked", tc.name, _failure_code(result))
        args = _normalize_tool_run_dir(tc.arguments, self.memory.run_dir)
        redacted_args = redact_payload(args)
        event_args = {key: str(value)[:200] for key, value in redacted_args.items()}
        self._emit(
            "tool_call",
            {
                "tool": tc.name,
                "arguments": event_args,
                "iter": iteration,
                "call_id": tc.id,
                "blocked": True,
            },
        )
        trace.write(
            {
                "type": "tool_call",
                "iter": iteration,
                "tool": tc.name,
                "call_id": tc.id,
                "args": redacted_args,
                "blocked": True,
            }
        )
        self._finalize_tool_result(
            tc,
            result,
            0,
            context,
            messages,
            trace,
            react_trace,
            iteration,
            update_memory=False,
        )

    def _batch_execute(
        self,
        tool_calls: list,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> None:
        """Execute tools with read/write batching.

        Consecutive readonly tools run in parallel via ThreadPoolExecutor.
        Write tools run serially between readonly batches.

        Args:
            tool_calls: Tool calls to execute.
            context: ContextBuilder.
            messages: Conversation messages.
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration.
        """
        # Split into batches: consecutive readonly → parallel, write → serial
        batches: list[tuple[str, list]] = []
        current_ro: list = []

        for tc in tool_calls:
            tool_def = self.registry.get(tc.name)
            if tool_def and tool_def.is_readonly:
                current_ro.append(tc)
            else:
                if current_ro:
                    batches.append(("parallel", current_ro))
                    current_ro = []
                batches.append(("serial", [tc]))
        if current_ro:
            batches.append(("parallel", current_ro))

        for mode, batch in batches:
            # Stop launching further tool batches once cancelled — the current
            # batch (if any) finishes, but no new work starts.
            if self._cancel_event.is_set():
                break
            if mode == "parallel" and len(batch) > 1:
                self._execute_parallel(batch, context, messages, trace, react_trace, iteration)
            else:
                for tc in batch:
                    self._execute_single(tc, context, messages, trace, react_trace, iteration)

    def _execute_parallel(
        self,
        tool_calls: list,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> None:
        """Execute readonly tools in parallel using threads.

        Args:
            tool_calls: Readonly tool calls to execute in parallel.
            context: ContextBuilder.
            messages: Conversation messages.
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration.
        """
        # Prepare args + emit events
        runnable: list[tuple] = []
        for tc in tool_calls:
            args = _normalize_tool_run_dir(tc.arguments, self.memory.run_dir)
            redacted_args = redact_payload(args)
            event_args = {k: str(v)[:200] for k, v in redacted_args.items()}
            self._emit(
                "tool_call",
                {
                    "tool": tc.name,
                    "arguments": event_args,
                    "iter": iteration,
                    "call_id": tc.id,
                },
            )
            trace.write({"type": "tool_call", "iter": iteration, "tool": tc.name, "call_id": tc.id, "args": redacted_args})
            runnable.append((tc, args))

        # Execute in parallel — each worker gets its own heartbeat + progress emitter.
        def _run(tc_args: tuple) -> tuple:
            tc, args = tc_args
            result, elapsed_ms = self._invoke_tool(tc.name, args, call_id=tc.id)
            return tc, result, elapsed_ms

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(runnable), 8)) as pool:
            futures = [pool.submit(_run, item) for item in runnable]
            results = []
            for i, f in enumerate(futures):
                try:
                    results.append(f.result())
                except Exception as exc:
                    tc = runnable[i][0]
                    results.append((tc, json.dumps({"status": "error", "error": str(exc)}), 0))

        # Process results in order
        for tc, result, elapsed_ms in results:
            self._finalize_tool_result(tc, result, elapsed_ms, context, messages, trace, react_trace, iteration)

    def _execute_single(
        self,
        tc: Any,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
    ) -> None:
        """Execute a single tool call.

        Args:
            tc: Tool call object.
            context: ContextBuilder.
            messages: Conversation messages.
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration.
        """
        args = _normalize_tool_run_dir(tc.arguments, self.memory.run_dir)

        redacted_args = redact_payload(args)
        event_args = {k: str(v)[:200] for k, v in redacted_args.items()}
        self._emit(
            "tool_call",
            {
                "tool": tc.name,
                "arguments": event_args,
                "iter": iteration,
                "call_id": tc.id,
            },
        )
        trace.write({"type": "tool_call", "iter": iteration, "tool": tc.name, "call_id": tc.id, "args": redacted_args})
        logger.info(f"Tool call: {tc.name}({list(args.keys())})")

        result, elapsed_ms = self._invoke_tool(tc.name, args, call_id=tc.id)

        self._finalize_tool_result(tc, result, elapsed_ms, context, messages, trace, react_trace, iteration)

    def _invoke_tool(
        self,
        tool_name: str,
        args: Dict[str, Any],
        *,
        call_id: str,
    ) -> tuple[str, int]:
        """Execute a tool with heartbeat + structured progress emission.

        Installs a thread-local progress emitter so the tool may call
        ``emit_progress()`` without taking a callback parameter, and runs a
        background heartbeat timer that ticks every ``_heartbeat_interval_s()``
        seconds. Both event streams are forwarded through ``self._emit`` and
        therefore land in the same SSE bus and CLI dashboard as normal
        tool events.

        Args:
            tool_name: Tool name to execute.
            args: Tool arguments dict.
            call_id: Stable identity of this tool invocation.

        Returns:
            Tuple of (result_str, elapsed_ms).
        """
        readonly = self._is_tool_readonly(tool_name)
        timed_out = threading.Event()

        def _on_progress(event: ProgressEvent) -> None:
            if timed_out.is_set():
                return
            payload = event.to_dict()
            payload["tool"] = tool_name
            payload["call_id"] = call_id
            self._emit("tool_progress", payload)

        def _on_heartbeat(payload: Dict[str, Any]) -> None:
            if timed_out.is_set():
                return
            payload["call_id"] = call_id
            self._emit("tool_heartbeat", payload)

        t0 = _time.perf_counter()
        _tool_timeout = _tool_timeout_seconds()
        timeout = _tool_timeout if _tool_timeout > 0 else None
        timeout_label = _format_timeout(timeout) if timeout is not None else ""

        def _elapsed_ms() -> int:
            """Return milliseconds elapsed since tool start.

            Returns:
                Elapsed wall-clock time in milliseconds.
            """
            return int((_time.perf_counter() - t0) * 1000)

        def _heartbeat_timer() -> HeartbeatTimer:
            """Build the per-invocation heartbeat timer.

            Returns:
                HeartbeatTimer wired to this invocation's heartbeat emitter.
            """
            return HeartbeatTimer(
                tool_name=tool_name,
                interval=_heartbeat_interval_s(),
                emit=_on_heartbeat,
            )

        def _emit_timeout_progress(stage: str, message: str, **extra: Any) -> int:
            """Emit a timeout-related tool_progress event.

            Args:
                stage: Progress stage label ("timeout" or "timeout_warning").
                message: Human-readable timeout message.
                **extra: Additional payload fields.

            Returns:
                Elapsed milliseconds at emission time.
            """
            elapsed_ms = _elapsed_ms()
            payload: Dict[str, Any] = {
                "tool": tool_name,
                "call_id": call_id,
                "stage": stage,
                "message": message,
                "elapsed_s": round(elapsed_ms / 1000, 2),
            }
            payload.update(extra)
            self._emit("tool_progress", payload)
            return elapsed_ms

        if not readonly:
            # Write tools are never killed: a watchdog warns once past the
            # timeout, then the result is awaited to completion.
            finished = threading.Event()

            def _warn_if_stale() -> None:
                if timeout is None or finished.wait(timeout):
                    return
                _emit_timeout_progress(
                    "timeout_warning",
                    (
                        f"Write tool exceeded {timeout_label} timeout; "
                        "waiting for completion because it cannot be safely cancelled"
                    ),
                    readonly=False,
                )

            watchdog = threading.Thread(
                target=_warn_if_stale,
                name=f"tool-watchdog-{tool_name}",
                daemon=True,
            )
            watchdog.start()
            _set_emitter(_on_progress)
            try:
                with _heartbeat_timer():
                    result = self.registry.execute(tool_name, args)
            finally:
                finished.set()
                _set_emitter(None)
            return result or "", _elapsed_ms()

        # Readonly tools run in a worker thread so a hung tool becomes a
        # bounded error: late results are discarded and the emitters are
        # suppressed via the timed_out event.
        result_queue: queue.Queue[tuple[str | None, BaseException | None]] = queue.Queue(maxsize=1)

        def _worker() -> None:
            _set_emitter(_on_progress)
            try:
                result_queue.put((self.registry.execute(tool_name, args), None))
            except BaseException as exc:  # noqa: BLE001 - propagate through caller thread
                result_queue.put((None, exc))
            finally:
                _set_emitter(None)

        worker = threading.Thread(
            target=_worker,
            name=f"tool-{tool_name}",
            daemon=True,
        )
        worker.start()
        with _heartbeat_timer():
            try:
                result, exc = result_queue.get(timeout=timeout)
            except queue.Empty:
                timed_out.set()
                elapsed_ms = _emit_timeout_progress(
                    "timeout", f"Tool exceeded {timeout_label} timeout"
                )
                return (
                    json.dumps(
                        {
                            "status": "error",
                            "error_code": "tool_timeout",
                            "tool": tool_name,
                            "timeout_seconds": timeout,
                            "message": f"Tool exceeded {timeout_label} timeout",
                        },
                        ensure_ascii=False,
                    ),
                    elapsed_ms,
                )
        if exc is not None:
            raise exc
        return result or "", _elapsed_ms()

    def _is_tool_readonly(self, tool_name: str) -> bool:
        """Return whether a tool is known to be side-effect free."""
        get_tool = getattr(self.registry, "get", None)
        if not callable(get_tool):
            return False
        try:
            tool_def = get_tool(tool_name)
        except Exception:  # noqa: BLE001 - unknown classification is not readonly
            return False
        return bool(tool_def and getattr(tool_def, "is_readonly", False))

    def _readonly_replay_allowed(self, tool_def: Any, arguments: Mapping[str, Any]) -> bool:
        """Whether an exact readonly result may be restored after compaction.

        This is intentionally narrower than ``is_readonly``: deterministic
        calls already use the existing cache, and ``no_cache=True`` explicitly
        requests a fresh read. Repeatable calls require explicit opt-in because
        they may otherwise be intentionally refreshed.
        """
        if tool_def is None or not getattr(tool_def, "is_readonly", False):
            return False
        if getattr(tool_def, "deterministic", False):
            return False
        try:
            if bool((arguments or {}).get("no_cache")):
                return False
        except AttributeError:
            return False
        if getattr(tool_def, "repeatable", False):
            return bool(getattr(tool_def, "replay_after_compaction", False))
        return True

    def _consume_readonly_replay_visibility(
        self, messages: list, trace: TraceWriter, iteration: int
    ) -> None:
        """Release replay leases once a successful model request carried them."""
        visible = {
            msg.get("tool_call_id")
            for msg in messages
            if msg.get("role") == "tool"
            and msg.get("tool_call_id") in self._readonly_replay_visibility_pending
            and not _result_data_gone(msg.get("content"))
        }
        for call_id in sorted(visible):
            self._readonly_replay_visibility_pending.discard(call_id)
            trace.write({"type": "replay_visibility_consumed", "iter": iteration, "call_id": call_id})

    def _readable_success_keys(self, messages: list) -> set[tuple[str, str]]:
        """Identify surviving successful results, not synthetic skip/stub calls."""
        return {
            self._successful_call_keys[msg["tool_call_id"]]
            for msg in messages
            if msg.get("role") == "tool"
            and msg.get("tool_call_id") in self._successful_call_keys
            and not _result_data_gone(msg.get("content"))
        }

    def _unblock_lost_readonly_results(
        self, messages: list, readable_before: set[tuple[str, str]]
    ) -> list[str]:
        """Recover only lost exact queries; context loss cannot replay writes."""
        lost = readable_before - self._readable_success_keys(messages)
        reopened = {
            key for key in lost & self._called_ok if self._is_tool_readonly(key[0])
        }
        self._called_ok.difference_update(reopened)
        # Every lost call reopens, as before replay existed; the replay budget
        # only decides, at call time, whether it is restored or run again.
        self._readonly_replay_protected.difference_update(reopened)
        self._readonly_replay_ready.update(
            key for key in reopened if key in self._readonly_replay_cache
        )
        return sorted({key[0] for key in reopened})

    def _identical_call_key(self, tool_name: str, arguments: Mapping[str, Any]) -> tuple[str, str] | None:
        """Build a stable key identifying a deterministic tool invocation.

        Args:
            tool_name: Tool name.
            arguments: Tool arguments.

        Returns:
            Tuple of (tool_name, canonical JSON of the args) usable as a
            dict key, or None when the args cannot be serialized.
        """
        try:
            normalized = _normalize_tool_run_dir(dict(arguments or {}), self.memory.run_dir)
            canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 - un-serializable args are never cached
            return None
        return (tool_name, canonical)

    def _finalize_tool_result(
        self,
        tc: Any,
        result: str,
        elapsed_ms: int,
        context: ContextBuilder,
        messages: list,
        trace: TraceWriter,
        react_trace: list,
        iteration: int,
        *,
        update_memory: bool = True,
    ) -> None:
        """Record a tool result: update memory, append message, write trace, emit event.

        Args:
            tc: Tool call object.
            result: Raw tool result string.
            elapsed_ms: Execution time in milliseconds.
            context: ContextBuilder.
            messages: Conversation messages.
            trace: TraceWriter.
            react_trace: React trace list.
            iteration: Current iteration.
            update_memory: Whether this call reached the tool implementation.
        """
        # Scrub before caching, truncation and model context, not just the
        # downstream trace/event preview. Shell stdout may hold credentials.
        result = redact_tool_result(result)
        if update_memory:
            self._update_memory(tc.name)

        # A tool completed - real progress for the stall watchdog.
        self._last_activity_wall = _time.time()

        success = _is_tool_success(result)
        if update_memory:
            self._tool_progress.record(
                tc.name,
                self._identical_call_key(tc.name, tc.arguments),
                result,
                success=success,
                is_readonly=self._is_tool_readonly(tc.name),
            )
        if success:
            recorded_key = self._identical_call_key(tc.name, tc.arguments)
            if recorded_key is not None:
                self._called_ok.add(recorded_key)
                self._successful_call_keys[tc.id] = recorded_key
            if tc.name == "backtest":
                try:
                    _archive_backtest_result(result, self.memory.run_dir, source_call_id=tc.id)
                except OSError as exc:
                    logger.warning("Could not archive backtest output into active run: %s", exc)
            if tc.name in {"write_file", "edit_file"}:
                self._record_written_target(tc.arguments)

        if self._identity is not None:
            self._identity.ingest_tool_result(
                tool_name=tc.name,
                arguments=_normalize_tool_run_dir(tc.arguments, self.memory.run_dir),
                result=result,
                call_id=tc.id,
                success=success,
            )
            if tc.name == "search_symbol":
                trace.write(
                    {
                        "type": "identity_state",
                        "iter": iteration,
                        "call_id": tc.id,
                        "identity": self._identity.identity_summary(),
                    }
                )

        # Cache successful deterministic results so an identical later call is
        # served without re-execution (regression: repeated financial_rigor
        # calcs after compaction, 2026-08-20 INTC run). Readonly results use a
        # separate run-scoped replay cache: it is only consulted after
        # compaction has made that exact result unreadable, and only for tools
        # whose replay policy allows it.
        if success:
            try:
                tool_def = self.registry.get(tc.name)
            except Exception:  # noqa: BLE001
                tool_def = None
            cache_key = self._identical_call_key(tc.name, tc.arguments)
            if tool_def is not None and getattr(tool_def, "deterministic", False):
                if cache_key is not None:
                    self._called_identical[cache_key] = result
            elif (
                cache_key is not None
                and self._readonly_replay_allowed(tool_def, tc.arguments)
            ):
                self._readonly_replay_cache[cache_key] = result
            # Its payload is visible again, so nothing is waiting to be restored.
            self._readonly_replay_ready.discard(cache_key)
            # A write can change what a readonly call reads (a factor file, a
            # config), so no result cached before it may be replayed after it.
            if update_memory and not self._is_tool_readonly(tc.name):
                self._readonly_replay_cache.clear()
                self._readonly_replay_ready.clear()
                self._readonly_replay_protected.clear()

        status = "ok" if success else "error"
        truncated = deliver_tool_result(result, self.memory.run_dir, self.registry)
        messages.append(context.format_tool_result(tc.id, tc.name, truncated))

        # One redaction feeds every subscriber below: the persisted trace
        # record, the react trace, and the SSE preview.
        trace_result = redact_tool_result(result)
        trace.write_tool_result(
            call_id=tc.id,
            result=trace_result,
            tool_name=tc.name,
            status=status,
            elapsed_ms=elapsed_ms,
            iteration=iteration,
        )
        preview = trace_result[:200]
        artifact = None
        if status == "ok" and tc.name in {"write_file", "render_shadow_report"}:
            try:
                payload = json.loads(trace_result)
                from src.tools.report_artifacts import report_path
                report_id = payload.get("report_id", "")
                path = report_path(report_id) if isinstance(report_id, str) else None
                if path is not None:
                    artifact = {"report_id": report_id, "filename": path.name,
                                "download_url": f"/api/reports/{report_id}"}
            except (ValueError, TypeError, AttributeError, OSError):
                pass
        react_trace.append({"type": "tool_call", "tool": tc.name, "result_preview": preview})
        self._emit(
            "tool_result",
            {
                "tool": tc.name,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "preview": preview,
                "call_id": tc.id,
                **({"artifact": artifact} if artifact else {}),
            },
        )

    def _update_memory(self, tool_name: str) -> None:
        """Update workspace memory counters after tool execution."""
        self.memory.increment(tool_name)
