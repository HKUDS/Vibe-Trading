"""Weekly and monthly bars, built from daily ones at the fetch boundary (#1479)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backtest import runner
from backtest.benchmark import _fetch_benchmark
from backtest.engines._market_hooks import _interval_span_hours
from backtest.loaders.base import resample_bars, source_interval
from backtest.metrics import calc_bars_per_year
from src.api.attribution_core import _attribution_bars_per_year
from src.market_data import fetch_market_data


def _daily(start: str, end: str, *, freq: str = "B") -> pd.DataFrame:
    index = pd.DatetimeIndex(pd.date_range(start, end, freq=freq), name="trade_date")
    step = np.arange(len(index), dtype=float)
    return pd.DataFrame(
        {
            "open": 100.0 + step,
            "high": 101.0 + step,
            "low": 99.0 + step,
            "close": 100.5 + step,
            "volume": 10.0 + step,
        },
        index=index,
    )


class TestResampleBars:
    def test_a_week_runs_monday_to_sunday_and_is_stamped_with_its_last_trading_day(self):
        frame = _daily("2024-01-03", "2024-01-19")  # Wed 3rd .. Fri 19th
        weekly = resample_bars(frame, "1W")

        assert list(weekly.index.strftime("%Y-%m-%d")) == ["2024-01-05", "2024-01-12", "2024-01-19"]
        first = frame.loc["2024-01-03":"2024-01-05"]
        assert weekly.iloc[0]["open"] == first["open"].iloc[0]
        assert weekly.iloc[0]["high"] == first["high"].max()
        assert weekly.iloc[0]["low"] == first["low"].min()
        assert weekly.iloc[0]["close"] == first["close"].iloc[-1]
        assert weekly.iloc[0]["volume"] == first["volume"].sum()

    def test_a_seven_day_market_closes_its_week_on_sunday(self):
        weekly = resample_bars(_daily("2024-01-01", "2024-01-14", freq="D"), "1W")
        assert list(weekly.index.strftime("%a %Y-%m-%d")) == ["Sun 2024-01-07", "Sun 2024-01-14"]

    def test_a_month_is_a_calendar_month_and_a_partial_last_one_stays_inside_it(self):
        monthly = resample_bars(_daily("2024-01-15", "2024-03-06"), "1M")

        assert list(monthly.index.strftime("%Y-%m-%d")) == ["2024-01-31", "2024-02-29", "2024-03-06"]
        assert monthly.loc["2024-02-29", "open"] == _daily("2024-01-15", "2024-03-06").loc["2024-02-01", "open"]

    def test_vwap_is_weighted_by_volume_and_funding_is_averaged(self):
        frame = _daily("2024-01-01", "2024-01-02")
        frame["vwap"] = [10.0, 20.0]
        frame["volume"] = [1.0, 3.0]
        frame["funding_rate"] = [0.0001, 0.0003]
        frame["pe"] = [5.0, 6.0]

        bar = resample_bars(frame, "1W").iloc[0]

        assert bar["vwap"] == pytest.approx(17.5)
        assert bar["funding_rate"] == pytest.approx(0.0002)
        assert bar["pe"] == 6.0

    def test_a_vwap_without_volume_is_unknown_not_the_last_day(self):
        frame = _daily("2024-01-01", "2024-01-02").drop(columns="volume")
        frame["vwap"] = [10.0, 20.0]
        assert np.isnan(resample_bars(frame, "1W").iloc[0]["vwap"])

    def test_missing_volume_stays_missing(self):
        frame = _daily("2024-01-01", "2024-01-05")
        frame["volume"] = np.nan
        assert np.isnan(resample_bars(frame, "1W").iloc[0]["volume"])

    def test_timezone_and_attributes_are_kept(self):
        frame = _daily("2024-01-01", "2024-01-10", freq="D")
        frame.index = frame.index.tz_localize("Asia/Shanghai")
        frame.attrs["quote_currency"] = "CNY"

        weekly = resample_bars(frame, "1W")

        assert str(weekly.index.tz) == "Asia/Shanghai"
        assert weekly.attrs == {"quote_currency": "CNY"}

    def test_resampling_twice_changes_nothing(self):
        weekly = resample_bars(_daily("2024-01-01", "2024-03-01"), "1W")
        pd.testing.assert_frame_equal(resample_bars(weekly, "1W"), weekly)

    @pytest.mark.parametrize("interval", ["1D", "1H", "1m"])
    def test_other_intervals_pass_through(self, interval):
        frame = _daily("2024-01-01", "2024-01-10")
        assert resample_bars(frame, interval) is frame
        assert source_interval(interval) == interval

    def test_the_period_intervals_are_fetched_daily(self):
        assert source_interval("1W") == source_interval("1M") == "1D"


class _RecordingLoader:
    name = "yahoo"
    asked: list[str] = []

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start_date, end_date, fields=None, interval="1D"):  # noqa: ANN001, ANN201
        type(self).asked.append(interval)
        return {code: _daily("2024-01-01", "2024-03-29") for code in codes}


@pytest.fixture
def recording_loader():
    _RecordingLoader.asked = []
    return _RecordingLoader


class TestFetchPaths:
    @pytest.mark.parametrize(("interval", "bars"), [("1W", 13), ("1M", 3)])
    def test_a_backtest_asks_for_daily_bars_and_gets_period_bars(
        self, monkeypatch, recording_loader, interval, bars
    ):
        monkeypatch.setattr(runner, "_get_loader", lambda source: recording_loader)
        result = runner.fetch_data_map(
            {"source": "yahoo", "codes": ["AAPL.US"], "start_date": "2024-01-01", "end_date": "2024-03-29", "interval": interval}
        )

        assert recording_loader.asked == ["1D"]
        assert len(result.data_map["AAPL.US"]) == bars

    def test_the_auto_route_asks_for_daily_bars_too(self, monkeypatch, recording_loader):
        monkeypatch.setattr(runner, "resolve_loader", lambda market: recording_loader())
        monkeypatch.setattr(runner, "LOADER_REGISTRY", {})
        result = runner.fetch_data_map(
            {"source": "auto", "codes": ["AAPL.US"], "start_date": "2024-01-01", "end_date": "2024-03-29", "interval": "1M"}
        )

        assert recording_loader.asked == ["1D"]
        assert list(result.data_map["AAPL.US"].index.strftime("%Y-%m-%d")) == ["2024-01-31", "2024-02-29", "2024-03-29"]

    def test_get_market_data_asks_for_daily_bars(self, recording_loader):
        out = fetch_market_data(
            codes=["AAPL.US"],
            start_date="2024-01-01",
            end_date="2024-03-29",
            source="yahoo",
            interval="1M",
            max_rows=0,
            loader_resolver=lambda source: recording_loader,
        )

        assert recording_loader.asked == ["1D"]
        rows = out["AAPL.US"]
        assert [row["trade_date"][:10] for row in rows] == ["2024-01-31", "2024-02-29", "2024-03-29"]

    def test_the_benchmark_is_built_the_same_way(self, recording_loader):
        frame = _fetch_benchmark("SPY", "2024-01-01", "2024-03-29", "1W", loader=recording_loader())

        assert recording_loader.asked == ["1D"]
        assert len(frame) == 13

    def test_the_config_accepts_both(self):
        for interval in ("1W", "1M"):
            runner.BacktestConfigSchema(codes=["AAPL.US"], start_date="2024-01-01", end_date="2024-03-29", interval=interval)
        with pytest.raises(ValueError):
            runner.BacktestConfigSchema(codes=["AAPL.US"], start_date="2024-01-01", end_date="2024-03-29", interval="1w")


class TestAnnualisation:
    @pytest.mark.parametrize("source", ["tushare", "yahoo", "okx", "mt5"])
    def test_a_week_and_a_month_are_calendar_counts(self, source):
        assert calc_bars_per_year("1W", source) == 52
        assert calc_bars_per_year("1w", source) == 52
        assert calc_bars_per_year("1M", source) == 12

    def test_a_minute_is_still_a_minute(self):
        assert calc_bars_per_year("1m", "yahoo") == 252 * 390

    def test_the_funding_span_of_a_period_bar(self):
        assert _interval_span_hours("1W") == 168.0
        assert _interval_span_hours("1M") == 730.5
        assert _interval_span_hours("1m") == pytest.approx(1 / 60)

    def test_attribution_reads_1M_as_a_month(self):
        assert _attribution_bars_per_year("1M") == 12
        assert _attribution_bars_per_year("1m") == 98280
        assert _attribution_bars_per_year("1W") == 52


def test_the_indicator_tool_fetches_whole_periods(monkeypatch):
    import src.tools.technical_indicator_tool as mod

    seen = {}

    def _fake_fetch(**kwargs):
        seen.update(kwargs)
        return {kwargs["codes"][0]: _daily("2020-01-01", "2024-03-29")}

    monkeypatch.setattr(mod, "fetch_market_data", _fake_fetch)
    out = json.loads(mod.TechnicalIndicatorTool().execute(symbol="AAPL.US", interval="1wk", lookback=100))

    assert seen["interval"] == "1W"
    start = datetime.strptime(seen["start_date"], "%Y-%m-%d")
    assert datetime.now() - start >= timedelta(days=699)
    assert out["interval"] == "1W"
