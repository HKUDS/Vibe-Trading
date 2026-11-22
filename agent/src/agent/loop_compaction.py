"""Context budgeting and compaction state for the agent turn loop.

The component keeps model-window measurements, learned provider limits,
compaction progress, and the prior summary together. The owner supplies
identity, thread, usage, and event callbacks used by the existing logic.
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from src.config.accessor import get_env_config

from src.agent.context_budget import (
    MIN_CONVERSATION_TOKENS, CompactionBudget, ContextMeter,
    estimate_tokens, parse_context_limit, resolve_window,
)
from src.agent.context_compact import (
    _context_collapse, _fix_tool_pairs, _microcompact, _summary_chunks,
    _tail_cut_index, _verification_ledger, _FOCUS_SECTION,
    _ITERATIVE_UPDATE_PROMPT, _STRUCTURED_SUMMARY_PROMPT,
)
from src.agent.tuning import _llm_timeout_seconds

logger = logging.getLogger(__name__)


class ContextCompactor:
    """Own context measurement and all five compaction layers."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.previous_summary = ""
        self.context_meter = ContextMeter()
        self.learned_context_window: int | None = None
        self.compacted_to_tokens: int | None = None
        self.tool_schema_tokens = 0
        self.timeout_provider = _llm_timeout_seconds

    def reset(self) -> None:
        """Reset run-scoped context state."""
        self.previous_summary = ""
        self.context_meter = ContextMeter()
        self.learned_context_window = None
        self.compacted_to_tokens = None
        self.tool_schema_tokens = 0
        self.timeout_provider = _llm_timeout_seconds

    def _context_budget(self, messages: list) -> CompactionBudget:
        """Compaction thresholds for the active model's real context window."""
        cfg = get_env_config()
        provider = (self.owner._llm_runtime.provider or "").strip().lower().replace("_", "-")
        model = getattr(self.owner.llm, "model_name", "") or cfg.llm.langchain_model_name
        window, source = resolve_window(
            provider,
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
        """Run the compaction layers the prompt has actually grown into.

        Args:
            messages: Message list, mutated in place.
            run_dir: Active run directory.
            trace: Run trace.
            iteration: Loop-local iteration (the microcompact event's key).
            current_iter: Session-wide iteration number.
            force: Summarise even under budget (the provider said it overflowed).
        """
        budget = self._context_budget(messages)
        tokens = self._prompt_tokens(messages)
        if tokens > budget.micro_at or force:
            decision = self.owner._run_hook(
                "PreCompact",
                {"session_id": getattr(self, "_session_id", ""), "iteration": current_iter, "prompt_tokens": tokens},
            )
            if decision is not None and decision.denied:
                logger.info("PreCompact hook refused compaction: %s", decision.reason)
                return
        if tokens > budget.micro_at:
            # Oldest results first and only until the prompt fits again:
            # clearing all but the last few is what sent a 12-company
            # comparison back to re-fetch its own evidence.
            self._microcompact_and_unblock(
                messages,
                trace,
                iteration,
                target_tokens=budget.micro_at,
                measure=self._prompt_tokens,
                preserve_tool_call_ids=self.owner._readonly_replay_visibility_pending,
            )
            tokens = self._prompt_tokens(messages)
        if tokens > budget.collapse_at:
            before = json.loads(json.dumps(messages, default=str, ensure_ascii=False))
            _context_collapse(messages, preserve_tool_call_ids=self.owner._readonly_replay_visibility_pending)
            self._record_compaction_layer(messages, 2, before)
            tokens = self._prompt_tokens(messages)
        # A summary keeps the static prompt plus a ~20K-token tail, so on a
        # window that small the prompt stays over the line after compacting;
        # without this every later iteration paid for another summary call.
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

    def _recover_context_overflow(
        self,
        exc: Exception,
        messages: list,
        run_dir: Path,
        trace: Any,
        iteration: int,
        current_iter: int,
    ) -> None:
        """Learn the real window from a context-length error and compact to it.

        A model missing from ``context_windows.json`` runs on the default
        window; if that is larger than the real one the provider says so, and
        the run shrinks to the limit instead of failing.

        Args:
            exc: The provider error that reported the overflow.
            messages: Message list, mutated in place.
            run_dir: Active run directory.
            trace: Run trace.
            iteration: Loop-local iteration.
            current_iter: Session-wide iteration number.
        """
        sent = self._prompt_tokens(messages)
        stated = parse_context_limit(str(exc))
        # The provider's own number when it gives one; otherwise the prompt
        # that did not fit, with a margin for our estimate of it.
        self.learned_context_window = stated or int(sent * 0.9)
        trace.write({
            "type": "context_overflow",
            "iter": current_iter,
            "prompt_tokens": sent,
            "stated_limit": stated,
            "learned_window": self.learned_context_window,
        })
        self.owner._compact_to_budget(messages, run_dir, trace, iteration, current_iter, force=True)

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
        """Run layer-1 microcompact and re-open lost readonly call identities.

        A readable result for another argument variant, or a synthetic skip,
        cannot satisfy "use the previous result". Keep an exact call gated if
        any successful copy survives; never re-open mutating tools just because
        their results were compacted away.

        Args:
            messages: Message list, mutated in place by the compaction.
            trace: Run trace; a ``microcompact_cleared`` event is written
                whenever the ledger is re-opened, because this layer used to
                act silently and left no evidence for diagnosis.
            iteration: Current ReAct iteration, recorded on the trace event.
            target_tokens: Clear oldest-first only until the prompt fits.
            measure: Prompt-size function for ``target_tokens``.
            preserve_tool_call_ids: Replayed results still owed one model request.

        Returns:
            The tool names re-opened, for callers and tests to assert on.
        """
        readable_before = self.owner._readable_success_keys(messages)
        before = json.loads(json.dumps(messages, default=str, ensure_ascii=False))
        _microcompact(
            messages,
            target_tokens=target_tokens,
            measure=measure,
            preserve_tool_call_ids=preserve_tool_call_ids,
        )
        self._record_compaction_layer(messages, 1, before)
        unreadable_tools = self.owner._unblock_lost_readonly_results(messages, readable_before)
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
        if self.owner._thread is None:
            return
        changed = []
        for previous, current in zip(before, messages):
            # The list order is stable for both in-place compaction layers.
            if previous != current:
                changed.append(current)
        self.owner._thread.compaction_layer(layer, changed)

    def _summarize_chunks(
        self, head: list[dict[str, Any]], focus_section: str, run_dir: Path, iteration: int
    ) -> tuple[str, list[str]] | None:
        """Summarize every folded chunk while charging each provider call."""
        # Fold every head chunk so no message falls between the summary prompt
        # and the preserved tail. The first fresh chunk gets the full
        # structured handoff; subsequent chunks incrementally update it.
        # Encrypted provider items are opaque to the summariser and only
        # cost tokens there; the messages they belong to are being folded.
        chunks = _summary_chunks(
            [{k: v for k, v in m.items() if k != "provider_items"} for m in head]
        )
        logger.info("Auto compact: folding %d summary chunks", len(chunks))
        summary = self.previous_summary or ""
        degraded_compact = False
        _compact_timeout = self.timeout_provider()
        for conv_text in chunks:
            if self.owner._cancel_event.is_set() or self.owner._budget_stop_reason is not None:
                return
            # Structured template while there is still nothing to update — that
            # covers a fresh session's first chunk and the corner case where
            # every fold so far returned empty content.
            if not summary:
                prompt = _STRUCTURED_SUMMARY_PROMPT.format(focus_section=focus_section) + conv_text
            else:
                prompt = _ITERATIVE_UPDATE_PROMPT.format(
                    previous_summary=summary,
                    new_turns=conv_text,
                    focus_section=focus_section,
                )

            # A silent provider stall on the summary call used to freeze the
            # whole run (no chunk arrives, so nothing aborts it). The provider
            # httpx timeout only bounds time-between-bytes, not total time, and
            # LangChain does not honor a per-call config "timeout", so a slow
            # but alive server can run for many minutes. Enforce a hard
            # wall-clock deadline via a daemon thread; on expiry fall back to
            # hard truncation so the loop continues.
            _compact_result: list = []
            _compact_error: list = []

            def _run_compact_summary() -> None:
                try:
                    resp = self.owner.llm.chat(
                        [{"role": "user", "content": prompt}],
                        timeout=_compact_timeout if _compact_timeout > 0 else None,
                    )
                    _compact_result.append(resp)
                except BaseException as exc:  # noqa: BLE001 - compaction must not crash the run
                    _compact_error.append(exc)

            if _compact_timeout > 0:
                # A new thread starts with an empty context, so the session
                # bound by run() (x-opencode-session, #1416) would not reach
                # this call: run it inside a copy of the caller's context.
                worker = threading.Thread(
                    target=contextvars.copy_context().run,
                    args=(_run_compact_summary,),
                    name="compact-summary",
                    daemon=True,
                )
                worker.start()
                worker.join(timeout=_compact_timeout)
                if worker.is_alive():
                    logger.warning(
                        "Auto compact summary call exceeded %.1fs; degrading compaction",
                        _compact_timeout,
                    )
                    degraded_compact = True
                    self.owner._account_llm_usage(run_dir, None, iteration, purpose="compaction")
                    break
                if _compact_error:
                    logger.warning(
                        "Auto compact LLM call failed (%s); degrading compaction",
                        _compact_error[0],
                    )
                    degraded_compact = True
                    self.owner._account_llm_usage(run_dir, None, iteration, purpose="compaction")
                    break
                summary_resp = _compact_result[0]
            else:
                try:
                    summary_resp = self.owner.llm.chat([{"role": "user", "content": prompt}])
                except Exception:
                    self.owner._account_llm_usage(run_dir, None, iteration, purpose="compaction")
                    raise
            self.owner._account_llm_usage(
                run_dir, getattr(summary_resp, "usage_metadata", None), iteration,
                purpose="compaction",
            )
            if self.owner._cancel_event.is_set() or self.owner._budget_stop_reason is not None:
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
        """Layer 3/4/5: structured LLM summary with token-budget tail protection.

        Upgrades over the original:
          - Token-budget tail: keeps ~20K tokens of recent messages (not a fixed count).
          - Structured summary template: preserves goal, progress, decisions, files, etc.
          - Iterative update: Nth compression updates previous summary, zero info decay.
          - Tool pair fix: repairs orphaned tool_call/tool_result after compression.
          - Focus-topic: optionally prioritize specific topic in summary.

        Args:
            messages: Message list (replaced in place).
            run_dir: Run directory.
            trace: Any.
            focus_topic: Optional topic to prioritize in the summary.
            iteration: Current trace iteration.
        """
        self.timeout_provider = _llm_timeout_seconds
        if self.owner._cancel_event.is_set() or self.owner._budget_stop_reason is not None:
            return
        readable_before = self.owner._readable_success_keys(messages)
        system_msg = messages[0]
        body = messages[1:]

        # Token-budget tail: size messages with their tool-call arguments so
        # oversized tool calls are folded instead of hiding in the tail.
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

        # Replayed results are owed one successful writing request. Keep the
        # entire assistant-call/result pair out of summaries until then.
        pending = self.owner._readonly_replay_visibility_pending
        leased = [msg for msg in head if (
            msg.get("role") == "tool" and msg.get("tool_call_id") in pending
        ) or any(call.get("id") in pending for call in msg.get("tool_calls") or [])]
        if leased:
            head = [msg for msg in head if all(msg is not kept for kept in leased)]
            tail = leased + tail

        # Build focus section
        focus_section = _FOCUS_SECTION.format(topic=focus_topic) if focus_topic else ""

        summarized = self._summarize_chunks(
            [{k: v for k, v in m.items() if k != "provider_items"} for m in head],
            focus_section, run_dir, iteration,
        )
        if summarized is None:
            return
        summary, chunks = summarized
        self.previous_summary = summary

        # Preserve deterministic verification records across the compaction.
        # The LLM summary does not reliably retain exact calc results, so the
        # model used to re-run the same financial_rigor expressions after a
        # compact to "re-verify" numbers it could no longer see (2026-08-20
        # INTC run: identical calcs re-ran 5-9x each). Re-attach a terse
        # ledger of already-verified values so the model does not re-run them.
        verification_ledger = _verification_ledger(head)

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
        self.owner._emit("item.delta", {"kind": "context.compacted", "tokens_before": tokens_before, "summary": summary[:200]})

        # Reconstruct: system + summary + acknowledge + preserved tail
        state_summary = self.owner.memory.to_summary()
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
        messages.clear()
        messages.append(system_msg)
        messages.append(summary_message)
        messages.extend(tail)

        # Fix orphaned tool pairs in the reconstructed message list
        _fix_tool_pairs(messages)
        self.owner._unblock_lost_readonly_results(messages, readable_before)
        # The next turn replays from this summary instead of from the items it
        # folded; those items stay in the thread file.
        if self.owner._records_into(messages):
            self.owner._thread.compaction(summary_message, tail)
