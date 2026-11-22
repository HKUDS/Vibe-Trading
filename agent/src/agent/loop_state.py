"""Mutable state passed between composed turn-loop components."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TurnState:
    """All per-turn values that formerly lived as local loop variables."""

    messages: list
    run_dir: Path
    trace: Any
    context: Any
    user_message: str
    run_started_wall: float
    session_id: str
    state_store: Any
    goal_store: Any = None
    active_goal_id: str | None = None
    iteration: int = 0
    current_iter: int = 0
    final_content: str = ""
    no_progress_reason: str | None = None
    content_filter_count: int = 0
    consecutive_content_filter_count: int = 0
    content_filter_circuit_breaker: bool = False
    empty_model_response_iter: int | None = None
    consecutive_empty_responses: int = 0
    truncation_reason: str | None = None
    last_response_model: str | None = None
    goal_continuations: int = 0
    goal_last_progress: tuple[int, int] | None = None
    wrap_up_at: int | None = None
    no_commentary_rounds: int = 0
    mid_turn_nudge_rounds: int = 0
    stream_failure_streak: int = 0
    final_answer_retry_pending: bool = False
    final_answer_retry: bool = False
    compact_requested: bool = False
    focus_topic: str = ""
    request_messages: list[dict[str, Any]] = field(default_factory=list)
    response: Any = None
    stream: Any = None
    tool_defs: Any = None
    thinking_text: str = ""
    current_response_model: str | None = None
    finished: bool = False


@dataclass
class TurnSetup:
    """Resources established before the iteration driver starts."""

    state: TurnState | None = None
    run_dir: Path | None = None
    trace: Any = None
    state_store: Any = None
    run_started_wall: float = 0.0
    active_goal_id: str | None = None
    denied_result: dict[str, Any] | None = None
