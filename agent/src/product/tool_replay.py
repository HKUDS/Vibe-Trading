"""Run-scoped call identities, deterministic caching and compaction replay."""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from src.session.compaction_ops import _result_data_gone
from src.product.result_artifacts import deliver_tool_result
from src.product.tool_results import parse_tool_payload
from src.tools._arguments import normalize_tool_run_dir
from src.tools.redaction import redact_tool_result

logger = logging.getLogger(__name__)


# Beyond this cap, a lost read may execute again under the normal progress budget.
MAX_READONLY_REPLAY_RECOVERIES = 6


def _replay_context_result(result: str) -> str:
    """Expose restored evidence with a replay notice while preserving the payload."""
    notice = (
        "Exact prior successful result restored after context compaction. "
        "Treat this payload as available evidence and continue the analysis. "
        "Do not change cache/freshness arguments merely to bypass replay; "
        "request a fresh fetch only when the evidence itself is stale/cached "
        "or the task genuinely requires newer data."
    )
    replay_payload = parse_tool_payload(result)
    if replay_payload is None:
        return f"{result}\n\n[Replay notice: {notice}]"
    replay_payload["_vibe_replay"] = {
        "restored": True,
        "notice": notice,
    }
    return json.dumps(replay_payload, ensure_ascii=False)


class ToolReplay:
    """Track exact successful calls and the visibility of restored results.

    Args:
        env: Tool environment supplying registry metadata for caching decisions.
    """

    def __init__(self, env):
        self.env = env
        self.reset()

    def reset(self) -> None:
        """Clear successful-call history, caches, and replay tracking for a new turn."""
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
        """Require compaction replay opt-in for repeatable reads and honor explicit freshness."""
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
        # The replay budget controls restoration, while lost reads can still execute again.
        self._readonly_replay_protected.difference_update(reopened)
        self._readonly_replay_ready.update(
            key for key in reopened if key in self._readonly_replay_cache
        )
        return sorted({key[0] for key in reopened})

    def _identical_call_key(self, tool_name: str, arguments: Mapping[str, Any]) -> tuple[str, str] | None:
        """Build a stable key identifying a deterministic tool invocation."""
        try:
            normalized = normalize_tool_run_dir(dict(arguments or {}), self.env.memory.run_dir)
            canonical = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001 - un-serializable args are never cached
            return None
        return (tool_name, canonical)

    def record_success(self, call_id: str, key: tuple[str, str] | None) -> None:
        """Track a successful call and the message carrying its evidence.

        Args:
            call_id: Provider identifier of the successful call.
            key: Canonical call identity, or None to omit it from deduplication.
        """
        if key is not None:
            self._called_ok.add(key)
            self._successful_call_keys[call_id] = key

    def _append_cached_result(self, delivery, tc, context, messages, result, key) -> None:
        delivery._append_tool_result(
            messages, context, tc.id, tc.name,
            deliver_tool_result(result, self.env.memory.run_dir, self.env.registry, tool_name=tc.name),
            status="ok", elapsed_ms=0,
        )
        self.record_success(tc.id, key)

    def deliver_cached(self, tc, tool_def, is_repeatable, dedup_key, context, messages, trace, iteration, delivery):
        """Deliver or skip an already authorized call when its replay policy permits.

        Args:
            tc: Provider tool call being considered for reuse.
            tool_def: Registered tool definition, if available, supplying replay flags.
            is_repeatable: Whether ordinary duplicate execution is allowed.
            dedup_key: Canonical call identity, or None if it could not be computed.
            context: Context builder used to format any delivered result.
            messages: Conversation messages that receive the cached result or skip notice.
            trace: Writer for cache, replay, and skip events.
            iteration: Current iteration number for trace events.
            delivery: Tool delivery state used for messages, events, and progress.

        Returns:
            True if the call was satisfied from cache or skipped as a duplicate, or
            False if it still needs execution.
        """
        if (
            dedup_key is not None
            and dedup_key in self._readonly_replay_ready
            and self._readonly_replay_recoveries < MAX_READONLY_REPLAY_RECOVERIES
            and self._readonly_replay_allowed(tool_def, tc.arguments)
            and dedup_key in self._readonly_replay_cache
        ):
            cached = self._readonly_replay_cache[dedup_key]
            self._append_cached_result(delivery, tc, context, messages, _replay_context_result(cached), dedup_key)
            self._readonly_replay_visibility_pending.add(tc.id)
            self._readonly_replay_ready.discard(dedup_key)
            self._readonly_replay_recoveries += 1
            # Refuse identical repeats while restored evidence is still visible.
            if getattr(tool_def, "repeatable", False):
                self._readonly_replay_protected.add(dedup_key)
            # Restoring evidence advances context without creating a new observation.
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
            logger.warning("Blocked duplicate call: %s (already succeeded)", tc.name)
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

        # Deterministic results can be reused after authorization and compaction.
        if getattr(tool_def, "deterministic", False) and dedup_key in self._called_identical:
            cached = self._called_identical[dedup_key]
            self._append_cached_result(delivery, tc, context, messages, cached, dedup_key)
            trace.write({"type": "tool_result_cached", "iter": iteration, "tool": tc.name, "call_id": tc.id})
            delivery.progress.note("cached", tc.name)
            delivery._emit_tool_completed(tc, "ok", 0, cached[:200], cached=True)
            return True

        return False

    def remember(self, tc, result, update_memory):
        """Store an eligible result and invalidate replayable reads after a mutation.

        Args:
            tc: Executed provider tool call whose arguments identify the cache entry.
            result: Tool result payload to cache when eligible.
            update_memory: Whether a mutable tool call should invalidate cached reads.
        """
        try:
            tool_def = self.env.registry.get(tc.name)
        except Exception:  # noqa: BLE001
            tool_def = None
        cache_key = self._identical_call_key(tc.name, tc.arguments)
        if cache_key is not None:
            if getattr(tool_def, "deterministic", False):
                self._called_identical[cache_key] = result
            elif self._readonly_replay_allowed(tool_def, tc.arguments):
                self._readonly_replay_cache[cache_key] = result
        # Its payload is visible again, so nothing is waiting to be restored.
        self._readonly_replay_ready.discard(cache_key)
        # Unrelated mutations may opt out; workspace writes still invalidate reads.
        if (
            update_memory
            and not self._is_tool_readonly(tc.name)
            and getattr(tool_def, "invalidates_readonly_cache", True)
        ):
            self._readonly_replay_cache.clear()
            self._readonly_replay_ready.clear()
            self._readonly_replay_protected.clear()
