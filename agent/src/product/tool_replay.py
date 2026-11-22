"""Run-scoped call identities, deterministic caching and compaction replay."""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from src.agent.context_compact import _replay_context_result, _result_data_gone
from src.product.result_artifacts import deliver_tool_result
from src.product.tool_results import _normalize_tool_run_dir
from src.tools.redaction import redact_tool_result

logger = logging.getLogger(__name__)


# Compaction recovery is a bounded reliability aid, not an alternate research
# loop: a run restores at most this many lost readonly payloads from its replay
# cache. Past the cap a lost call runs again as it does without replay, so the
# model is never told to use a result it can no longer see, and a loop of
# identical re-runs still ends at the no-progress limit.
MAX_READONLY_REPLAY_RECOVERIES = 6


class ToolReplay:
    """Track exact successful calls and the visibility of restored results."""

    def __init__(self, env):
        self.env = env
        self.reset()

    def reset(self) -> None:
        self._called_ok = set()
        self._successful_call_keys = {}
        self._called_identical = {}
        self._readonly_replay_cache = {}
        self._readonly_replay_ready = set()
        self._readonly_replay_protected = set()
        self._readonly_replay_visibility_pending = set()
        self._readonly_replay_recoveries = 0

    def _is_tool_readonly(self, tool_name: str) -> bool:
        """Return whether a tool is known to be side-effect free."""
        get_tool = getattr(self.env.registry, "get", None)
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
        self, messages: list, trace: Any, iteration: int
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
            normalized = _normalize_tool_run_dir(dict(arguments or {}), self.env.memory.run_dir)
            canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 - un-serializable args are never cached
            return None
        return (tool_name, canonical)

    def deliver_cached(self, tc, tool_def, is_repeatable, dedup_key, context, messages, trace, iteration, delivery):
        """Deliver or skip an already authorized call when its replay policy permits."""
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
            delivery._append_tool_result(
                messages, context, tc.id, tc.name,
                deliver_tool_result(restored, self.env.memory.run_dir, self.env.registry),
                status="ok", elapsed_ms=0,
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
            delivery.progress.mark_context_restored()
            trace.write({
                "type": "tool_result_replayed",
                "iter": iteration,
                "tool": tc.name,
                "call_id": tc.id,
                "recovery_count": self._readonly_replay_recoveries,
                "recovery_limit": MAX_READONLY_REPLAY_RECOVERIES,
            })
            delivery.progress.note("replayed", tc.name)
            delivery._emit_tool_completed(tc, "ok", 0, redact_tool_result(cached)[:200], cached=True)
            return True

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
            delivery._append_tool_result(messages, context, tc.id, tc.name, skip_msg, elapsed_ms=0)
            trace.write({"type": "tool_skipped", "iter": iteration, "tool": tc.name})
            delivery.progress.note("skipped", tc.name)
            return True

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
                delivery._append_tool_result(
                    messages, context, tc.id, tc.name,
                    deliver_tool_result(cached, self.env.memory.run_dir, self.env.registry),
                    status="ok", elapsed_ms=0,
                )
                self._successful_call_keys[tc.id] = cache_key
                self._called_ok.add(cache_key)
                trace.write({
                    "type": "tool_result_cached",
                    "iter": iteration,
                    "tool": tc.name,
                    "call_id": tc.id,
                })
                delivery.progress.note("cached", tc.name)
                delivery._emit_tool_completed(tc, "ok", 0, cached[:200], cached=True)
                return True

        return False

    def remember(self, tc, result, update_memory):
        try:
            tool_def = self.env.registry.get(tc.name)
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
