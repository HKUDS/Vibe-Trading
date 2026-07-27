"""Tests for backtest/correlation.py"""

import numpy as np
import pandas as pd
import pytest

from backtest.correlation import (
    _normalize_symbol,
    _rolling_correlation_matrix,
    infer_market,
)


class TestInferMarket:
    def test_crypto_usdt(self):
        assert infer_market("BTC-USDT") == "crypto"
        assert infer_market("ETH-USDT") == "crypto"

    def test_a_share(self):
        assert infer_market("000001.SZ") == "a_share"
        assert infer_market("600519.SH") == "a_share"

    def test_us_equity(self):
        assert infer_market("AAPL") == "us_equity"
        assert infer_market("SPY") == "us_equity"

    def test_hk_leading_zero_tickers(self):
        # Leading-zero HK tickers like 0700.HK / 0005.HK must be classified as
        # hk_equity, NOT a_share (which also starts with 0)
        assert infer_market("0700.HK") == "hk_equity"
        assert infer_market("0005.HK") == "hk_equity"
        assert infer_market("0000.HK") == "hk_equity"
        assert infer_market("9988.HK") == "hk_equity"

    def test_hk_suffix_before_a_share_prefix(self):
        # .HK suffix should be checked before A-share numeric prefix checks
        assert infer_market("000001.HK") == "hk_equity"

    def test_bare_hk_tickers_by_digit_length(self):
        # HK codes are <=5 digits; A-share codes are exactly 6 digits. A bare
        # short numeric code must classify as HK, not A-share / US.
        assert infer_market("0700") == "hk_equity"   # 腾讯
        assert infer_market("0005") == "hk_equity"   # 汇丰
        assert infer_market("0001") == "hk_equity"   # 长和
        assert infer_market("0388") == "hk_equity"   # 港交所
        assert infer_market("3690") == "hk_equity"   # 美团
        assert infer_market("9988") == "hk_equity"   # 阿里 (starts with 9)
        assert infer_market("700") == "hk_equity"    # unpadded form

    def test_bare_a_share_tickers_by_digit_length(self):
        # Exactly-6-digit bare codes are A-share regardless of prefix.
        assert infer_market("600000") == "a_share"   # 浦发银行 沪
        assert infer_market("000001") == "a_share"   # 平安银行 深
        assert infer_market("300750") == "a_share"   # 宁德时代 创业板
        assert infer_market("688981") == "a_share"   # 中芯国际 科创板
        assert infer_market("830799") == "a_share"   # 北交所
        assert infer_market("399001") == "a_share"   # 深证成指

    def test_explicit_suffix_always_wins(self):
        assert infer_market("600519.SH") == "a_share"
        assert infer_market("000001.SZ") == "a_share"
        assert infer_market("830799.BJ") == "a_share"
        assert infer_market("AAPL.US") == "us_equity"
        assert infer_market("9988.HK") == "hk_equity"


class TestNormalizeSymbol:
    def test_bare_us_equity_gets_us_suffix(self):
        # Regression: bare US tickers were passed to loaders that require the
        # canonical ``.US`` form, so the correlation matrix fetched nothing.
        assert _normalize_symbol("AAPL", "us_equity") == "AAPL.US"
        assert _normalize_symbol("SPY", "us_equity") == "SPY.US"

    def test_bare_a_share_gets_exchange_suffix(self):
        assert _normalize_symbol("600000", "a_share") == "600000.SH"
        assert _normalize_symbol("000001", "a_share") == "000001.SZ"
        assert _normalize_symbol("300750", "a_share") == "300750.SZ"
        assert _normalize_symbol("830799", "a_share") == "830799.BJ"

    def test_already_suffixed_passes_through(self):
        assert _normalize_symbol("AAPL.US", "us_equity") == "AAPL.US"
        assert _normalize_symbol("600000.SH", "a_share") == "600000.SH"
        assert _normalize_symbol("0700.HK", "hk_equity") == "0700.HK"

    def test_crypto_passes_through(self):
        assert _normalize_symbol("BTC-USDT", "crypto") == "BTC-USDT"
        assert _normalize_symbol("ETH-USDT", "crypto") == "ETH-USDT"

    def test_bare_hk_gets_hk_suffix(self):
        assert _normalize_symbol("0700", "hk_equity") == "0700.HK"

    def test_case_and_whitespace_normalized(self):
        assert _normalize_symbol(" aapl ", "us_equity") == "AAPL.US"


