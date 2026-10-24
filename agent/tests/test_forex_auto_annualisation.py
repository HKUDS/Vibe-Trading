"""An auto-sourced forex run annualises on a 24x5 session, not A-share hours."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.metrics import calc_bars_per_year
from backtest.runner import _annualisation_bars, _detect_primary_source


@pytest.mark.parametrize("codes", [["EURUSD"], ["EUR/USD", "USDJPY"]])
def test_auto_forex_run_uses_the_forex_session(codes: list[str]) -> None:
    assert _detect_primary_source(codes, "auto") == "mt5"


def test_hourly_forex_bars_annualise_round_the_clock() -> None:
    index = pd.date_range("2026-09-07", periods=24 * 5, freq="1h")
    data = {"EURUSD": pd.DataFrame({"close": [1.1] * len(index)}, index=index)}
    source = _detect_primary_source(["EURUSD"], "auto")
    assert _annualisation_bars("1H", source, data, ["EURUSD"]) == 260 * 24
    assert calc_bars_per_year("1D", source) == 260


def test_explicit_source_and_other_markets_are_unchanged() -> None:
    assert _detect_primary_source(["EURUSD"], "akshare") == "akshare"
    assert _detect_primary_source(["600519.SH"], "auto") == "tushare"
