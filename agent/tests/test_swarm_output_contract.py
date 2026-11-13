"""Delivery status and tool errors remain factual; prose is not graded."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.providers.chat import LLMResponse, ToolCallRequest
from src.swarm.models import (
    RunStatus,
    SwarmAgentSpec,
    SwarmEvent,
    SwarmRun,
    SwarmTask,
    WorkerResult,
)
from src.swarm.store import SwarmStore
from src.swarm.worker import (
    _delivery_error,
    _collect_artifacts,
    _is_error_result,
    run_worker,
)
import src.swarm.runtime as rt
import src.swarm.worker as worker_mod

PLAN_STUB = (
    "### Phase 1 — Plan\n"
    "1. Load the asset-allocation skill\n"
    "2. Fetch data\n\n"
    "### Phase 2 — Execute\n"
    "First, I'll load the necessary skills."
)
REAL_REPORT = (
    "# BTC-USDT — Short-Term View\n\n"
    "Spot fetched via okx: 81,704.6 (2026-05-05). 7d range 77,750–82,842.\n\n"
    "**Recommendation: accumulate on dips to 79k; invalidation below 77.5k.**\n"
    "Position 3% NAV, stop 76,900, target 86,000. Funding 0.035%/8h is elevated\n"
    "but not extreme; on-chain exchange reserves declining (bullish)."
)


@pytest.mark.parametrize("text", [PLAN_STUB, REAL_REPORT, "Hold.",
    "No mock data was used. Hold based on the supplied data.",
    '{"ok": true, "content": "Hold"}',
    "## Plan\nAnalysis complete. Hold the existing position."])
def test_report_shape_is_not_a_delivery_error(text):
    assert _delivery_error(text) is None


def test_actual_delivery_errors():
    assert _delivery_error(" ") == "empty response"
    assert _delivery_error("<tool_call_begin>broken")


# ---- runtime integrity ----------------------------------------------------
def _run(tmp_path: Path, worker_result: WorkerResult) -> SwarmRun:
    store = SwarmStore(base_dir=tmp_path)
    runtime = rt.SwarmRuntime(store=store)
    agent = SwarmAgentSpec(id="analyst", role="Analyst", system_prompt="x", max_retries=0)
    task = SwarmTask(id="t1", agent_id="analyst", prompt_template="do x")
    run = SwarmRun(id="r", preset_name="demo", created_at="2026-01-01T00:00:00Z", agents=[agent], tasks=[task])
    store.create_run(run)
    runtime._execute_run(run, threading.Event())
    reloaded = store.load_run(run.id)
    assert reloaded is not None
    return reloaded


def test_timeout_terminal_run_not_completed(tmp_path, monkeypatch):
    """fail-before / pass-after anchor: timeout terminal must not be a success."""
    monkeypatch.setattr(
        rt,
        "run_worker",
        lambda *a, **k: WorkerResult(status="timeout", summary="partial work"),
    )
    run = _run(tmp_path, None)
    assert run.status != RunStatus.completed
    assert run.final_report
    assert run.report_is_partial


def test_incomplete_terminal_run_not_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rt,
        "run_worker",
        lambda *a, **k: WorkerResult(
            status="incomplete",
            summary=PLAN_STUB,
            error="output contract not met: plan-only stub",
        ),
    )
    run = _run(tmp_path, None)
    assert run.status != RunStatus.completed
    assert run.final_report
    assert run.report_is_partial
    assert run.tasks[0].error and "plan-only" in run.tasks[0].error


def test_genuine_completion_still_succeeds(tmp_path, monkeypatch):
    """Guard: a real deliverable must still complete and become final_report."""
    monkeypatch.setattr(
        rt,
        "run_worker",
        lambda *a, **k: WorkerResult(status="completed", summary=REAL_REPORT, iterations=4),
    )
    run = _run(tmp_path, None)
    assert run.status == RunStatus.completed
    assert run.final_report == REAL_REPORT


# ---- _is_error_result: JSON parse + truncation fallback -------------------
# Follow-up from #119: the substring head-match could (a) false-positive on
# a nested ``status`` field and (b) false-negate when the envelope sat past
# the 160-char head. Parsing the envelope as JSON pins both.


def test_is_error_result_top_level_error():
    assert _is_error_result('{"status": "error", "error": "bad key"}') is True
    assert _is_error_result('{"status":"error"}') is True


def test_is_error_result_top_level_ok():
    assert _is_error_result('{"status": "ok", "content": "..."}') is False


def test_is_error_result_nested_error_no_false_positive():
    """A nested ``status`` (e.g. inside ``data``) must NOT count — only the
    envelope status matters for the deliverable contract."""
    nested = '{"status": "ok", "data": {"status": "error", "detail": "x"}}'
    assert _is_error_result(nested) is False


def test_is_error_result_error_past_substring_head():
    """G2: an error envelope where ``status`` sits past the 160-char head
    (long preamble in another field). Substring head-match used to miss
    this; JSON parse catches it."""
    long_field = "x" * 200
    payload = '{"meta": "' + long_field + '", "status": "error"}'
    assert _is_error_result(payload) is True


def test_is_error_result_truncated_falls_back_to_substring():
    """Truncated / unparseable JSON still gets the original substring
    classifier; the function must never raise on the worker hot path."""
    truncated = '{"status": "error", "trace": "...'  # missing closing quote
    assert _is_error_result(truncated) is True


def test_is_error_result_non_json_safe():
    assert _is_error_result("") is False
    assert _is_error_result(None) is False  # type: ignore[arg-type]
    assert _is_error_result("plain text output") is False
    assert _is_error_result("[1, 2, 3]") is False  # JSON array, not envelope


def test_is_error_result_other_status_values():
    """Only ``"error"`` counts; ``"warning"`` / ``"degenerate"`` etc. are
    not error envelopes (the worker still credits them as a tool call)."""
    assert _is_error_result('{"status": "degenerate", "warning": "T=0"}') is False
    assert _is_error_result('{"status": "warning"}') is False


def test_is_error_result_ok_false_envelope_no_status_key():
    """A failure reported only via ``ok: false`` (no top-level ``status``,
    e.g. get_stock_news's real failure shape) must count as an error. This
    is the exact envelope that let a failed tool call be silently credited
    as a completed data tool call before this fix."""
    assert (
        _is_error_result('{"ok": false, "error": "eastmoney news fetch failed"}')
        is True
    )


def test_is_error_result_success_false_envelope_no_status_key():
    assert _is_error_result('{"success": false, "error": "boom"}') is True


def test_is_error_result_ok_true_is_not_an_error():
    assert _is_error_result('{"ok": true, "data": []}') is False


def test_is_error_result_nested_ok_false_no_false_positive():
    """A nested ``ok: false`` (e.g. inside ``data``) must NOT count. Only
    the envelope's own ``ok``/``success`` matters, mirroring the existing
    nested-``status`` guarantee."""
    nested = '{"status": "ok", "data": {"ok": false, "detail": "x"}}'
    assert _is_error_result(nested) is False


class _ResultTool(BaseTool):
    """Return one canned result or raise to exercise ToolRegistry normalization."""

    name = "market_probe"
    description = "Return a canned market result."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, result: str, *, raises: bool = False) -> None:
        self._result = result
        self._raises = raises

    def execute(self, **kwargs) -> str:
        if self._raises:
            raise RuntimeError("local probe failed")
        return self._result


class _ScriptedLLM:
    def __init__(self) -> None:
        self._responses = [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallRequest(id="call-1", name="market_probe", arguments={})
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Completed the requested market analysis with a clear conclusion.",
                tool_calls=[],
                finish_reason="stop",
            ),
        ]

    def stream_chat(self, messages, tools=None, timeout=None, on_text_chunk=None, on_waiting_chunk=None):
        return self._responses.pop(0)

    def close(self) -> None:
        """No-op: the scripted stub owns no HTTP client."""


@pytest.mark.parametrize(
    ("result", "raises", "expected_event_status", "expected_worker_status"),
    [
        ('{"status": "ok", "data": [1]}', False, "ok", "completed"),
        ('{"status": "error", "trace": "...', False, "error", "completed"),
        ("", True, "error", "completed"),
        (
            '{"ok": false, "error": "eastmoney news fetch failed"}',
            False,
            "error",
            "completed",
        ),
    ],
)
def test_tool_result_event_status_and_evidence_credit_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: str,
    raises: bool,
    expected_event_status: str,
    expected_worker_status: str,
) -> None:
    registry = ToolRegistry()
    registry.register(_ResultTool(result, raises=raises))
    monkeypatch.setattr(
        worker_mod, "build_swarm_registry", lambda *args, **kwargs: registry
    )
    monkeypatch.setattr(worker_mod, "ChatLLM", lambda *args, **kwargs: _ScriptedLLM())

    events: list[SwarmEvent] = []
    worker_result = run_worker(
        agent_spec=SwarmAgentSpec(
            id="analyst",
            role="Analyst",
            system_prompt="Analyse the result.",
            tools=["market_probe"],
            max_iterations=3,
        ),
        task=SwarmTask(
            id="task", agent_id="analyst", prompt_template="Probe the market."
        ),
        upstream_summaries={},
        user_vars={},
        run_dir=tmp_path,
        event_callback=events.append,
    )

    tool_result = next(event for event in events if event.type == "tool_result")
    assert tool_result.data["status"] == expected_event_status
    assert worker_result.status == expected_worker_status


def test_collect_artifacts_recurses_and_returns_sorted_run_relative_paths(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "run" / "artifacts" / "analyst"
    (artifact_dir / "nested").mkdir(parents=True)
    (artifact_dir / "other").mkdir()
    (artifact_dir / "summary.md").write_text("summary", encoding="utf-8")
    (artifact_dir / "nested" / "report.json").write_text("{}", encoding="utf-8")
    (artifact_dir / "other" / "report.json").write_text("{}", encoding="utf-8")

    assert _collect_artifacts(tmp_path / "run", artifact_dir) == [
        "artifacts/analyst/nested/report.json",
        "artifacts/analyst/other/report.json",
        "artifacts/analyst/summary.md",
    ]


def test_collect_artifacts_rejects_symlink_escape(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "run" / "artifacts" / "analyst"
    artifact_dir.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    escape = artifact_dir / "escape.txt"
    try:
        escape.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    assert _collect_artifacts(tmp_path / "run", artifact_dir) == []


# ---------------------------------------------------------------------------
# ChatLLM lifecycle: run_worker must close the per-task LLM (regression #1141)
# ---------------------------------------------------------------------------


def test_run_worker_closes_llm_on_success(monkeypatch, tmp_path: Path) -> None:
    """A successful run must close the per-task ChatLLM exactly once."""
    import src.swarm.worker as worker_mod

    registry = ToolRegistry()
    registry.register(_ResultTool("done", raises=False))
    monkeypatch.setattr(
        worker_mod, "build_swarm_registry", lambda *args, **kwargs: registry
    )
    closed = []

    class _TrackingLLM(_ScriptedLLM):
        def close(self) -> None:
            closed.append(1)

    monkeypatch.setattr(
        worker_mod, "ChatLLM", lambda *args, **kwargs: _TrackingLLM()
    )

    worker_result = run_worker(
        agent_spec=SwarmAgentSpec(
            id="analyst",
            role="Analyst",
            system_prompt="Analyse the result.",
            tools=["market_probe"],
            max_iterations=3,
        ),
        task=SwarmTask(
            id="task", agent_id="analyst", prompt_template="Probe the market."
        ),
        upstream_summaries={},
        user_vars={},
        run_dir=tmp_path,
    )
    assert worker_result.status.value == "completed"
    assert len(closed) == 1, f"close must be called exactly once, got {len(closed)}"


def test_run_worker_closes_llm_on_tool_exception(monkeypatch, tmp_path: Path) -> None:
    """close() must fire even when the run dies on a tool exception."""
    import src.swarm.worker as worker_mod

    registry = ToolRegistry()
    registry.register(_ResultTool("boom", raises=True))
    monkeypatch.setattr(
        worker_mod, "build_swarm_registry", lambda *args, **kwargs: registry
    )
    closed = []

    class _TrackingLLM(_ScriptedLLM):
        def close(self) -> None:
            closed.append(1)

    monkeypatch.setattr(
        worker_mod, "ChatLLM", lambda *args, **kwargs: _TrackingLLM()
    )

    worker_result = run_worker(
        agent_spec=SwarmAgentSpec(
            id="analyst",
            role="Analyst",
            system_prompt="Analyse the result.",
            tools=["market_probe"],
            max_iterations=3,
        ),
        task=SwarmTask(
            id="task", agent_id="analyst", prompt_template="Probe the market."
        ),
        upstream_summaries={},
        user_vars={},
        run_dir=tmp_path,
    )
    assert worker_result.status.value == "completed"
    assert len(closed) == 1, f"close must fire on failure path, got {len(closed)}"


def test_chatllm_close_is_best_effort_noop_without_client() -> None:
    """ChatLLM.close() must not raise when the provider adapter has no
    closeable client (e.g. scripted/native adapters without root_client)."""
    from src.providers.chat import ChatLLM

    class _BareLLM:
        def bind_tools(self, tools):
            return self

    llm = ChatLLM.__new__(ChatLLM)
    llm._llm = _BareLLM()  # no root_client / client attributes
    llm.close()  # must not raise
