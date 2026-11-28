"""Context budgets, overflow recovery and five-layer compaction for a turn."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from src.kernel import events as vocabulary
from src.config.accessor import get_env_config

from src.session.context_budget import (
    MIN_CONVERSATION_TOKENS, CompactionBudget, ContextMeter,
    estimate_tokens, parse_context_limit, resolve_window,
)
from src.session.compaction_ops import (
    _context_collapse, _fix_tool_pairs, _microcompact, _summary_chunks,
    _tail_cut_index, _FOCUS_SECTION,
    _ITERATIVE_UPDATE_PROMPT, _STRUCTURED_SUMMARY_PROMPT,
)
from src.session.request import SummaryUnavailable, request_summary

logger = logging.getLogger(__name__)


class ContextCompactor:
    """Own context measurement and all five compaction layers.

    Args:
        llm: Model client used for summary requests.
        provider: Provider label used for context sizing.
        conversation: Conversation state and thread recorder.
        replay: Replay controller that tracks tool results awaiting visibility.
        state_summary: Callback that supplies the current agent state as text.
        should_stop: Callback that reports whether the run should stop.
        record_usage: Callback that records model usage.
        verification_ledger: Callback that extracts verified values from the compressed messages.
        timeout_seconds: Callback that resolves the model request timeout in seconds.
        threshold_override: Callback that returns an explicit token threshold or None to use the
            model window.
        hook: Callback that runs the PreCompact hook.
        emit: Callback that publishes compaction events.
    """

    def __init__(
        self, *, llm, provider, conversation, replay, state_summary, should_stop,
        record_usage, verification_ledger, timeout_seconds, threshold_override, hook, emit,
    ) -> None:
        self.llm = llm
        self.provider = provider
        self.conversation = conversation
        self.replay = replay
        self.state_summary = state_summary
        self.should_stop = should_stop
        self.record_usage = record_usage
        self.verification_ledger = verification_ledger
        self.timeout_seconds = timeout_seconds
        self.threshold_override = threshold_override
        self.hook = hook
        self.emit = emit
        self.reset()

    def reset(self) -> None:
        """Reset run-scoped context state."""
        self.previous_summary = ""
        self.context_meter = ContextMeter()
        self.learned_context_window = None
        self.compacted_to_tokens = None
        self.tool_schema_tokens = 0

    def update_tool_schemas(self, tools: list) -> None:
        """Include the current registry schemas in the next compaction decision.

        Args:
            tools: Tool schemas currently exposed to the model.
        """
        self.tool_schema_tokens = estimate_tokens(tools)

    def observe_request(self, usage, messages: list, tools: list | None) -> None:
        """Anchor the budget on the successful projection and its actual schemas.

        Args:
            usage: Provider usage with a context or input token count, when available.
            messages: Exact messages sent in the successful request.
            tools: Tool schemas sent in that request, or None.
        """
        input_tokens = None
        if isinstance(usage, dict):
            input_tokens = usage.get("context_input_tokens", usage.get("input_tokens"))
        self.context_meter.observe(
            input_tokens, messages, tool_schema_tokens=estimate_tokens(tools) if tools else 0,
        )

    def _context_budget(self, messages: list) -> CompactionBudget:
        """Compaction thresholds for the active model's real context window."""
        cfg = get_env_config()
        model = getattr(self.llm, "model_name", "") or cfg.llm.langchain_model_name
        window, source = resolve_window(
            self.provider,
            str(model or ""),
            env_window=cfg.agent_tuning.vibe_trading_context_window,
            learned_window=self.learned_context_window,
        )
        return CompactionBudget(
            window=window,
            source=source,
            max_tokens=cfg.agent_tuning.vibe_trading_context_max_tokens,
            static_tokens=self.context_meter.static(messages, self.tool_schema_tokens),
        )

    def _prompt_tokens(self, messages: list) -> int:
        """Real-token size the next request would have."""
        return self.context_meter.tokens(messages, self.tool_schema_tokens)

    def compact_if_needed(
        self, messages: list, run_dir: Path, trace, iteration: int, current_iter: int, *, session_id: str,
    ) -> None:
        """Apply the model-window budget or the explicit legacy test threshold.

        Args:
            messages: Conversation messages that compaction may replace in place.
            run_dir: Run directory used by summary requests.
            trace: Trace sink for compaction records.
            iteration: Iteration used by the model-budget and microcompaction paths.
            current_iter: Iteration reported to the hook and explicit-threshold summarizer.
            session_id: Session ID passed to the PreCompact hook.
        """
        threshold = self.threshold_override()
        if threshold is None:
            self._compact_to_budget(messages, run_dir, trace, iteration, current_iter)
            return
        pending = self.replay._readonly_replay_visibility_pending
        tokens = estimate_tokens(messages)
        if tokens > int(threshold * 0.5):
            self._microcompact_and_unblock(messages, trace, iteration, preserve_tool_call_ids=pending)
            tokens = estimate_tokens(messages)
        if tokens > int(threshold * 0.7):
            self._collapse(messages)
            tokens = estimate_tokens(messages)
        if tokens > threshold:
            decision = self.hook("PreCompact", {
                "session_id": session_id, "iteration": current_iter, "prompt_tokens": tokens,
            })
            if decision is None or not decision.denied:
                self.auto_compact(messages, run_dir, trace, iteration=current_iter)

    def _collapse(self, messages: list) -> None:
        before = json.loads(json.dumps(messages, default=str, ensure_ascii=False))
        _context_collapse(messages, preserve_tool_call_ids=self.replay._readonly_replay_visibility_pending)
        self._record_compaction_layer(messages, 2, before)

    def _compact_to_budget(
        self,
        messages: list,
        run_dir: Path,
        trace: Any,
        iteration: int,
        current_iter: int,
        *,
        force: bool = False,
    ) -> None:
        """Run the compaction layers the prompt has actually grown into."""
        budget = self._context_budget(messages)
        tokens = self._prompt_tokens(messages)
        if tokens > budget.micro_at or force:
            decision = self.hook(
                "PreCompact",
                {"session_id": getattr(self, "_session_id", ""), "iteration": current_iter, "prompt_tokens": tokens},
            )
            if decision is not None and decision.denied:
                logger.info("PreCompact hook refused compaction: %s", decision.reason)
                return
        if tokens > budget.micro_at:
            # Stop clearing old results once the prompt fits.
            self._microcompact_and_unblock(
                messages,
                trace,
                iteration,
                target_tokens=budget.micro_at,
                measure=self._prompt_tokens,
                preserve_tool_call_ids=self.replay._readonly_replay_visibility_pending,
            )
            tokens = self._prompt_tokens(messages)
        if tokens > budget.collapse_at:
            self._collapse(messages)
            tokens = self._prompt_tokens(messages)
        # Require regrowth before paying for another summary of a tiny window.
        regrown = (
            self.compacted_to_tokens is None
            or tokens > self.compacted_to_tokens + MIN_CONVERSATION_TOKENS
        )
        if force or (tokens > budget.compact_at and regrown):
            logger.info(
                "Auto compact triggered: %s real tokens > %s (window %s from %s)",
                tokens, budget.compact_at, budget.window, budget.source,
            )
            self.auto_compact(messages, run_dir, trace, iteration=current_iter)
            self.compacted_to_tokens = self._prompt_tokens(messages)

    def recover_context_overflow(
        self,
        exc: Exception,
        messages: list,
        run_dir: Path,
        trace: Any,
        iteration: int,
        current_iter: int,
    ) -> None:
        """Learn the model limit and compact messages in place.

        Args:
            exc: The provider error that reported the overflow.
            messages: Message list, mutated in place by compaction.
            run_dir: Active run directory.
            trace: Run trace that receives overflow and compaction records.
            iteration: Loop-local iteration.
            current_iter: Session-wide iteration.
        """
        sent = self._prompt_tokens(messages)
        stated = parse_context_limit(str(exc))
        self.learned_context_window = stated or int(sent * 0.9)
        trace.write({
            "type": "context_overflow",
            "iter": current_iter,
            "prompt_tokens": sent,
            "stated_limit": stated,
            "learned_window": self.learned_context_window,
        })
        self._compact_to_budget(messages, run_dir, trace, iteration, current_iter, force=True)

    def _microcompact_and_unblock(
        self,
        messages: list,
        trace: Any,
        iteration: int,
        *,
        target_tokens: Optional[int] = None,
        measure: Optional[Callable[[list], int]] = None,
        preserve_tool_call_ids: Optional[set[str]] = None,
    ) -> list[str]:
        """Run layer-1 microcompact and re-open lost readonly call identities."""
        readable_before = self.replay._readable_success_keys(messages)
        before = json.loads(json.dumps(messages, default=str, ensure_ascii=False))
        _microcompact(
            messages,
            target_tokens=target_tokens,
            measure=measure,
            preserve_tool_call_ids=preserve_tool_call_ids,
        )
        self._record_compaction_layer(messages, 1, before)
        unreadable_tools = self.replay._unblock_lost_readonly_results(messages, readable_before)
        if unreadable_tools:
            trace.write({
                "type": "microcompact_cleared",
                "iter": iteration,
                "tools": unreadable_tools,
            })
        return unreadable_tools

    def _record_compaction_layer(
        self, messages: list, layer: int, before: list[dict[str, Any]]
    ) -> None:
        """Persist the exact post-layer message view for thread replay."""
        if self.conversation.thread is None:
            return
        # Both in-place layers preserve message order.
        changed = [current for previous, current in zip(before, messages) if previous != current]
        self.conversation.thread.compaction_layer(layer, changed)

    def _summarize_chunks(
        self, head: list[dict[str, Any]], focus_section: str, run_dir: Path, iteration: int
    ) -> tuple[str, list[str]] | None:
        """Summarize every folded chunk while charging each provider call."""
        # Opaque provider items add tokens without helping the summarizer.
        chunks = _summary_chunks(
            [{k: v for k, v in m.items() if k != "provider_items"} for m in head]
        )
        logger.info("Auto compact: folding %d summary chunks", len(chunks))
        summary = self.previous_summary or ""
        degraded_compact = False
        timeout = self.timeout_seconds()
        for conv_text in chunks:
            if self.should_stop():
                return
            if not summary:
                prompt = _STRUCTURED_SUMMARY_PROMPT.format(focus_section=focus_section) + conv_text
            else:
                prompt = _ITERATIVE_UPDATE_PROMPT.format(
                    previous_summary=summary,
                    new_turns=conv_text,
                    focus_section=focus_section,
                )

            try:
                summary_resp = request_summary(self.llm, prompt, timeout)
            except SummaryUnavailable:
                self.record_usage(run_dir, None, iteration, purpose="compaction")
                degraded_compact = True
                break
            except Exception:
                self.record_usage(run_dir, None, iteration, purpose="compaction")
                raise
            self.record_usage(
                run_dir, getattr(summary_resp, "usage_metadata", None), iteration,
                purpose="compaction",
            )
            if self.should_stop():
                return
            if summary_resp.content:
                summary = summary_resp.content
        if degraded_compact and not summary:
            summary = (
                "[compaction degraded: LLM summarization timed out or failed; "
                "earlier tool results were truncated. Raw conversation items "
                "remain available in the session thread."
            )
        return summary, chunks

    def auto_compact(
        self,
        messages: list,
        run_dir: Path,
        trace: Any,
        focus_topic: str = "",
        iteration: int = 0,
    ) -> None:
        """Summarize older messages while preserving a recent tail.

        Args:
            messages: Message list, replaced in place when a summary is produced.
            run_dir: Run directory used by summary requests.
            trace: Trace sink for compaction records.
            focus_topic: Optional topic to prioritize in the summary.
            iteration: Current trace iteration.
        """
        if self.should_stop():
            return
        readable_before = self.replay._readable_success_keys(messages)
        system_msg = messages[0]
        body = messages[1:]

        cut_idx = _tail_cut_index(body)

        head = body[:cut_idx]
        tail = body[cut_idx:]

        if not head:
            # All body fits in tail budget — force a split to avoid infinite loop
            if len(body) > 2:
                cut_idx = max(1, len(body) // 2)
                head = body[:cut_idx]
                tail = body[cut_idx:]
            else:
                logger.warning("Auto compact: nothing to compress (body too small)")
                return

        # Keep each replayed pair until a successful writing request sees it.
        pending = self.replay._readonly_replay_visibility_pending
        leased = [msg for msg in head if (
            msg.get("role") == "tool" and msg.get("tool_call_id") in pending
        ) or any(call.get("id") in pending for call in msg.get("tool_calls") or [])]
        if leased:
            head = [msg for msg in head if all(msg is not kept for kept in leased)]
            tail = leased + tail

        focus_section = _FOCUS_SECTION.format(topic=focus_topic) if focus_topic else ""

        summarized = self._summarize_chunks(
            head, focus_section, run_dir, iteration,
        )
        if summarized is None:
            return
        summary, chunks = summarized
        self.previous_summary = summary

        # Carry verified values forward so compaction does not force recalculation.
        verification_ledger = self.verification_ledger(head)

        tokens_before = estimate_tokens(messages)
        trace.write(
            {
                "type": "compact",
                "iter": iteration,
                "tokens_before": tokens_before,
                "focus_topic": focus_topic or "(none)",
                "summary_chunks": len(chunks),
                "summary": summary,
            },
        )
        self.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.CONTEXT_COMPACTED, "tokens_before": tokens_before, "summary": summary[:200]})

        state_summary = self.state_summary()
        compressed = f"[Conversation compressed — handoff summary]\n\n{summary}"
        if verification_ledger:
            compressed += (
                "\n\n[Verified tool results from the compressed turns - do NOT "
                "re-run these tools, they are already verified]:\n"
                + verification_ledger
            )
        if state_summary and state_summary != "(empty state)":
            compressed += f"\n\nCurrent agent state:\n{state_summary}"

        summary_message = {"role": "user", "content": f"{compressed}\n\n<system>Continue from the summary above.</system>"}
        messages[:] = [system_msg, summary_message, *tail]

        _fix_tool_pairs(messages)
        self.replay._unblock_lost_readonly_results(messages, readable_before)
        if self.conversation.records_into(messages):
            self.conversation.thread.compaction(summary_message, tail)