class TestFetchFallsThroughChain:
    """A loader that is available but returns no data must not end the search.

    Regression: HK codes silently vanished from the matrix whenever the first
    loader in the market chain (eastmoney) hit a network error, even though
    the next loader (yahoo) could serve the symbol.
    """

    @staticmethod
    def _price_df(n=60):
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        rng = np.random.default_rng(7)
        return pd.DataFrame(
            {"close": np.cumsum(rng.standard_normal(n)) + 100},
            index=pd.Index(dates, name="trade_date"),
        )

    def test_falls_through_to_next_loader_when_first_returns_empty(self, monkeypatch):
        from backtest.loaders import registry
        from backtest.correlation import compute_correlation_matrix

        good_df = self._price_df()

        class EmptyLoader:
            name = "fake_empty"
            markets = {"us_equity"}

            def is_available(self):
                return True

            def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
                return {}  # available but serves nothing (e.g. network error)

        class GoodLoader:
            name = "fake_good"
            markets = {"us_equity"}

            def is_available(self):
                return True

            def fetch(self, codes, start_date, end_date, *, interval="1D", fields=None):
                return {c: good_df.copy() for c in codes}

        monkeypatch.setattr(registry, "_registered", True)
        monkeypatch.setattr(
            registry, "LOADER_REGISTRY",
            {"fake_empty": EmptyLoader, "fake_good": GoodLoader},
        )
        monkeypatch.setattr(
            registry, "FALLBACK_CHAINS",
            {"us_equity": ["fake_empty", "fake_good"]},
        )

        result = compute_correlation_matrix(codes=["AAPL", "SPY"], days=30)
        assert result["labels"] == ["AAPL", "SPY"]
        assert result["matrix"][0][1] == pytest.approx(1.0)  # identical series


