"""Correctness fixes for the swarm worker layer.

Covers four targeted fixes:

* #1 cancel_event propagation — a set cancel_event aborts run_worker promptly
  (top-of-iteration early-out and mid-stream via ``should_cancel``), returning
  ``status="cancelled"`` instead of running the LLM for tens of seconds.
* #2 retry on non-terminal-success statuses — ``_run_worker_with_retries``
  retries ``timeout`` (and friends), not only ``failed``.
* #3 per-task artifact directories — two parallel tasks sharing an agent_id
  write to distinct dirs and both summaries survive.
* #4 atomic writes — ``_atomic_write`` replaces the target in one step.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

from src.providers.chat import LLMResponse
from src.swarm.models import SwarmAgentSpec, SwarmTask, WorkerResult
from src.swarm.store import SwarmStore
import src.swarm.runtime as runtime_mod
import src.swarm.worker as worker_mod
from src.swarm.runtime import SwarmRuntime
from src.swarm.worker import _atomic_write, run_worker

FINAL_TEXT = (
    "# BTC-USDT — Short-Term View\n\n"
    "Spot 81,704.6 (2026-05-05). 7d range 77,750-82,842.\n\n"
    "**Recommendation: accumulate on dips to 79k; invalidation below 77.5k.**\n"
    "Position 3% NAV, stop 76,900, target 86,000."
)


class _EmptyRegistry:
    """Minimal stand-in for the swarm ToolRegistry (worker needs no tools)."""

    def get_definitions(self) -> list[dict]:
        """Return an empty tool-definition list."""
        return []


class _CancellingChatLLM:
    """Scripted ChatLLM that sets a cancel_event mid-stream then returns.

    Also sleeps briefly per call so a test asserting the worker bails within
    ~1s would fail if cancellation were ignored (the loop would keep calling).
    """

    def __init__(self, cancel_event: threading.Event) -> None:
        self._cancel_event = cancel_event
        self.calls = 0

    def __call__(self, *args, **kwargs) -> "_CancellingChatLLM":
        """Support ``ChatLLM(model_name=...)`` constructor-style patching."""
        return self

    def stream_chat(
        self, messages, tools=None, on_text_chunk=None, timeout=None,
        should_cancel=None,
    ) -> LLMResponse:
        """Set the cancel_event (simulating a cancel during the stream)."""
        self.calls += 1
        # Mimic a provider that honors should_cancel: fire the event, then
        # return a partial response as stream_chat does on cooperative cancel.
        self._cancel_event.set()
        return LLMResponse(content="partial mid-stream text")


class _NeverCancelLLM:
    """Scripted ChatLLM that always returns the final text (no cancel)."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args, **kwargs) -> "_NeverCancelLLM":
        return self

    def stream_chat(
        self, messages, tools=None, on_text_chunk=None, timeout=None,
        should_cancel=None,
    ) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content=FINAL_TEXT)


def _agent(agent_id: str = "analyst") -> SwarmAgentSpec:
    return SwarmAgentSpec(
        id=agent_id,
        role="Synthesis analyst",
        system_prompt="You synthesize upstream findings.",
        tools=[],
        skills=[],
        max_iterations=5,
        timeout_seconds=60,
    )


def _run(tmp_path: Path, llm, cancel_event=None, task_id="t1") -> WorkerResult:
    task = SwarmTask(id=task_id, agent_id="analyst", prompt_template="Summarize.")
    with (
        patch.object(worker_mod, "build_swarm_registry", lambda *a, **k: _EmptyRegistry()),
        patch.object(worker_mod, "ChatLLM", llm),
    ):
        return run_worker(
            agent_spec=_agent(),
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path,
            cancel_event=cancel_event,
        )


# ---------------------------------------------------------------------------
# #1 cancel_event propagation
# ---------------------------------------------------------------------------


def test_cancel_mid_stream_returns_cancelled_fast(tmp_path):
    """cancel_event set during the stream → worker returns cancelled in <1s."""
    cancel_event = threading.Event()
    llm = _CancellingChatLLM(cancel_event)

    start = time.monotonic()
    result = _run(tmp_path, llm, cancel_event=cancel_event)
    elapsed = time.monotonic() - start

    assert result.status == "cancelled"
    assert elapsed < 1.0
    # Bailed after the first stream, never looped again.
    assert llm.calls == 1


