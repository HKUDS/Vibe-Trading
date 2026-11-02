"""Long/short support for the portfolio risk x-ray.

`risk_xray.py` documented "Long-only v1: negative weights are rejected up
front (a short leg is a different feature)" and both `compute_risk_xray` and
`average_invested_weights` raised on any negative weight. `run_backtest`
swallowed that with `except ValueError: pass`, so a long/short book, which
the global-equity, forex, crypto and options engines all produce and which
`constraints.py` says "work too", got no risk artifact at all and no
indication why.

This is that feature: the x-ray describes the whole book, gross and net, and
long-only behaviour is unchanged.
"""

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


def _closes(series_map: dict[str, list[float]], start: str = "2026-01-01") -> pd.DataFrame:
    n = max(len(v) for v in series_map.values())
    idx = pd.date_range(start, periods=n, freq="D")
    return pd.DataFrame({k: pd.Series(v, index=idx[: len(v)]) for k, v in series_map.items()})


def _assert_strict_json(payload: dict) -> None:
    json.dumps(payload, allow_nan=False)


def _basket() -> pd.DataFrame:
    return _closes(
        {
            "LONG": list(range(100, 160)),
            "SHORT": list(range(200, 140, -1)),
            "FLAT": list(range(50, 110)),
        }
    )


# ── exposure ─────────────────────────────────────────────────────────────


def test_long_short_book_reports_gross_and_net_exposure():
    result = compute_risk_xray(_basket(), {"LONG": 0.6, "SHORT": -0.4}, min_history=10)
    exposure = result["exposure"]
    assert exposure["gross"] == pytest.approx(1.0)
    assert exposure["net"] == pytest.approx(0.2)
    assert exposure["long_weight"] == pytest.approx(0.6)
    assert exposure["short_weight"] == pytest.approx(-0.4)
    assert exposure["long_count"] == 1
    assert exposure["short_count"] == 1
    _assert_strict_json(result)


def test_weights_are_gross_normalized_and_say_so():
    result = compute_risk_xray(_basket(), {"LONG": 1.2, "SHORT": -0.8}, min_history=10)
    assert result["inputs"]["weights"] == {"LONG": pytest.approx(0.6), "SHORT": pytest.approx(-0.4)}
    assert any("gross" in w for w in result["warnings"])
    _assert_strict_json(result)


# ── the numbers have to be right, not just present ───────────────────────


def test_concentration_measures_gross_share_not_signed_share():
    # Signed weights would make a hedged book look diversified: the two legs
    # cancel in the sum and the HHI collapses. Concentration is a property of
    # how much of the book each position carries, so it runs on |w| / gross.
    closes = _closes({"AAA": list(range(100, 160)), "BBB": list(range(200, 140, -1))})
    result = compute_risk_xray(closes, {"AAA": 0.5, "BBB": -0.5}, min_history=10)
    conc = result["concentration"]
    assert conc["hhi"] == pytest.approx(0.5)
    assert conc["effective_n"] == pytest.approx(2.0)
    assert conc["top1_weight"] == pytest.approx(0.5)


def test_diversification_ratio_uses_gross_weights():
    # sum(|w_i| * sigma_i) / sigma_p, not sum(w_i * sigma_i): with signed
    # weights the numerator would understate the book's own volatility and
    # the ratio could go below 1 for a well diversified book.
    closes = _closes({"AAA": list(range(100, 160)), "BBB": list(range(200, 140, -1))})
    result = compute_risk_xray(closes, {"AAA": 0.5, "BBB": -0.5}, min_history=10)
    ratio = result["diversification"]["diversification_ratio"]
    assert ratio is not None
    assert ratio >= 1.0


def test_portfolio_return_is_the_signed_weighted_sum():
    # The signs have to carry through the return aggregation. If the weights
    # were applied as absolute values the resulting series would be a
    # different one and the vol would not match the hand computation.
    closes = _closes(
        {
            "AAA": [100.0, 110.0, 105.0, 115.0],
            "BBB": [200.0, 190.0, 196.0, 182.0],
        }
    )
    weights = {"AAA": 0.75, "BBB": -0.25}
    result = compute_risk_xray(closes, weights, min_history=2)

    rets = closes.pct_change(fill_method=None).dropna(how="any")
    manual = rets["AAA"] * 0.75 + rets["BBB"] * -0.25
    expected_vol = float(manual.std(ddof=1)) * math.sqrt(result["volatility"].get("_ppy") or 252)

    # Fall back to comparing against the reported annualization when the
    # report does not carry its own factor.
    got = result["volatility"]["annualized_vol"]
    assert got == pytest.approx(expected_vol, rel=1e-6) or got == pytest.approx(
        float(manual.std(ddof=1)) * math.sqrt(252), rel=1e-6
    )
    _assert_strict_json(result)


# ── long-only is unchanged ───────────────────────────────────────────────


def test_long_only_gross_normalization_matches_the_old_net_normalization():
    closes = _closes({"AAA": list(range(100, 160)), "BBB": list(range(50, 110))})
    result = compute_risk_xray(closes, {"AAA": 0.5, "BBB": 0.5}, min_history=10)
    assert result["exposure"]["gross"] == pytest.approx(1.0)
    assert result["exposure"]["net"] == pytest.approx(1.0)
    assert result["exposure"]["short_count"] == 0
    assert result["concentration"]["hhi"] == pytest.approx(0.5)


# ── the engine-facing helper stops refusing the book ─────────────────────


def test_average_invested_weights_describes_a_long_short_book():
    pos = pd.DataFrame(
        {"LONG": [1.0, 1.0, 1.0], "SHORT": [-0.5, -0.5, -0.5]},
        index=pd.date_range("2026-01-01", periods=3),
    )
    weights, avg_invested = average_invested_weights(pos)
    assert weights == {"LONG": pytest.approx(1.0), "SHORT": pytest.approx(-0.5)}
    assert avg_invested == pytest.approx(0.5)


def test_average_invested_weights_still_refuses_an_empty_book():
    with pytest.raises(ValueError, match="empty"):
        average_invested_weights(pd.DataFrame())


# ── the artifact is readable ─────────────────────────────────────────────


def test_markdown_renders_the_exposure_section():
    result = compute_risk_xray(_basket(), {"LONG": 0.6, "SHORT": -0.4}, min_history=10)
    text = render_risk_xray_markdown(result)
    assert "gross" in text.lower()
    assert "net" in text.lower()
