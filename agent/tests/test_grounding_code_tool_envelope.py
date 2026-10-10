"""Operational envelope fields of code-running tools are not financial evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger

pytestmark = pytest.mark.unit


def _ledger(tmp_path: Path, tool: str, payload: dict) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Analyze AAPL.US")
    ledger.ingest_tool_result(
        tool_name=tool,
        arguments={"run_dir": str(tmp_path)},
        result=json.dumps(payload),
        call_id="call-1",
        success=True,
    )
    return ledger


@pytest.mark.parametrize("tool", ["backtest", "bash"])
@pytest.mark.parametrize("field", ["exit_code", "elapsed_seconds"])
def test_envelope_bookkeeping_is_not_observed_evidence(
    tmp_path: Path, tool: str, field: str
) -> None:
    ledger = _ledger(
        tmp_path,
        tool,
        {
            "status": "ok",
            "exit_code": 0,
            "elapsed_seconds": 12.5,
            "stdout": "done",
            "stderr": "",
        },
    )

    assert [
        r for r in ledger._evidence if r.field in {"exit_code", "elapsed_seconds"}
    ] == []

    claim = "12.5" if field == "elapsed_seconds" else "0.0"
    result = ledger.validate_final_answer(
        f"The run reported {claim}.\n\n```figures\n{claim} | observed | {field} | {tool}\n```"
    )
    assert result.valid is False


def test_explicit_numeric_result_of_a_tool_still_grounds(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        "bash",
        {"status": "ok", "exit_code": 0, "result": {"sma_20": 187.42}},
    )

    assert any(
        r.field == "result.sma_20" and r.value == 187.42 for r in ledger._evidence
    )
