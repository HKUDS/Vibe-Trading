"""Tests for the rebalance notes module."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from backtest.rebalance_notes import (
    compute_rebalance_notes,
    render_rebalance_notes_markdown,
    write_rebalance_notes,
)


def _frame(rows, codes=("A", "B")):
    dates = pd.date_range("2025-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(rows, index=dates, columns=list(codes))


def test_turnover_entries_exits_and_top_moves():
    pos = _frame(
        [
            [0.5, 0.5],
            [0.75, 0.25],  # turnover 0.25, A up, B down
            [0.0, 1.0],  # turnover 0.75, A exits, B grows
        ]
    )

    notes = compute_rebalance_notes(pos)

    rebalances = notes["rebalances"]
    assert len(rebalances) == 2
    assert rebalances[0]["turnover"] == pytest.approx(0.25)
    assert rebalances[0]["entries"] == []
    assert rebalances[0]["exits"] == []
    assert [m["code"] for m in rebalances[0]["top_moves"]] == ["A", "B"]
    assert rebalances[0]["top_moves"][0]["delta"] == pytest.approx(0.25)

    second = rebalances[1]
    assert second["turnover"] == pytest.approx(0.75)
    assert [e["code"] for e in second["exits"]] == ["A"]
    assert second["exits"][0]["weight"] == pytest.approx(0.75)
    assert second["top_moves"][0]["code"] == "A"


def test_epsilon_skips_noop_dates():
    pos = _frame(
        [
            [0.5, 0.5],
            [0.5 + 1e-9, 0.5 - 1e-9],  # drift far below epsilon
            [0.9, 0.1],
        ]
    )

    notes = compute_rebalance_notes(pos)

    assert len(notes["rebalances"]) == 1
    assert notes["rebalances"][0]["date"] == "2025-01-03"


def test_summary_aggregates_and_largest_date():
    pos = _frame(
        [
            [1.0, 0.0],
            [0.5, 0.5],  # turnover 0.5
            [0.2, 0.8],  # turnover 0.3
        ]
    )

    summary = compute_rebalance_notes(pos)["summary"]

    assert summary["rebalance_count"] == 2
    assert summary["turnover_total"] == pytest.approx(0.8)
    assert summary["turnover_mean"] == pytest.approx(0.4)
    assert summary["turnover_max"] == pytest.approx(0.5)
    assert summary["largest_rebalance_date"] == "2025-01-02"


def test_short_and_long_only_frames():
    pos = _frame([[0.0, 0.0], [0.4, 0.6]])
    notes = compute_rebalance_notes(pos)
    assert len(notes["rebalances"]) == 1
    assert {e["code"] for e in notes["rebalances"][0]["entries"]} == {"A", "B"}

    assert compute_rebalance_notes(pos.iloc[:1])["summary"]["rebalance_count"] == 0
    assert compute_rebalance_notes(pos.iloc[0:0])["rebalances"] == []


def test_nan_cells_treated_as_zero():
    pos = _frame([[0.5, np.nan], [0.5, 0.5]])
    notes = compute_rebalance_notes(pos)
    assert notes["rebalances"][0]["entries"][0]["code"] == "B"


def test_write_strict_json_and_markdown(tmp_path):
    pos = _frame([[0.5, 0.5], [0.9, 0.1]])
    notes = compute_rebalance_notes(pos)

    out = tmp_path / "nested" / "rebalance_notes.json"
    payload = write_rebalance_notes(out, notes)

    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["summary"]["rebalance_count"] == 1
    assert parsed["rebalances"][0]["turnover"] == pytest.approx(0.4)
    assert payload == parsed

    md = render_rebalance_notes_markdown(notes)
    assert "2025-01-02" in md
    assert "turnover 0.4000" in md
    assert "A: 0.5000 -> 0.9000 (+0.4000)" in md
