"""Pin the extraction contract of the run-outcome module (issue #1624).

``AgentLoop._run_bound`` used to resolve its terminal status, end event,
and result dict inline in a 100-line tail; that ladder now lives in
``src.agent.run_outcome`` and is called from ``loop.py``. These tests pin
each branch of the ladder directly — something the pre-extraction layout
could only exercise by stubbing a whole LLM — plus the re-export surface
``loop.py`` must keep importing.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

import src.agent.loop as loop
import src.agent.run_outcome as run_outcome
from src.agent.run_outcome import (
    OutcomeInputs,
    RunOutcome,
    build_end_event,
    build_result_dict,
    resolve_final_status,
)

RE_EXPORTS = [
    "OutcomeInputs",
    "RunOutcome",
    "build_end_event",
    "build_result_dict",
    "resolve_final_status",
]


@pytest.mark.parametrize("name", RE_EXPORTS)
def test_loop_reexports(name: str) -> None:
    """Every moved name resolves through ``src.agent.loop`` (back-compat)."""
    assert getattr(loop, name) is getattr(run_outcome, name)


def _inputs(**over: object) -> OutcomeInputs:
    base = dict(
        stall_reason=None,
        cancelled=False,
        no_progress_reason=None,
        content_filter_circuit_breaker=False,
        has_output=True,
        released_fallback=False,
        released_fallback_reason=None,
        grounding_validation_count=0,
        pending_write_directive=lambda: None,
        empty_model_response_iter=None,
        empty_response_provider="openai",
        empty_response_model="stub-model",
        max_iterations=12,
    )
    base.update(over)
    return OutcomeInputs(**base)  # type: ignore[arg-type]


class TestResolveFinalStatus:
    def test_clean_success(self) -> None:
        out = resolve_final_status(_inputs())
        assert (out.status, out.reason, out.mark, out.degraded) == (
            "success", None, "success", False,
        )

    def test_stall_wins_and_does_not_remark(self) -> None:
        out = resolve_final_status(_inputs(stall_reason="stalled: no progress"))
        assert out.status == "failed"
        assert out.reason == "stalled: no progress"
        # The watchdog already wrote the failed state.
        assert out.mark is None

    def test_cancelled(self) -> None:
        out = resolve_final_status(_inputs(cancelled=True))
        assert (out.status, out.reason, out.mark) == (
            "cancelled", "cancelled by user", "cancelled",
        )

    def test_no_progress(self) -> None:
        out = resolve_final_status(_inputs(no_progress_reason="no forward progress"))
        assert (out.status, out.mark) == ("failed", "failure")
        assert out.reason == "no forward progress"

    def test_content_filter_breaker_message(self) -> None:
        out = resolve_final_status(_inputs(content_filter_circuit_breaker=True))
        assert out.status == "failed"
        assert out.reason is not None
        assert out.reason.startswith("content_filter_circuit_breaker:")
        from src.providers.content_filter import MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS
        assert str(MAX_CONSECUTIVE_CONTENT_FILTER_SKIPS) in out.reason

    def test_success_with_released_fallback_reason(self) -> None:
        out = resolve_final_status(
            _inputs(
                released_fallback=True,
                released_fallback_reason="final answer released with unverified figures redacted after 2 rejected drafts",
            )
        )
        assert (out.status, out.degraded, out.mark) == ("success", True, "success")
        assert out.reason is not None
        assert "unverified figures" in out.reason

    def test_success_fallback_reason_built_lazily_from_count(self) -> None:
        out = resolve_final_status(
            _inputs(released_fallback=True, grounding_validation_count=3)
        )
        assert out.reason is not None
        assert "3" in out.reason
        assert "deterministic fallback" in out.reason

    def test_success_with_pending_write_directive(self) -> None:
        calls: list[int] = []

        def directive() -> Optional[str]:
            calls.append(1)
            return "metrics.csv named in the task but never written"

        out = resolve_final_status(_inputs(pending_write_directive=directive))
        assert (out.status, out.degraded) == ("success", True)
        assert out.reason is not None
        assert out.reason.startswith("run ended without writing the task target file(s):")
        assert calls == [1]

    def test_pending_directive_not_evaluated_on_other_paths(self) -> None:
        def boom() -> str:
            raise AssertionError("directive must be lazy")

        # Failure path: directive is never consulted.
        out = resolve_final_status(_inputs(cancelled=True, pending_write_directive=boom))
        assert out.status == "cancelled"

    def test_empty_model_response(self) -> None:
        out = resolve_final_status(
            _inputs(has_output=False, empty_model_response_iter=4)
        )
        assert (out.status, out.mark) == ("failed", "failure")
        assert out.reason is not None
        assert out.reason.startswith("empty_model_response:")
        assert "provider=openai" in out.reason
        assert "model=stub-model" in out.reason
        assert "iteration 4" in out.reason

    def test_max_iterations(self) -> None:
        out = resolve_final_status(_inputs(has_output=False, max_iterations=12))
        assert out.status == "failed"
        assert out.reason == "reached max iterations (12) without final answer"

    def test_ladder_precedence_stall_beats_cancel(self) -> None:
        out = resolve_final_status(
            _inputs(stall_reason="stalled", cancelled=True)
        )
        assert out.status == "failed"
        assert out.mark is None


class TestBuildEndEvent:
    def test_clean(self) -> None:
        ev = build_end_event(RunOutcome("success", None, "success", False), 3, 7)
        assert ev == {"type": "end", "iter": 3, "status": "success", "iterations": 7}

    def test_reason_and_degraded_flags(self) -> None:
        ev = build_end_event(RunOutcome("failed", "boom", "failure", True), 2, 5)
        assert ev["reason"] == "boom"
        assert ev["degraded"] is True


class TestBuildResultDict:
    def _runtime(self) -> SimpleNamespace:
        return SimpleNamespace(
            provider="openai", configured_model="gpt-test", reasoning_effort="low"
        )

    def test_fields_and_model_source(self) -> None:
        r = build_result_dict(
            RunOutcome("success", None, "success", False),
            Path("/tmp/runs/abc123"),
            [{"type": "answer"}],
            4,
            12,
            "the answer",
            self._runtime(),
            None,
            content_filter_count=0,
        )
        assert r["status"] == "success"
        assert r["run_id"] == "abc123"
        assert r["content"] == "the answer"
        assert r["model"] == "gpt-test"
        assert r["model_source"] == "configured"
        assert "degraded" not in r
        assert "reason" not in r

    def test_provider_response_model_wins(self) -> None:
        r = build_result_dict(
            RunOutcome("success", None, "success", False),
            Path("/tmp/runs/x"),
            [],
            1,
            12,
            "",
            self._runtime(),
            "provider-reported-model",
            content_filter_count=0,
        )
        assert r["model"] == "provider-reported-model"
        assert r["model_source"] == "provider_response"

    def test_degraded_and_reason_propagate(self) -> None:
        r = build_result_dict(
            RunOutcome("success", "degraded for a reason", "success", True),
            Path("/tmp/runs/x"),
            [],
            1,
            12,
            "text",
            self._runtime(),
            None,
            content_filter_count=0,
        )
        assert r["degraded"] is True
        assert r["reason"] == "degraded for a reason"
