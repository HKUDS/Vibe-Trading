"""Recovery hints for container refs and multi-call field refs.

A ref that names a structured container (``call::data.groups.positive``), or a
tool name shared by several calls, cannot ground a figure by itself. These tests
pin that the correction feedback points at the exact leaf ref holding the
figure's value, and that no hint ever widens what a ref authorizes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger

pytestmark = pytest.mark.unit

TOOL = "report_tool"
CALL = "call_1|fc_1"
GROUPS = {
    "ok": True,
    "data": {
        "groups": {
            "positive": [
                {"symbol": "AAA", "move_pct": 2.50, "weight_pct": 10.0, "contribution_pct": 0.25},
                {"symbol": "BBB", "move_pct": 1.00, "weight_pct": 5.0, "contribution_pct": 0.05},
            ],
            "negative": [
                {"symbol": "CCC", "move_pct": -3.00, "weight_pct": 20.0, "contribution_pct": -0.60},
            ],
        },
        "other": {"metric": 42.5},
    },
}


def _ledger(tmp_path: Path, *calls: tuple[str, dict]) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Show contributions per group")
    for call_id, payload in calls or ((CALL, GROUPS),):
        ledger.ingest_tool_result(
            tool_name=TOOL,
            arguments={},
            result=json.dumps(payload),
            call_id=call_id,
            success=True,
        )
    return ledger


def _issue(tmp_path: Path, figure: str, ref: str, *calls: tuple[str, dict]):
    ledger = _ledger(tmp_path, *calls)
    result = ledger.validate_final_answer(
        f"The value was {figure}.\n\n```figures\n{figure} | observed | value | {ref}\n```"
    )
    return ledger, result


def _leaf(group: str, index: int, field: str) -> str:
    return f"{CALL}::data.groups.{group}[{index}].{field}"


@pytest.mark.parametrize(
    ("figure", "expected"),
    [
        ("2.50%", _leaf("positive", 0, "move_pct")),
        ("10.0%", _leaf("positive", 0, "weight_pct")),
        ("0.25%", _leaf("positive", 0, "contribution_pct")),
        ("1.00%", _leaf("positive", 1, "move_pct")),
    ],
)
def test_container_ref_lists_the_value_matched_leaf_first(tmp_path: Path, figure: str, expected: str) -> None:
    _, result = _issue(tmp_path, figure, f"{CALL}::data.groups.positive")
    assert result.valid is False
    candidates = result.issues[0]["field_ref_candidates"]
    assert candidates[0] == expected
    assert len(candidates) <= 5


def test_tool_scoped_container_ref_lists_exact_call_leaf(tmp_path: Path) -> None:
    # A tool name and a path missing its ``data.`` prefix still lead to exact refs.
    _, result = _issue(tmp_path, "-3.00%", f"{TOOL}::groups.negative")
    assert result.issues[0]["field_ref_candidates"][0] == _leaf("negative", 0, "move_pct")


def test_container_hints_stay_inside_the_named_container(tmp_path: Path) -> None:
    _, result = _issue(tmp_path, "2.50%", f"{CALL}::data.groups.negative")
    assert result.valid is False
    assert not any("positive" in item for item in result.issues[0].get("field_ref_candidates") or [])


def test_explicit_element_container_does_not_hint_a_sibling(tmp_path: Path) -> None:
    _, result = _issue(tmp_path, "1.00%", f"{CALL}::data.groups.positive[0]")
    assert result.valid is False
    assert not any("positive[1]" in item for item in result.issues[0].get("field_ref_candidates") or [])


def test_container_ref_never_authorizes_a_value_by_itself(tmp_path: Path) -> None:
    for figure in ("2.50%", "-3.00%", "0.25%"):
        _, result = _issue(tmp_path, figure, f"{CALL}::data.groups.positive")
        assert result.valid is False, figure
        assert {issue["reason"] for issue in result.issues} == {"not_in_referenced_call"}


def test_a_value_that_does_not_exist_gets_no_candidate_and_stays_rejected(
    tmp_path: Path,
) -> None:
    _, result = _issue(tmp_path, "7.77%", f"{CALL}::data.groups.positive")
    assert result.valid is False
    assert not result.issues[0].get("field_ref_candidates")


def test_explicit_element_ref_does_not_authorize_another_element(tmp_path: Path) -> None:
    _, result = _issue(tmp_path, "1.00%", _leaf("positive", 0, "move_pct"))
    assert result.valid is False
    assert {issue["reason"] for issue in result.issues} == {"not_in_referenced_call"}


def test_exact_leaf_ref_from_a_hint_validates(tmp_path: Path) -> None:
    _, result = _issue(tmp_path, "1.00%", _leaf("positive", 1, "move_pct"))
    assert result.valid is True, result.issues


def test_unrelated_refs_get_no_descendant_list(tmp_path: Path) -> None:
    for ref in (f"{CALL}::data.other.metric", f"{CALL}::data.groups.zzz", f"{CALL}::data.zzz"):
        _, result = _issue(tmp_path, "2.50%", ref)
        assert result.valid is False
        assert not result.issues[0].get("field_ref_candidates"), ref


def test_scalar_refs_keep_working(tmp_path: Path) -> None:
    _, result = _issue(tmp_path, "42.5", f"{CALL}::data.other.metric")
    assert result.valid is True, result.issues


def test_feedback_lists_each_candidate_once_and_within_the_cap(tmp_path: Path) -> None:
    ledger, result = _issue(tmp_path, "2.50%", f"{CALL}::data.groups.positive")
    prompt = ledger.correction_prompt(result)
    assert prompt.count(_leaf("positive", 0, "move_pct")) == 1
    assert "valid field refs: " + _leaf("positive", 0, "move_pct") in prompt


# --- several calls returning the same field ---------------------------------

CALL_A, CALL_B = "call_A|fc_a", "call_B|fc_b"


def _returns(value: float) -> dict:
    return {"ok": True, "data": {"portfolio_return_pct": value}}


def test_call_candidates_put_the_value_matched_call_first(tmp_path: Path) -> None:
    _, result = _issue(
        tmp_path,
        "-1.75%",
        f"{TOOL}::portfolio_return_pct",
        (CALL_A, _returns(-2.29)),
        (CALL_B, _returns(-1.75)),
    )
    issue = result.issues[0]
    assert issue["reason"] == "field_ref_needs_call_id"
    assert issue["field_ref_candidates"][0] == f"{CALL_B}::data.portfolio_return_pct"
    assert issue["ambiguous_sources"][0] == issue["field_ref_candidates"][0]


def test_call_candidates_are_capped_and_deterministic(tmp_path: Path) -> None:
    calls = tuple((f"call_{i:02d}|fc_{i}", _returns(float(i))) for i in range(12))
    first = _issue(tmp_path, "-1.75%", f"{TOOL}::portfolio_return_pct", *calls)[1]
    second = _issue(tmp_path, "-1.75%", f"{TOOL}::portfolio_return_pct", *calls)[1]
    candidates = first.issues[0]["field_ref_candidates"]
    assert len(candidates) <= 5
    assert candidates == second.issues[0]["field_ref_candidates"]


def test_call_feedback_does_not_repeat_the_candidate_list(tmp_path: Path) -> None:
    ledger, result = _issue(
        tmp_path,
        "-1.75%",
        f"{TOOL}::portfolio_return_pct",
        (CALL_A, _returns(-2.29)),
        (CALL_B, _returns(-1.75)),
    )
    prompt = ledger.correction_prompt(result)
    assert prompt.count(f"{CALL_B}::data.portfolio_return_pct") == 1


def test_a_call_ref_never_authorizes_a_value_seen_only_in_another_call(
    tmp_path: Path,
) -> None:
    _, result = _issue(
        tmp_path,
        "-1.75%",
        f"{CALL_A}::data.portfolio_return_pct",
        (CALL_A, _returns(-2.29)),
        (CALL_B, _returns(-1.75)),
    )
    assert result.valid is False
    assert {issue["reason"] for issue in result.issues} == {"not_in_referenced_call"}


def test_the_matching_call_ref_validates_once_chosen(tmp_path: Path) -> None:
    _, result = _issue(
        tmp_path,
        "-1.75%",
        f"{CALL_B}::data.portfolio_return_pct",
        (CALL_A, _returns(-2.29)),
        (CALL_B, _returns(-1.75)),
    )
    assert result.valid is True, result.issues


def test_a_tool_scoped_ref_with_a_nonexistent_value_stays_rejected(tmp_path: Path) -> None:
    _, result = _issue(
        tmp_path,
        "-9.99%",
        f"{TOOL}::portfolio_return_pct",
        (CALL_A, _returns(-2.29)),
        (CALL_B, _returns(-1.75)),
    )
    assert result.valid is False


def test_wrong_call_for_the_right_field_hints_the_call_holding_the_value(tmp_path: Path) -> None:
    _, result = _issue(
        tmp_path,
        "-1.75%",
        f"{CALL_A}::data.portfolio_return_pct",
        (CALL_A, _returns(-2.29)),
        (CALL_B, _returns(-1.75)),
    )
    assert result.valid is False
    assert result.issues[0]["field_ref_candidates"] == [f"{CALL_B}::data.portfolio_return_pct"]


def test_wrong_call_hint_is_value_matched_only(tmp_path: Path) -> None:
    _, result = _issue(
        tmp_path,
        "-9.99%",
        f"{CALL_A}::data.portfolio_return_pct",
        (CALL_A, _returns(-2.29)),
        (CALL_B, _returns(-1.75)),
    )
    assert result.valid is False
    assert not result.issues[0].get("field_ref_candidates")


def test_wrong_call_hint_stays_within_the_declared_calls_tool(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, (CALL_A, _returns(-2.29)))
    ledger.ingest_tool_result(
        tool_name="other_tool",
        arguments={},
        result=json.dumps(_returns(-1.75)),
        call_id="call_X|fc_x",
        success=True,
    )
    result = ledger.validate_final_answer(
        f"The value was -1.75%.\n\n```figures\n-1.75% | observed | v | {CALL_A}::data.portfolio_return_pct\n```"
    )
    assert result.valid is False
    assert not result.issues[0].get("field_ref_candidates")
