"""Tests for the technical indicator tool."""

import json

import pandas as pd
import pytest

from src.shadow_account.indicators import compute_rsi as shadow_rsi
from src.tools.technical_indicator_tool import (
    TechnicalIndicatorTool,
    _compute_bollinger,
    _compute_ema,
    _compute_macd,
    _compute_rsi,
    _compute_sma,
    _compute_volume_stats,
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

    def test_rsi_first_value_is_the_seed_average(self):
        """Classic 15-bar Wilder worked example: with exactly 14 deltas the
        RSI is the seed itself, the simple mean of the 14 gains and losses
        (approx 70.46, TA-Lib's value). An exponential mean started from the
        first delta gives approx 71.80 for the same input.
        """
        close = pd.Series(
            [
                44.34,
                44.09,
                44.15,
                43.61,
                44.33,
                44.83,
                45.10,
                45.42,
                45.84,
                46.08,
                45.89,
                46.03,
                45.61,
                46.28,
                46.28,
            ]
        )
        rsi = _compute_rsi(close, period=14)
        assert rsi == pytest.approx(70.4641, abs=0.01)
        assert rsi != pytest.approx(71.8024, abs=0.01)

    def test_rsi_matches_shadow_account_wilder_rsi(self):
        """Regression: must agree with the SMA-seeded Wilder RSI that
        shadow_account/extractor.py and shadow_account/scanner.py use
        (shadow_account/indicators.py). An exponential mean started from the
        first delta reads approx 18.82 on this 20-delta series, 10 points
        below the Wilder value.
        """
        close = pd.Series(
            [
                float(x)
                for x in [
                    100,
                    101,
                    102.5,
                    104,
                    103.5,
                    105,
                    106.5,
                    108,
                    107.5,
                    109,
                    110.5,
                    109.5,
                    108,
                    106,
                    103.5,
                    101,
                    98,
                    95.5,
                    93,
                    90.5,
                    88,
                ]
            ]
        )
        period = 14

        rsi = _compute_rsi(close, period=period)
        assert rsi == pytest.approx(float(shadow_rsi(close, period).iloc[-1]), abs=1e-9)
        assert rsi == pytest.approx(28.9835, abs=0.01)


class TestVolume:
    def test_volume_stats_normal(self):
        volume = pd.Series([float(1000 + i) for i in range(20)])
        result = _compute_volume_stats(volume)
        assert result["latest"] == 1019.0
        assert result["sma_20"] == pytest.approx(1009.5)
        assert result["ratio_20"] == pytest.approx(1019.0 / 1009.5)

    def test_volume_stats_require_complete_window(self):
        volume = pd.Series([float(1000 + i) for i in range(19)] + [float("nan")])
        result = _compute_volume_stats(volume)
        assert result["latest"] is None
        assert result["sma_20"] is None
        assert result["ratio_20"] is None


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

    def test_bollinger_uses_population_std(self):
        """Bands use the population std of the window (TA-Lib, pandas-ta).
        For 1..20 that is sqrt(33.25) approx 5.766, so the upper band is
        approx 22.03; the sample std (approx 5.916) would give approx 22.33.
        """
        close = pd.Series(range(1, 21), dtype=float)
        result = _compute_bollinger(close, period=20)
        assert result["middle"] == pytest.approx(10.5)
        assert result["upper"] == pytest.approx(10.5 + 2 * 33.25**0.5, abs=0.01)
        assert result["lower"] == pytest.approx(10.5 - 2 * 33.25**0.5, abs=0.01)

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
        assert result["indicators"]["volume"] == {
            "latest": None,
            "sma_20": None,
            "ratio_20": None,
            "unit": None,
        }

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
        short_close = pd.Series(
            [float(100 + i) for i in range(10)],
            index=pd.date_range("2026-06-01", periods=10, freq="B"),
        )
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

    def test_read_identity_pins_requested_boundary_and_provenance(
        self, monkeypatch, sample_df
    ):
        seen = {}
        provenance = {
            "AAPL": {
                "source": "fake",
                "requested_source": "auto",
                "fallback_used": False,
                "volume_unit": "shares",
            }
        }

        def _mock_fetch(**kwargs):
            seen.update(kwargs)
            return {"AAPL": sample_df, "_provenance": provenance}

        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            _mock_fetch,
        )
        result = json.loads(
            TechnicalIndicatorTool().execute(
                symbol="AAPL",
                end_date="2026-09-24",
            )
        )

        identity = result["read_identity"]
        assert result["ok"] is True
        assert seen["end_date"] == "2026-09-24"
        assert identity["mode"] == "pinned_boundary"
        assert identity["requested_end_date"] == "2026-09-24"
        assert identity["bar_count"] == 200
        assert identity["provenance"]["source"] == "fake"
        assert len(identity["dataset_fingerprint"]) == 64

    def test_dataset_fingerprint_is_stable_for_same_observation_and_changes_with_bars(
        self, monkeypatch, sample_df
    ):
        payload = sample_df.copy()
        provenance = {"AAPL": {"source": "fake", "fallback_used": False}}

        def _mock_fetch(**kwargs):
            return {"AAPL": payload.copy(), "_provenance": provenance}

        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            _mock_fetch,
        )
        tool = TechnicalIndicatorTool()
        first = json.loads(tool.execute(symbol="AAPL", end_date="2026-09-24"))
        second = json.loads(tool.execute(symbol="AAPL", end_date="2026-09-24"))
        assert (
            first["read_identity"]["dataset_fingerprint"]
            == second["read_identity"]["dataset_fingerprint"]
        )

        payload.iloc[-1, payload.columns.get_loc("close")] += 1.0
        changed = json.loads(tool.execute(symbol="AAPL", end_date="2026-09-24"))
        assert (
            changed["read_identity"]["dataset_fingerprint"]
            != first["read_identity"]["dataset_fingerprint"]
        )

    @pytest.mark.parametrize(
        "end_date",
        [
            "24-09-2026",
            "2026-9-4",
            "2026-09-4",
            "2026-9-04",
        ],
    )
    def test_invalid_end_date_fails_closed(self, monkeypatch, end_date):
        called = False

        def _mock_fetch(**kwargs):
            nonlocal called
            called = True
            return {}

        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            _mock_fetch,
        )
        result = json.loads(
            TechnicalIndicatorTool().execute(
                symbol="AAPL",
                end_date=end_date,
            )
        )
        assert result["ok"] is False
        assert "YYYY-MM-DD" in result["error"]
        assert called is False

    def test_declares_the_end_date_input(self):
        assert "end_date" in TechnicalIndicatorTool().parameters["properties"]


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
        assert result["indicators"]["volume"]["latest"] == 1_000_029.0
        assert result["indicators"]["volume"]["sma_20"] == pytest.approx(1_000_019.5)
        assert result["indicators"]["volume"]["ratio_20"] == pytest.approx(
            1_000_029.0 / 1_000_019.5
        )

    def test_an_undated_bar_with_no_volume_is_not_filled_by_the_bar_before(self, monkeypatch):
        """Without dates, bars align by position: dropping the gap would report bar 28 as latest."""
        records = self._records()
        for record in records:
            del record["trade_date"]
        records[-1]["volume"] = None
        monkeypatch.setattr(
            "src.tools.technical_indicator_tool.fetch_market_data",
            lambda **kw: {"MSFT": pd.DataFrame(records)},
        )
        result = json.loads(TechnicalIndicatorTool().execute(symbol="MSFT"))

        assert result["indicators"]["volume"]["latest"] is None
        assert result["indicators"]["volume"]["sma_20"] is None

    @pytest.mark.parametrize("declared", ["lots", "shares", None])
    def test_volume_carries_the_unit_its_source_declared(self, monkeypatch, declared):
        """An A-share source counts board lots of 100, the Yahoo family shares (#1062)."""
        seen: dict = {}
        provenance = {} if declared is None else {"600519.SH": {"volume_unit": declared}}

        def fetch(**kwargs):
            seen.update(kwargs)
            return {"600519.SH": self._records(), "_provenance": provenance}

        monkeypatch.setattr("src.tools.technical_indicator_tool.fetch_market_data", fetch)
        result = json.loads(TechnicalIndicatorTool().execute(symbol="600519.SH"))

        assert seen["include_provenance"] is True
        assert result["indicators"]["volume"]["unit"] == declared

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
