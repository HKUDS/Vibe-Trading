"""Tests for runner market detection, source mapping, and code normalization.

Also covers the audit-2026-05-18 B1 routing bug: composite.py previously
had a truncated ``_is_china_futures`` that only inspected the exchange
suffix, so a bare ``RB2410`` was misrouted to GlobalFuturesEngine. After
the consolidation in ``_market_hooks``, both the suffix form and the
bare product-code form must resolve identically.
"""

from __future__ import annotations

import pytest

from backtest.engines._market_hooks import _is_china_futures, code_currency
from backtest.runner import (
    _detect_market,
    _detect_source,
    _group_codes_by_market,
    _group_codes_by_source,
    _normalize_codes,
)


# ---------------------------------------------------------------------------
# _detect_market
# ---------------------------------------------------------------------------


class TestDetectMarket:
    """Symbol pattern → market type mapping."""

    @pytest.mark.parametrize(
        "code, expected",
        [
            # A-share mainboard
            ("000001.SZ", "a_share"),
            ("600519.SH", "a_share"),
            ("300750.SZ", "a_share"),
            # A-share Beijing exchange
            ("830799.BJ", "a_share"),
            # A-share ETF
            ("510300.SH", "a_share"),
            ("159919.SZ", "a_share"),
            ("560010.SH", "a_share"),
            # US equity
            ("AAPL.US", "us_equity"),
            ("TSLA.US", "us_equity"),
            ("NVDA.US", "us_equity"),
            # US equity — bare tickers without the .US suffix (issue #986)
            ("AAPL", "us_equity"),
            ("MSFT", "us_equity"),
            ("NVDA", "us_equity"),
            ("AMZN", "us_equity"),
            ("GOOGL", "us_equity"),
            ("SPY", "us_equity"),
            ("T", "us_equity"),
            ("V", "us_equity"),
            # HK equity
            ("0700.HK", "hk_equity"),
            ("9988.HK", "hk_equity"),
            ("00005.HK", "hk_equity"),
            # India equity (NSE / BSE)
            ("RELIANCE.NS", "india_equity"),
            ("TCS.NS", "india_equity"),
            ("M&M.NS", "india_equity"),  # ampersand
            ("BAJAJ-AUTO.NS", "india_equity"),  # hyphen
            ("500325.BO", "india_equity"),  # numeric BSE scrip code
            # Korea equity (KRX)
            ("005930.KS", "kr_equity"),  # KOSPI
            ("247540.KQ", "kr_equity"),  # KOSDAQ
            # Canada equity (TSX / TSX Venture)
            ("TD.TO", "ca_equity"),
            ("BBD-B.TO", "ca_equity"),
            ("PNG.V", "ca_equity"),
            # UK equity (LSE)
            ("VOD.L", "uk_equity"),
            ("SHEL.L", "uk_equity"),
            ("BARC.L", "uk_equity"),
            # Crypto
            ("BTC-USDT", "crypto"),
            ("ETH-USDT", "crypto"),
            ("BTC/USDT", "crypto"),
            # Futures
            ("IF2406.CFFEX", "futures"),
            ("AU2412.SHFE", "futures"),
            ("C2409.DCE", "futures"),
            ("CF2409.ZCE", "futures"),
            ("SC2406.INE", "futures"),
            # Forex
            ("EUR/USD", "forex"),
            ("USD/JPY", "forex"),
            ("EURUSD.FX", "forex"),
        ],
    )
    def test_known_patterns(self, code: str, expected: str) -> None:
        assert _detect_market(code) == expected

    def test_case_insensitive(self) -> None:
        assert _detect_market("000001.sz") == "a_share"
        assert _detect_market("aapl.us") == "us_equity"
        assert _detect_market("aapl") == "us_equity"
        assert _detect_market("btc-usdt") == "crypto"
        assert _detect_market("td.to") == "ca_equity"

    def test_unknown_defaults_to_a_share(self) -> None:
        assert _detect_market("UNKNOWN") == "a_share"
        assert _detect_market("random-string") == "a_share"
        # Bare codes outside the 1-5 letter US shape keep the old default.
        assert _detect_market("EURUSD") == "a_share"
        assert _detect_market("BTCUSDT") == "a_share"


