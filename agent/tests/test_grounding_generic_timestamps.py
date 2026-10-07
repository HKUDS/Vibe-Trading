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


def test_generic_snapshot_inherits_latest_date(tmp_path: Path) -> None:
    ledger = GroundingLedger(
        run_dir=tmp_path,
        user_message="Show AAPL.US technical indicators by date",
    )
    ledger.ingest_tool_result(
        tool_name="technical_indicators",
        arguments={"symbol": "AAPL.US"},
        result=json.dumps(
            {
                "ok": True,
                "symbol": "AAPL.US",
                "interval": "1d",
                "latest_close": 214.0,
                "latest_date": "2026-08-04",
                "indicators": {
                    "rsi_14": 55.2,
                    "sma_20": 210.5,
                    "macd": {
                        "macd_line": 1.2,
                        "signal_line": 0.9,
                        "histogram": 0.3,
                    },
                    "volume": {
                        "latest": 1_500_000.0,
                        "sma_20": 1_250_000.0,
                        "ratio_20": 1.2,
                    },
                },
            }
        ),
        call_id="indicators",
        success=True,
    )

    artifact = json.loads(
        (tmp_path / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )
    timestamp_by_field = {
        row["field"]: row["timestamp"]
        for row in artifact["evidence"]
        if row["tool"] == "technical_indicators"
    }

    assert timestamp_by_field["latest_close"] == "2026-08-04"
    assert timestamp_by_field["indicators.rsi_14"] == "2026-08-04"
    assert timestamp_by_field["indicators.sma_20"] == "2026-08-04"
    assert timestamp_by_field["indicators.macd.macd_line"] == "2026-08-04"
    assert timestamp_by_field["indicators.volume.latest"] == "2026-08-04"
    assert timestamp_by_field["indicators.volume.sma_20"] == "2026-08-04"
    assert timestamp_by_field["indicators.volume.ratio_20"] == "2026-08-04"


def test_generic_latest_date_beats_as_of_but_local_date_wins(tmp_path: Path) -> None:
    _ledger(
        tmp_path,
        {
            "source": "external",
            "as_of": "2026-08-05T09:00:00Z",
            "latest_date": "2026-08-04",
            "snapshot": {"close": 214.0},
            "rows": [
                {"trade_date": "2026-08-03", "close": 212.5},
                {"date": "2026-08-04", "close": 214.0},
            ],
        },
    )

    artifact = json.loads(
        (tmp_path / "artifacts" / "grounding_evidence.json").read_text(encoding="utf-8")
    )
    timestamp_by_field = {
        row["field"]: row["timestamp"]
        for row in artifact["evidence"]
        if row["tool"] == "external_market_tool"
    }

    assert timestamp_by_field["snapshot.close"] == "2026-08-04"
    assert timestamp_by_field["rows[0].close"] == "2026-08-03"
    assert timestamp_by_field["rows[1].close"] == "2026-08-04"


@pytest.mark.parametrize("timestamps, expected", [
    ({"latest_date": None, "as_of": "2026-08-05"}, "2026-08-05"),
    ({"latest_date": "2026-08-04", "as_of": "2026-08-05"}, "2026-08-04"),
    ({"date": "2026-08-03", "latest_date": "2026-08-04"}, "2026-08-03"),
    ({"latest_date": None}, None),
    ({}, None),
])
def test_latest_date_preserves_timestamp_priority_and_absence(tmp_path, timestamps, expected):
    ledger = _ledger(tmp_path, {**timestamps, "snapshot": {"close": 212.5}})
    evidence = json.loads((tmp_path / "artifacts" / "grounding_evidence.json").read_text())
    record = next(row for row in evidence["evidence"] if row["field"] == "snapshot.close")
    assert record["timestamp"] == expected
    answer = f"| Date | Close |\n|---|---|\n| {expected or '2026-08-04'} | 212.5 |"
    assert ledger.validate_final_answer(answer).valid is (expected is not None)
    assert not ledger.validate_final_answer(
        "| Date | Close |\n|---|---|\n| 2020-01-01 | 212.5 |"
    ).valid
