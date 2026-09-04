"""Tests for the #1301 price-caliber provenance.

Every served frame now declares what its prices mean (``adjustment`` in
``_provenance``), and a backtest whose basket mixes calibers logs a warning
instead of silently comparing raw against adjusted series.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest import runner
from backtest.loaders.registry import (
    FALLBACK_CHAINS,
    mixed_caliber_warning,
    price_caliber,
)
from src.market_data import fetch_market_data


def _df() -> pd.DataFrame:
    index = pd.DatetimeIndex(pd.to_datetime(["2024-01-02"]))
    return pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]},
        index=index,
    )


# --------------------------------------------------------------------------
# price_caliber table
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        ("yahoo", "split_dividend"),
        ("yfinance", "split_dividend"),
        ("eastmoney", "split_dividend"),
        ("tencent", "split_dividend"),
        ("akshare", "split_dividend"),
        ("baostock", "split_dividend"),
        ("tushare", "split_dividend"),
        ("pykrx", "split"),
        ("tiingo", "split_dividend"),
        ("fmp", "split_dividend"),
        ("sina", "raw"),
        ("alphavantage", "raw"),
        ("longbridge", "raw"),
        # Neither measured nor pinned by an endpoint choice: must not guess.
        ("stooq", "unknown"),
        ("finnhub", "unknown"),
        ("local", "unknown"),
    ],
)
def test_source_calibers(source: str, expected: str) -> None:
    assert price_caliber(source, "us_equity") == expected


def test_tushare_hk_override_is_raw() -> None:
    """Tushare publishes no HK adjustment-factor series, so only its
    A-share/fund paths are adjusted."""
    assert price_caliber("tushare", "hk_equity") == "raw"
    assert price_caliber("tushare", "a_share") == "split_dividend"


def test_non_equity_markets_stamp_na() -> None:
    assert price_caliber("binance", "crypto") == "na"
    # The market wins over the per-source table: yfinance serving BTC has
    # nothing to adjust for.
    assert price_caliber("yfinance", "crypto") == "na"
    assert price_caliber("mt5", "forex") == "na"


def test_every_chain_source_resolves() -> None:
    for market, chain in FALLBACK_CHAINS.items():
        for source in chain:
            assert price_caliber(source, market) in {
                "raw",
                "split",
                "split_dividend",
                "na",
                "unknown",
            }


# --------------------------------------------------------------------------
# mixed_caliber_warning
# --------------------------------------------------------------------------


def test_warning_fires_on_mixed_basket() -> None:
    msg = mixed_caliber_warning(
        {
            "AAPL.US": ("yahoo", "split_dividend"),
            "TSLA.US": ("sina", "raw"),
        }
    )
    assert msg is not None
    assert "AAPL.US" in msg and "TSLA.US" in msg
    assert "split_dividend" in msg and "raw" in msg


def test_warning_silent_on_single_caliber() -> None:
    assert (
        mixed_caliber_warning(
            {
                "AAPL.US": ("yahoo", "split_dividend"),
                "MSFT.US": ("yfinance", "split_dividend"),
            }
        )
        is None
    )


def test_warning_ignores_unknown_and_na() -> None:
    assert (
        mixed_caliber_warning(
            {
                "AAPL.US": ("yahoo", "split_dividend"),
                "XYZ.US": ("finnhub", "unknown"),
                "BTC-USDT": ("binance", "na"),
            }
        )
        is None
    )


# --------------------------------------------------------------------------
# _provenance stamp in fetch_market_data
# --------------------------------------------------------------------------


class _StubLoader:
    def fetch(self, codes, start, end, *, interval="1D"):  # noqa: ANN001, ANN201
        return {code: _df() for code in codes}


def test_provenance_stamps_adjustment_for_adjusted_source() -> None:
    out = fetch_market_data(
        codes=["600519.SH"],
        start_date="2024-01-01",
        end_date="2024-01-03",
        source="tencent",
        loader_resolver=lambda src: _StubLoader,
        include_provenance=True,
    )
    assert out["_provenance"]["600519.SH"]["adjustment"] == "split_dividend"


def test_provenance_stamps_adjustment_for_raw_source() -> None:
    out = fetch_market_data(
        codes=["AAPL.US"],
        start_date="2024-01-01",
        end_date="2024-01-03",
        source="sina",
        loader_resolver=lambda src: _StubLoader,
        include_provenance=True,
    )
    assert out["_provenance"]["AAPL.US"]["adjustment"] == "raw"


# --------------------------------------------------------------------------
# fetch_data_map: run-level mixed-caliber warning
# --------------------------------------------------------------------------


class _YahooStub:
    name = "yahoo"

    def fetch(self, codes, start, end, fields=None, interval="1D"):  # noqa: ANN001, ANN201
        return {"AAPL.US": _df()}


class _SinaStub:
    name = "sina"

    def is_available(self) -> bool:
        return True

    def fetch(self, codes, start, end, interval="1D"):  # noqa: ANN001, ANN201
        return {"TSLA.US": _df()}


def test_fetch_data_map_warns_on_mixed_caliber_basket(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """yahoo serves AAPL (split_dividend), sina serves TSLA down the chain
    (raw): the run must say the basket mixes calibers."""
    monkeypatch.setattr(runner, "resolve_loader", lambda market: _YahooStub())
    monkeypatch.setattr(runner, "LOADER_REGISTRY", {"sina": _SinaStub})

    result = runner.fetch_data_map(
        {
            "source": "auto",
            "codes": ["AAPL.US", "TSLA.US"],
            "start_date": "2024-01-01",
            "end_date": "2024-01-03",
            "interval": "1D",
        }
    )

    assert result.caliber_warning is not None
    assert "AAPL.US" in result.caliber_warning
    assert "TSLA.US" in result.caliber_warning
    assert "mixed price calibers" in caplog.text


def test_fetch_data_map_silent_on_single_caliber(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _YahooBoth:
        name = "yahoo"

        def fetch(self, codes, start, end, fields=None, interval="1D"):  # noqa: ANN001, ANN201
            return {code: _df() for code in codes}

    monkeypatch.setattr(runner, "resolve_loader", lambda market: _YahooBoth())
    monkeypatch.setattr(runner, "LOADER_REGISTRY", {})

    result = runner.fetch_data_map(
        {
            "source": "auto",
            "codes": ["AAPL.US", "MSFT.US"],
            "start_date": "2024-01-01",
            "end_date": "2024-01-03",
            "interval": "1D",
        }
    )

    assert result.caliber_warning is None
    assert "mixed price calibers" not in caplog.text


# --------------------------------------------------------------------------
# The table is a claim about the loader. #1320 changed the FMP and Tiingo
# loaders to serve adjusted OHLC and left this table saying "raw", which is
# worse than the bug it fixed: a mislabelled frame is what the mixed-caliber
# comparison is built to catch, and it cannot catch its own label. These pin
# the two together, so flipping one without the other goes red.
# --------------------------------------------------------------------------


def _bar(**over):
    bar = {
        "date": "2024-01-03",
        "open": 100.0,
        "high": 100.0,
        "low": 100.0,
        "close": 100.0,
        "adjClose": 50.0,
        "volume": 1000.0,
    }
    bar.update(over)
    return bar


def test_fmp_loader_serves_the_caliber_the_table_claims() -> None:
    from backtest.loaders.fmp_loader import _parse_historical

    assert price_caliber("fmp", "us_equity") == "split_dividend"
    df = _parse_historical([_bar()])
    assert df is not None
    # adjClose/close = 0.5, so OHLC halves and volume does not.
    assert df["close"].iloc[0] == pytest.approx(50.0)
    assert df["open"].iloc[0] == pytest.approx(50.0)
    assert df["volume"].iloc[0] == pytest.approx(1000.0)


def test_tiingo_loader_serves_the_caliber_the_table_claims() -> None:
    from backtest.loaders.tiingo_loader import _rows_to_frame

    assert price_caliber("tiingo", "us_equity") == "split_dividend"
    df = _rows_to_frame([_bar(date="2024-01-03T00:00:00.000Z")])
    assert df is not None
    assert df["close"].iloc[0] == pytest.approx(50.0)
    assert df["open"].iloc[0] == pytest.approx(50.0)
    assert df["volume"].iloc[0] == pytest.approx(1000.0)
