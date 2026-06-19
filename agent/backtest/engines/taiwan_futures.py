"""Taiwan futures backtest engine."""

from __future__ import annotations

import re
from typing import Final

import pandas as pd

from backtest.engines.futures_base import FuturesBaseEngine

CONTRACTS: Final[dict[str, dict[str, float]]] = {
    "TXF": {"multiplier": 200, "margin_rate": 0.12},
    "MXF": {"multiplier": 50, "margin_rate": 0.12},
    "TE": {"multiplier": 4000, "margin_rate": 0.10},
    "TF": {"multiplier": 1000, "margin_rate": 0.10},
    "GBF": {"multiplier": 200000, "margin_rate": 0.03},
}
DEFAULT_MARGIN_RATE: Final[float] = 0.10
DEFAULT_MULTIPLIER: Final[float] = 1.0
DEFAULT_COMMISSION_PER_CONTRACT: Final[float] = 50.0
DEFAULT_PRICE_LIMIT: Final[float] = 0.10
DEFAULT_SLIPPAGE: Final[float] = 0.0005


def _extract_product(symbol: str) -> str:
    """Extract the TAIFEX product code from a symbol."""
    code = symbol.split(".")[0]
    match = re.match(r"([A-Za-z]+)", code)
    return match.group(1).upper() if match else code.upper()


class TaiwanFuturesEngine(FuturesBaseEngine):
    """TAIFEX futures engine with contract multipliers and margin rates."""

    def __init__(self, config: dict):
        leverage = config.get("leverage")
        if leverage is None:
            codes = config.get("codes", [])
            if codes:
                leverage = 1.0 / self.get_margin_rate(codes[0])
            else:
                leverage = 1.0 / DEFAULT_MARGIN_RATE
        config = {**config, "leverage": leverage}
        super().__init__(config)
        self.slippage_rate: float = config.get("slippage", DEFAULT_SLIPPAGE)
        self.commission_per_contract: float = config.get(
            "commission_per_contract",
            DEFAULT_COMMISSION_PER_CONTRACT,
        )
        self.price_limit: float = config.get("price_limit", DEFAULT_PRICE_LIMIT)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Allow T+0 Taiwan futures trading unless daily limits block it."""
        pct_chg = _calc_pct_change(bar)
        if pct_chg is None:
            return True
        if direction == 1 and pct_chg >= self.price_limit:
            return False
        if direction == -1 and pct_chg <= -self.price_limit:
            return False
        if direction == 0:
            position = self.positions.get(symbol)
            if position is not None:
                if position.direction == 1 and pct_chg <= -self.price_limit:
                    return False
                if position.direction == -1 and pct_chg >= self.price_limit:
                    return False
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """Round down to whole futures contracts."""
        return max(int(raw_size), 0)

    def calc_commission(self, size: float, price: float, _direction: int, is_open: bool) -> float:
        """Return fixed per-contract commission using the active symbol."""
        return self.calc_commission_for_symbol(self._active_symbol, size, price, is_open)

    def calc_commission_for_symbol(
        self,
        symbol: str,
        size: float,
        price: float,
        is_open: bool,
    ) -> float:
        """Return fixed one-side commission for a Taiwan futures symbol."""
        del symbol
        del price
        del is_open
        return size * self.commission_per_contract

    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply proportional Taiwan futures slippage."""
        return price * (1 + direction * self.slippage_rate)

    def get_contract_multiplier(self, symbol: str) -> float:
        """Return the configured multiplier for a Taiwan futures product."""
        product = _extract_product(symbol)
        contract = CONTRACTS.get(product)
        if contract is None:
            return DEFAULT_MULTIPLIER
        return contract["multiplier"]

    def get_margin_rate(self, symbol: str) -> float:
        """Return the configured margin rate for a Taiwan futures product."""
        product = _extract_product(symbol)
        contract = CONTRACTS.get(product)
        if contract is None:
            return DEFAULT_MARGIN_RATE
        return contract["margin_rate"]


def _calc_pct_change(bar: pd.Series) -> float | None:
    """Calculate fractional price change from futures bar data."""
    settle = bar.get("settle")
    pre_settle = bar.get("pre_settle")
    if settle is not None and pre_settle is not None and pre_settle > 0:
        return (float(settle) - float(pre_settle)) / float(pre_settle)

    close = bar.get("close")
    pre_close = bar.get("pre_close")
    if close is not None and pre_close is not None and pre_close > 0:
        return (float(close) - float(pre_close)) / float(pre_close)

    if "pct_chg" in bar.index:
        pct_chg = bar["pct_chg"]
        if pd.notna(pct_chg):
            return float(pct_chg) / 100.0
    return None
