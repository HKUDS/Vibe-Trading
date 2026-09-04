from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent.grounding import GroundingLedger

pytestmark = pytest.mark.unit


def _ledger(tmp_path: Path, payload: dict) -> GroundingLedger:
    ledger = GroundingLedger(run_dir=tmp_path, user_message="Show AAPL.US prices by date")
    ledger.ingest_tool_result(
        tool_name="external_market_tool",
        arguments={"symbol": "AAPL.US"},
        result=json.dumps(payload),
        call_id="quote",
        success=True,
    )
    return ledger


def test_generic_quote_inherits_parent_as_of(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        {
            "source": "external",
            "as_of": "2026-08-03T15:30:00Z",
            "data": {"quote": [{"close": 212.5}]},
        },
    )

    result = ledger.validate_final_answer(
        "| Date | Close |\n|---|---|\n| 2026-08-03 | 212.5 |"
    )

    assert result.valid is True, result.issues


def test_generic_rows_keep_their_own_trade_dates(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        {
            "source": "external",
            "as_of": "2026-08-04T23:59:00Z",
            "data": {
                "bars": [
                    {"trade_date": "2026-08-03", "close": 212.5},
                    {"trade_date": "2026-08-04", "close": 214.0},
                ]
            },
        },
    )

    result = ledger.validate_final_answer(
        "| Date | Close |\n|---|---|\n| 2026-08-03 | 212.5 |\n| 2026-08-04 | 214.0 |"
    )

    assert result.valid is True, result.issues


def test_generic_quote_without_timestamp_stays_undated(tmp_path: Path) -> None:
    ledger = _ledger(
        tmp_path,
        {"source": "external", "data": {"quote": [{"close": 212.5}]}},
    )

    result = ledger.validate_final_answer(
        "| Date | Close |\n|---|---|\n| 2026-08-03 | 212.5 |"
    )

    assert result.valid is False
    assert [issue["code"] for issue in result.issues] == ["numeric_claim_unavailable"]
