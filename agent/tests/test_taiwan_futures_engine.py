"""Tests for TaiwanFuturesEngine market rules."""

from __future__ import annotations

import pandas as pd
import pytest

from backtest.runner import _create_market_engine


def _make_bar(
    close: float = 22000.0,
    pre_close: float | None = None,
    settle: float | None = None,
    pre_settle: float | None = None,
) -> pd.Series:
    data: dict[str, float] = {"close": close, "open": close}
    if pre_close is not None:
        data["pre_close"] = pre_close
    if settle is not None:
        data["settle"] = settle
    if pre_settle is not None:
        data["pre_settle"] = pre_settle
    return pd.Series(data)


def _make_engine(**overrides):
    from backtest.engines.taiwan_futures import TaiwanFuturesEngine

    config = {"initial_cash": 1_000_000, "codes": ["TXF.TAIFEX"]}
    config.update(overrides)
    return TaiwanFuturesEngine(config)


class TestTaiwanFuturesExecutionRules:
    def test_long_and_short_allowed(self) -> None:
        engine = _make_engine()

        assert engine.can_execute("TXF.TAIFEX", 1, _make_bar()) is True
        assert engine.can_execute("TXF.TAIFEX", -1, _make_bar()) is True

    def test_limit_up_blocks_long(self) -> None:
        engine = _make_engine()

        assert engine.can_execute("TXF.TAIFEX", 1, _make_bar(close=24200.0, pre_close=22000.0)) is False


class TestTaiwanFuturesRoundSize:
    def test_rounds_down_to_integer_contracts(self) -> None:
        engine = _make_engine()

        assert engine.round_size(2.8, 22000.0) == 2
        assert engine.round_size(0.9, 22000.0) == 0


class TestTaiwanFuturesContractSpecs:
    @pytest.mark.parametrize(
        ("symbol", "expected_multiplier", "expected_margin_rate"),
        [
            ("TXF.TAIFEX", 200, 0.12),
            ("MXF.TAIFEX", 50, 0.12),
            ("TE.TAIFEX", 4000, 0.10),
            ("TF.TAIFEX", 1000, 0.10),
            ("GBF.TAIFEX", 200000, 0.03),
        ],
    )
    def test_multiplier_and_margin_rate(
        self,
        symbol: str,
        expected_multiplier: int,
        expected_margin_rate: float,
    ) -> None:
        engine = _make_engine()

        assert engine.get_contract_multiplier(symbol) == expected_multiplier
        assert engine.get_margin_rate(symbol) == expected_margin_rate

    def test_txf_leverage_derived_from_margin_rate(self) -> None:
        engine = _make_engine(codes=["TXF.TAIFEX"])

        assert engine.default_leverage == pytest.approx(1 / 0.12)


class TestTaiwanFuturesCommission:
    def test_default_commission_per_contract(self) -> None:
        engine = _make_engine()
        engine._active_symbol = "TXF.TAIFEX"

        assert engine.calc_commission(2, 22000.0, 1, is_open=True) == pytest.approx(100.0)


class TestTaiwanFuturesRunnerInstantiation:
    def test_runner_creates_taiwan_futures_engine(self) -> None:
        from backtest.engines.taiwan_futures import TaiwanFuturesEngine

        engine = _create_market_engine("shioaji", {"initial_cash": 100_000}, ["TXF.TAIFEX"])

        assert isinstance(engine, TaiwanFuturesEngine)
