"""Backtest fallback decides which symbols were served after bar preparation."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from backtest import runner
from backtest.loaders import stooq_loader, yahoo_client
from backtest.loaders.base import NoAvailableSourceError


@pytest.fixture
def chart_feeds(monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_DATA_CACHE", "0")
    monkeypatch.setitem(runner.FALLBACK_CHAINS, "us_equity", ["yahoo", "stooq"])
    monkeypatch.setattr(stooq_loader, "_challenge_until", 0.0)
    dates = ["2026-01-05", "2026-01-06", "2026-01-12"]
    timestamps = [int(pd.Timestamp(date, tz="UTC").timestamp()) for date in dates]
    calls = []
    csv = ["Date,Open,High,Low,Close,Volume\n"]

    def chart(url, *, params, **kwargs):
        symbol = url.rsplit("/", 1)[-1]
        calls.append(("yahoo", symbol, params["interval"]))
        highs = {"AAPL": [9, 12, 13], "MSFT": [9, 9, 9]}[symbol]
        quote = {
            "open": [10, 10, 11],
            "high": highs,
            "low": [9, 9, 10],
            "close": [10, 11, 12],
            "volume": [100, 100, 100],
        }
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "timestamp": timestamps,
                        "indicators": {"quote": [quote]},
                    }
                ]
            }
        }

    def stooq(url, *, params, **kwargs):
        calls.append(("stooq", params["s"], params["i"]))
        return SimpleNamespace(status_code=200, text="".join(csv), raise_for_status=lambda: None)

    monkeypatch.setattr(yahoo_client, "throttled_get_json", chart)
    monkeypatch.setattr(stooq_loader, "throttled_get", stooq)
    return dates, csv, calls


@pytest.mark.parametrize("source", ["auto", "yahoo"])
@pytest.mark.parametrize("interval", ["1D", "1W"])
def test_retries_only_the_symbol_with_no_valid_bars(source, interval, chart_feeds):
    dates, csv, calls = chart_feeds
    csv.extend(f"{date},20,24,19,{close},100\n" for date, close in zip(dates, [21, 22, 23]))

    result = runner.fetch_data_map(
        {
            "source": source,
            "codes": ["AAPL.US", "MSFT.US"],
            "interval": interval,
            "start_date": dates[0],
            "end_date": dates[-1],
        }
    )

    assert calls == [("yahoo", "AAPL", "1d"), ("yahoo", "MSFT", "1d"), ("stooq", "msft.us", "d")]
    assert result.effective_sources == (["stooq", "yahoo"] if source == "auto" else ["yahoo", "stooq"])
    assert result.data_map["AAPL.US"]["close"].tolist() == [11, 12]
    backup = result.data_map["MSFT.US"]
    expected_dates = dates if interval == "1D" else dates[1:]
    assert backup.index.strftime("%Y-%m-%d").tolist() == expected_dates
    assert backup["close"].tolist() == ([21, 22, 23] if interval == "1D" else [22, 23])
    assert backup["volume"].tolist() == ([100, 100, 100] if interval == "1D" else [200, 100])


@pytest.mark.parametrize("source", ["auto", "yahoo"])
def test_a_fallback_with_no_valid_bars_does_not_complete_the_basket(source, chart_feeds):
    dates, csv, calls = chart_feeds
    csv.append(f"{dates[0]},20,19,18,20,100\n")

    with pytest.raises(NoAvailableSourceError, match=r"missing symbols: .*MSFT\.US"):
        runner.fetch_data_map(
            {
                "source": source,
                "codes": ["MSFT.US"],
                "start_date": dates[0],
                "end_date": dates[-1],
            }
        )

    assert calls == [("yahoo", "MSFT", "1d"), ("stooq", "msft.us", "d")]


def test_backtest_uses_the_fallback_bars_and_reports_their_source(monkeypatch, tmp_path, chart_feeds):
    dates, csv, _ = chart_feeds
    csv.extend(f"{date},20,24,19,{close},100\n" for date, close in zip(dates, [21, 22, 23]))
    run_dir = tmp_path / "run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "config.json").write_text(
        json.dumps(
            {
                "source": "auto",
                "codes": ["AAPL.US", "MSFT.US"],
                "interval": "1W",
                "start_date": dates[0],
                "end_date": dates[-1],
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "code" / "signal_engine.py").write_text(
        "class SignalEngine:\n"
        "    def generate(self, data_map):\n"
        "        return {code: bars['close'] * 0 for code, bars in data_map.items()}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))

    runner.main(run_dir)

    card = json.loads((run_dir / "run_card.json").read_text(encoding="utf-8"))
    assert card["metrics"]["benchmark_label"] == "equal-weight basket of 2 symbols"
    assert card["metrics"]["benchmark_return"] == pytest.approx(0.175)
    assert card["data_sources"] == ["stooq", "yahoo"]
