"""A recovered high-water mark starts a new underwater episode."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.quantlib.risk import max_drawdown_analysis
from src.tools.quantlib_tool import QuantlibCallTool


@pytest.mark.parametrize(
    "values,peak,trough,recovery",
    [
        ([100, 90, 100, 80, 100], 2, 3, 4),
        ([100, 100, 80, 100], 1, 2, 3),
        ([100, 80, 100, 70], 2, 3, None),
        ([90, 100, 80, 110], 1, 2, 3),
        ([100, 70, 100, 80], 0, 1, 2),
        ([100, 100, 100], 0, 0, 0),
    ],
)
def test_episode_starts_at_last_high_water_mark_before_worst_trough(
    values, peak, trough, recovery
):
    result = max_drawdown_analysis(values)
    assert result["peak_date"] == peak
    assert result["trough_date"] == trough
    assert result["recovery_date"] == recovery
    assert result["peak_to_trough_periods"] == trough - peak
    assert result["max_drawdown"] == pytest.approx(1 - values[trough] / values[peak])


def test_calendar_underwater_duration_excludes_an_already_recovered_episode():
    equity = pd.Series(
        [100, 90, 100, 80, 100],
        index=pd.to_datetime(
            ["2025-01-01", "2025-01-02", "2025-01-10", "2025-01-12", "2025-01-15"]
        ),
    )
    result = max_drawdown_analysis(equity)
    assert result["peak_date"] == pd.Timestamp("2025-01-10")
    assert result["underwater_days"] == 2
    assert result["recovery_days"] == 3


def test_registered_quantlib_tool_reports_the_current_drawdown_episode():
    result = json.loads(
        QuantlibCallTool().execute(
            action="call",
            module="risk",
            function="max_drawdown_analysis",
            kwargs={"equity": [100, 90, 100, 80, 100]},
        )
    )
    assert result["ok"] is True
    assert result["result"]["peak_date"] == 2
    assert result["result"]["peak_to_trough_periods"] == 1