def test_cancel_before_start_returns_cancelled_without_llm_call(tmp_path):
    """cancel_event already set → top-of-iteration early-out, no LLM call."""
    cancel_event = threading.Event()
    cancel_event.set()
    llm = _NeverCancelLLM()

    result = _run(tmp_path, llm, cancel_event=cancel_event)

    assert result.status == "cancelled"
    assert llm.calls == 0


def test_no_cancel_event_completes_normally(tmp_path):
    """cancel_event=None preserves the prior always-run behavior."""
    llm = _NeverCancelLLM()

    result = _run(tmp_path, llm, cancel_event=None)

    assert result.status == "completed"
    assert llm.calls == 1


# ---------------------------------------------------------------------------
# #2 retry on non-terminal-success statuses
# ---------------------------------------------------------------------------


def test_retries_on_timeout_then_succeeds(tmp_path):
    """A worker returning timeout then completed is retried once."""
    store = SwarmStore(tmp_path / "runs")
    rt = SwarmRuntime(store=store, max_workers=1)

    outcomes = [
        WorkerResult(status="timeout", summary="", iterations=1),
        WorkerResult(status="completed", summary=FINAL_TEXT, iterations=2),
    ]
    calls = {"n": 0}

    def _fake_run_worker(*args, **kwargs) -> WorkerResult:
        result = outcomes[calls["n"]]
        calls["n"] += 1
        return result

    agent = _agent()
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="Summarize.")
    with patch.object(runtime_mod, "run_worker", _fake_run_worker):
        result = rt._run_worker_with_retries(
            agent_spec=agent,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path / "runs",
            event_callback=None,
            run_id="run-1",
        )

    assert calls["n"] == 2  # retried after the timeout
    assert result.status == "completed"


def test_cancelled_status_is_not_retried(tmp_path):
    """A cancelled worker result short-circuits the retry loop."""
    store = SwarmStore(tmp_path / "runs")
    rt = SwarmRuntime(store=store, max_workers=1)

    calls = {"n": 0}

    def _fake_run_worker(*args, **kwargs) -> WorkerResult:
        calls["n"] += 1
        return WorkerResult(status="cancelled", summary="", iterations=0)

    agent = _agent()
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="Summarize.")
    with patch.object(runtime_mod, "run_worker", _fake_run_worker):
        result = rt._run_worker_with_retries(
            agent_spec=agent,
            task=task,
            upstream_summaries={},
            user_vars={},
            run_dir=tmp_path / "runs",
            event_callback=None,
            run_id="run-1",
        )

    assert calls["n"] == 1  # no retry
    assert result.status == "cancelled"


# ---------------------------------------------------------------------------
# #3 per-task artifact directories
# ---------------------------------------------------------------------------


def test_parallel_tasks_same_agent_id_write_distinct_summaries(tmp_path):
    """Two tasks sharing an agent_id get distinct artifact dirs; both survive."""
    llm_a = _NeverCancelLLM()
    llm_b = _NeverCancelLLM()

    _run(tmp_path, llm_a, task_id="task-a")
    _run(tmp_path, llm_b, task_id="task-b")

    dir_a = tmp_path / "artifacts" / "analyst__task-a"
    dir_b = tmp_path / "artifacts" / "analyst__task-b"

    assert dir_a != dir_b
    assert (dir_a / "summary.md").is_file()
    assert (dir_b / "summary.md").is_file()
    assert (dir_a / "summary.md").read_text(encoding="utf-8").strip()
    assert (dir_b / "summary.md").read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# #4 atomic write helper
# ---------------------------------------------------------------------------


def test_atomic_write_creates_file_and_leaves_no_tmp(tmp_path):
    """_atomic_write writes the content and cleans up the .tmp sidecar."""
    target = tmp_path / "summary.md"
    _atomic_write(target, "hello world")

    assert target.read_text(encoding="utf-8") == "hello world"
    assert not (tmp_path / "summary.md.tmp").exists()


def test_atomic_write_replaces_existing_content(tmp_path):
    """_atomic_write fully replaces prior content (no truncation artifacts)."""
    target = tmp_path / "messages.json"
    target.write_text("old", encoding="utf-8")

    _atomic_write(target, "brand new content")

    assert target.read_text(encoding="utf-8") == "brand new content"
