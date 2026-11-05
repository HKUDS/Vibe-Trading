"""Long/short exposure and return semantics for the portfolio risk x-ray."""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from backtest.risk_xray import (
    average_invested_weights,
    compute_risk_xray,
    render_risk_xray_markdown,
)


def _closes() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=5, freq="D")
    return pd.DataFrame(
        {
            "AAA": [100.0, 110.0, 105.0, 115.0, 120.0],
            "BBB": [200.0, 190.0, 196.0, 182.0, 175.0],
        },
        index=index,
    )


def _manual(closes: pd.DataFrame, weights: dict[str, float]):
    returns = closes.pct_change(fill_method=None).dropna(how="any")
    portfolio = returns["AAA"] * weights["AAA"] + returns["BBB"] * weights["BBB"]
    return returns, portfolio


def test_long_short_preserves_exposure_scale_for_returns_and_report():
    closes = _closes()
    small = compute_risk_xray(closes, {"AAA": 0.75, "BBB": -0.25}, min_history=2)
    large = compute_risk_xray(closes, {"AAA": 1.5, "BBB": -0.5}, min_history=2)

    assert small["exposure"] == {
        "gross": pytest.approx(1.0),
        "net": pytest.approx(0.5),
        "long_weight": pytest.approx(0.75),
        "short_weight": pytest.approx(-0.25),
        "long_count": 1,
        "short_count": 1,
    }
    assert large["exposure"] == {
        "gross": pytest.approx(2.0),
        "net": pytest.approx(1.0),
        "long_weight": pytest.approx(1.5),
        "short_weight": pytest.approx(-0.5),
        "long_count": 1,
        "short_count": 1,
    }
    assert large["inputs"]["weights"] == {"AAA": 1.5, "BBB": -0.5}

    _, small_port = _manual(closes, {"AAA": 0.75, "BBB": -0.25})
    _, large_port = _manual(closes, {"AAA": 1.5, "BBB": -0.5})
    assert small["volatility"]["daily_vol"] == pytest.approx(
        float(small_port.std(ddof=1))
    )
    assert large["volatility"]["daily_vol"] == pytest.approx(
        float(large_port.std(ddof=1))
    )
    assert large["volatility"]["daily_vol"] == pytest.approx(
        2 * small["volatility"]["daily_vol"]
    )
    json.dumps(large, allow_nan=False)


def test_concentration_uses_gross_share_without_rescaling_the_book():
    result = compute_risk_xray(_closes(), {"AAA": 1.5, "BBB": -0.5}, min_history=2)

    assert result["concentration"] == {
        "hhi": pytest.approx(0.625),
        "effective_n": pytest.approx(1.6),
        "top1_weight": pytest.approx(0.75),
        "top3_weight": pytest.approx(1.0),
    }
    assert result["exposure"]["gross"] == pytest.approx(2.0)


def test_diversification_uses_original_weight_scale():
    closes = _closes()
    weights = {"AAA": 1.5, "BBB": -0.5}
    result = compute_risk_xray(closes, weights, min_history=2)
    returns, portfolio = _manual(closes, weights)
    expected = (
        1.5 * returns["AAA"].std(ddof=1) + 0.5 * returns["BBB"].std(ddof=1)
    ) / portfolio.std(ddof=1)

    assert result["diversification"]["diversification_ratio"] == pytest.approx(expected)


def test_history_filter_does_not_rescale_surviving_long_short_exposure():
    closes = _closes()
    closes["THIN"] = [1.0, 2.0, None, None, None]
    result = compute_risk_xray(
        closes,
        {"AAA": 1.5, "BBB": -0.5, "THIN": 10.0},
        min_history=3,
    )

    assert result["skipped"] == [
        {"symbol": "THIN", "reason": "only 2 valid bars (min 3)"}
    ]
    assert result["inputs"]["weights"] == {"AAA": 1.5, "BBB": -0.5}
    assert result["exposure"]["gross"] == pytest.approx(2.0)
    assert result["exposure"]["net"] == pytest.approx(1.0)


def test_history_filter_preserves_scale_when_short_leg_is_skipped():
    closes = _closes().drop(columns="BBB")
    closes["THIN_SHORT"] = [200.0, 190.0, None, None, None]
    result = compute_risk_xray(
        closes,
        {"AAA": 1.5, "THIN_SHORT": -0.5},
        min_history=3,
    )

    assert result["skipped"] == [
        {"symbol": "THIN_SHORT", "reason": "only 2 valid bars (min 3)"}
    ]
    assert result["inputs"]["weights"] == {"AAA": 1.5}
    assert result["exposure"]["gross"] == pytest.approx(1.5)
    assert result["exposure"]["net"] == pytest.approx(1.5)
    assert result["warnings"] == [
        "weights preserved at gross exposure 2.000000; concentration uses gross shares",
        "history filter preserved original long/short exposure",
    ]


def test_average_invested_weights_preserves_long_short_exposure():
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    target_pos = pd.DataFrame({"AAA": [1.5] * 4, "BBB": [-0.5] * 4}, index=index)

    weights, avg_invested = average_invested_weights(target_pos)

    assert weights == {"AAA": pytest.approx(1.5), "BBB": pytest.approx(-0.5)}
    assert avg_invested == pytest.approx(1.0)


def test_long_only_normalization_and_exposure_remain_compatible():
    closes = _closes()
    result = compute_risk_xray(closes, {"AAA": 2.0, "BBB": 1.0}, min_history=2)
    normalized = {"AAA": 2 / 3, "BBB": 1 / 3}
    _, portfolio = _manual(closes, normalized)

    assert result["inputs"]["weights"] == {
        "AAA": pytest.approx(2 / 3),
        "BBB": pytest.approx(1 / 3),
    }
    assert result["exposure"]["gross"] == pytest.approx(1.0)
    assert result["exposure"]["net"] == pytest.approx(1.0)
    assert result["exposure"]["short_count"] == 0
    assert result["volatility"]["daily_vol"] == pytest.approx(
        float(portfolio.std(ddof=1))
    )
    assert result["warnings"] == ["weights summed to 3.000000; renormalized to 1.0"]


def test_markdown_reports_long_short_exposure():
    report = compute_risk_xray(_closes(), {"AAA": 0.75, "BBB": -0.25}, min_history=2)

    markdown = render_risk_xray_markdown(report)

    assert "gross 100.00%" in markdown
    assert "net 50.00%" in markdown
    assert "long 75.00%" in markdown
    assert "short -25.00%" in markdown
    assert math.isfinite(report["exposure"]["gross"])
