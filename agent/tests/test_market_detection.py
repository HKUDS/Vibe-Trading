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
            # US equity — dotted class shares in the .US form (BRK.B, BF.A,
            # RDS.A) must not fall through to the a_share default.
            ("BRK.B.US", "us_equity"),
            ("BRK.A.US", "us_equity"),
            ("BF.B.US", "us_equity"),
            ("RDS.A.US", "us_equity"),
            ("WRB.B.US", "us_equity"),
            ("LEN.B.US", "us_equity"),
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
        assert _detect_market("brk.b.us") == "us_equity"

    def test_unknown_defaults_to_a_share(self) -> None:
        # Symbols that don't match any pattern fall through to the
        # ``a_share`` default. ``EURUSD`` and ``BTCUSDT`` used to be
        # examples but are now classified (PR #1280); use truly
        # unclassifiable inputs so the default-to-``a_share`` behavior
        # is pinned without coupling to a specific routing decision.
        assert _detect_market("UNKNOWN") == "a_share"
        assert _detect_market("random-string") == "a_share"
        assert _detect_market("12345") == "a_share"
        assert _detect_market("123456") == "a_share"
        assert _detect_market("@#$") == "a_share"

    def test_tushare_suffix_china_futures_classify_as_china_futures(self) -> None:
        # #1394: Tushare spells the exchanges SHF/CZC/CFX/GFE where the
        # canonical set is SHFE/ZCE/CFFEX/GFEX; without the alias these
        # contracts fell through to the a_share default or the global engine
        # (wrong multiplier, wrong currency, wrong band rules).
        for code in ("CU1811.SHF", "CF501.CZC", "IF2406.CFX", "SC2409.GFE"):
            assert _detect_market(code) == "futures", code
            assert code_currency(code) == "CNY", code
        # Canonical spellings keep working.
        assert _detect_market("CU2406.SHFE") == "futures"
        assert code_currency("rb2410.DCE") == "CNY"
        # A non-China exchange must still not classify as China futures.
        assert not _is_china_futures("M2412.CBOT")
        assert not _is_china_futures("CL2412.NYMEX")
        # And a global futures code with a recognized venue keeps its currency.
        assert code_currency("ES.CME") == "USD"

    def test_dated_global_futures_with_a_venue_suffix_classify_as_futures(self) -> None:
        # The sibling of #1394 on the global side: the bare dated forms
        # (CL2412, ESZ4) classified, and the continuous form with a venue
        # (ES.CME) classified, but the combination fell through to the a_share
        # default -- so a USD contract was settled in CNY under A-share T+1
        # rules with no shorting.
        for code in ("CL2412.NYMEX", "ES2503.CME", "ESZ4.CME", "GCM2025.COMEX"):
            assert _detect_market(code) == "futures", code
            assert not _is_china_futures(code), code
            assert code_currency(code) == "USD", code
        # The venue decides the currency, not the default.
        assert code_currency("FDAX2412.EUREX") == "EUR"
        # A recognized venue is what admits a single-letter product (CBOT
        # grains); the bare form stays out because nothing proves its class.
        assert _detect_market("C2412.CBOT") == "futures"
        assert _detect_market("C2412") == "a_share"
        # Equities that share the shape must not be captured.
        assert _detect_market("AAPL.US") == "us_equity"
        assert _detect_market("TD.TO") == "ca_equity"

    def test_concatenated_crypto_pairs_route_to_crypto(self) -> None:
        # Separator-less spot pairs (the Binance spelling) used to fall
        # through every pattern and pick up a_share rules, T+1 and no
        # shorting on a perpetual. The quote-asset table mirrors the
        # trade-journal parser.
        assert _detect_market("BTCUSDT") == "crypto"
        assert _detect_market("ETHUSDT") == "crypto"
        assert _detect_market("ETHUSDC") == "crypto"
        assert _detect_market("DOGEUSDT") == "crypto"
        assert code_currency("BTCUSDT") == "USD"
        # Metals and G10 FX end in USD, not a stablecoin quote, and stay forex.
        assert _detect_market("XAUUSD") == "forex"
        assert _detect_market("EURUSD") == "forex"
        # A bare 6-letter code outside every table still hits the default.
        assert _detect_market("NFLXLI") == "a_share"


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

    def test_dotted_class_share_source_and_currency(self) -> None:
        """Dotted class shares must route to USD + yfinance, not CNY/tushare."""
        for code in ("BRK.B.US", "BRK.A.US", "BF.B.US"):
            assert _detect_source(code) == "yfinance", code
            assert code_currency(code) == "USD", code

    def test_dotted_class_share_groups_with_other_us_equities(self) -> None:
        basket = ["BRK.B.US", "AAPL.US"]
        groups = _group_codes_by_market(basket)
        assert groups == {"us_equity": basket}

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

    def test_bare_code_of_every_priced_product(self) -> None:
        from backtest.engines.china_futures import _MULTIPLIER

        for product in _MULTIPLIER:
            assert _is_china_futures(f"{product}2501") is True, product


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

    def test_bare_fx_pair_classifies_as_forex(self) -> None:
        # Bare 6-character G10 / precious-metal pairs. PR #1280 added
        # the whitelist-restricted regex so ``XAUUSD`` / ``EURUSD`` route
        # to ``forex`` instead of falling through to the ``a_share``
        # default. The test pins the new behavior explicitly.
        assert _detect_market("XAUUSD") == "forex"
        assert _detect_market("EURUSD") == "forex"
        assert _detect_market("XAGUSD") == "forex"
        assert _detect_market("XPTUSD") == "forex"
        assert _detect_market("XPDUSD") == "forex"
        assert _detect_market("GBPUSD") == "forex"
        assert _detect_market("USDJPY") == "forex"

    def test_yahoo_equals_notation_routes_to_underlying_market(self) -> None:
        # Yahoo's continuous-front-month futures form (``=F``) and forex
        # form (``=X``). PR #1280 added these patterns.
        assert _detect_market("GC=F") == "futures"
        assert _detect_market("CL=F") == "futures"
        assert _detect_market("SI=F") == "futures"
        assert _detect_market("HG=F") == "futures"
        assert _detect_market("MGC=F") == "futures"
        assert _detect_market("XAUUSD=X") == "forex"
        assert _detect_market("EURUSD=X") == "forex"

    def test_bare_fx_pair_classification_is_case_insensitive(self) -> None:
        # The bare-6-character regex in ``_MARKET_PATTERNS`` is compiled
        # with ``re.I``. This is the same case-insensitive convention the
        # project has always used for symbol matching (see also
        # ``test_case_insensitive``), so ``eurusd`` / ``xauusd`` resolving
        # as ``forex`` is intentional rather than incidental.
        assert _detect_market("eurusd") == "forex"
        assert _detect_market("xauusd") == "forex"
        assert _detect_market("gbpusd") == "forex"
        assert _detect_market("usdjpy") == "forex"
        assert _detect_market("gc=f") == "futures"
        assert _detect_market("eurusd=x") == "forex"


