"""TTM flow sums need four adjacent quarters, not any four quarterly rows.

IPO-year shape: the first 10-Q is for Q2, so the 10-K full year has only two
quarters inside it and fiscal Q4 cannot be synthesized. The next four rows
(Q2, Q3, Q1, Q2) cover 15 months with Q4 missing; summing them is not TTM.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.test_fundamentals_pit import _fact_row, _facts, _install_schema_stub, _patch_sec
from backtest.loaders import fundamentals_loader


def _load(index):
    return fundamentals_loader.load_fundamental_panel(
        ["NEWCO"],
        ["revenue"],
        str(index[0].date()),
        str(index[-1].date()),
        freq="ttm",
        index=index,
    )["revenue"]["NEWCO"]


def test_missing_quarter_does_not_yield_a_fifteen_month_ttm(monkeypatch: pytest.MonkeyPatch):
    _install_schema_stub(monkeypatch)
    rows = [
        _fact_row("2022-06-30", "2022-08-10", 20.0, start="2022-04-01"),
        _fact_row("2022-09-30", "2022-11-10", 30.0, start="2022-07-01"),
        _fact_row("2022-12-31", "2023-03-01", 110.0, form="10-K", start="2022-01-01"),
        _fact_row("2023-03-31", "2023-05-10", 25.0, start="2023-01-01"),
        _fact_row("2023-06-30", "2023-08-10", 35.0, start="2023-04-01"),
        _fact_row("2023-09-30", "2023-11-10", 45.0, start="2023-07-01"),
        _fact_row("2023-12-31", "2024-03-01", 150.0, form="10-K", start="2023-01-01"),
    ]
    _patch_sec(monkeypatch, {"NEWCO": _facts({"Revenues": rows})})
    index = pd.to_datetime(["2023-08-10", "2023-11-10", "2024-03-01"])

    series = _load(index)

    # Q2'22 + Q3'22 + Q1'23 + Q2'23 skips Q4'22: no trailing year exists yet.
    assert pd.isna(series.loc[pd.Timestamp("2023-08-10")])
    assert pd.isna(series.loc[pd.Timestamp("2023-11-10")])
    # FY2023's Q4 is synthesized (150 - 105 = 45); Q1..Q4 2023 is a real TTM.
    assert series.loc[pd.Timestamp("2024-03-01")] == pytest.approx(150.0)