# ---------------------------------------------------------------------------
# Issue #986 — bare US tickers must route to the us_equity chain
# ---------------------------------------------------------------------------


class TestBareUsTickerRouting:
    """Regression suite for issue #986.

    Bare US tickers (the Shadow Account US basket, agent-generated configs)
    previously fell through to the a_share default, walked the A-share
    loader chain, and died with NoAvailableSourceError. The catch-all
    ``^[A-Z]{1,5}$`` pattern must stay the lowest-priority entry so every
    suffixed / futures / crypto / forex form keeps winning first.
    """

    def test_shadow_us_basket_groups_into_us_equity(self) -> None:
        basket = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
        groups = _group_codes_by_market(basket)
        assert groups == {"us_equity": basket}

    def test_bare_ticker_source_and_currency(self) -> None:
        assert _detect_source("AAPL") == "yfinance"
        assert code_currency("AAPL") == "USD"
        assert code_currency("AAPL.US") == "USD"

    def test_canadian_tickers_route_to_canada_and_cad(self) -> None:
        assert _detect_source("TD.TO") == "yahoo"
        assert _detect_source("PNG.V") == "yahoo"
        assert code_currency("TD.TO") == "CAD"
        assert code_currency("PNG.V") == "CAD"

    def test_catch_all_is_lowest_priority(self) -> None:
        assert _detect_market("600519.SH") == "a_share"
        assert _detect_market("00700.HK") == "hk_equity"
        assert _detect_market("BTC-USDT") == "crypto"
        assert _detect_market("RELIANCE.NS") == "india_equity"
        assert _detect_market("005930.KS") == "kr_equity"
        assert _detect_market("RB2410") == "futures"
        assert _detect_market("ES2503") == "futures"
        assert _detect_market("CLZ4") == "futures"
        assert _detect_market("EUR/USD") == "forex"

    def test_shadow_liquid_baskets_route_to_their_own_market(self) -> None:
        from src.shadow_account.backtester import _LIQUID_BASKETS

        expected = {
            "china_a": "a_share",
            "hk": "hk_equity",
            "us": "us_equity",
            "crypto": "crypto",
        }
        for market, codes in _LIQUID_BASKETS.items():
            for code in codes:
                assert _detect_market(code) == expected[market], (
                    f"{market} basket code {code!r} detected as "
                    f"{_detect_market(code)!r}, expected {expected[market]!r}"
                )


# ---------------------------------------------------------------------------
# _detect_source
# ---------------------------------------------------------------------------


class TestDetectSource:
    """Market type → legacy source name."""

    @pytest.mark.parametrize(
        "code, expected_source",
        [
            ("000001.SZ", "tushare"),
            ("AAPL.US", "yfinance"),
            ("0700.HK", "yfinance"),
            ("RELIANCE.NS", "yahoo"),
            ("500325.BO", "yahoo"),
            ("005930.KS", "pykrx"),
            ("247540.KQ", "pykrx"),
            ("TD.TO", "yahoo"),
            ("PNG.V", "yahoo"),
            ("BTC-USDT", "okx"),
            ("IF2406.CFFEX", "tushare"),
            ("EUR/USD", "akshare"),
        ],
    )
    def test_source_mapping(self, code: str, expected_source: str) -> None:
        assert _detect_source(code) == expected_source


# ---------------------------------------------------------------------------
# _group_codes_by_market
# ---------------------------------------------------------------------------


class TestGroupCodes:
    def test_mixed_codes(self) -> None:
        codes = ["000001.SZ", "AAPL.US", "BTC-USDT", "0700.HK", "TD.TO"]
        groups = _group_codes_by_market(codes)
        assert groups["a_share"] == ["000001.SZ"]
        assert groups["us_equity"] == ["AAPL.US"]
        assert groups["crypto"] == ["BTC-USDT"]
        assert groups["hk_equity"] == ["0700.HK"]
        assert groups["ca_equity"] == ["TD.TO"]

    def test_same_market(self) -> None:
        codes = ["000001.SZ", "600519.SH"]
        groups = _group_codes_by_market(codes)
        assert groups["a_share"] == ["000001.SZ", "600519.SH"]
        assert len(groups) == 1

    def test_empty(self) -> None:
        assert _group_codes_by_market([]) == {}

    def test_group_by_source(self) -> None:
        codes = ["000001.SZ", "AAPL.US"]
        groups = _group_codes_by_source(codes)
        assert "tushare" in groups
        assert "yfinance" in groups


