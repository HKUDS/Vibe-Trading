"""An alias before ``::`` names no call: the correction lists the real refs, grants nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.context import _SYSTEM_PROMPT
from src.agent.grounding import GroundingLedger
from src.agent.loop import AgentLoop
from src.agent.tools import BaseTool, ToolRegistry
from src.agent.trace import TraceWriter
from src.providers.chat import LLMResponse, ToolCallRequest

pytestmark = pytest.mark.unit

PATH = "data.summary.total_return"


def _ledger(tmp_path: Path, values: dict[str, float]) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report the total return")
    for call_id, value in values.items():
        ledger.ingest_tool_result(
            tool_name="report_tool",
            arguments={"id": call_id},
            result=json.dumps({"data": {"summary": {"total_return": value}}}),
            call_id=call_id,
            success=True,
        )
    return ledger


def _check(ledger: GroundingLedger, ref: str, written: str = "12.5"):
    return ledger.validate_final_answer(
        f"Total return {written}.\n```figures\n{written} | observed | total return | {ref}\n```"
    )


def test_alias_stays_rejected_and_lists_the_real_ref(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, {"call_9f3a": 12.5})

    result = _check(ledger, f"r1::{PATH}")

    assert result.valid is False
    issue = result.issues[0]
    assert issue["reason"] == "unknown_call_id"
    assert issue["field_ref_candidates"] == [f"call_9f3a::{PATH}"]
    correction = ledger.correction_prompt(result)
    assert f"call_9f3a::{PATH}" in correction
    assert "not an alias" in correction
    # The suggestion is advisory: only the exact ref is accepted.
    assert _check(ledger, f"call_9f3a::{PATH}").valid is True


def test_alias_with_a_shortened_path_lists_the_full_path(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, {"call_9f3a": 12.5})

    result = _check(ledger, "r1::summary.total_return")

    assert result.valid is False
    assert result.issues[0]["field_ref_candidates"] == [f"call_9f3a::{PATH}"]


def test_candidates_matching_the_value_come_first(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, {"a_call": 3.0, "b_call": 12.5, "c_call": 7.0})

    result = _check(ledger, f"r1::{PATH}")

    assert result.valid is False
    candidates = result.issues[0]["field_ref_candidates"]
    assert candidates[0] == f"b_call::{PATH}"
    assert set(candidates) == {f"{call}::{PATH}" for call in ("a_call", "b_call", "c_call")}


def test_candidates_are_capped(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, {f"call_{index}": float(index) for index in range(9)})

    result = _check(ledger, f"r1::{PATH}", "12.5")

    assert result.valid is False
    assert len(result.issues[0]["field_ref_candidates"]) == 5


def test_alias_for_a_field_no_call_returned_lists_nothing(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, {"call_9f3a": 12.5})

    result = _check(ledger, "r1::data.summary.missing_field")

    assert result.valid is False
    assert result.issues[0]["reason"] == "not_in_referenced_call"
    assert not result.issues[0].get("field_ref_candidates")


def test_a_real_call_without_the_field_is_not_treated_as_an_alias(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, {"call_9f3a": 12.5})

    result = _check(ledger, "call_9f3a::data.summary.missing_field")

    assert result.valid is False
    assert result.issues[0]["reason"] != "unknown_call_id"


def test_a_bare_unknown_ref_does_not_get_candidates(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, {"call_9f3a": 12.5})

    result = _check(ledger, "r1")

    assert not any(issue.get("reason") == "unknown_call_id" for issue in result.issues)


def test_prompt_example_is_a_placeholder_not_a_call_id_shape() -> None:
    assert "q1::" not in _SYSTEM_PROMPT
    assert "<call_id>::historical_var" in _SYSTEM_PROMPT
    assert "never invent a short alias" in _SYSTEM_PROMPT


@pytest.mark.parametrize("written", ["12.6", "12.55", "15.0"])
def test_copying_a_real_ref_does_not_authorize_an_invented_value(
    tmp_path: Path, written: str
) -> None:
    ledger = _ledger(tmp_path, {"call_9f3a": 12.5})
    rejected = _check(ledger, f"r1::{PATH}", written)
    assert not rejected.valid
    ref = rejected.issues[0]["field_ref_candidates"][0]

    assert not _check(ledger, ref, written).valid
    assert _check(ledger, ref).valid


@pytest.mark.parametrize("written", ["12.5%", "0.125"])
def test_corrected_percent_or_decimal_preserves_existing_unit_matching(
    tmp_path: Path, written: str
) -> None:
    ledger = _ledger(tmp_path, {"call_9f3a": 0.125})
    rejected = _check(ledger, f"r1::{PATH}", written)
    assert not rejected.valid
    ref = rejected.issues[0]["field_ref_candidates"][0]

    assert _check(ledger, ref, written).valid


@pytest.mark.parametrize(
    ("field", "written"),
    [
        ("total_return", "$12.5"),
        ("close", "12.5%"),
        ("return_observations", "12.5%"),
    ],
)
def test_candidates_do_not_offer_a_field_of_the_wrong_kind(
    tmp_path: Path, field: str, written: str
) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report the value")
    ledger.ingest_tool_result(
        tool_name="report_tool",
        arguments={},
        result=json.dumps({"data": {field: 12.5}}),
        call_id="call_9f3a",
        success=True,
    )
    result = _check(ledger, f"r1::data.{field}", written)

    assert not result.valid
    assert not any(issue.get("field_ref_candidates") for issue in result.issues)
    assert not _check(ledger, f"call_9f3a::data.{field}", written).valid


def test_candidates_remain_scoped_to_the_declared_symbol(tmp_path: Path) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report summary metrics")
    for call_id, symbol, value in (
        ("call_aapl", "AAPL.US", 12.5),
        ("call_msft", "MSFT.US", 12.5),
    ):
        ledger.ingest_tool_result(
            tool_name="report_tool",
            arguments={"symbol": symbol},
            result=json.dumps({"symbol": symbol, "data": {"summary": {"total_return": value}}}),
            call_id=call_id,
            success=True,
        )
    result = ledger.validate_final_answer(
        f"Total return 12.5.\n```figures\n12.5 | observed | AAPL.US total return | r1::{PATH}\n```"
    )

    assert not result.valid
    issue = next(issue for issue in result.issues if issue.get("reason") == "unknown_call_id")
    assert issue["field_ref_candidates"] == [f"call_aapl::{PATH}"]


@pytest.mark.parametrize("path", ["data.positions[0].total_return", "positions.0.total_return"])
def test_alias_with_an_explicit_index_never_offers_a_sibling(
    tmp_path: Path, path: str
) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report the values")
    ledger.ingest_tool_result(
        tool_name="report_tool",
        arguments={},
        result=json.dumps({"data": {"positions": [{"total_return": 3.0}, {"total_return": 12.5}]}}),
        call_id="call_9f3a",
        success=True,
    )
    rejected = _check(ledger, f"r1::{path}")
    assert not rejected.valid
    candidates = rejected.issues[0]["field_ref_candidates"]
    assert candidates == ["call_9f3a::data.positions[0].total_return"]
    assert not _check(ledger, candidates[0]).valid
    assert _check(ledger, candidates[0], "3.0").valid


def test_a_known_tool_keeps_its_existing_correction_reason(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, {"call_9f3a": 12.5})
    result = _check(ledger, f"report_tool::{PATH}")

    assert not result.valid
    assert result.issues[0]["reason"] == "field_ref_needs_call_id"
    assert result.issues[0]["field_ref_candidates"] == [f"call_9f3a::{PATH}"]


@pytest.mark.parametrize("ref", [f"::{PATH}", "r1::", "r1::data.summary"])
def test_incomplete_or_container_refs_get_no_scalar_hint(tmp_path: Path, ref: str) -> None:
    result = _check(_ledger(tmp_path, {"call_9f3a": 12.5}), ref)

    assert not result.valid
    assert not any(issue.get("field_ref_candidates") for issue in result.issues)


@pytest.mark.parametrize("written", ["12.5%", "$0.125"])
def test_analysis_only_candidates_preserve_the_figure_kind(tmp_path: Path, written: str) -> None:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Report the tail risk")
    ledger.ingest_tool_result(
        tool_name="quantlib_call",
        arguments={"action": "call", "function": "historical_var"},
        result=json.dumps({"ok": True, "result": 0.125}),
        call_id="call_9f3a",
        success=True,
    )
    result = _check(ledger, "r1::historical_var", written)

    assert not result.valid
    if written.endswith("%"):
        ref = result.issues[0]["field_ref_candidates"][0]
        assert ref == "call_9f3a::historical_var"
        assert _check(ledger, ref, written).valid
    else:
        assert not any(issue.get("field_ref_candidates") for issue in result.issues)


class _ReportTool(BaseTool):
    name = "report_tool"
    description = "Return summary metrics."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, result: str) -> None:
        self.result = result

    def execute(self, **_kwargs) -> str:
        return self.result


def test_agent_loop_sends_the_hint_and_releases_the_corrected_answer(tmp_path: Path) -> None:
    """Replay the provider response locally through the actual tool and release path."""
    exact_ref = f"call_9f3a::{PATH}"

    def draft(ref: str) -> str:
        return f"Total return 12.5.\n```figures\n12.5 | observed | total return | {ref}\n```"

    class CopyingLLM:
        calls = 0

        def stream_chat(self, messages, on_text_chunk=None, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(tool_calls=[ToolCallRequest("call_9f3a", "report_tool", {})])
            if self.calls == 2:
                content = draft(f"r1::{PATH}")
            else:
                assert self.calls == 3
                correction = messages[-1]["content"]
                assert exact_ref in correction
                assert "not an alias" in correction
                content = draft(exact_ref)
            if on_text_chunk:
                on_text_chunk(content)
            return LLMResponse(content=content)

        def chat(self, _messages, **_kwargs):
            return LLMResponse(content="")

    registry = ToolRegistry()
    registry.register(_ReportTool(json.dumps({"data": {"summary": {"total_return": 12.5}}})))
    llm = CopyingLLM()
    events = []
    agent = AgentLoop(
        registry=registry,
        llm=llm,
        max_iterations=5,
        event_callback=lambda event, data: events.append((event, data)),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    result = agent.run("Report the total return")

    assert result["status"] == "success"
    assert not result.get("degraded")
    assert result["content"] == "Total return 12.5."
    assert llm.calls == 3
    rejected = [event for event in TraceWriter.read(run_dir) if event.get("type") == "answer_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["issues"][0]["reason"] == "unknown_call_id"
    assert rejected[0]["issues"][0]["field_ref_candidates"] == [exact_ref]
    assert any(event == "grounding_status" and data["stage"] == "revising" for event, data in events)


def test_agent_loop_keeps_clean_figures_and_revalidates_the_repair(tmp_path: Path) -> None:
    """Exercise keep feedback through the actual AgentLoop without a paid model."""
    class RepairingLLM:
        calls = 0

        def stream_chat(self, messages, on_text_chunk=None, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(tool_calls=[ToolCallRequest("call_report", "report_tool", {})])
            if self.calls == 2:
                drawdown = "99.9"
            else:
                assert self.calls == 3
                keep = next(line for line in messages[-1]["content"].splitlines() if "checked clean" in line)
                assert "12.5" in keep and "99.9" not in keep
                drawdown = "23.75"
            content = (
                f"Total return 12.5. Maximum drawdown {drawdown}.\n"
                "```figures\n12.5 | observed | total return | call_report::data.summary.total_return\n"
                f"{drawdown} | observed | maximum drawdown | call_report::data.summary.max_drawdown\n```"
            )
            if on_text_chunk:
                on_text_chunk(content)
            return LLMResponse(content=content)

        def chat(self, _messages, **_kwargs):
            return LLMResponse(content="")

    registry = ToolRegistry()
    registry.register(_ReportTool(json.dumps({"data": {"summary": {"total_return": 12.5, "max_drawdown": 23.75}}})))
    llm = RepairingLLM()
    agent = AgentLoop(registry=registry, llm=llm, max_iterations=5)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    agent.memory.run_dir = str(run_dir)
    result = agent.run("Report the total return and maximum drawdown")
    assert result["status"] == "success"
    assert result["content"] == "Total return 12.5. Maximum drawdown 23.75."
    assert not result.get("degraded")
    assert llm.calls == 3
    rejected = [event for event in TraceWriter.read(run_dir) if event.get("type") == "answer_rejected"]
    assert len(rejected) == 1
    assert rejected[0]["issues"][0]["value"] == "99.9"