class TestChinaFuturesMainContract:
    """#1395 — ``<product>0`` is the rolled series, and it was not routed.

    A dated contract lives about one year (``RB2601`` measured at 242 trading
    days), so any backtest spanning more than a contract cycle has to name the
    main continuous series. ``RB0`` matched no pattern and fell to the
    ``a_share`` default, which both applied T+1 and no-shorting to a leveraged
    futures series and kept it out of the futures loader chain.
    """

    @pytest.mark.parametrize("code", [
        "RB0",    # SHFE rebar
        "rb0",    # lowercase — the table is case-insensitive
        "IF0",    # CFFEX index future
        "T0",     # CFFEX 10y treasury, single-letter product
        "MA0",    # ZCE methanol
        "SI0",    # GFEX industrial silicon
        "V0",     # DCE PVC, single-letter product
    ])
    def test_main_contract_resolves_to_futures(self, code: str) -> None:
        assert _detect_market(code) == "futures"

    @pytest.mark.parametrize("code", [
        "TSLA0",   # not a whitelisted product — must stay off the futures path
        "ABCD0",   # NB: "ZZZ0" is genuinely a global month-code contract
                   # (product ZZ, Z = December) under the pre-existing rule,
                   # so it is not a counter-example to this one.
        "AAPL",
        "600519.SH",
        "000001.SZ",
    ])
    def test_non_product_codes_do_not_become_futures(self, code: str) -> None:
        """The other side of the gate.

        The rule is anchored on the product whitelist rather than a width
        heuristic precisely so an ordinary symbol ending in ``0`` keeps its
        own market.
        """
        assert _detect_market(code) != "futures"

    def test_main_contract_is_recognised_as_chinese(self) -> None:
        """It must reach ChinaFuturesEngine, not GlobalFutures."""
        assert _is_china_futures("RB0")
        assert _is_china_futures("IF0")
        assert not _is_china_futures("CL2412.NYMEX")

    def test_dated_contracts_keep_their_routing(self) -> None:
        """Adding the main-contract rule must not disturb the dated forms."""
        for code in ("RB2601", "rb2410.SHFE", "IF2406.CFFEX", "CL2412.NYMEX", "ESZ4"):
            assert _detect_market(code) == "futures", code


