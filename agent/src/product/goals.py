"""Goal budget accounting, continuation and channel projection."""

from __future__ import annotations

import logging
from typing import Any

from src.agent.tuning import _goal_max_continuations
from src.goal.context import format_goal_continuation_prompt, goal_needs_continuation, goal_progress_tuple

logger = logging.getLogger(__name__)


def goal_state_ws_blob(meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a WebSocket payload for the current active goal state."""
    if not isinstance(meta, dict):
        return {"active": False, "active_goals": [], "completed_goals": []}
    goal_state = meta.get("goal_state")
    if isinstance(goal_state, dict):
        return {
            "active": bool(goal_state.get("active")),
            "active_goals": list(goal_state.get("active_goals") or []),
            "completed_goals": list(goal_state.get("completed_goals") or []),
        }
    goal = meta.get("active_goal") or meta.get("goal")
    if isinstance(goal, dict):
        return {"active": True, "active_goals": [goal], "completed_goals": []}
    return {"active": False, "active_goals": [], "completed_goals": []}

class GoalBudget:
    """Charge each model call and count the turn once across parent and child calls."""

    def __init__(self, emit):
        self.emit = emit
        self.start("", None)

    def start(self, session_id, goal_id):
        self.session_id = session_id
        self.goal_id = goal_id
        self.store = None
        self.turn_accounted = False
        self.continuations = 0
        self.last_progress = None
        self.stop_reason = None
        if goal_id and session_id:
            from src.goal import GoalStore
            self.store = GoalStore()
            self.check(self.store.get_goal_snapshot(goal_id))

    def check(self, snapshot: dict[str, Any] | None) -> None:
        goal = (snapshot or {}).get("goal") or {}
        limit = goal.get("token_budget")
        if limit is not None and int(goal.get("tokens_used") or 0) >= limit:
            self.stop_reason = (
                "goal_token_budget_exhausted: the research goal's token budget "
                "has been reached. End the goal to continue; a new goal can set a "
                "larger budget."
            )

    def account(self, usage_delta: dict[str, int] | None) -> bool:
        if not (self.goal_id and self.session_id):
            return True
        token_delta = int(usage_delta.get("total_tokens") or 0) if usage_delta else 0
        turn_delta = 0 if self.turn_accounted else 1
        if not (token_delta or turn_delta):
            return True
        try:
            self.store.account_usage(
                session_id=self.session_id,
                goal_id=self.goal_id,
                expected_goal_id=self.goal_id,
                token_delta=token_delta,
                turn_delta=turn_delta,
            )
            self.turn_accounted = True
            snapshot = self.store.get_goal_snapshot(self.goal_id)
            self.check(snapshot)
            if snapshot is not None:
                self.emit("goal.updated", {"goal": snapshot["goal"], "snapshot": snapshot})
        except Exception as exc:  # noqa: BLE001
            logger.debug("Goal usage accounting skipped: %s", exc)
            return False
        return True



    def continue_goal(self, state: Any, conversation) -> bool:
        """Continue an active goal only when progress and budget allow it."""
        if state.final_answer_retry or not self.goal_id or not self.session_id:
            return False
        maximum = _goal_max_continuations()
        if maximum <= 0:
            return False
        try:
            if self.store is None:
                from src.goal import GoalStore
                self.store = GoalStore()
            snapshot = self.store.get_goal_snapshot(self.goal_id)
            if not snapshot or not goal_needs_continuation(snapshot):
                return False
        except Exception as exc:
            logger.debug("Goal continuation check skipped: %s", exc)
            return False
        progress = goal_progress_tuple(snapshot)
        no_new_progress = self.last_progress is not None and progress <= self.last_progress
        if self.continuations >= maximum or (no_new_progress and self.continuations > 0):
            state.trace.write({"type": "goal_continuation_suppressed", "iter": state.current_iter, "goal_id": self.goal_id, "progress": progress, "continuations": self.continuations})
            return False
        state.trace.write({"type": "goal_intermediate_answer", "iter": state.current_iter, "goal_id": self.goal_id, "progress": progress, "content": state.final_content})
        conversation.append_assistant(state.view.messages, {"role": "assistant", "content": state.final_content}, phase="commentary")
        conversation.inject(state.view.messages, format_goal_continuation_prompt(snapshot, previous_answer=state.final_content))
        self.last_progress = progress
        self.continuations += 1
        return True
