"""An alias before ``::`` names no call: the correction lists the real refs, grants nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.grounding import GroundingLedger

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
