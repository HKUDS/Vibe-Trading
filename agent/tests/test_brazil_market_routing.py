"""Brazil (B3 .SA) routing and execution rules.

Deterministic, no network: pins the routing contract and the B3 cost model.
"""

from __future__ import annotations

import pytest

from backtest.benchmark import MARKET_BENCHMARKS, _infer_market
from backtest.engines._market_hooks import _detect_market, code_currency
from backtest.engines.brazil_equity import BrazilEquityEngine
from backtest.engines.composite import _build_rule_engines
from backtest.loaders.base import normalize_declared_quote_currency
from backtest.loaders.registry import FALLBACK_CHAINS, price_caliber
from backtest.loaders.yahoo_loader import _is_supported as yahoo_is_supported
from backtest.loaders.yfinance_loader import _to_yfinance_symbol
from backtest.runner import _create_market_engine, _detect_source
from src.market_data import detect_source
from src.tools.stock_profile_tool import _market_for


@pytest.mark.parametrize("symbol", ["PETR4.SA", "VALE3.SA", "BOVA11.SA", "HGLG11.SA", "AAPL34.SA", "PETR4F.SA"])
def test_sa_symbols_share_one_market_data_contract(symbol: str) -> None:
    assert _detect_market(symbol) == "br_equity"
    assert code_currency(symbol) == "BRL"
    assert detect_source(symbol) == "yahoo"
    assert _detect_source(symbol) == "yahoo"
    assert yahoo_is_supported(symbol)
    assert _to_yfinance_symbol(symbol) == symbol
    assert _market_for(symbol) == "br"


def test_brazil_chain_is_yahoo_then_official_files() -> None:
    assert FALLBACK_CHAINS["br_equity"] == ["yahoo", "yfinance", "b3_cotahist", "local"]
    assert price_caliber("b3_cotahist", "br_equity") == "raw"


def test_brazil_benchmark_is_ibovespa_etf() -> None:
    assert _infer_market(["PETR4.SA"], "yahoo") == "br_equity"
    assert MARKET_BENCHMARKS["br_equity"] == "BOVA11.SA"


def test_sa_lines_must_be_declared_in_brl() -> None:
    import pandas as pd

    frame = pd.DataFrame({"close": [10.0]})
    assert normalize_declared_quote_currency(frame, "PETR4.SA", "BRL").attrs["quote_currency"] == "BRL"
    with pytest.raises(ValueError, match="BRL"):
        normalize_declared_quote_currency(frame, "PETR4.SA", "USD")


def test_runner_and_composite_use_the_b3_engine() -> None:
    assert isinstance(_create_market_engine("yahoo", {}, ["PETR4.SA"]), BrazilEquityEngine)
    engines = _build_rule_engines({}, ["PETR4.SA", "VALE3.SA"])
    assert isinstance(engines["br_equity"], BrazilEquityEngine)


class TestBrazilEquityEngine:
    def test_costs_are_b3_fees_bilateral(self) -> None:
        engine = BrazilEquityEngine({})
        # 0.005% trading + 0.025% settlement on R$10,000.
        assert engine.calc_commission(100, 100.0, 1, True) == pytest.approx(3.0)
        assert engine.calc_commission(100, 100.0, 1, False) == pytest.approx(3.0)
        assert engine.calc_commission(0, 100.0, 1, True) == 0.0

    def test_broker_commission_is_configurable(self) -> None:
        engine = BrazilEquityEngine({"br_brokerage_rate": 0.001, "br_brokerage_fixed": 4.9})
        assert engine.calc_commission(100, 100.0, 1, True) == pytest.approx(3.0 + 10.0 + 4.9)

    def test_lots_default_to_one_share_or_round_lots(self) -> None:
        assert BrazilEquityEngine({}).round_size(157.9, 30.0) == 157.0
        assert BrazilEquityEngine({"br_lot_size": 100}).round_size(157.9, 30.0) == 100.0
        assert BrazilEquityEngine({}).round_size(-3, 30.0) == 0.0

    def test_slippage_snaps_to_cent_against_trader(self) -> None:
        engine = BrazilEquityEngine({"slippage_br": 0.0})
        assert engine.apply_slippage(10.001, 1) == 10.01
        assert engine.apply_slippage(10.009, -1) == 10.0
        engine = BrazilEquityEngine({"slippage_br": 0.001})
        assert engine.apply_slippage(10.0, 1) == 10.01
        assert engine.apply_slippage(10.0, -1) == 9.99

    def test_short_selling_can_be_disabled(self) -> None:
        import pandas as pd

        bar = pd.Series({"close": 10.0})
        assert BrazilEquityEngine({}).can_execute("PETR4.SA", -1, bar)
        assert not BrazilEquityEngine({"allow_short": False}).can_execute("PETR4.SA", -1, bar)
        assert BrazilEquityEngine({"allow_short": False}).can_execute("PETR4.SA", 1, bar)
