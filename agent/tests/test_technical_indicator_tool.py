"""Tests for the technical indicator tool."""

import json

import pandas as pd
import pytest

from src.tools.technical_indicator_tool import (
    TechnicalIndicatorTool,
    _compute_bollinger,
    _compute_ema,
    _compute_macd,
    _compute_rsi,
    _compute_sma,
)


class TestSMA:
    def test_sma_normal(self):
        close = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0], dtype=float)
        assert _compute_sma(close, 3) == pytest.approx(40.0)  # (30+40+50)/3

    def test_sma_insufficient_bars(self):
        close = pd.Series([10.0, 20.0], dtype=float)
        assert _compute_sma(close, 5) is None

    def test_sma_exact_bars(self):
        close = pd.Series([10.0, 20.0, 30.0], dtype=float)
        assert _compute_sma(close, 3) == pytest.approx(20.0)


class TestEMA:
    def test_ema_normal(self):
        close = pd.Series(range(1, 31), dtype=float)
        result = _compute_ema(close, 10)
        assert result is not None
        assert 25 < result < 30  # EMA should be near recent values

    def test_ema_insufficient_bars(self):
        close = pd.Series([10.0], dtype=float)
        assert _compute_ema(close, 10) is None


class TestRSI:
    def test_rsi_uptrend(self):
        """All gains, no losses → RSI should approach 100."""
        close = pd.Series([float(100 + i) for i in range(30)], dtype=float)
        rsi = _compute_rsi(close)
        assert rsi is not None
        assert 95 <= rsi <= 100

    def test_rsi_flat(self):
        """Zero change → avg_loss = 0 → RSI = 100 (no downward pressure)."""
        close = pd.Series([100.0] * 30, dtype=float)
        rsi = _compute_rsi(close)
        assert rsi == 100.0

    def test_rsi_downtrend(self):
        """All losses, no gains → RSI should approach 0."""
        close = pd.Series([float(100 - i) for i in range(30)], dtype=float)
        rsi = _compute_rsi(close)
        assert rsi is not None
        assert 0 <= rsi <= 5

    def test_rsi_insufficient_bars(self):
        close = pd.Series([100.0, 101.0], dtype=float)
        assert _compute_rsi(close, 14) is None


class TestMACD:
    def test_macd_normal(self):
        close = pd.Series(range(1, 101), dtype=float)
        result = _compute_macd(close)
        assert result is not None
        assert "macd_line" in result
        assert "signal_line" in result
        assert "histogram" in result
        assert isinstance(result["macd_line"], float)

    def test_macd_insufficient_bars(self):
        close = pd.Series(range(1, 20), dtype=float)
        assert _compute_macd(close) is None


class TestBollinger:
    def test_bollinger_normal(self):
        close = pd.Series(range(1, 51), dtype=float)
        result = _compute_bollinger(close, period=20)
        assert result is not None
        assert result["upper"] > result["middle"] > result["lower"]

    def test_bollinger_flat(self):
        """Flat prices → bands collapse to the same value."""
        close = pd.Series([100.0] * 30, dtype=float)
        result = _compute_bollinger(close)
        assert result is not None
        assert result["upper"] == result["middle"] == result["lower"]

    def test_bollinger_insufficient_bars(self):
        close = pd.Series(range(1, 10), dtype=float)
        assert _compute_bollinger(close) is None


class TestTechnicalIndicatorTool:
    def test_missing_symbol(self):
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute())
        assert result["ok"] is False
        assert "symbol" in result["error"]

    def test_empty_symbol(self):
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="   "))
        assert result["ok"] is False

    def test_invalid_lookback_clamped(self):
        tool = TechnicalIndicatorTool()
        # Should not crash with non-numeric lookback
        result = json.loads(tool.execute(symbol="INVALID_SYMBOL_XYZ", lookback="abc"))
        assert "ok" in result


class TestTechnicalIndicatorToolIntegration:
    """End-to-end tests with mocked fetch_market_data."""

    @pytest.fixture
    def sample_close(self):
        """250-bar uptrend series, enough for all indicators including SMA 200."""
        return pd.Series(
            [float(100 + i) for i in range(250)],
            index=pd.date_range("2024-01-01", periods=250, freq="B"),
            name="close",
        )

    @pytest.fixture
    def sample_df(self, sample_close):
        return pd.DataFrame({"close": sample_close, "open": sample_close * 0.99})

    def test_execute_success(self, monkeypatch, sample_df):
        """Full pipeline: fetch → compute → JSON output."""
        def _mock_fetch(**kwargs):
            return {"AAPL": sample_df}
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            _mock_fetch,
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="AAPL"))
        assert result["ok"] is True
        assert result["symbol"] == "AAPL"
        assert result["indicators"]["rsi_14"] is not None
        assert result["indicators"]["macd"] is not None
        assert result["indicators"]["bollinger"] is not None
        assert result["indicators"]["sma_20"] is not None
        assert result["indicators"]["sma_50"] is not None
        assert result["indicators"]["sma_200"] is not None
        assert result["indicators"]["ema_20"] is not None
        assert result["latest_close"] == 349.0
        assert result["latest_date"] == str(sample_df.index[-1].date())

    def test_execute_dataframe_with_adj_close(self, monkeypatch, sample_close):
        """Loader returns 'adj_close' instead of 'close'."""
        df = pd.DataFrame({"adj_close": sample_close})
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"AAPL": df},
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="AAPL"))
        assert result["ok"] is True
        assert result["indicators"]["rsi_14"] is not None

    def test_execute_fetch_failure(self, monkeypatch):
        """Loader raises → error envelope."""
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("network down")),
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="AAPL"))
        assert result["ok"] is False
        assert "network down" in result["error"]

    def test_execute_empty_data(self, monkeypatch):
        """Loader returns empty → error."""
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"AAPL": pd.DataFrame()},
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="AAPL"))
        assert result["ok"] is False
        assert "No data" in result["error"]

    def test_execute_no_close_column(self, monkeypatch):
        """DataFrame without close column → error."""
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"AAPL": pd.DataFrame({"high": [1.0], "low": [0.5]})},
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="AAPL"))
        assert result["ok"] is False
        assert "close" in result["error"].lower()

    def test_execute_short_data_returns_nulls(self, monkeypatch):
        """Too few bars → indicators return null, but not error."""
        short_close = pd.Series([float(100 + i) for i in range(10)],
                                index=pd.date_range("2026-06-01", periods=10, freq="B"))
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"AAPL": pd.DataFrame({"close": short_close})},
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="AAPL", lookback=10))
        assert result["ok"] is True
        # With 10 bars: RSI needs 15, MACD needs 35, BB needs 20 → all null
        assert result["indicators"]["rsi_14"] is None
        assert result["indicators"]["macd"] is None
        assert result["indicators"]["bollinger"] is None
        # But SMA 20 should be null, SMA 50/200 null — only EMA 20 needs 20 bars, null too
        assert result["indicators"]["sma_20"] is None


