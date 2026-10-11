"""Brazil equity (B3) backtest engine.

Covers everything B3 lists under Yahoo's ``.SA`` suffix: shares (PETR4.SA),
units, ETFs (BOVA11.SA), FIIs (HGLG11.SA) and BDRs (AAPL34.SA). All settle in
BRL.

Market rules:
  - Same-session round trips are allowed (day trade). Settlement is D+2, which
    restricts cash, not the ability to sell shares bought today.
  - Short selling is allowed (via the B3 securities-lending facility, BTC).
    Set ``allow_short=False`` to model a long-only account.
  - No hard daily price limits: B3 uses auction tunnels that pause trading
    rather than blocking a price, so every bar is executable.
  - Whole shares. The standard lot is 100, but the odd-lot (fractional)
    market accepts single shares, so the default lot is 1. Set
    ``br_lot_size=100`` to trade only round lots.
  - Price increment R$0.01, rounded against the trader.

Cost stack (all config-driven). B3 tariffs change; verify against the current
B3 price list before relying on absolute figures:
  - B3 trading fee (emolumentos):   0.005% bilateral   [br_trading_fee]
  - B3 settlement fee (liquidação): 0.025% bilateral   [br_settlement_fee]
  - Broker commission: 0% (most retail brokers)        [br_brokerage_rate]
  - Fixed broker fee per order: R$0                     [br_brokerage_fixed]

Income tax (15% swing / 20% day trade on net gains, monthly R$20k sales
exemption for shares) is assessed on the investor's monthly result, not per
trade, so it is not charged here.
"""

from __future__ import annotations

import math

import pandas as pd

from backtest.engines.base import BaseEngine

_TICK = 0.01


class BrazilEquityEngine(BaseEngine):
    """B3 cash-equity engine.

    Config keys (all optional; defaults shown in the module docstring):
      - allow_short: bool, default True
      - slippage_br: default 0.0005
      - br_lot_size: default 1
      - br_trading_fee / br_settlement_fee / br_brokerage_rate /
        br_brokerage_fixed
    """

    def __init__(self, config: dict):
        config = {**config, "leverage": config.get("leverage", 1.0)}
        super().__init__(config)
        self.allow_short: bool = bool(config.get("allow_short", True))
        self.slippage_br: float = config.get("slippage_br", 0.0005)
        self.br_lot_size: int = max(int(config.get("br_lot_size", 1)), 1)
        self.br_trading_fee: float = config.get("br_trading_fee", 0.00005)
        self.br_settlement_fee: float = config.get("br_settlement_fee", 0.00025)
        self.br_brokerage_rate: float = config.get("br_brokerage_rate", 0.0)
        self.br_brokerage_fixed: float = config.get("br_brokerage_fixed", 0.0)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Every bar is executable; only opening a short can be disabled."""
        if direction == -1 and not self.allow_short:
            return False
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """Floor to whole lots (1 share by default, 100 for round lots)."""
        lot = self.br_lot_size
        return float(math.floor(max(raw_size, 0.0) / lot) * lot)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """B3 fees (bilateral) plus the configured broker commission."""
        notional = size * price
        if notional <= 0:
            return 0.0
        comm = notional * (self.br_trading_fee + self.br_settlement_fee)
        comm += notional * self.br_brokerage_rate
        comm += self.br_brokerage_fixed
        return comm

    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply slippage, then snap to the R$0.01 grid against the trader."""
        slipped = price * (1 + direction * self.slippage_br)
        units = slipped / _TICK
        if direction > 0:
            steps = math.ceil(units - 1e-9)
        elif direction < 0:
            steps = math.floor(units + 1e-9)
        else:
            steps = round(units)
        return round(steps * _TICK, 2)
