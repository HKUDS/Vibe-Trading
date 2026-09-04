"""Test UK equity (LSE .L) market support end to end.

Regression suite for issue #1205: UK symbols used to fall through the
source/market detection tables to the tushare default and the China
fallback chain, surfacing as ``_unresolved`` after several seconds of
network attempts. They must now route as a first-class market with the
same parity as Canada/US: yahoo source, ``uk_equity`` market, a GBP-only
loader/accounting contract, and GlobalEquityEngine with ``market="uk"``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.engines.global_equity import GlobalEquityEngine
from backtest.engines._market_hooks import _detect_market, _detect_submarket, code_currency
from backtest.loaders.base import (
    is_lse_symbol,
    normalize_lse_quote_currency,
    scale_pence_to_currency,
)
from backtest.loaders.registry import FALLBACK_CHAINS
from backtest.runner import _create_market_engine, _MARKET_TO_SOURCE
from src.market_data import detect_source


class TestUKSourceDetection:
    def test_lse_routes_to_yahoo(self) -> None:
        assert detect_source("VOD.L") == "yahoo"
        assert detect_source("SHEL.L") == "yahoo"

    def test_other_lse_name_routes_to_yahoo(self) -> None:
        assert detect_source("BARC.L") == "yahoo"

    def test_lowercase_suffix_routes_to_yahoo(self) -> None:
        assert detect_source("vod.l") == "yahoo"


class TestUKMarketClassification:
    def test_lse_classifies_as_uk_equity(self) -> None:
        assert _detect_market("VOD.L") == "uk_equity"
        assert _detect_market("HSBA.L") == "uk_equity"

    def test_other_lse_name_classifies_as_uk_equity(self) -> None:
        assert _detect_market("BARC.L") == "uk_equity"

    def test_lowercase_classifies_as_uk_equity(self) -> None:
        assert _detect_market("shel.l") == "uk_equity"

    def test_submarket_detects_uk(self) -> None:
        assert _detect_submarket(["VOD.L", "SHEL.L"]) == "uk"
        assert _detect_submarket(["BARC.L"]) == "uk"

    def test_submarket_still_detects_other_markets(self) -> None:
        assert _detect_submarket(["AAPL.US"]) == "us"
        assert _detect_submarket(["TD.TO"]) == "ca"
        assert _detect_submarket(["700.HK"]) == "hk"


class TestUKSettlementContract:
    def test_lse_settles_in_gbp(self) -> None:
        # This is the supported post-loader contract. Source metadata gates out
        # USD/other/unknown .L lines before the engine sees them.
        assert code_currency("VOD.L") == "GBP"
        assert code_currency("SHEL.L") == "GBP"

    def test_other_lse_name_uses_gbp_contract(self) -> None:
        assert code_currency("BARC.L") == "GBP"

    def test_uk_market_cost_is_separate_from_cad(self) -> None:
        # The composite engine refuses mixed-currency sets; UK must not
        # collapse into the CAD or USD bucket.
        assert code_currency("VOD.L") != code_currency("TD.TO")
        assert code_currency("VOD.L") != code_currency("AAPL.US")


class TestUKFallbackChain:
    def test_uk_chain_prefers_yahoo(self) -> None:
        assert FALLBACK_CHAINS["uk_equity"] == ["yahoo", "yfinance", "local"]

    def test_uk_chain_is_a_member_of_global_routing(self) -> None:
        # get_market_data's _chain_for resolves any source in any chain;
        # yahoo must find uk_equity the same way it finds us_equity.
        assert "yahoo" in FALLBACK_CHAINS["uk_equity"]


class TestUKBacktestRouting:
    def test_lse_engine_is_global_equity(self) -> None:
        engine = _create_market_engine("yahoo", {"initial_cash": 100_000}, ["VOD.L"])
        assert isinstance(engine, GlobalEquityEngine)

    def test_lse_engine_gets_uk_submarket(self) -> None:
        engine = _create_market_engine("yahoo", {"initial_cash": 100_000}, ["VOD.L"])
        assert engine.market == "uk"

    def test_auto_source_lse_engine_is_global_equity(self) -> None:
        # source=auto resolves to yahoo via _MARKET_TO_SOURCE; the engine
        # must land on GlobalEquity, never CryptoEngine (the silent wrong
        # routing a uk_equity gap used to produce).
        assert _MARKET_TO_SOURCE["uk_equity"] == "yahoo"
        engine = _create_market_engine("auto", {"initial_cash": 100_000}, ["SHEL.L"])
        assert isinstance(engine, GlobalEquityEngine)
        assert engine.market == "uk"

    def test_other_lse_name_engine_is_global_equity(self) -> None:
        engine = _create_market_engine("auto", {"initial_cash": 100_000}, ["BARC.L"])
        assert isinstance(engine, GlobalEquityEngine)
        assert engine.market == "uk"


class TestGbpPenceNormalization:
    """GBp-quoted UK prices must normalize to GBP (÷100) at the loader."""

    def test_scale_scales_pence_when_currency_is_gbp_pence(self) -> None:
        frame = pd.DataFrame(
            {
                "open": [117.0],
                "high": [118.5],
                "low": [116.0],
                "close": [117.5],
                "volume": [1000],
            }
        )
        scaled, applied = scale_pence_to_currency(frame, "GBp")
        assert applied == "GBp→GBP (÷100)"
        assert scaled["close"].iloc[0] == 117.5 / 100
        # Volume is never part of the price normalization.
        assert scaled["volume"].iloc[0] == 1000

    def test_scale_leaves_other_currencies_untouched(self) -> None:
        frame = pd.DataFrame(
            {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [1]}
        )
        for currency in ("USD", "GBP", "EUR", "HKD", ""):
            scaled, applied = scale_pence_to_currency(frame, currency)
            assert applied == "none"
            assert scaled["close"].iloc[0] == 10.5

    def test_scale_empty_frame_is_noop(self) -> None:
        empty = pd.DataFrame()
        scaled, applied = scale_pence_to_currency(empty, "GBp")
        assert applied == "none"
        assert scaled.empty

    def test_lse_symbol_detection_does_not_claim_currency(self) -> None:
        assert is_lse_symbol("VOD.L")
        assert is_lse_symbol("BARC.L")
        assert is_lse_symbol("vod.l")
        assert not is_lse_symbol("AAPL.US")
        assert not is_lse_symbol("0700.HK")
        assert not is_lse_symbol("GC=F")

    @pytest.mark.parametrize("currency", ["USD", "EUR", "", None])
    def test_lse_contract_rejects_non_gbp_or_missing_currency(
        self, currency: str | None
    ) -> None:
        frame = pd.DataFrame(
            {"open": [1.0], "high": [1.1], "low": [0.9], "close": [1.05]}
        )

        with pytest.raises(ValueError, match="must be declared as GBP or GBp"):
            normalize_lse_quote_currency(frame, currency)
