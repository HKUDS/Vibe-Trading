"""Undefined pairs must not hide correlations between the other holdings."""

import json

import numpy as np
import pandas as pd
import pytest

from backtest.risk_xray import compute_risk_xray


@pytest.mark.parametrize(
    "symbols",
    [("FLAT", "AAA", "BBB"), ("AAA", "FLAT", "BBB"), ("AAA", "BBB", "FLAT")],
)
def test_flat_holding_does_not_hide_a_valid_correlation_pair(symbols):
    closes = pd.DataFrame(
        {
            "FLAT": [100.0] * 6,
            "AAA": [100.0, 110.0, 99.0, 118.8, 106.92, 117.612],
            "BBB": [200.0, 180.0, 198.0, 158.4, 174.24, 156.816],
        },
        index=pd.date_range("2026-01-05", periods=6),
    )[list(symbols)]

    report = compute_risk_xray(closes, dict.fromkeys(symbols, 1 / 3), min_history=2)
    correlation = report["correlation"]

    assert correlation["avg_pairwise_abs"] == pytest.approx(1.0)
    assert correlation["max_pair"]["symbols"] == ["AAA", "BBB"]
    assert correlation["max_pair"]["corr"] == pytest.approx(-1.0)
    # The flat position still participates in exposure and the portfolio model.
    assert set(report["inputs"]["symbols"]) == set(symbols)
    assert report["exposure"]["long_count"] == 3
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("second", [[200.0] * 6, [200.0, 210.0, 205.0, 220.0, 215.0, 225.0]])
def test_no_estimable_pairs_are_reported_as_unavailable(second):
    closes = pd.DataFrame({"FLAT": [100.0] * 6, "BBB": second})

    report = compute_risk_xray(closes, {"FLAT": 0.5, "BBB": 0.5}, min_history=2)

    assert report["correlation"]["avg_pairwise_abs"] is None
    assert report["correlation"]["max_pair"] is None
    json.dumps(report, allow_nan=False)


def test_all_estimable_pairs_contribute_to_the_average():
    closes = pd.DataFrame(
        {
            "AAA": [100.0, 110.0, 99.0, 118.8, 106.92, 117.612],
            "BBB": [200.0, 180.0, 198.0, 158.4, 174.24, 156.816],
            "CCC": [50.0, 52.0, 54.0, 53.0, 55.0, 56.0],
        }
    )
    pairs = closes.pct_change(fill_method=None).corr().to_numpy()[np.triu_indices(3, k=1)]

    correlation = compute_risk_xray(closes, dict.fromkeys(closes.columns, 1 / 3), min_history=2)["correlation"]

    assert correlation["avg_pairwise_abs"] == pytest.approx(np.abs(pairs).mean())
    assert correlation["max_pair"]["symbols"] == ["AAA", "BBB"]
    assert correlation["max_pair"]["corr"] == pytest.approx(-1.0)
