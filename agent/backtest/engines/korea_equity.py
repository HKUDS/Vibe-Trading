"""Korea equity (KRX: KOSPI / KOSDAQ) backtest engine.

Models the Korean cash-equity segment on daily bars.

Market rules:
  - Same-day round trips are allowed: shares bought today CAN be sold the same
    day (unlike China A-share T+1 or India delivery), so there is no same-bar
    sell block.
  - No short selling by default: retail short selling is heavily restricted
    on KRX. Set ``allow_short=True`` to model institutional shorting.
  - Price limit: ±30% daily band on both KOSPI and KOSDAQ (since June 2015).
    Set ``price_limit`` to ``0`` / ``None`` to disable.
  - Lot size: 1 share (KRX abolished the 10-share odd-lot rule in 2014).

Cost stack (discount-broker defaults; all config-driven). NOTE: Korean
securities transaction tax rates are revised periodically (they stepped down
2023 -> 2025) — verify ``kr_*`` rates against the current schedule before
relying on absolute cost figures:
  - Brokerage: 0.015% per side (typical online rate)        [kr_brokerage]
  - Securities transaction tax (incl. special rural-development surtax
    where applicable): 0.15% on SELL only, KOSPI and KOSDAQ
    both effectively 0.15% as of 2025                       [kr_tax_sell]
"""

from __future__ import annotations

import pandas as pd

from backtest.engines.base import BaseEngine
from backtest.engines.china_a import _calc_pct_change


class KoreaEquityEngine(BaseEngine):
    """KRX (KOSPI / KOSDAQ) cash-equity engine.

    Config keys (all optional; defaults shown in the module docstring):
      - allow_short: bool, default False
      - price_limit: float fraction or None, default 0.30
      - slippage: default 0.001
      - kr_brokerage / kr_tax_sell
    """

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}  # cash equity: no leverage
        super().__init__(config)
        self.allow_short: bool = bool(config.get("allow_short", False))
        self.price_limit = config.get("price_limit", 0.30)
        self.slippage_rate: float = config.get("slippage", 0.001)
        # Cost stack
        self.kr_brokerage: float = config.get("kr_brokerage", 0.00015)
        self.kr_tax_sell: float = config.get("kr_tax_sell", 0.0015)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """KRX execution rules.

        Args:
            symbol: KRX symbol (e.g. ``005930.KS``, ``247540.KQ``).
            direction: 1 (buy), -1 (short), 0 (sell/close).
            bar: Current bar (needs ``close`` + ``pre_close``/``pct_chg`` for
                price-limit checks).

        Returns:
            True if the trade is allowed.
        """
        # 1. Short selling: blocked unless explicitly enabled.
        if direction == -1 and not self.allow_short:
            return False

        # 2. Same-day sell is allowed on KRX — no T+1 interception.

        # 3. Daily price limit ±30% (disabled when falsy).
        if self.price_limit:
            pct_chg = _calc_pct_change(bar)
            if pct_chg is not None:
                limit = float(self.price_limit)
                if direction == 1 and pct_chg >= limit - 0.001:
                    return False  # limit-up (상한가): can't buy
                if direction == 0 and pct_chg <= -limit + 0.001:
                    return False  # limit-down (하한가): can't sell
        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """Cash equity trades in 1-share lots."""
        return float(max(int(raw_size), 0))

    def calc_commission(self, size: float, price: float, _direction: int, is_open: bool) -> float:
        """Korea cost stack: bilateral brokerage + sell-only transaction tax."""
        notional = size * price
        comm = notional * self.kr_brokerage
        if not is_open:
            comm += notional * self.kr_tax_sell
        return comm

    def apply_slippage(self, price: float, direction: int) -> float:
        """Korea slippage (configurable)."""
        return price * (1 + direction * self.slippage_rate)
