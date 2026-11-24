"""Offline regressions for Yahoo's hourly-to-four-hour bar aggregation."""

from unittest.mock import patch

import pandas as pd
import pytest

from backtest.loaders.yahoo_loader import DataLoader


@pytest.mark.parametrize("interval", ["4H", "4h", " 4h "])
def test_fetch_four_hour_bars_preserves_provider_contract(interval: str) -> None:
    # Include bars outside the date window, a missing day, and partial buckets.
    timestamps = pd.to_datetime(
        [
            "2024-01-01 23:00", "2024-01-02 00:00", "2024-01-02 01:00",
            "2024-01-02 02:00", "2024-01-02 03:00", "2024-01-02 04:00",
            "2024-01-04 23:00", "2024-01-05 00:00",
        ], utc=True,
    )
    payload = {
        "chart": {
            "result": [{
                "meta": {"currency": "GBp"},
                "timestamp": [int(stamp.timestamp()) for stamp in timestamps],
                "indicators": {
                    "quote": [{
                        "open": [200, 200, 400, 600, 800, 1000, 1200, 200],
                        "high": [220, 220, 420, 620, 820, 1020, 1220, 220],
                        "low": [180, 180, 380, 580, 780, 980, 1180, 180],
                        "close": [210, 210, 410, 610, 810, 1010, 1210, 210],
                        "volume": [999, 10, 20, 30, 40, 50, 60, 999],
                    }],
                    # The client's adjustment runs before loader aggregation.
                    "adjclose": [{
                        "adjclose": [105, 105, 205, 305, 405, 505, 605, 105],
                    }],
                },
            }],
        },
    }
    with (
        patch("backtest.loaders.base.loader_cache_enabled", return_value=False),
        patch(
            "backtest.loaders.yahoo_client.throttled_get_json", return_value=payload
        ) as request,
    ):
        result = DataLoader().fetch(
            ["VOD.L"], "2024-01-02", "2024-01-04", interval=interval
        )["VOD.L"]

    assert request.call_args.kwargs["params"] == {
        "interval": "1h",
        "events": "div,splits",
        "period1": int(pd.Timestamp("2024-01-02", tz="UTC").timestamp()),
        "period2": int(pd.Timestamp("2024-01-05", tz="UTC").timestamp()),
    }
    expected = pd.DataFrame(
        {
            "open": [1.0, 5.0, 6.0],
            "high": [4.1, 5.1, 6.1],
            "low": [0.9, 4.9, 5.9],
            "close": [4.05, 5.05, 6.05],
            "volume": [100.0, 50.0, 60.0],
        },
        index=pd.DatetimeIndex(
            ["2024-01-02 00:00", "2024-01-02 04:00", "2024-01-04 20:00"],
            name="trade_date",
        ),
    )
    pd.testing.assert_frame_equal(result, expected, check_index_type=False)
    assert result.attrs == {
        "timezone": "UTC",
        "timestamp_basis": "bar_open",
        "quote_currency": "GBP",
        "currency_conversion": "GBp→GBP (÷100)",
    }


def test_fetch_four_hour_bars_resamples_existing_hourly_cache() -> None:
    cached = pd.DataFrame(
        {
            "open": [1.0, 2.0], "high": [1.5, 2.5], "low": [0.5, 1.5],
            "close": [1.25, 2.25], "volume": [10.0, 20.0],
        },
        index=pd.date_range("2024-01-02", periods=2, freq="h", name="trade_date"),
    )
    cached.attrs = {
        "timezone": "UTC", "timestamp_basis": "bar_open", "quote_currency": "USD",
        "price_adjustment": "qfq",
    }
    with (
        patch("backtest.loaders.base.loader_cache_get", return_value=cached),
        patch("backtest.loaders.yahoo_loader.yahoo_client.get_chart") as chart,
    ):
        result = DataLoader().fetch(
            ["AAPL.US"], "2024-01-02", "2024-01-02", interval="4H"
        )["AAPL.US"]
        repeated = DataLoader().fetch(
            ["AAPL.US"], "2024-01-02", "2024-01-02", interval="4H"
        )["AAPL.US"]

    chart.assert_not_called()
    assert len(result) == 1
    assert result.iloc[0].to_dict() == {
        "open": 1.0, "high": 2.5, "low": 0.5, "close": 2.25, "volume": 30.0,
    }
    assert result.attrs == cached.attrs
    assert len(cached) == 2  # Returning bars must not mutate the cached frame.
    pd.testing.assert_frame_equal(repeated, result)


@pytest.mark.parametrize("interval", ["1H", "1D"])
def test_fetch_other_intervals_keep_source_bars(interval: str) -> None:
    times = pd.date_range(
        "2024-01-02", periods=2, freq="h" if interval == "1H" else "D", tz="UTC"
    )
    rows = [
        dict(trade_date=int(stamp.timestamp()), open=value, high=value + 0.5,
             low=value - 0.5, close=value + 0.25, volume=10 * value)
        for stamp, value in zip(times, [1.0, 2.0])
    ]
    with (
        patch("backtest.loaders.base.loader_cache_enabled", return_value=False),
        patch(
            "backtest.loaders.yahoo_loader.yahoo_client.get_chart",
            return_value=(rows, "USD"),
        ) as chart,
    ):
        result = DataLoader().fetch(
            ["AAPL.US"], "2024-01-02", "2024-01-03", interval=interval
        )["AAPL.US"]

    assert chart.call_args.kwargs["interval"] == interval.lower()
    assert list(result.index) == list(times.tz_localize(None))
    assert result["open"].tolist() == [1.0, 2.0]
    assert result["close"].tolist() == [1.25, 2.25]
    assert result["volume"].tolist() == [10.0, 20.0]
    assert result.attrs["timestamp_basis"] == (
        "bar_open" if interval == "1H" else "session_date"
    )


def test_fetch_four_hour_bars_omits_empty_resampled_cache() -> None:
    cached = pd.DataFrame(
        {column: [float("nan")] for column in ("open", "high", "low", "close", "volume")},
        index=pd.DatetimeIndex(["2024-01-02"], name="trade_date"),
    )
    with (
        patch("backtest.loaders.base.loader_cache_get", return_value=cached),
        patch("backtest.loaders.yahoo_loader.yahoo_client.get_chart") as chart,
    ):
        result = DataLoader().fetch(
            ["AAPL.US"], "2024-01-02", "2024-01-02", interval="4H"
        )

    chart.assert_not_called()
    assert result == {}
