"""Composed usage ledger for agent and child-provider calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.kernel import events as vocabulary
from src.agent.llm_usage import (
    _record_llm_usage,
    _record_unreported_llm_call,
)


class UsageLedger:
    """Own one run's usage summary and its event/accounting callbacks."""

    def __init__(self, owner: Any, summary: dict[str, Any] | None = None) -> None:
        self.owner = owner
        self.summary = summary or {}
        self.goal_callback = None

    def reset(self, summary: dict[str, Any]) -> None:
        """Replace the accumulator at the start of a run."""
        self.summary = summary
        self.goal_callback = None

    def record(
        self,
        run_dir: Path,
        usage: Any,
        iteration: int,
        *,
        purpose: str | None = None,
        include_call_index: bool = True,
    ) -> None:
        """Persist usage and emit usage through the item/run vocabulary."""
        delta = _record_llm_usage(run_dir, self.summary, usage, iteration, purpose=purpose)
        if self.goal_callback is not None:
            self.goal_callback(delta)
        metadata: dict[str, Any] = {"iter": iteration}
        if purpose is not None:
            metadata["purpose"] = purpose
        if delta:
            event = {**delta, **metadata}
            if include_call_index:
                event["call_index"] = self.summary["totals"]["calls"]
            self.owner._emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.RUN_USAGE, **event})
        elif purpose is None and not self.owner._cancel_event.is_set():
            self.owner._emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.RUN_USAGE_UNAVAILABLE, **metadata})
        elif purpose == "subagent":
            self.owner._emit(vocabulary.ITEM_DELTA, {"kind": vocabulary.RUN_USAGE_UNAVAILABLE, **metadata})
            _record_unreported_llm_call(run_dir, self.summary)
        else:
            _record_unreported_llm_call(run_dir, self.summary)

    def record_subagent(self, event_type: str, data: dict[str, Any]) -> bool:
        """Account one child event in the parent's run."""
        run_dir = self.owner.memory.run_dir
        if not run_dir:
            return False
        self.record(
            Path(run_dir),
            data if event_type == vocabulary.ITEM_DELTA and data.get("kind") == vocabulary.RUN_USAGE else None,
            self.owner._run_iteration,
            purpose="subagent",
            include_call_index=False,
        )
        return self.owner._budget_stop_reason is not None
