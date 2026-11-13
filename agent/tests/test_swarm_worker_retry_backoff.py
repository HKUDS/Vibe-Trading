"""Worker-level retry backoff regression tests."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config.accessor import reset_env_config
from src.config.env_schema import SwarmConfig
from src.swarm.models import SwarmAgentSpec, SwarmTask, WorkerResult
from src.swarm.runtime import (
    SwarmRuntime,
    _worker_retry_budget_s,
    _worker_retry_delay_s,
)
from src.swarm.store import SwarmStore


def _runtime(tmp_path: Path) -> SwarmRuntime:
    return SwarmRuntime(SwarmStore(base_dir=tmp_path / "runs"))


def _agent(max_retries: int = 2) -> SwarmAgentSpec:
    return SwarmAgentSpec(
        id="analyst",
        role="Analyst",
        system_prompt="Analyze",
        max_retries=max_retries,
    )


def _task() -> SwarmTask:
    return SwarmTask(id="task-1", agent_id="analyst", prompt_template="Analyze")


def _run(runtime: SwarmRuntime, tmp_path: Path, cancel_event=None) -> WorkerResult:
    return runtime._run_worker_with_retries(
        agent_spec=_agent(),
        task=_task(),
        upstream_summaries={},
        user_vars={},
        run_dir=tmp_path / "run-1",
        event_callback=None,
        run_id="run-1",
        cancel_event=cancel_event,
    )


def test_worker_retry_delay_is_exponential_and_capped(monkeypatch) -> None:
    monkeypatch.setenv("SWARM_WORKER_RETRY_BASE_DELAY_S", "2")
    monkeypatch.setenv("SWARM_WORKER_RETRY_MAX_DELAY_S", "5")
    reset_env_config()

    with patch("src.swarm.runtime.random.uniform", side_effect=lambda low, high: high):
        assert [_worker_retry_delay_s(n) for n in range(1, 5)] == [2, 4, 5, 5]

    assert _worker_retry_budget_s(4) == 16


def test_worker_retry_delay_uses_equal_jitter(monkeypatch) -> None:
    monkeypatch.setenv("SWARM_WORKER_RETRY_BASE_DELAY_S", "4")
    monkeypatch.setenv("SWARM_WORKER_RETRY_MAX_DELAY_S", "30")
    reset_env_config()

    with patch("src.swarm.runtime.random.uniform", return_value=3.0) as uniform:
        assert _worker_retry_delay_s(1) == 3.0

    uniform.assert_called_once_with(2.0, 4.0)


def test_worker_retry_delay_rejects_invalid_retry_number() -> None:
    with pytest.raises(ValueError, match="retry_number"):
        _worker_retry_delay_s(0)


def test_swarm_config_rejects_retry_cap_below_base() -> None:
    with pytest.raises(ValueError, match="SWARM_WORKER_RETRY_MAX_DELAY_S"):
        SwarmConfig(
            swarm_worker_retry_base_delay_s=2,
            swarm_worker_retry_max_delay_s=1,
        )


def test_failed_worker_waits_before_each_retry_and_reports_delay(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    waits: list[float] = []
    events = []
    results = [
        WorkerResult(status="failed", summary="failed-1", error="overloaded"),
        WorkerResult(status="failed", summary="failed-2", error="overloaded"),
        WorkerResult(status="completed", summary="done"),
    ]

    with (
        patch("src.swarm.runtime.run_worker", side_effect=results),
        patch("src.swarm.runtime._worker_retry_delay_s", side_effect=[1.5, 3.0]),
        patch.object(
            runtime,
            "_emit_event",
            side_effect=lambda _run_id, event: events.append(event),
        ),
        patch(
            "src.swarm.runtime._wait_for_worker_retry",
            side_effect=lambda delay, _event: waits.append(delay) or False,
        ),
    ):
        result = _run(runtime, tmp_path)

    assert result.status == "completed"
    assert waits == [1.5, 3.0]
    assert [event.data["retry_delay_s"] for event in events] == [1.5, 3.0]


def test_cancellation_interrupts_backoff_without_starting_another_attempt(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    cancel_event = threading.Event()
    failed = WorkerResult(
        status="failed",
        summary="provider overloaded",
        error="529 overloaded",
        input_tokens=12,
        output_tokens=3,
    )

    with (
        patch("src.swarm.runtime.run_worker", return_value=failed) as run_worker,
        patch("src.swarm.runtime._worker_retry_delay_s", return_value=10.0),
        patch("src.swarm.runtime._wait_for_worker_retry", return_value=True),
    ):
        result = _run(runtime, tmp_path, cancel_event=cancel_event)

    assert run_worker.call_count == 1
    assert result.status == "cancelled"
    assert result.error == "529 overloaded"
    assert result.summary == "provider overloaded"
    assert result.input_tokens == 12
    assert result.output_tokens == 3
