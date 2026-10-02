"""An alias before ``::`` names no call: the correction lists the real refs, grants nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.context import _SYSTEM_PROMPT
from src.agent.grounding import GroundingLedger

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
