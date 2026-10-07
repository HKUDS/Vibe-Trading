"""Field refs into list elements: index spelling, exact candidates, isolation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger

pytestmark = pytest.mark.unit

TOOL = "report_tool"
CALL = "call_1|fc_1"
PAYLOAD = {
    "ok": True,
    "data": {
        "total_return_pct": 0.36,
        "positions": [
            {"symbol": "AAA", "contribution_pct": 1.23},
            {"symbol": "BBB", "contribution_pct": -0.87},
        ],
    },
}


def _ledger(tmp_path: Path) -> GroundingLedger:
    ledger = GroundingLedger(
        run_dir=tmp_path, user_message="Show contributions per position"
    )
    ledger.ingest_tool_result(
        tool_name=TOOL,
        arguments={},
        result=json.dumps(PAYLOAD),
        call_id=CALL,
        success=True,
    )
    return ledger


def _validate(tmp_path: Path, prose: str, *rows: str):
    block = "\n\n```figures\n" + "\n".join(rows) + "\n```"
    return _ledger(tmp_path).validate_final_answer(prose + block)


def _ref(index: int, dotted: bool = False, field: str = "contribution_pct") -> str:
    path = f"positions.{index}" if dotted else f"positions[{index}]"
    return f"{CALL}::data.{path}.{field}"


def test_bracket_index_ref_validates(tmp_path: Path) -> None:
    result = _validate(
        tmp_path,
        "One item contributed 1.23% and the other -0.87%.",
        f"1.23% | observed | first item | {_ref(0)}",
        f"-0.87% | observed | second item | {_ref(1)}",
    )
    assert result.valid is True, result.issues


def test_dotted_index_ref_validates_the_same_elements(tmp_path: Path) -> None:
    result = _validate(
        tmp_path,
        "One item contributed 1.23% and the other -0.87%.",
        f"1.23% | observed | first item | {_ref(0, dotted=True)}",
        f"-0.87% | observed | second item | {_ref(1, dotted=True)}",
    )
    assert result.valid is True, result.issues


@pytest.mark.parametrize("dotted", [False, True])
def test_wrong_value_for_an_indexed_element_is_rejected(
    tmp_path: Path, dotted: bool
) -> None:
    result = _validate(
        tmp_path,
        "The first item contributed 1.24%.",
        f"1.24% | observed | first item | {_ref(0, dotted)}",
    )
    assert result.valid is False
    assert {issue["code"] for issue in result.issues} == {"numeric_claim_conflict"}


@pytest.mark.parametrize("dotted", [False, True])
def test_other_elements_value_is_not_authorized_by_an_indexed_ref(
    tmp_path: Path, dotted: bool
) -> None:
    # -0.87 exists in the call, but only at positions[1].
    result = _validate(
        tmp_path,
        "The first item contributed -0.87%.",
        f"-0.87% | observed | first item | {_ref(0, dotted)}",
    )
    assert result.valid is False
    assert {issue["reason"] for issue in result.issues} == {"not_in_referenced_call"}


@pytest.mark.parametrize("dotted", [False, True])
def test_explicit_leaf_ref_never_hints_a_sibling(tmp_path: Path, dotted: bool) -> None:
    result = _validate(
        tmp_path,
        "The first item contributed -0.87%.",
        f"-0.87% | observed | first item | {_ref(0, dotted)}",
    )
    assert not result.valid
    candidates = result.issues[0].get("field_ref_candidates") or []
    assert not any("positions[1]" in ref for ref in candidates)


def test_elements_are_not_ambiguous_with_each_other(tmp_path: Path) -> None:
    result = _validate(
        tmp_path,
        "Contributions were 1.23% and -0.87%.",
        f"1.23% | observed | first | {_ref(0, dotted=True)}",
        f"-0.87% | observed | second | {_ref(1)}",
    )
    assert result.valid is True, result.issues
    assert not any(
        issue.get("reason") == "ambiguous_field_ref" for issue in result.issues
    )


def test_dotted_index_does_not_touch_unindexed_or_scalar_refs(tmp_path: Path) -> None:
    result = _validate(
        tmp_path,
        "Total return was 0.36%.",
        f"0.36% | observed | total | {CALL}::data.total_return_pct",
    )
    assert result.valid is True, result.issues


@pytest.mark.parametrize(
    "ref",
    [
        f"{CALL}::data.positions.contribution_pct",
        f"{TOOL}::positions.contribution_pct",
    ],
)
def test_failed_ref_lists_exact_indexed_candidates(tmp_path: Path, ref: str) -> None:
    result = _validate(
        tmp_path,
        "The first item contributed 1.23%.",
        f"1.23% | observed | first item | {ref}",
    )
    assert result.valid is False
    candidates = result.issues[0]["field_ref_candidates"]
    assert candidates[0] == _ref(0)  # the one matching the figure first
    assert set(candidates) == {_ref(0), _ref(1)}
    assert all(item.startswith(f"{CALL}::data.positions[") for item in candidates)


def test_out_of_range_explicit_index_never_selects_or_hints_another_item(tmp_path: Path) -> None:
    result = _validate(
        tmp_path, "The missing item contributed 1.23%.",
        f"1.23% | observed | missing item | {CALL}::data.positions.2.contribution_pct",
    )
    assert not result.valid
    assert not result.issues[0].get("field_ref_candidates")


def test_candidates_are_shown_to_the_model_in_the_correction(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    result = ledger.validate_final_answer(
        "The second item contributed -0.87%.\n\n```figures\n"
        f"-0.87% | observed | second item | {TOOL}::positions.contribution_pct\n```"
    )
    assert f"valid field refs: {_ref(1)}" in ledger.correction_prompt(result)


def test_unrelated_field_gets_no_candidates(tmp_path: Path) -> None:
    result = _validate(
        tmp_path,
        "Something was 9.99%.",
        f"9.99% | observed | x | {CALL}::data.positions.weight_pct",
    )
    assert result.valid is False
    assert not result.issues[0].get("field_ref_candidates")
