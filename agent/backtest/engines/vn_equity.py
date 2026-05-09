"""Vietnam equity (HOSE/HNX/UPCoM) backtest engine.

Market rules:
  - T+2 settlement: cannot sell shares bought today or yesterday
  - No retail short selling
  - Price bands: HOSE ±7%, HNX ±10%, UPCoM ±15%
  - Lot size: 100 shares (round-lot buys only; odd lots sellable)
  - Sell-side tax: 0.1% of notional
  - Broker commission: configurable bilateral, default 0.15%
"""

from __future__ import annotations

import re

import pandas as pd

from backtest.engines.base import BaseEngine


# Matches an explicit Vietnamese exchange suffix: .HOSE / .HNX / .UPCOM
_VN_EXCHANGE_RE = re.compile(r"\.(HOSE|HNX|UPCOM)$", re.I)


def _classify_vn_exchange(symbol: str) -> str:
    """Return 'HOSE', 'HNX', or 'UPCOM' for a VN ticker.

    Bare 3-letter tickers (no dot suffix) default to ``HOSE`` — the
    largest VN exchange and the home of the most-traded common stocks.
    """
    m = _VN_EXCHANGE_RE.search(symbol or "")
    if m:
        return m.group(1).upper()
    return "HOSE"


class VNEquityEngine(BaseEngine):
    """Vietnam equity market engine.

    Config keys:
      - commission_rate: default 0.0015 (0.15% bilateral)
      - sell_tax_rate: default 0.001 (0.1% sell-side only)
      - slippage: default 0.001
      - lot_size: default 100
      - t_plus: default 2 (T+2 settlement)
      - price_band_hose: default 0.07
      - price_band_hnx: default 0.10
      - price_band_upcom: default 0.15
    """

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}  # VN equity: no leverage
        super().__init__(config)
        self.commission_rate: float = config.get("commission_rate", 0.0015)
        self.sell_tax_rate: float = config.get("sell_tax_rate", 0.001)
        self.slippage_rate: float = config.get("slippage", 0.001)
        self.lot_size: int = int(config.get("lot_size", 100))
        self.t_plus: int = int(config.get("t_plus", 2))
        self.price_band_hose: float = config.get("price_band_hose", 0.07)
        self.price_band_hnx: float = config.get("price_band_hnx", 0.10)
        self.price_band_upcom: float = config.get("price_band_upcom", 0.15)

    def _price_band(self, symbol: str) -> float:
        """Return the configured daily price band for the symbol's exchange."""
        exch = _classify_vn_exchange(symbol)
        if exch == "HNX":
            return self.price_band_hnx
        if exch == "UPCOM":
            return self.price_band_upcom
        return self.price_band_hose

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Vietnam equity execution rules.

        Args:
            symbol: VN ticker (e.g. ``VNM.HOSE``, ``SHB.HNX``, ``VEA.UPCOM``).
            direction: 1 (buy), -1 (short — always blocked), 0 (sell/close).
            bar: Current bar (``close``, ``pre_close`` or ``pct_chg``).

        Returns:
            True if the trade is allowed.
        """
        # 1. No retail short selling
        if direction == -1:
            return False

        # 2. T+2: shares bought within the last `t_plus` calendar days
        #    cannot be sold yet. Day-zero buy and day-one hold are blocked;
        #    the position becomes sellable on day +t_plus.
        if direction == 0:
            pos = self.positions.get(symbol)
            if pos is not None:
                bar_date = _bar_date(bar)
                entry_date = (
                    pos.entry_time.date() if hasattr(pos.entry_time, "date") else None
                )
                if bar_date is not None and entry_date is not None:
                    delta_days = (bar_date - entry_date).days
                    if delta_days < self.t_plus:
                        return False

        # 3. Price band — block buys at/near limit-up, sells at/near limit-down
        pct_chg = _calc_pct_change(bar)
        if pct_chg is not None:
            band = self._price_band(symbol)
            if direction == 1 and pct_chg >= band - 0.001:
                return False  # limit-up: can't buy
            if direction == 0 and pct_chg <= -band + 0.001:
                return False  # limit-down: can't sell

        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """Round down to lot-size shares (default 100).

        Buys are round-lot only. Odd-lot sells are technically allowed in
        VN but the engine routes everything through this rounder for
        simplicity; partial-sell odd-lot handling is out of scope.
        """
        return max(int(raw_size / self.lot_size) * self.lot_size, 0)

    def calc_commission(
        self, size: float, price: float, direction: int, is_open: bool,
    ) -> float:
        """VN fee structure: bilateral broker commission + sell-side tax."""
        notional = abs(size) * price
        commission = notional * self.commission_rate
        # 0.1% transfer/income tax applies to sell-side only (direction == 0)
        tax = notional * self.sell_tax_rate if direction == 0 else 0.0
        return commission + tax

    def apply_slippage(self, price: float, direction: int) -> float:
        """Apply symmetric slippage (HOSE tick sizes are reasonably tight)."""
        return price * (1 + direction * self.slippage_rate)


# ── Helpers ──


def _bar_date(bar: pd.Series):
    """Extract date from bar, handling various column names."""
    for col in ("trade_date", "date"):
        if col in bar.index:
            val = bar[col]
            if hasattr(val, "date"):
                return val.date()
            try:
                return pd.Timestamp(val).date()
            except Exception:
                pass
    if hasattr(bar, "name") and hasattr(bar.name, "date"):
        return bar.name.date()
    return None


def _calc_pct_change(bar: pd.Series):
    """Calculate price change percentage from bar data."""
    if "pct_chg" in bar.index:
        val = bar["pct_chg"]
        if pd.notna(val):
            return float(val) / 100.0  # tushare-style pct_chg in percentage points

    close = bar.get("close")
    pre_close = bar.get("pre_close")
    if close is not None and pre_close is not None and pre_close > 0:
        return (float(close) - float(pre_close)) / float(pre_close)
    return None
