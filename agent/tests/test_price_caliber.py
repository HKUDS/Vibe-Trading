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
    additive_caliber_warning,
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
        ("tencent", "split_dividend_additive"),
        ("akshare", "split_dividend"),
        ("baostock", "split_dividend"),
        ("tushare", "split_dividend"),
        ("pykrx", "split"),
        ("tiingo", "split_dividend"),
        ("fmp", "split_dividend"),
        ("gildata", "split_dividend"),
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


# --------------------------------------------------------------------------
# Tencent's adjustment is additive in dividends (#1493): between corporate
# actions its qfq equals raw plus a constant, measured on 600519.SH where the
# offset takes five values over 500 bars and steps only at dividend dates. An
# additive series is not on the same scale as a multiplicative one, so sharing
# the `split_dividend` label made the mixed-caliber warning blind to exactly the
# mix it exists to catch. Its HK series is not adjusted at all.
# --------------------------------------------------------------------------


def test_tencent_a_share_caliber_is_additive_not_multiplicative() -> None:
    """A-share qfq subtracts cash dividends from the level, not by a ratio."""
    assert price_caliber("tencent", "a_share") == "split_dividend_additive"


def test_tencent_hk_series_is_unadjusted() -> None:
    """Tencent serves no adjusted HK series at all: its fqkline reply carries only
    "day" for HK symbols (never "qfqday"/"hfqday"), so the loader's ``qfqday or
    day`` fallback silently serves unadjusted bars and the `,qfq` request
    parameter changes nothing. The actions are real — eastmoney's adjusted HK
    series differs from raw over the same window — this source just does not
    apply them."""
    assert price_caliber("tencent", "hk_equity") == "raw"


def test_tencent_a_share_basket_warns_against_multiplicative_sources() -> None:
    """The label collision was the bug: with both sources on `split_dividend`
    the warning returned None for a basket that mixes them."""
    stamps = {
        "600519.SH": ("tencent", price_caliber("tencent", "a_share")),
        "000001.SZ": ("baostock", price_caliber("baostock", "a_share")),
    }
    msg = mixed_caliber_warning(stamps)
    assert msg is not None
    assert "600519.SH" in msg and "000001.SZ" in msg
    assert "split_dividend_additive" in msg and "split_dividend" in msg


def test_eastmoney_and_akshare_a_share_are_additive_too() -> None:
    """The same endpoint family: eastmoney fqt=1 has tencent's five offsets on
    600519.SH, and akshare's stock_zh_a_hist(adjust="qfq") calls it."""
    assert price_caliber("eastmoney", "a_share") == "split_dividend_additive"
    assert price_caliber("akshare", "a_share") == "split_dividend_additive"
    # unmeasured markets keep the per-source label
    assert price_caliber("eastmoney", "hk_equity") == "split_dividend"
    assert price_caliber("akshare", "us_equity") == "split_dividend"


def test_tencent_and_eastmoney_a_share_basket_is_not_a_mix() -> None:
    """Both additive with the same offsets: warning them apart was a false positive."""
    stamps = {
        "600519.SH": ("tencent", price_caliber("tencent", "a_share")),
        "000001.SZ": ("eastmoney", price_caliber("eastmoney", "a_share")),
    }
    assert mixed_caliber_warning(stamps) is None
    assert additive_caliber_warning(stamps) is not None


def test_tencent_only_basket_stays_silent() -> None:
    """One additive source is not a mix, so nothing to warn about."""
    assert (
        mixed_caliber_warning(
            {
                "600519.SH": ("tencent", "split_dividend_additive"),
                "000001.SZ": ("tencent", "split_dividend_additive"),
            }
        )
        is None
    )


def test_additive_warning_fires_on_a_single_source() -> None:
    """The blind spot the caliber alone could not cover: a run with no mix at
    all still computes its returns off additive levels, and with tencent
    heading the A-share chain that is the ordinary case, not an edge one."""
    msg = additive_caliber_warning({"600519.SH": ("tencent", "split_dividend_additive")})
    assert msg is not None
    assert "600519.SH" in msg and "tencent" in msg
    assert "not total returns" in msg