class TestLoaderPayloadShapes:
    """Regression: #1002 — loader payloads arrive as list[dict], not DataFrame."""

    def _records(self, n: int = 30) -> list[dict]:
        """Simulate fetch_market_data's real return shape: list of OHLCV dicts."""
        return [
            {
                "trade_date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=i),
                "open": float(100 + i),
                "high": float(101 + i),
                "low": float(99 + i),
                "close": float(100 + i),
                "volume": 1_000_000 + i,
            }
            for i in range(n)
        ]

    def test_list_of_dicts_success(self, monkeypatch):
        """Real fetch_market_data payload (list[dict]) must not crash (#1002)."""
        payload = {"MSFT": self._records()}
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: payload,
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="MSFT"))
        assert result["ok"] is True
        assert result["indicators"]["rsi_14"] is not None
        assert result["latest_close"] == 129.0
        assert result["latest_date"] == "2026-01-30"

    def test_wrapped_capped_payload_is_rejected(self, monkeypatch):
        """A discontinuous capped payload must never produce indicators."""
        payload = {
            "MSFT": {
                "rows": 42,
                "returned": 30,
                "truncated": True,
                "policy": "every-14th-row",
                "hint": "narrow the date range",
                "data": self._records(),
            }
        }
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: payload,
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="MSFT"))
        assert result["ok"] is False
        assert "consecutive" in result["error"]

    def test_fetches_uncapped_then_sorts_and_tails_locally(self, monkeypatch):
        """Long windows use the latest consecutive bars, not even-stride samples."""
        records = self._records(600)
        observed: dict[str, int] = {}

        def _mock_fetch(**kwargs):
            observed["max_rows"] = kwargs["max_rows"]
            if kwargs["max_rows"]:
                step = len(records) // kwargs["max_rows"]
                return {"MSFT": records[::step]}
            return {"MSFT": list(reversed(records))}

        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            _mock_fetch,
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="MSFT", lookback=30))
        assert observed["max_rows"] == 0
        assert result["ok"] is True
        assert result["latest_close"] == 699.0
        assert result["latest_date"] == "2027-08-23"
        assert result["indicators"]["sma_20"] == pytest.approx(689.5)

    def test_list_of_dicts_uppercase_key(self, monkeypatch):
        """Loader with Close key (case variant) still resolves."""
        records = self._records()
        records[0]["Close"] = records[0].pop("close")
        for r in records[1:]:
            r["Close"] = r.pop("close")
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"MSFT": records},
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="MSFT"))
        assert result["ok"] is True
        assert result["indicators"]["rsi_14"] is not None
        assert result["latest_date"] == "2026-01-30"

    def test_empty_list(self, monkeypatch):
        """Empty list payload → clean error, not AttributeError."""
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"MSFT": []},
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="MSFT"))
        assert result["ok"] is False

    def test_list_missing_close(self, monkeypatch):
        """Records without any close key → clean error."""
        records = self._records()
        for r in records:
            r.pop("close")
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"MSFT": records},
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="MSFT"))
        assert result["ok"] is False
        assert "close" in result["error"].lower()

    def test_dict_payload_success(self, monkeypatch):
        """dict-like payload with 'close' key still works."""
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"MSFT": {"close": [float(100 + i) for i in range(30)]}},
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="MSFT"))
        assert result["ok"] is True
        assert result["indicators"]["rsi_14"] is not None
        assert result["latest_date"] is None

    def test_dataframe_payload_still_works(self, monkeypatch):
        """DataFrame payload keeps working (existing loader contract)."""
        close = pd.Series(
            [float(100 + i) for i in range(30)],
            index=pd.date_range("2026-01-01", periods=30, freq="D"),
        )
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"MSFT": pd.DataFrame({"close": close})},
        )
        tool = TechnicalIndicatorTool()
        result = json.loads(tool.execute(symbol="MSFT"))
        assert result["ok"] is True
        assert result["indicators"]["rsi_14"] is not None
        assert result["latest_date"] == "2026-01-30"
