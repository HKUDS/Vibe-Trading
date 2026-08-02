"""Regression: equity.csv may use nav/value instead of equity."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backtest.validation import _load_equity


def test_load_equity_accepts_nav_column(tmp_path: Path) -> None:
    arts = tmp_path / "artifacts"
    arts.mkdir()
    pd.DataFrame({"nav": [100.0, 101.0]}, index=pd.date_range("2024-01-01", periods=2)).to_csv(arts / "equity.csv")
    s = _load_equity(tmp_path)
    assert list(s.values) == [100.0, 101.0]


def test_load_equity_accepts_equity_column(tmp_path: Path) -> None:
    arts = tmp_path / "artifacts"
    arts.mkdir()
    pd.DataFrame({"equity": [1.0, 2.0]}, index=pd.date_range("2024-01-01", periods=2)).to_csv(arts / "equity.csv")
    assert list(_load_equity(tmp_path).values) == [1.0, 2.0]


def test_load_equity_accepts_value_column(tmp_path: Path) -> None:
    arts = tmp_path / "artifacts"
    arts.mkdir()
    pd.DataFrame({"value": [9.0, 10.0]}, index=pd.date_range("2024-01-01", periods=2)).to_csv(arts / "equity.csv")
    assert list(_load_equity(tmp_path).values) == [9.0, 10.0]


def test_load_equity_unknown_columns_raise(tmp_path: Path) -> None:
    arts = tmp_path / "artifacts"
    arts.mkdir()
    pd.DataFrame({"foo": [1.0]}, index=pd.date_range("2024-01-01", periods=1)).to_csv(arts / "equity.csv")
    with pytest.raises(ValueError, match="equity/nav/value"):
        _load_equity(tmp_path)