# ---------------------------------------------------------------------------
# _normalize_codes
# ---------------------------------------------------------------------------


class TestNormalizeCodes:
    def test_okx_slash_to_hyphen(self) -> None:
        assert _normalize_codes(["btc/usdt", "eth/usdt"], "okx") == [
            "BTC-USDT",
            "ETH-USDT",
        ]

    def test_ccxt_uppercase(self) -> None:
        assert _normalize_codes(["btc-usdt"], "ccxt") == ["BTC-USDT"]

    def test_non_crypto_unchanged(self) -> None:
        codes = ["000001.SZ", "AAPL.US"]
        assert _normalize_codes(codes, "tushare") == codes
        assert _normalize_codes(codes, "yfinance") == codes


# ---------------------------------------------------------------------------
# _is_china_futures — audit-2026-05-18 B1 bug fix coverage
# ---------------------------------------------------------------------------


class TestIsChinaFutures:
    """Regression suite for the composite.py truncated-routing bug.

    Before the fix, a bare ``RB2410`` returned False (composite.py only
    checked the exchange suffix) and was misrouted to GlobalFuturesEngine.
    Both forms must now agree.
    """

    def test_bare_uppercase_product(self) -> None:
        # The bug case: bare uppercase code with no suffix.
        assert _is_china_futures("RB2410") is True

    def test_bare_lowercase_product(self) -> None:
        assert _is_china_futures("rb2410") is True

    def test_suffix_lowercase(self) -> None:
        assert _is_china_futures("rb2410.SHFE") is True

    def test_suffix_uppercase(self) -> None:
        assert _is_china_futures("RB2410.SHFE") is True

    def test_global_with_exchange_suffix(self) -> None:
        # NYMEX is not a Chinese exchange.
        assert _is_china_futures("CL.NYMEX") is False

    def test_global_month_code_form(self) -> None:
        # CLZ4 = global futures month-code form, no Chinese product.
        assert _is_china_futures("CLZ4") is False

    # ── Audit-2026-05-18 regression guard: non-CN exchange must short-circuit ──
    # Without the guard, codes like ``M2412.CBOT`` (US soybean meal) would
    # extract product letter ``m`` (lowercased), find it in the CN product
    # table (China bean meal), and return True.

    def test_us_meal_on_cbot_not_chinese(self) -> None:
        assert _is_china_futures("M2412.CBOT") is False

    def test_us_cotton_on_ice_not_chinese(self) -> None:
        # ICE Cotton — letter prefix ``cf`` collides with CN Cotton (CFEX).
        assert _is_china_futures("CF2412.ICE") is False

    def test_us_gold_on_comex_not_chinese(self) -> None:
        # COMEX gold — letter prefix ``au`` collides with CN Au (SHFE).
        assert _is_china_futures("AU2412.COMEX") is False

    def test_eurex_short_code_not_chinese(self) -> None:
        # EUREX FGBL — letter prefix ``fg`` collides with CN flat glass.
        assert _is_china_futures("FG2412.EUREX") is False

    def test_bare_cn_collision_product_still_chinese(self) -> None:
        # Heuristic still fires when there is no exchange suffix.
        assert _is_china_futures("CF2412") is True
        assert _is_china_futures("M2412") is True


# ---------------------------------------------------------------------------
# _detect_market — task-required exhaustive assertions
# ---------------------------------------------------------------------------


class TestDetectMarketRequired:
    """Spot-check assertions called out explicitly by the audit task."""

    def test_bare_chinese_futures_is_futures(self) -> None:
        assert _detect_market("RB2410") == "futures"

    def test_a_share_with_sz_suffix(self) -> None:
        assert _detect_market("000001.SZ") == "a_share"

    def test_crypto_hyphen_form(self) -> None:
        assert _detect_market("BTC-USDT") == "crypto"
