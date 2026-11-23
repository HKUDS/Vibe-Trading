"""Deliver scrubbed tool results to the model, artifacts, recorder and live subscribers."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Mapping

from src.kernel import events as vocabulary
from src.product.context import ContextBuilder
from src.product.result_artifacts import deliver_tool_result
from src.product.tool_progress import ToolProgress
from src.product.tool_results import _archive_backtest_result, _failure_code, _is_tool_success
from src.tools._arguments import normalize_tool_run_dir
from src.tools.redaction import RESULT_SINK, redact_payload, redact_tool_result

logger = logging.getLogger(__name__)


class ToolDelivery:
    """Publish a sanitized result to every model, recording and artifact sink."""

    def __init__(self, env, replay, conversation, emit, activity, record_write):
        self.env = env
        self.replay = replay
        self.conversation = conversation
        self._emit = emit
        self.activity = activity
        self.record_write = record_write
        self._live_tool_ids = {}
        self.reset()

    def reset(self) -> None:
        self.waiting_user = None
        self.progress = ToolProgress()

    def deliver_blocked_call(
        self,
        tc: Any,
        result: str,
        context: ContextBuilder,
        messages: list,
        trace: Any,
        iteration: int,
        *,
        blocked: bool = True,
    ) -> None:
        """Record a blocked call without invoking its implementation.

        Args:
            tc: Provider tool-call object.
            result: Structured identity-gate error payload.
            context: Context builder.
            messages: Conversation messages.
            trace: Persistent trace writer.
            iteration: Current iteration.
        """
        self.progress.note("blocked", tc.name, _failure_code(result))
        args = normalize_tool_run_dir(tc.arguments, self.env.memory.run_dir)
        self._emit_tool_started(tc, args, iteration, blocked=blocked)
        trace.write(
            {
                "type": "tool_execution",
                "iter": iteration,
                "tool": tc.name,
                "call_id": tc.id,
                **({"blocked": True} if blocked else {}),
            }
        )
        self._finalize_tool_result(
            tc,
            result,
            0,
            context,
            messages,
            trace,
            iteration,
            update_memory=False,
        )

    def deliver_cancelled_calls(
        self,
        tool_calls: list[Any],
        context: ContextBuilder,
        messages: list,
        trace: Any,
        iteration: int,
    ) -> None:
        """Record calls skipped after cancellation as explicit tool errors."""
        result = json.dumps(
            {
                "status": "error",
                "error_code": "tool_cancelled",
                "message": "Run stopped before this tool started; no action was performed.",
            },
            ensure_ascii=False,
        )
        for tc in tool_calls:
            self.deliver_blocked_call(
                tc,
                result,
                context,
                messages,
                trace,
                iteration,
                blocked=False,
            )

    def _emit_tool_started(self, tc: Any, arguments: Mapping[str, Any], iteration: int, *, blocked: bool = False) -> None:
        """Publish the canonical live item for a tool call."""
        redacted = redact_payload(arguments)
        live_id = self._live_tool_ids[tc.id] = f"tool:{uuid.uuid4().hex}"
        self._emit(
            vocabulary.ITEM_STARTED,
            {
                "kind": vocabulary.TOOL_STARTED,
                "live_id": live_id,
                "item": {
                    "type": "tool_result",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "arguments": {key: str(value)[:200] for key, value in redacted.items()},
                    **({"blocked": True} if blocked else {}),
                },
                "iter": iteration,
            },
        )

    def _emit_tool_completed(self, tc: Any, status: str, elapsed_ms: int, preview: str, *, artifact: dict | None = None, cached: bool = False) -> None:
        """Publish the canonical live outcome for a tool call."""
        self._emit(
            vocabulary.ITEM_COMPLETED,
            {
                "kind": vocabulary.TOOL_COMPLETED if status == "ok" else vocabulary.TOOL_FAILED,
                "live_id": self._live_tool_ids.pop(tc.id, f"tool:{uuid.uuid4().hex}"),
                "item": {
                    "type": "tool_result",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "content": preview,
                    **({"artifact": artifact} if artifact else {}),
                    **({"cached": True} if cached else {}),
                },
            },
        )

    def _emit_tool_progress(self, payload: Dict[str, Any], *, heartbeat: bool = False) -> None:
        """Publish canonical progress for a running tool item."""
        self._emit(
            vocabulary.ITEM_DELTA,
            {
                "kind": vocabulary.TOOL_PROGRESS,
                "live_id": self._live_tool_ids.get(payload.get("call_id")),
                "progress": redact_payload(payload, sink=RESULT_SINK),
                "heartbeat": heartbeat,
            },
        )

    def _append_tool_result(
        self,
        messages: list,
        context: ContextBuilder,
        call_id: str,
        tool_name: str,
        content: str,
        *,
        status: str | None = None,
        elapsed_ms: int | None = None,
        artifact: dict | None = None,
        images: list[dict] | None = None,
    ) -> None:
        """Append a tool message and record it as the model receives it.

        Args:
            messages: Conversation messages (appended in place).
            context: ContextBuilder for formatting.
            call_id: Provider tool-call id.
            tool_name: Tool name.
            content: Delivered result text (already redacted and capped).
            status: ``ok`` / ``error``; derived from the content when omitted.
            elapsed_ms: Execution time.
            artifact: Display-only report link.
        """
        message = context.format_tool_result(call_id, tool_name, content)
        self.conversation.append(messages, message)
        if self.conversation.records_into(messages):
            self.conversation.thread.tool_result(
                message,
                status=status or ("ok" if _is_tool_success(content) else "error"),
                elapsed_ms=elapsed_ms,
                artifact=artifact,
                images=images,
            )

    def _finalize_tool_result(
        self,
        tc: Any,
        result: str,
        elapsed_ms: int,
        context: ContextBuilder,
        messages: list,
        trace: Any,
        iteration: int,
        *,
        update_memory: bool = True,
        update_identity: bool = True,
    ) -> None:
        """Record a tool result: update memory, append message, write trace, emit event.

        Args:
            tc: Tool call object.
            result: Raw tool result string.
            elapsed_ms: Execution time in milliseconds.
            context: ContextBuilder.
            messages: Conversation messages.
            trace: Any.
            iteration: Current iteration.
            update_memory: Whether this call reached the tool implementation.
            update_identity: False for a local replay of an unchanged identity.
        """
        # Scrub before caching, truncation and model context, not just the
        # downstream trace/event preview. Shell stdout may hold credentials.
        result = redact_tool_result(result)
        # Image bytes belong in artifacts, never in the canonical result or
        # its metadata. Keep one reference-only payload for all later sinks.
        try:
            parsed = json.loads(result)
        except (TypeError, ValueError):
            parsed = None
        payload = parsed if isinstance(parsed, dict) else None
        image_refs = []
        if payload is not None and isinstance(payload.get("images"), list):
            payload["images"] = [
                {key: image[key] for key in ("path", "mime_type", "alt", "download_url")
                 if isinstance(image.get(key), str) and not image[key].startswith("data:")}
                for image in payload["images"]
                if isinstance(image, dict) and isinstance(image.get("path"), str)
                and not image["path"].startswith("data:")
            ]
            result = json.dumps(payload, ensure_ascii=False)
            image_refs = payload["images"]
        if update_memory:
            self.env.memory.increment(tc.name)

        # A tool completed - real progress for the stall watchdog.
        self.activity()

        success = _is_tool_success(result)
        if update_memory:
            self.progress.record(
                tc.name,
                self.replay._identical_call_key(tc.name, tc.arguments),
                result,
                success=success,
                is_readonly=self.replay._is_tool_readonly(tc.name),
            )
        if success:
            recorded_key = self.replay._identical_call_key(tc.name, tc.arguments)
            if recorded_key is not None:
                self.replay._called_ok.add(recorded_key)
                self.replay._successful_call_keys[tc.id] = recorded_key
            if tc.name == "backtest":
                try:
                    _archive_backtest_result(
                        result, self.env.memory.run_dir, source_call_id=tc.id,
                        roots=self.env.registry.policy.file_roots,
                    )
                except OSError as exc:
                    logger.warning("Could not archive backtest output into active run: %s", exc)
            if tc.name in {"write_file", "edit_file"}:
                self.record_write(tc.arguments)

        if self.env.identity is not None and update_identity:
            self.env.identity.ingest_tool_result(
                tool_name=tc.name,
                arguments=normalize_tool_run_dir(tc.arguments, self.env.memory.run_dir),
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
                        "identity": self.env.identity.identity_summary(),
                    }
                )

        if success:
            self.replay.remember(tc, result, update_memory)

        status = "ok" if success else "error"
        if payload is not None and payload.get("status") == "waiting_user":
            self.waiting_user = payload
            if self.conversation.thread is not None:
                self.conversation.thread.question(payload.get("question_id", ""), payload.get("prompt", ""), payload.get("options", []), bool(payload.get("allow_free_text", True)))
        if payload is not None and payload.get("status") == "ok" and tc.name == "plan" and self.conversation.thread is not None:
            self.conversation.thread.plan(payload.get("plan_id", ""), payload.get("steps", []))
        artifact = None
        if status == "ok" and payload is not None and tc.name in {"write_file", "render_shadow_report"}:
            try:
                from src.tools.report_artifacts import report_path
                report_id = payload.get("report_id", "")
                path = report_path(report_id) if isinstance(report_id, str) else None
                if path is not None:
                    artifact = {"report_id": report_id, "filename": path.name,
                                "download_url": f"/api/reports/{report_id}"}
            except (ValueError, TypeError, AttributeError, OSError):
                pass
        truncated = deliver_tool_result(result, self.env.memory.run_dir, self.env.registry)
        self._append_tool_result(
            messages, context, tc.id, tc.name, truncated,
            status=status, elapsed_ms=elapsed_ms, artifact=artifact,
            images=image_refs,
        )
        preview = result[:200]
        self._emit_tool_completed(tc, status, elapsed_ms, preview, artifact=artifact)


def write_run_manifest(trace_dir: Path, messages: list, registry, iteration: int) -> None:
    """Record what methodology produced this run, beside its trace.

    Answers "under what system prompt, which skills, and which tool set was
    that number produced" -- the question a reproducibility review asks and
    that nothing in this repo could previously answer. Written once per run
    as ``run_manifest.json`` in the run directory.

    The system-prompt hash transitively covers every skill injected at
    context-build time, because those skills ARE part of the prompt string.
    Skills pulled mid-run via ``load_skill`` are not, and appear in the
    trace instead; the manifest says so rather than implying coverage it
    does not have.

    The prompt itself is never stored -- only its hash. The prompt can carry
    user memory and workspace content, and this file is a provenance record,
    not a second copy of the conversation.

    Args:
        trace_dir: Directory holding this run's trace.
        messages: The fully built message list about to be sent.

    Note:
        Never raises. A provenance record that can break a run is worse than
        a missing one; a failure is logged and the run continues.
    """
    try:
        from datetime import datetime, timezone

        from src.governance.manifest import (
            build_run_manifest,
            collect_key_package_versions,
        )

        system_prompt = next(
            (m.get("content", "") for m in messages if m.get("role") == "system"), ""
        )
        manifest = build_run_manifest(
            run_id=f"iter-{iteration + 1}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            system_prompt=str(system_prompt),
            tool_names=list(registry.tool_names),
            package_versions=collect_key_package_versions(),
            extra={
                "skill_coverage": (
                    "skills injected at context-build time are inside the "
                    "hashed system prompt; skills loaded mid-run via "
                    "load_skill are recorded in the conversation thread"
                ),
            },
        )
        path = trace_dir / "run_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.to_json(indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("run manifest not written (%s: %s)", type(exc).__name__, exc)
