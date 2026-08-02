"""Reject non-positive MA periods in run-detail indicator overlays."""

from __future__ import annotations

import json
from pathlib import Path

from src.ui_services import build_indicator_series, infer_indicator_periods


def _rows():
    return [
        {
            "time": f"2020-01-0{i}",
            "code": "AAPL",
            "close": float(i),
            "open": 1,
            "high": 1,
            "low": 1,
            "volume": 1,
        }
        for i in range(1, 6)
    ]


def test_build_indicator_series_skips_zero_period() -> None:
    series = build_indicator_series(_rows(), [0, 5])
    assert "ma0" not in series["AAPL"]
    assert "ma5" in series["AAPL"]
    assert len(series["AAPL"]["ma5"]) == 5


def test_infer_indicator_periods_drops_nonpositive(tmp_path: Path) -> None:
    (tmp_path / "planner_output.json").write_text(
        json.dumps(
            {
                "coding_contract": {
                    "input_logic": {"parameters": {"signal_params": {"ma_window": 0, "ma_fast": 5, "ma_slow": -3}}}
                }
            }
        )
    )
    assert infer_indicator_periods(tmp_path) == [5]