def test_additive_warning_stays_silent_on_multiplicative_and_raw() -> None:
    """Tencent's HK path rides in the same basket and must not trip it: that
    series is stamped raw by the market override, not additive."""
    assert (
        additive_caliber_warning(
            {
                "600519.SH": ("baostock", "split_dividend"),
                "AAPL.US": ("yahoo", "split_dividend"),
                "0700.HK": ("tencent", "raw"),
                "BTC-USDT": ("okx", "na"),
            }
        )
        is None
    )


def test_additive_warning_truncates_a_long_served_list() -> None:
    stamps = {f"{600000 + i}.SH": ("tencent", "split_dividend_additive") for i in range(6)}
    msg = additive_caliber_warning(stamps)
    assert msg is not None
    assert "+2 more" in msg


def test_non_equity_markets_stamp_na() -> None:
    assert price_caliber("binance", "crypto") == "na"
    # The market wins over the per-source table: yfinance serving BTC has
    # nothing to adjust for.
    assert price_caliber("yfinance", "crypto") == "na"
    assert price_caliber("mt5", "forex") == "na"


@pytest.mark.parametrize("source", ["tencent", "eastmoney", "akshare", "tushare", "baostock"])
@pytest.mark.parametrize("code", ["000300.SH", "000001.SH", "399001.SZ", "399006.SZ", "899050.BJ"])
def test_an_a_share_index_is_raw_on_every_source(source: str, code: str) -> None:
    """An index has no corporate actions: eastmoney's fqt=1 equals its fqt=0 on
    every bar and Tencent serves only "day", so the additive stamp a stock gets
    from these sources is wrong for it (#1541)."""
    assert price_caliber(source, "a_share", code) == "raw"


@pytest.mark.parametrize("code", ["000001.SZ", "600519.SH", "510300.SH", "399001.SH", "000300.SZ", "830799.BJ"])
def test_an_a_share_stock_or_fund_keeps_its_source_caliber(code: str) -> None:
    """The index codes are exchange-specific: 000001.SZ is Ping An Bank, not
    the SSE Composite, and 510300.SH is an ETF that pays distributions."""
    assert price_caliber("tencent", "a_share", code) == "split_dividend_additive"
    assert price_caliber("tushare", "a_share", code) == "split_dividend"


def test_a_yahoo_index_is_raw() -> None:
    """Yahoo's adjclose equals close on ^GSPC / ^NDX / ^HSI: nothing was adjusted."""
    assert price_caliber("yahoo", "index", "^GSPC") == "raw"
    assert price_caliber("yfinance", "index") == "raw"
    assert price_caliber("yahoo", "us_equity", "AAPL.US") == "split_dividend"


def test_without_a_symbol_the_market_default_applies() -> None:
    assert price_caliber("tencent", "a_share") == "split_dividend_additive"


