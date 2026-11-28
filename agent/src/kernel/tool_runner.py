"""Schedule bound calls and collect worker outcomes in submission order."""
from __future__ import annotations

import concurrent.futures
import contextvars
import json
import queue
import threading
import time as _time
from itertools import groupby
from typing import Any, Callable, ContextManager

from .contracts import BoundCall


def execute_batch(calls: list[BoundCall], cancelled: Callable[[], bool]) -> None:
    """Run adjacent parallel calls together and deliver results in call order.

    Args:
        calls: Bound calls in execution order, each with its own parallel eligibility.
        cancelled: Check before each serial call or parallel group to skip pending work.

    Raises:
        Exception: An error from a serial invocation or a call lifecycle callback.
    """
    for parallel, group in groupby(calls, key=lambda call: call.parallel):
        batch = list(group)
        if parallel and len(batch) > 1:
            if cancelled():
                for call in batch:
                    call.skip()
                continue
            workers = [call.start(True) for call in batch]
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(batch), 8)) as pool:
                # One copy per call: a Context cannot be entered by two threads at once.
                futures = [pool.submit(contextvars.copy_context().run, invoke) for invoke in workers]
                results = []
                for future in futures:
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        results.append((json.dumps({"status": "error", "error": str(exc)}), 0))
            for call, result in zip(batch, results):
                call.finish(*result)
        else:
            for call in batch:
                if cancelled():
                    call.skip()
                    continue
                invoke = call.start(False)
                call.finish(*invoke())


def _format_timeout(seconds: float) -> str:
    """Return a human-readable timeout label."""
    if seconds < 1:
        return f"{seconds:.2f}s"
    return f"{seconds:.0f}s"


def wait_for_tool(
    tool_name: str, call_id: str, invoke: Callable[[], str], *,
    readonly: bool, detachable: bool, timeout: float | None,
    cancelled: Callable[[], bool], heartbeat: Callable[[Callable], ContextManager],
    set_emitter: Callable,
    progress: Callable[..., None], post_result: Callable[[str, str], None] | None,
) -> tuple[str, int]:
    """Run a tool in a worker thread and monitor its progress until the wait ends.

    Args:
        tool_name: Name used to identify the worker and its progress events.
        call_id: Identifier attached to progress events for this invocation.
        invoke: Callable that runs the tool and returns its result payload.
        readonly: Whether the tool can run without side effects.
        detachable: Whether cancellation can end the wait while the worker is active.
        timeout: Maximum wait in seconds, or None to wait without a deadline.
        cancelled: Callable that reports whether the run has been cancelled.
        heartbeat: Context manager factory that accepts the waiting-event callback.
        set_emitter: Worker-local setter called with a progress callback and cleared on exit.
        progress: Sink for progress and waiting events, including the heartbeat flag.
        post_result: Optional callback receiving the result payload and its status.

    Returns:
        The tool payload and elapsed milliseconds, or a JSON error and elapsed time
        on timeout or detachable cancellation. The error reports an unknown outcome
        when the call is side-effecting or cannot be detached.

    Raises:
        BaseException: Propagates an exception raised by the worker when its result is collected.
    """
    side_effecting = not readonly or not detachable
    timed_out = threading.Event()

    def _on_progress(event) -> None:
        if timed_out.is_set():
            return
        payload = event.to_dict()
        payload["tool"] = tool_name
        payload["call_id"] = call_id
        progress(payload)

    def _on_heartbeat(payload: dict[str, Any]) -> None:
        if timed_out.is_set():
            return
        payload["call_id"] = call_id
        progress(payload, heartbeat=True)

    t0 = _time.perf_counter()
    timeout_label = _format_timeout(timeout) if timeout is not None else ""

    def _elapsed_ms() -> int:
        """Return milliseconds elapsed since tool start."""
        return int((_time.perf_counter() - t0) * 1000)

    def _emit_timeout_progress(stage: str, message: str, **extra: Any) -> int:
        """Publish timeout progress and return elapsed milliseconds."""
        elapsed_ms = _elapsed_ms()
        payload: dict[str, Any] = {
            "tool": tool_name,
            "call_id": call_id,
            "stage": stage,
            "message": message,
            "elapsed_s": round(elapsed_ms / 1000, 2),
        }
        payload.update(extra)
        progress(payload)
        return elapsed_ms

    # Discard late daemon-worker results because Python cannot safely stop a blocked thread.
    result_queue: queue.Queue[tuple[str | None, BaseException | None]] = queue.Queue(maxsize=1)

    def _worker() -> None:
        set_emitter(_on_progress)
        try:
            result_queue.put((invoke(), None))
        except BaseException as exc:  # noqa: BLE001 - propagate through caller thread
            result_queue.put((None, exc))
        finally:
            set_emitter(None)

    worker_context = contextvars.copy_context()

    def _run_in_context() -> None:
        worker_context.run(_worker)

    worker = threading.Thread(
        target=_run_in_context,
        name=f"tool-{tool_name}",
        daemon=True,
    )
    worker.start()

    def _terminal_error(error_code: str, message: str) -> tuple[str, int]:
        timed_out.set()
        outcome_unknown = side_effecting
        terminal_stage = "cancelled" if error_code == "tool_cancelled" else "timeout"
        if outcome_unknown:
            error_code = "tool_outcome_unknown"
            message = (
                f"{message}. The tool may have completed after this wait ended. "
                "Check the external state before retrying."
            )
        elapsed_ms = _emit_timeout_progress(
            terminal_stage,
            message,
            readonly=readonly,
            orphaned_worker=worker.is_alive(),
            **({"outcome": "unknown", "retryable": False} if outcome_unknown else {}),
        )
        result = json.dumps(
            {
                "status": "error",
                "error_code": error_code,
                "tool": tool_name,
                **({"timeout_seconds": timeout} if error_code == "tool_timeout" else {}),
                "message": message,
                "orphaned_worker": worker.is_alive(),
                **({"outcome": "unknown", "retryable": False} if outcome_unknown else {}),
            },
            ensure_ascii=False,
        )
        if post_result is not None:
            post_result(result, "error")
        return result, elapsed_ms

    with heartbeat(_on_heartbeat):
        deadline = None if timeout is None else _time.monotonic() + timeout
        while True:
            if cancelled() and detachable:
                return _terminal_error(
                    "tool_cancelled",
                    "Run was cancelled while this tool was running",
                )
            if deadline is not None:
                remaining = deadline - _time.monotonic()
                if remaining <= 0:
                    return _terminal_error(
                        "tool_timeout",
                        f"Tool exceeded {timeout_label} timeout",
                    )
                wait = min(0.05, remaining)
            else:
                wait = 0.05
            try:
                result, exc = result_queue.get(timeout=wait)
                break
            except queue.Empty:
                continue
    if exc is not None:
        if post_result is not None:
            post_result(json.dumps({"status": "error", "error": str(exc)}), "error")
        raise exc
    result = result or ""
    elapsed_ms = _elapsed_ms()
    if post_result is not None:
        post_result(result, "ok")
    return result, elapsed_ms
