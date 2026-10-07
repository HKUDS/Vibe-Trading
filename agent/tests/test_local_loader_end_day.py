"""Inclusive local-data date ranges include the final fractional second."""

from pathlib import Path

import pandas as pd
import pytest

from backtest.loaders import base, local_loader


@pytest.mark.parametrize("interval", ["1m", "1D"])
def test_end_day_includes_subsecond_bars_but_not_next_midnight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interval: str
) -> None:
    """Exercise real CSV parsing, range filtering, and OHLCV aggregation."""
    path = tmp_path / "bars.csv"
    pd.DataFrame(
        {
            "date": [
                "2025-01-01T23:59:59.999999999Z",
                "2025-01-02T23:59:58.999999999Z",
                "2025-01-02T23:59:59.999999999Z",
                "2025-01-03T00:00:00.000000000Z",
            ],
            "open": [5, 10, 20, 30],
            "high": [6, 11, 21, 31],
            "low": [4, 9, 19, 29],
            "close": [5, 10, 20, 30],
            "volume": [50, 100, 200, 300],
        }
    ).to_csv(path, index=False)
    monkeypatch.setattr(base, "loader_cache_enabled", lambda: False)
    monkeypatch.setattr(
        local_loader,
        "_load_config",
        lambda: {"sources": [{"symbol": "AAA.US", "type": "csv", "path": str(path)}]},
    )

    frame = local_loader.DataLoader().fetch(
        ["AAA.US"], "2025-01-02", "2025-01-02", interval=interval
    )["AAA.US"]

    assert len(frame) == 1
    assert frame.iloc[0].to_dict() == {
        "open": 10,
        "high": 21,
        "low": 9,
        "close": 20,
        "volume": 300,
    }
    assert frame.index[0].date().isoformat() == "2025-01-02"