def test_every_chain_source_resolves() -> None:
    for market, chain in FALLBACK_CHAINS.items():
        for source in chain:
            assert price_caliber(source, market) in {
                "raw",
                "split",
                "split_dividend",
                "split_dividend_additive",
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
    assert out["_provenance"]["600519.SH"]["adjustment"] == "split_dividend_additive"


def test_provenance_marks_tencent_hk_as_unadjusted() -> None:
    """HK rows served by tencent are unadjusted, and the field the caller reads
    before comparing price levels has to say so (#1493)."""
    out = fetch_market_data(
        codes=["00939.HK"],
        start_date="2024-01-01",
        end_date="2024-01-03",
        source="tencent",
        loader_resolver=lambda src: _StubLoader,
        include_provenance=True,
    )
    assert out["_provenance"]["00939.HK"]["adjustment"] == "raw"


def test_provenance_marks_an_a_share_index_as_unadjusted() -> None:
    out = fetch_market_data(
        codes=["000300.SH", "600519.SH"],
        start_date="2024-01-01",
        end_date="2024-01-03",
        source="tencent",
        loader_resolver=lambda src: _StubLoader,
        include_provenance=True,
    )
    assert out["_provenance"]["000300.SH"]["adjustment"] == "raw"
    assert out["_provenance"]["600519.SH"]["adjustment"] == "split_dividend_additive"


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


class _TencentStub:
    name = "tencent"

    def fetch(self, codes, start, end, fields=None, interval="1D"):  # noqa: ANN001, ANN201
        return {"600519.SH": _df()}


def test_fetch_data_map_warns_on_additive_caliber(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A single-source tencent run mixes nothing, so the mixed-caliber warning
    is right to stay silent — but the series it served is additive, and the
    run must still say so."""
    monkeypatch.setattr(runner, "resolve_loader", lambda market: _TencentStub())
    monkeypatch.setattr(runner, "LOADER_REGISTRY", {})

    result = runner.fetch_data_map(
        {
            "source": "auto",
            "codes": ["600519.SH"],
            "start_date": "2024-01-01",
            "end_date": "2024-01-03",
            "interval": "1D",
        }
    )

    assert result.caliber_warning is not None
    assert "additive price adjustment" in result.caliber_warning
    assert "600519.SH" in result.caliber_warning
    assert "not total returns" in result.caliber_warning
    assert "mixed price calibers" not in result.caliber_warning
    assert "additive price adjustment" in caplog.text


def test_fetch_data_map_does_not_call_an_index_additive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tencent run over an index and a stock warns about the stock only."""

    class _TencentBoth:
        name = "tencent"

        def fetch(self, codes, start, end, fields=None, interval="1D"):  # noqa: ANN001, ANN201
            return {code: _df() for code in codes}

    monkeypatch.setattr(runner, "resolve_loader", lambda market: _TencentBoth())
    monkeypatch.setattr(runner, "LOADER_REGISTRY", {})
    config = {"source": "auto", "start_date": "2024-01-01", "end_date": "2024-01-03", "interval": "1D"}

    index_only = runner.fetch_data_map({**config, "codes": ["000300.SH"]})
    assert index_only.caliber_warning is None

    both = runner.fetch_data_map({**config, "codes": ["000300.SH", "600519.SH"]})
    assert both.caliber_warning is not None
    assert "additive price adjustment in this run: 600519.SH (tencent)." in both.caliber_warning
    assert "mixed price calibers" in both.caliber_warning


def test_fetch_data_map_reports_both_warnings_when_they_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tencent (additive) serving 600519.SH beside sina (raw) serving TSLA.US is
    both a mixed basket and an additive series; one warning must not shadow the
    other, since each says something the other does not."""
    monkeypatch.setattr(runner, "resolve_loader", lambda market: _TencentStub())
    monkeypatch.setattr(runner, "LOADER_REGISTRY", {"sina": _SinaStub})

    result = runner.fetch_data_map(
        {
            "source": "auto",
            "codes": ["600519.SH", "TSLA.US"],
            "start_date": "2024-01-01",
            "end_date": "2024-01-03",
            "interval": "1D",
        }
    )

    assert result.caliber_warning is not None
    assert "mixed price calibers" in result.caliber_warning
    assert "additive price adjustment" in result.caliber_warning


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


def test_gildata_loader_serves_the_caliber_the_table_claims() -> None:
    from backtest.loaders.gildata_loader import _RESTORATION_QFQ, _parse_daily_rows

    assert price_caliber("gildata", "a_share") == "split_dividend"
    # The caliber is pinned by the request parameter, not by any local
    # scaling: restorationStatus=1 asks the vendor for 前复权 bars, and the
    # parser must pass that OHLC through untouched (volume keeps its own
    # unit conversion).
    assert _RESTORATION_QFQ == "1"
    df = _parse_daily_rows(
        [
            {
                "tradingday": "2024-01-03",
                "openprice": 1.0, "highprice": 2.0, "lowprice": 0.5,
                "closeprice": 1.5, "turnovervolume": 100.0,
            }
        ]
    )
    assert df is not None
    assert df["close"].iloc[0] == pytest.approx(1.5)
    assert df["open"].iloc[0] == pytest.approx(1.0)
