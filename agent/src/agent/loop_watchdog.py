"""Stall watchdog state for an agent turn."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from src.kernel import events as vocabulary


class StallWatchdog:
    """Watch one run's forward progress and cancel it after a hard idle limit.

    Args:
        activity: Run tracker supplying the latest activity and completion and cancellation events.
        emit: Sink for stall warnings and terminal stall events.
    """

    def __init__(self, activity, emit) -> None:
        self.activity = activity
        self.emit = emit
        self.reason: str | None = None

    def start(self, trace: Any, run_dir: Path, state_store: Any, timeout: float) -> None:
        """Start a daemon watcher when the configured timeout is positive.

        Args:
            trace: Sink for the terminal failure trace.
            run_dir: Run directory whose state is updated if the run stalls.
            state_store: Store used to mark a stalled run as failed.
            timeout: Idle threshold in seconds. Nonpositive values disable the watcher.
        """
        if timeout <= 0:
            return
        thread = threading.Thread(
            target=self.watch,
            args=(trace, run_dir, state_store, timeout),
            name="run-stall-watchdog",
            daemon=True,
        )
        thread.start()

    def watch(self, trace: Any, run_dir: Path, state_store: Any, timeout: float) -> None:
        """Fail the run after two consecutive observations beyond the idle threshold.

        Args:
            trace: Sink for the terminal failure trace.
            run_dir: Run directory whose state is updated if the run stalls.
            state_store: Store used to mark a stalled run as failed.
            timeout: Idle threshold in seconds used to derive the polling interval.
        """
        run_done = self.activity.done
        warned = False
        while not run_done.is_set():
            wait_s = min(30.0, max(5.0, timeout / 4))
            if run_done.wait(timeout=wait_s):
                return
            idle = time.time() - self.activity.last_activity
            if idle < timeout:
                warned = False
                continue
            if not warned:
                warned = True
                self.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.RUN_STALL_WARNING, "idle_s": round(idle, 1), "timeout_s": timeout})
                continue
            self.reason = (
                "run stalled: no LLM completion or tool result for "
                + str(int(idle)) + "s (stall watchdog)"
            )
            self.activity.stall_reason = self.reason
            try:
                trace.write({"type": "end", "iter": self.activity.iteration, "status": "failed", "reason": self.reason, "stalled": True})
            except Exception:
                pass
            try:
                state_store.mark_failure(run_dir, self.reason)
            except Exception:
                pass
            self.emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.RUN_STALLED, "reason": self.reason})
            self.activity.cancel.set()
            return