class TestRollingCorrelationMatrix:
    def _make_price_df(self, closes):
        """Build a DataFrame with trade_date as the index name (like real loaders)."""
        dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
        return pd.DataFrame(
            {"close": closes},
            index=pd.Index(dates, name="trade_date"),
        )

    def test_window_parameter_is_respected(self):
        # Full history has 50 rows; window=10 should use only the last 10 days.
        # Two assets with perfectly positively correlated full history but
        # negatively correlated last 10 days — verifies window is applied.
        np.random.seed(42)
        n = 50
        closes_a = list(np.cumsum(np.random.randn(n)) + 100)
        closes_b = list(np.cumsum(np.random.randn(n)) + 100)
        price_series = {
            "A": self._make_price_df(closes_a),
            "B": self._make_price_df(closes_b),
        }
        _, matrix_full = _rolling_correlation_matrix(price_series, window=1000, method="pearson")
        _, matrix_window = _rolling_correlation_matrix(price_series, window=10, method="pearson")
        # Matrices should be different when window is applied vs full history
        assert matrix_window[0][1] != pytest.approx(matrix_full[0][1])
        # But both should be valid correlations
        assert -1 <= matrix_window[0][1] <= 1
        assert -1 <= matrix_full[0][1] <= 1

    def test_same_asset_correlation_is_one(self):
        price_series = {
            "A": self._make_price_df([100, 105, 110, 108, 112]),
        }
        labels, matrix = _rolling_correlation_matrix(price_series, window=5, method="pearson")
        assert labels == ["A"]
        assert matrix[0][0] == pytest.approx(1.0)

    def test_matrix_is_symmetric(self):
        np.random.seed(42)
        price_series = {
            "A": self._make_price_df(np.cumsum(np.random.randn(100)).tolist()),
            "B": self._make_price_df(np.cumsum(np.random.randn(100)).tolist()),
            "C": self._make_price_df(np.cumsum(np.random.randn(100)).tolist()),
        }
        labels, matrix = _rolling_correlation_matrix(price_series, window=30, method="pearson")
        n = len(labels)
        assert len(labels) == 3
        for i in range(n):
            for j in range(n):
                assert matrix[i][j] == pytest.approx(matrix[j][i])

    def test_diagonal_is_one(self):
        np.random.seed(42)
        price_series = {
            "X": self._make_price_df(np.cumsum(np.random.randn(50)).tolist()),
            "Y": self._make_price_df(np.cumsum(np.random.randn(50)).tolist()),
        }
        labels, matrix = _rolling_correlation_matrix(price_series, window=20, method="pearson")
        n = len(labels)
        for i in range(n):
            assert matrix[i][i] == pytest.approx(1.0)

    def test_spearman_vs_pearson_diff(self):
        np.random.seed(0)
        # Non-linear relationship: Pearson < Spearman
        x = np.linspace(0, 10, 50)
        y = np.power(x, 2) + np.random.randn(50) * 5
        price_series = {
            "A": self._make_price_df((x * 100 + 1000).tolist()),
            "B": self._make_price_df((y + 1000).tolist()),
        }
        _, p_matrix = _rolling_correlation_matrix(price_series, window=30, method="pearson")
        _, s_matrix = _rolling_correlation_matrix(price_series, window=30, method="spearman")
        # Spearman can be higher for monotonic (not linear) relationships
        assert isinstance(p_matrix[0][1], float)
        assert isinstance(s_matrix[0][1], float)
        # Both should be reasonable correlations
        assert -1 <= p_matrix[0][1] <= 1
        assert -1 <= s_matrix[0][1] <= 1

    def test_does_not_forward_fill_missing_closes(self):
        # Under pandas>=2,<3 a bare pct_change() forward-fills NaN closes,
        # manufacturing a 0% return on the halted session and pairing it
        # against the peer's real move. GAP tracks PEER exactly, so once the
        # halted session is dropped instead of filled the two are perfectly
        # correlated. Mirrors TestAlignedReturns in test_regime.py.
        peer_closes = [100.0, 110.0, 115.5, 112.035, 121.0, 123.42]
        gap_closes = [c / 2.0 for c in peer_closes]
        gap_closes[2] = np.nan  # trading halt: no close printed
        price_series = {
            "GAP": self._make_price_df(gap_closes),
            "PEER": self._make_price_df(peer_closes),
        }
        labels, matrix = _rolling_correlation_matrix(price_series, window=30, method="pearson")
        i, j = labels.index("GAP"), labels.index("PEER")
        assert matrix[i][j] == pytest.approx(1.0)

    def test_empty_dict_returns_empty(self):
        labels, matrix = _rolling_correlation_matrix({}, window=30, method="pearson")
        assert labels == []
        assert matrix == []

    def test_missing_close_column_raises(self):
        df = pd.DataFrame({"open": [1, 2, 3]})
        with pytest.raises(ValueError, match="No 'close' column"):
            _rolling_correlation_matrix({"X": df}, window=30, method="pearson")


def test_rolling_correlation_unnamed_datetime_index() -> None:
    """OHLCV frames with an unnamed DatetimeIndex must not KeyError on trade_date."""
    import numpy as np
    import pandas as pd
    from backtest.correlation import _rolling_correlation_matrix

    idx = pd.date_range("2020-01-01", periods=40, freq="B")
    series = {
        "A": pd.DataFrame({"close": np.linspace(100, 110, 40)}, index=idx),
        "B": pd.DataFrame({"close": np.linspace(50, 60, 40)}, index=idx),
    }
    labels, matrix = _rolling_correlation_matrix(series, window=20, method="pearson")
    assert labels == ["A", "B"]
    assert len(matrix) == 2
