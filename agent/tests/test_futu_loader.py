"""Tests for FutuLoader — all Futu API calls are mocked.

futu-api is not installed in CI, so we stub ``sys.modules['futu']`` before
importing the loader.  Every external call goes through the stub.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Stub futu before importing loader
# ---------------------------------------------------------------------------


class _KLType:
    K_1M = "K_1M"
    K_5M = "K_5M"
    K_15M = "K_15M"
    K_30M = "K_30M"
    K_DAY = "K_DAY"
    K_60M = "K_60M"
    K_240M = "K_240M"
    K_WEEK = "K_WEEK"
    K_MON = "K_MON"


_futu_stub = MagicMock()
_futu_stub.RET_OK = 0
_futu_stub.KLType = _KLType
sys.modules.setdefault("futu", _futu_stub)

from backtest.loaders.futu import (  # noqa: E402
    FutuLoader,
    _normalize_frame,
    _to_futu_symbol,
    _to_futu_ktype,
)
from backtest.loaders.base import NoAvailableSourceError  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_futu_mock():
    """Ensure the futu stub is clean before and after every test."""
    _futu_stub.OpenQuoteContext.reset_mock()
    _futu_stub.OpenQuoteContext.side_effect = None
    yield
    _futu_stub.OpenQuoteContext.reset_mock()
    _futu_stub.OpenQuoteContext.side_effect = None


def _make_kline_df(dates=None) -> pd.DataFrame:
    """Build a minimal Futu kline DataFrame mirroring request_history_kline output."""
    dates = dates or ["2024-01-02 00:00:00", "2024-01-03 00:00:00"]
    n = len(dates)
    return pd.DataFrame({
        "code":     ["HK.00700"] * n,
        "time_key": dates,
        "open":     [350.0] * n,
        "high":     [360.0] * n,
        "low":      [345.0] * n,
        "close":    [355.0] * n,
        "volume":   [1_000_000] * n,
        "turnover": [350_000_000.0] * n,
    })


# ---------------------------------------------------------------------------
# Symbol mapping
# ---------------------------------------------------------------------------

class TestSymbolMapping:
    def test_hk_five_digit(self):
        assert _to_futu_symbol("700.HK") == "HK.00700"

    def test_hk_short_padded(self):
        assert _to_futu_symbol("5.HK") == "HK.00005"

    def test_sz_symbol(self):
        assert _to_futu_symbol("000001.SZ") == "SZ.000001"

    def test_sh_symbol(self):
        assert _to_futu_symbol("600519.SH") == "SH.600519"

    def test_case_insensitive(self):
        assert _to_futu_symbol("700.hk") == "HK.00700"


# ---------------------------------------------------------------------------
# Interval mapping
# ---------------------------------------------------------------------------


class TestIntervalMapping:
    @pytest.mark.parametrize(
        ("interval", "expected"),
        [
            ("1m", "K_1M"),
            ("5m", "K_5M"),
            ("15m", "K_15M"),
            ("30m", "K_30M"),
            ("1H", "K_60M"),
            ("4H", "K_240M"),
            ("1D", "K_DAY"),
            ("1W", "K_WEEK"),
            ("1M", "K_MON"),
        ],
    )
    def test_supported_intervals(self, interval, expected):
        assert _to_futu_ktype(interval) == expected

    def test_unknown_fails_closed(self):
        with pytest.raises(NoAvailableSourceError, match="unsupported Futu interval"):
            _to_futu_ktype("999X")


# ---------------------------------------------------------------------------
# _normalize_frame
# ---------------------------------------------------------------------------


class TestNormalizeFrame:
    def test_ohlcv_columns(self):
        result = _normalize_frame(_make_kline_df())
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]

    def test_index_name(self):
        result = _normalize_frame(_make_kline_df())
        assert result.index.name == "trade_date"

    def test_sorted_ascending(self):
        df = _make_kline_df(dates=["2024-01-03 00:00:00", "2024-01-02 00:00:00"])
        result = _normalize_frame(df)
        assert result.index[0] < result.index[1]

    def test_empty_input(self):
        result = _normalize_frame(pd.DataFrame())
        assert result.empty
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]

    def test_drops_nan_ohlc_rows(self):
        df = _make_kline_df()
        df.loc[0, "close"] = None
        result = _normalize_frame(df)
        assert len(result) == 1

    def test_fills_nan_volume_with_zero(self):
        df = _make_kline_df()
        df.loc[0, "volume"] = None
        result = _normalize_frame(df)
        assert result["volume"].iloc[0] == 0.0


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_false_when_host_missing(self, monkeypatch):
        from src.config.accessor import reset_env_config

        monkeypatch.setenv("FUTU_HOST", "")
        monkeypatch.setenv("FUTU_PORT", "11111")
        reset_env_config()
        assert FutuLoader().is_available() is False
        reset_env_config()

    def test_false_when_port_missing(self, monkeypatch):
        from src.config.accessor import reset_env_config

        monkeypatch.setenv("FUTU_HOST", "127.0.0.1")
        monkeypatch.setenv("FUTU_PORT", "0")
        reset_env_config()
        assert FutuLoader().is_available() is False
        reset_env_config()

    def test_true_when_connection_succeeds(self, monkeypatch):
        from src.config.accessor import reset_env_config

        monkeypatch.setenv("FUTU_HOST", "127.0.0.1")
        monkeypatch.setenv("FUTU_PORT", "11111")
        reset_env_config()
        mock_ctx = MagicMock()
        _futu_stub.OpenQuoteContext.return_value = mock_ctx
        assert FutuLoader().is_available() is True
        mock_ctx.close.assert_called_once()
        reset_env_config()

    def test_false_when_connection_raises(self, monkeypatch):
        from src.config.accessor import reset_env_config

        monkeypatch.setenv("FUTU_HOST", "127.0.0.1")
        monkeypatch.setenv("FUTU_PORT", "11111")
        reset_env_config()
        _futu_stub.OpenQuoteContext.side_effect = OSError("connection refused")
        assert FutuLoader().is_available() is False
        reset_env_config()


# ---------------------------------------------------------------------------
# fetch()
# ---------------------------------------------------------------------------

class TestFetch:
    @pytest.fixture()
    def loader(self, monkeypatch):
        monkeypatch.setenv("FUTU_HOST", "127.0.0.1")
        monkeypatch.setenv("FUTU_PORT", "11111")
        return FutuLoader()

    @pytest.fixture()
    def mock_ctx(self):
        ctx = MagicMock()
        _futu_stub.OpenQuoteContext.return_value = ctx
        return ctx

    def test_empty_codes_returns_empty(self, loader):
        assert loader.fetch([], "2024-01-01", "2024-01-31") == {}

    def test_returns_normalized_dataframe(self, loader, mock_ctx):
        mock_ctx.request_history_kline.return_value = (0, _make_kline_df(), None)
        result = loader.fetch(["700.HK"], "2024-01-01", "2024-01-31")
        assert "700.HK" in result
        df = result["700.HK"]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.index.name == "trade_date"

    def test_futu_symbol_converted_correctly(self, loader, mock_ctx):
        mock_ctx.request_history_kline.return_value = (0, _make_kline_df(), None)
        loader.fetch(["700.HK"], "2024-01-01", "2024-01-31")
        args, _ = mock_ctx.request_history_kline.call_args
        assert args[0] == "HK.00700"

    def test_raises_on_connection_failure(self, loader):
        _futu_stub.OpenQuoteContext.side_effect = OSError("connection refused")
        with pytest.raises(NoAvailableSourceError):
            loader.fetch(["700.HK"], "2024-01-01", "2024-01-31")

    def test_skips_symbol_on_non_ret_ok(self, loader, mock_ctx):
        mock_ctx.request_history_kline.return_value = (1, "error message", None)
        result = loader.fetch(["700.HK"], "2024-01-01", "2024-01-31")
        assert "700.HK" not in result

    def test_context_always_closed(self, loader, mock_ctx):
        mock_ctx.request_history_kline.return_value = (0, _make_kline_df(), None)
        loader.fetch(["700.HK"], "2024-01-01", "2024-01-31")
        mock_ctx.close.assert_called_once()

    def test_fetch_unknown_interval_fails_before_opening_context(self, loader):
        with pytest.raises(NoAvailableSourceError, match="unsupported Futu interval"):
            loader.fetch(["700.HK"], "2024-01-01", "2024-01-31", interval="2m")
        _futu_stub.OpenQuoteContext.assert_not_called()

    def test_forwards_page_key_and_normalizes_all_pages_once(
        self, loader, mock_ctx, monkeypatch
    ):
        import backtest.loaders.futu as futu_loader

        first = _make_kline_df(["2024-01-02 00:00:00"])
        second = _make_kline_df(["2024-01-03 00:00:00"])
        mock_ctx.request_history_kline.side_effect = [
            (0, first, b"next-page"),
            (0, second, None),
        ]
        normalize = MagicMock(side_effect=_normalize_frame)
        monkeypatch.setattr(futu_loader, "_normalize_frame", normalize)

        result = loader.fetch(["700.HK"], "2024-01-01", "2024-01-31")

        assert len(result["700.HK"]) == 2
        assert normalize.call_count == 1
        assert len(normalize.call_args.args[0]) == 2
        assert (
            mock_ctx.request_history_kline.call_args_list[0].kwargs["page_req_key"]
            is None
        )
        assert (
            mock_ctx.request_history_kline.call_args_list[1].kwargs["page_req_key"]
            == b"next-page"
        )

    def test_later_page_failure_discards_symbol(self, loader, mock_ctx, monkeypatch):
        import backtest.loaders.futu as futu_loader

        mock_ctx.request_history_kline.side_effect = [
            (0, _make_kline_df(["2024-01-02 00:00:00"]), b"next-page"),
            (1, "page failed", None),
        ]
        cache_put = MagicMock()
        monkeypatch.setattr(futu_loader, "loader_cache_put", cache_put)

        result = loader.fetch(["700.HK"], "2024-01-01", "2024-01-31")

        assert "700.HK" not in result
        cache_put.assert_not_called()

    def test_empty_success_is_not_returned_or_cached(
        self, loader, mock_ctx, monkeypatch
    ):
        import backtest.loaders.futu as futu_loader

        mock_ctx.request_history_kline.return_value = (0, pd.DataFrame(), None)
        cache_put = MagicMock()
        monkeypatch.setattr(futu_loader, "loader_cache_put", cache_put)

        result = loader.fetch(["700.HK"], "2024-01-01", "2024-01-31")

        assert "700.HK" not in result
        cache_put.assert_not_called()

    def test_duplicate_timestamps_keep_last_page_value(self, loader, mock_ctx):
        first = _make_kline_df(["2024-01-02 00:00:00"])
        second = _make_kline_df(["2024-01-02 00:00:00"])
        second.loc[0, "close"] = 360.0
        mock_ctx.request_history_kline.side_effect = [
            (0, first, b"next-page"),
            (0, second, None),
        ]

        result = loader.fetch(["700.HK"], "2024-01-01", "2024-01-31")

        assert len(result["700.HK"]) == 1
        assert result["700.HK"].iloc[0]["close"] == 360.0
