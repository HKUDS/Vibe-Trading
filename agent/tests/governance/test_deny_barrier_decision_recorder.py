"""Tests for v1.2.1 deny barrier and DecisionRecorder behavior."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from src.agent.tools import BaseTool, ToolRegistry
from src.agent.trace import TraceWriter
from src.governance.decision_recorder import DecisionRecorder
from src.governance.decisions import PolicyDecision
from src.governance.runtime import GovernedToolRegistry, PolicyDenied, RuntimeContext
from src.reliability.artifacts.store import ArtifactStore


class CountingTool(BaseTool):
    name = "fake_tool"
    description = "Fake counted tool."
    parameters = {"type": "object", "properties": {}}
    risk_level = "R1_READ"

    def __init__(self) -> None:
        self.execution_counter = 0

    def execute(self, **kwargs: Any) -> str:
        self.execution_counter += 1
        return json.dumps({"status": "ok", "params": kwargs}, ensure_ascii=False)


class StaticPolicy:
    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        self.calls = 0

    def evaluate(self, *, name: str, params: dict[str, Any], manifest: Any, context: RuntimeContext) -> PolicyDecision:
        self.calls += 1
        return self.decision.model_copy(update={"tool_name": name, "risk_level": manifest.risk_level})


class FailingArtifactStore:
    def write_json(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("artifact store unavailable")


class FailingTraceWriter:
    def write(self, entry: dict[str, Any]) -> None:
        raise RuntimeError("trace unavailable")


def _registry_with(tool: CountingTool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool)
    return registry


def _deny_decision(risk_level: str) -> PolicyDecision:
    return PolicyDecision(
        tool_name="fake_tool",
        action="deny",
        risk_level=risk_level,
        reasons=["blocked by test policy"],
        reason_codes=[f"{risk_level}_DENIED"],
        policy_engine_version="engine-test",
    )


def test_idempotent_record_retry_does_not_duplicate_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    recorder = DecisionRecorder(artifact_store=ArtifactStore(tmp_path))
    context = RuntimeContext(mode="warn", surface="remote_api", run_id="run_1")
    decision = _deny_decision("R5_SHELL")

    envelope1 = recorder.prepare(decision, params={"cmd": "echo hi"}, context=context)
    outcome1 = recorder.record_best_effort(envelope1)
    envelope2 = recorder.prepare(decision, params={"cmd": "echo hi"}, context=context)
    outcome2 = recorder.record_best_effort(envelope2)

    assert outcome1.policy_decision_artifact_id == outcome2.policy_decision_artifact_id
    assert envelope1.decision_id == envelope2.decision_id
    with sqlite3.connect(tmp_path / "artifact_index.sqlite") as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE artifact_type = 'policy_decision'"
        ).fetchone()[0]
    assert count == 1


def test_r5_remote_shell_deny_barrier_prevents_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    tool = CountingTool()
    tool.name = "fake_shell"
    tool.risk_level = "R5_SHELL"
    recorder = DecisionRecorder(artifact_store=ArtifactStore(tmp_path))
    governed = GovernedToolRegistry(
        _registry_with(tool),
        policy=StaticPolicy(_deny_decision("R5_SHELL")),
        decision_recorder=recorder,
        context=RuntimeContext(mode="observe", surface="remote_api", run_id="run_r5"),
    )

    with pytest.raises(PolicyDenied) as exc_info:
        governed.execute("fake_shell", {"cmd": "whoami"})

    assert tool.execution_counter == 0
    envelope = exc_info.value.envelope
    assert envelope.deny_barrier_engaged is True
    assert envelope.shadow_deny is True
    assert envelope.inner_tool_executed is False
    assert envelope.write_outcome is not None
    assert envelope.write_outcome.artifact_written is True


def test_r4_scheduler_trade_deny_barrier_prevents_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    tool = CountingTool()
    tool.name = "fake_trade_write"
    tool.risk_level = "R4_TRADE_WRITE"
    governed = GovernedToolRegistry(
        _registry_with(tool),
        policy=StaticPolicy(_deny_decision("R4_TRADE_WRITE")),
        decision_recorder=DecisionRecorder(artifact_store=ArtifactStore(tmp_path)),
        context=RuntimeContext(mode="warn", surface="scheduler", run_id="run_r4"),
    )

    with pytest.raises(PolicyDenied) as exc_info:
        governed.execute("fake_trade_write", {"symbol": "AAPL", "qty": 1})

    assert tool.execution_counter == 0
    assert exc_info.value.envelope.deny_barrier_engaged is True
    assert exc_info.value.envelope.inner_tool_executed is False


def test_artifact_write_failure_does_not_execute_inner_tool() -> None:
    tool = CountingTool()
    tool.name = "fake_shell"
    tool.risk_level = "R5_SHELL"
    governed = GovernedToolRegistry(
        _registry_with(tool),
        policy=StaticPolicy(_deny_decision("R5_SHELL")),
        decision_recorder=DecisionRecorder(artifact_store=FailingArtifactStore()),
        context=RuntimeContext(mode="warn", surface="remote_api", run_id="run_fail"),
    )

    with pytest.raises(PolicyDenied) as exc_info:
        governed.execute("fake_shell", {"cmd": "echo should-not-run"})

    assert tool.execution_counter == 0
    assert exc_info.value.envelope.inner_tool_executed is False
    assert exc_info.value.envelope.write_outcome is not None
    assert exc_info.value.envelope.write_outcome.status == "write_failed"
    assert exc_info.value.envelope.write_outcome.errors


def test_trace_write_failure_marks_partial_but_denies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    tool = CountingTool()
    tool.name = "fake_shell"
    tool.risk_level = "R5_SHELL"
    governed = GovernedToolRegistry(
        _registry_with(tool),
        policy=StaticPolicy(_deny_decision("R5_SHELL")),
        decision_recorder=DecisionRecorder(
            artifact_store=ArtifactStore(tmp_path),
            trace_writer=FailingTraceWriter(),
        ),
        context=RuntimeContext(mode="warn", surface="remote_api", run_id="run_trace_fail"),
    )

    with pytest.raises(PolicyDenied) as exc_info:
        governed.execute("fake_shell", {"cmd": "echo should-not-run"})

    assert tool.execution_counter == 0
    outcome = exc_info.value.envelope.write_outcome
    assert outcome is not None
    assert outcome.artifact_written is True
    assert outcome.trace_written is False
    assert outcome.status == "partial_artifact_only"


def test_secret_redaction_in_params_preview() -> None:
    recorder = DecisionRecorder()
    envelope = recorder.prepare(
        _deny_decision("R5_SHELL"),
        params={
            "apiToken": "sk-test-secret-value-abcdefghijklmnopqrstuvwxyz",
            "nested": {"broker_password": "plain-password"},
            "safe": "visible",
        },
        context=RuntimeContext(mode="warn", surface="remote_api", run_id="run_redact"),
    )

    dumped = json.dumps(envelope.redacted_params_preview, ensure_ascii=False)
    assert "[REDACTED]" in dumped
    assert "sk-test-secret-value" not in dumped
    assert "plain-password" not in dumped
    assert envelope.redacted_params_preview["safe"] == "visible"


def test_governance_mode_off_preserves_legacy_no_artifact_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIBE_TRADING_GOVERNANCE_MODE", "off")
    monkeypatch.setenv("VIBE_TRADING_RELIABILITY_MODE", "observe")
    tool = CountingTool()
    tool.name = "fake_shell"
    tool.risk_level = "R5_SHELL"
    governed = GovernedToolRegistry(
        _registry_with(tool),
        policy=StaticPolicy(_deny_decision("R5_SHELL")),
        decision_recorder=DecisionRecorder(
            artifact_store=ArtifactStore(tmp_path),
            trace_writer=TraceWriter(tmp_path / "trace"),
        ),
        context=RuntimeContext(mode="warn", surface="remote_api", run_id="run_off"),
    )

    result = json.loads(governed.execute("fake_shell", {"cmd": "legacy"}))

    assert result["status"] == "ok"
    assert tool.execution_counter == 1
    assert not (tmp_path / "artifact_index.sqlite").exists()
