"""Mutable state passed between composed turn-loop components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.kernel.contracts import LoopContext


@dataclass
class TurnState:
    """All per-turn values that formerly lived as local loop variables."""

    view: LoopContext
    run_dir: Path
    trace: Any
    context: Any
    user_message: str
    run_started_wall: float
    session_id: str
    state_store: Any
    iteration: int = 0
    current_iter: int = 0
    final_content: str = ""
    no_progress_reason: str | None = None
    content_filter_count: int = 0
    consecutive_content_filter_count: int = 0
    content_filter_circuit_breaker: bool = False
    empty_model_response_iter: int | None = None
    consecutive_empty_responses: int = 0
    released_fallback: bool = False
    released_fallback_reason: str | None = None
    truncation_reason: str | None = None
    last_response_model: str | None = None
    no_commentary_rounds: int = 0
    mid_turn_nudge_rounds: int = 0
    final_answer_retry: bool = False
    stream: Any = None
    thinking_text: str = ""
    current_response_model: str | None = None
