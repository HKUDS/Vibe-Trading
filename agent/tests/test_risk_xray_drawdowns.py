"""Risk X-Ray exposes observed drawdown periods, not just a worst loss."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from backtest.risk_xray import (
    compute_risk_xray,
    render_risk_xray_markdown,
    write_risk_xray,
)
from backtest.risk_xray_drawdowns import describe_drawdown_episodes
from src.tools.portfolio_risk_tool import PortfolioRiskXrayTool


def test_risk_xray_reports_recovered_and_ongoing_drawdowns():
    dates = pd.date_range("2026-01-01", periods=7, freq="D")
    closes = pd.DataFrame(
        {"AAA": [100.0, 120.0, 60.0, 90.0, 120.0, 132.0, 99.0]}, index=dates
    )

    report = compute_risk_xray(closes, {"AAA": 1.0}, min_history=2)

    assert report["drawdown"]["max_drawdown"] == pytest.approx(-0.5)
    episodes = report["drawdown"].get("episodes")
    assert episodes is not None, "Risk X-Ray needs the observed drawdown periods"
    assert episodes["available"] is True
    assert episodes["basis"] == "constant_weight_model"
    assert episodes["duration_unit"] == "bars"
    assert episodes.get("recovery_rtol") == 1e-12
    assert episodes["total"] == 2
    assert episodes["limit"] == 5
    recovered, ongoing = episodes["items"]
    assert recovered == {
        "peak": str(dates[1]),
        "trough": str(dates[2]),
        "recovery": str(dates[4]),
        "depth": pytest.approx(-0.5),
        "duration_bars": 3,
    }
    assert ongoing == {
        "peak": str(dates[5]),
        "trough": str(dates[6]),
        "recovery": None,
        "depth": pytest.approx(-0.25),
        "duration_bars": 1,
    }
    assert episodes["current"] == ongoing
    json.dumps(report, allow_nan=False)


def test_first_loss_uses_the_first_shared_close_as_the_peak():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    closes = pd.DataFrame({"AAA": [None, 100.0, 80.0, 100.0, None]}, index=dates)

    report = compute_risk_xray(closes, {"AAA": 1.0}, min_history=2)
    episodes = report["drawdown"].get("episodes")

    assert episodes is not None
    assert episodes["available"] is True
    assert episodes["total"] == 1
    assert episodes["items"][0] == {
        "peak": str(dates[1]),
        "trough": str(dates[2]),
        "recovery": str(dates[3]),
        "depth": pytest.approx(-0.2),
        "duration_bars": 2,
    }


def test_missing_inner_closes_do_not_invent_a_recovery_path():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    closes = pd.DataFrame({"AAA": [100.0, 90.0, None, 80.0, 100.0]}, index=dates)

    report = compute_risk_xray(closes, {"AAA": 1.0}, min_history=2)
    episodes = report["drawdown"].get("episodes")

    assert episodes is not None
    assert episodes["available"] is False
    assert episodes["reason"] == "missing_return_observations"
    assert episodes["items"] == []
    assert episodes["total"] is None
    assert episodes["current"] is None
    assert report["inputs"]["return_observations"] == 2
    assert report["volatility"]["annualized_vol"] is not None
    json.dumps(report, allow_nan=False)


def test_non_positive_model_wealth_is_not_interpreted_as_a_recovery():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    closes = pd.DataFrame({"AAA": [100.0, 10.0, 20.0], "BBB": [100.0] * 3}, index=dates)

    report = compute_risk_xray(closes, {"AAA": 2.0, "BBB": -1.0}, min_history=2)
    episodes = report["drawdown"].get("episodes")

    assert episodes is not None
    assert episodes["available"] is False
    assert episodes["reason"] == "non_positive_wealth"
    assert episodes["items"] == []
    assert episodes["current"] is None
    assert report["drawdown"]["max_drawdown"] == pytest.approx(-3.4)
    json.dumps(report, allow_nan=False)


def test_monotonic_wealth_is_available_without_drawdown_episodes():
    dates = pd.date_range("2026-01-01", periods=4, freq="D")
    closes = pd.DataFrame({"AAA": [100.0, 110.0, 120.0, 130.0]}, index=dates)

    report = compute_risk_xray(closes, {"AAA": 1.0}, min_history=2)
    episodes = report["drawdown"].get("episodes")

    assert episodes is not None
    assert episodes["available"] is True
    assert episodes["total"] == 0
    assert episodes["items"] == []
    assert episodes["current"] is None


def test_top_five_does_not_hide_an_ongoing_shallower_episode():
    prices = [100.0]
    for depth in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]:
        peak = prices[-1]
        prices.extend([peak * (1.0 - depth), peak * 1.1])
    prices.append(prices[-1] * 0.99)
    dates = pd.date_range("2026-01-01", periods=len(prices), freq="D")

    report = compute_risk_xray(
        pd.DataFrame({"AAA": prices}, index=dates), {"AAA": 1.0}, min_history=2
    )
    episodes = report["drawdown"].get("episodes")

    assert episodes is not None
    assert episodes["total"] == 8
    assert episodes["limit"] == len(episodes["items"]) == 5
    assert [item["depth"] for item in episodes["items"]] == pytest.approx(
        [-0.7, -0.6, -0.5, -0.4, -0.3]
    )
    assert episodes["current"]["depth"] == pytest.approx(-0.01)
    assert episodes["current"]["recovery"] is None
    assert episodes["current"] not in episodes["items"]


@pytest.mark.parametrize("frequency", ["D", "W", "MS"])
def test_durations_count_observed_bars_not_calendar_days(frequency):
    dates = pd.date_range("2026-01-01", periods=4, freq=frequency)
    closes = pd.DataFrame({"AAA": [100.0, 80.0, 90.0, 110.0]}, index=dates)

    report = compute_risk_xray(closes, {"AAA": 1.0}, min_history=2)
    episodes = report["drawdown"].get("episodes")

    assert episodes is not None
    assert episodes["duration_unit"] == "bars"
    assert episodes["items"][0]["duration_bars"] == 3
    assert episodes["items"][0]["recovery"] == str(dates[-1])


def test_material_remaining_loss_is_not_rounded_into_recovery():
    dates = pd.date_range("2026-01-01", periods=3, freq="D")
    closes = pd.DataFrame({"AAA": [100.0, 80.0, 99.9999999]}, index=dates)

    report = compute_risk_xray(closes, {"AAA": 1.0}, min_history=2)
    episodes = report["drawdown"]["episodes"]

    assert episodes["available"] is True
    assert episodes["total"] == 1
    assert episodes["items"][0]["recovery"] is None
    assert episodes["current"]["recovery"] is None
    assert episodes["current"]["duration_bars"] == 2


def test_markdown_reports_recovery_and_observed_duration() -> None:
    dates = pd.date_range("2026-01-01", periods=7, freq="D")
    closes = pd.DataFrame(
        {"AAA": [100.0, 120.0, 60.0, 90.0, 120.0, 132.0, 99.0]}, index=dates
    )
    report = compute_risk_xray(closes, {"AAA": 1.0}, min_history=2)

    text = render_risk_xray_markdown(report)

    assert "## Drawdown periods" in text
    assert "constant-weight" in text.lower()
    assert "not calendar days" in text
    assert "relative tolerance 1e-12" in text
    assert "| Depth | Peak | Trough | Recovery | Observed bars |" in text
    assert f"| -50.00% | {dates[1]} | {dates[2]} | {dates[4]} | 3 |" in text
    assert f"| -25.00% | {dates[5]} | {dates[6]} | Not recovered | 1 |" in text
    assert "Window-end drawdown: -25.00%; observed bars: 1" in text


@pytest.mark.parametrize("missing", [False, True])
def test_markdown_distinguishes_empty_and_unavailable_periods(missing: bool) -> None:
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = (
        [100.0, 90.0, None, 80.0, 100.0]
        if missing
        else [100.0, 110.0, 120.0, 130.0, 140.0]
    )
    report = compute_risk_xray(
        pd.DataFrame({"AAA": prices}, index=dates), {"AAA": 1.0}, min_history=2
    )

    text = render_risk_xray_markdown(report)

    if missing:
        assert "Drawdown periods unavailable: missing return observations." in text
        assert "No drawdown periods observed" not in text
    else:
        assert "No drawdown periods observed in this window." in text
        assert "Drawdown periods unavailable" not in text
    assert "| Depth |" not in text


def test_markdown_keeps_a_window_end_period_outside_the_deepest_five() -> None:
    prices = [100.0]
    for depth in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]:
        prices.extend([prices[-1] * (1.0 - depth), prices[-1] * 1.1])
    prices.append(prices[-1] * 0.99)
    dates = pd.date_range("2026-01-01", periods=len(prices), freq="D")
    report = compute_risk_xray(
        pd.DataFrame({"AAA": prices}, index=dates), {"AAA": 1.0}, min_history=2
    )

    text = render_risk_xray_markdown(report)

    assert "Showing 5 of 8 observed drawdowns." in text
    assert "Window-end drawdown: -1.00%; observed bars: 1" in text
    assert f"Window-end peak: {dates[-2]}; trough: {dates[-1]}" in text


def test_markdown_keeps_observation_labels_inside_their_cells() -> None:
    closes = pd.DataFrame(
        {"AAA": [100.0, 80.0, 100.0]}, index=["a|peak", "b\nlow", "c-recovery"]
    )
    report = compute_risk_xray(closes, {"AAA": 1.0}, min_history=2)

    text = render_risk_xray_markdown(report)

    assert "| -20.00% | a\\|peak | b low | c-recovery | 2 |" in text


def test_markdown_accepts_a_legacy_report_without_periods() -> None:
    report = compute_risk_xray(
        pd.DataFrame({"AAA": [100.0, 80.0, 90.0]}), {"AAA": 1.0}, min_history=2
    )
    del report["drawdown"]["episodes"]

    text = render_risk_xray_markdown(report)

    assert "max drawdown: -20.00%" in text
    assert "Drawdown periods" not in text


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        ([], "empty_path"),
        ([float("inf")], "non_finite_wealth"),
        ([float("nan")], "non_finite_wealth"),
    ],
)
def test_unusable_wealth_is_unavailable_instead_of_zero_risk(
    values: list[float], reason: str
) -> None:
    episodes = describe_drawdown_episodes(
        pd.Series(values, dtype=float), initial_label="start", complete=True
    )

    assert episodes["available"] is False
    assert episodes["reason"] == reason
    assert episodes["total"] is None
    assert episodes["items"] == []
    assert episodes["current"] is None
    json.dumps(episodes, allow_nan=False)


def test_tool_and_strict_json_artifact_preserve_drawdown_periods(
    tmp_path: Path,
) -> None:
    prices = [100.0] * 30 + [120.0, 60.0, 90.0, 120.0, 132.0, 99.0]
    dates = pd.date_range("2026-01-01", periods=len(prices), freq="D")
    requests = []

    def fetch(**kwargs):
        requests.append(kwargs)
        return {
            "AAA": [
                {"date": str(date.date()), "close": price}
                for date, price in zip(dates, prices)
            ]
        }

    tool = PortfolioRiskXrayTool(data_fetcher=fetch)
    payload = json.loads(
        tool.execute(symbols=["AAA"], start_date="2026-01-01", end_date="2026-03-01")
    )

    assert payload["status"] == "ok"
    assert requests == [
        {
            "codes": ["AAA"],
            "start_date": "2026-01-01",
            "end_date": "2026-03-01",
            "source": "auto",
            "interval": "1D",
            "max_rows": 0,
        }
    ]
    episodes = payload["data"]["drawdown"]["episodes"]
    assert episodes["total"] == 2
    assert episodes["items"][0]["recovery"] == str(dates[33].date())
    assert episodes["items"][0]["duration_bars"] == 3
    assert episodes["current"]["recovery"] is None
    assert episodes["current"]["depth"] == pytest.approx(-0.25)
    path = tmp_path / "risk_xray.json"
    safe = write_risk_xray(path, payload["data"])
    assert json.loads(path.read_text(encoding="utf-8")) == safe == payload["data"]
    json.dumps(safe, allow_nan=False)


def test_run_emits_periods_that_survive_the_run_detail_reader(tmp_path: Path) -> None:
    import api_server
    from backtest.engines.base import BaseEngine

    class _Engine(BaseEngine):
        def can_execute(self, symbol, direction, bar):
            return True

        def round_size(self, raw_size, price):
            return float(raw_size)

        def calc_commission(self, size, price, direction, is_open):
            return 0.0

        def apply_slippage(self, price, direction):
            return price

    prices = [100.0] * 30 + [120.0, 60.0, 90.0, 120.0, 132.0, 99.0]
    dates = pd.date_range("2026-01-01", periods=len(prices), freq="D")
    frame = pd.DataFrame({"open": prices, "close": prices}, index=dates)

    class _Loader:
        def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):
            return {"AAA": frame}

    class _Signals:
        def generate(self, data):
            return {"AAA": pd.Series(1.0, index=dates)}

    metrics = _Engine({"initial_cash": 100_000.0}).run_backtest(
        {"codes": ["AAA"], "start_date": "2026-01-01", "end_date": "2026-03-01"},
        _Loader(),
        _Signals(),
        tmp_path,
    )

    path = tmp_path / "artifacts" / "risk_xray.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    periods = report["drawdown"]["episodes"]
    assert periods["basis"] == "constant_weight_model"
    assert periods["total"] == 2
    assert periods["items"][0]["depth"] == pytest.approx(-0.5)
    assert periods["items"][0]["recovery"] == str(dates[33])
    assert periods["current"]["depth"] == pytest.approx(-0.25)
    assert metrics["risk_xray_max_drawdown"] == pytest.approx(-0.5)
    assert "## Drawdown periods" in (tmp_path / "artifacts" / "risk_xray.md").read_text(
        encoding="utf-8"
    )

    response = api_server._build_response_from_run_dir(tmp_path, elapsed=0.0)
    assert response.risk_xray == report
    assert json.loads(response.model_dump_json())["risk_xray"] == report