class TestBareThreeDigitZceFutures:
    """Zhengzhou prints delivery year/month in three digits.

    ``CF501.ZCE`` and ``CF501.CZC`` already reach China futures, and the
    engine prices the bare code at multiplier 5. The bare spelling matched
    no rule, so config validation refused it and the runner built a
    ``ChinaAEngine`` (T+1, no shorting, 100-share lots) instead.
    """

    @pytest.mark.parametrize(
        "code",
        [
            "AP501",
            "CF501",
            "CJ501",
            "CY501",
            "FG501",
            "MA501",
            "OI501",
            "PF501",
            "PK501",
            "RM501",
            "SA501",
            "SR501",
            "TA501",
            "UR501",
            "cf501",
            "local:CF501",
        ],
    )
    def test_bare_zce_month_is_china_futures(self, code: str) -> None:
        assert _detect_market(code) == "futures"
        assert _is_china_futures(code)
        assert code_currency(code) == "CNY"

    def test_bare_code_uses_the_futures_multiplier_not_share_lots(self) -> None:
        from backtest.engines.china_futures import ChinaFuturesEngine
        from backtest.runner import _select_market_engine

        engine = _select_market_engine(
            "tushare",
            {"codes": ["CF501"], "initial_capital": 1_000_000},
            ["CF501"],
        )
        assert isinstance(engine, ChinaFuturesEngine)
        # Same contract the suffixed spelling already priced: 5 CNY per point,
        # 7% margin, 4.3 CNY per lot. One lot at 15000 is 75000 notional.
        assert engine.get_contract_multiplier("CF501") == 5.0
        assert engine.get_margin_rate("CF501") == 0.07
        assert engine.calc_commission_for_symbol("CF501", 1, 15000.0, True) == 4.3
        suffixed = ChinaFuturesEngine(
            {"codes": ["CF501.ZCE"], "initial_capital": 1_000_000}
        )
        assert suffixed.get_contract_multiplier("CF501.ZCE") == 5.0

    @pytest.mark.parametrize(
        "code",
        [
            "CL501",
            "ES501",
            "IF501",
            "RB501",
            "CS501",
            "C2412",
            "M2501",
            "I2501",
            "600519",
            "AAPL",
            "00700.HK",
        ],
    )
    def test_other_bare_shapes_stay_out_of_this_rule(self, code: str) -> None:
        """Non-ZCE futures, single-letter products, and equities stay out."""
        assert _detect_market(code) != "futures"
