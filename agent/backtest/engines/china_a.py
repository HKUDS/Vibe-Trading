"""A-share (China mainland) backtest engine.

Market rules:
  - T+1: cannot sell shares bought today
  - No short selling for retail investors
  - Price limits: ±10% main board, ±20% ChiNext/STAR, ±5% ST
  - Minimum lot: 100 shares (odd lots can only be sold, not bought)
  - Commission: ¥5 minimum, 0.025% bilateral
  - Stamp tax: 0.05% sell-side only
  - Transfer fee: 0.001% bilateral
"""

from __future__ import annotations

import pandas as pd

from backtest.engines.base import BaseEngine


class ChinaAEngine(BaseEngine):
    """A-share market engine.

    Config keys:
      - commission_rate: default 0.00025 (万2.5)
      - commission_min: default 5.0 (RMB)
      - stamp_tax: default 0.0005 (万5, sell-only)
      - transfer_fee: default 0.00001 (万0.1)
      - slippage: default 0.001
    """

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}  # A-shares: no leverage
        super().__init__(config)
        self.commission_rate: float = config.get("commission_rate", 0.00025)
        self.commission_min: float = config.get("commission_min", 5.0)
        self.stamp_tax: float = config.get("stamp_tax", 0.0005)
        self.transfer_fee: float = config.get("transfer_fee", 0.00001)
        self.slippage_rate: float = config.get("slippage", 0.001)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """A-share execution rules.

        Args:
            symbol: Stock code (e.g. 000001.SZ).
            direction: 1 (buy), -1 (short — always blocked), 0 (sell/close).
            bar: Current bar (needs 'close', 'pre_close' or 'pct_chg').

        Returns:
            True if the trade is allowed.
        """
        # 1. No short selling
        if direction == -1:
            return False

        # 2. T+1: can't sell shares bought today
        if direction == 0:
            pos = self.positions.get(symbol)
            if pos is not None:
                bar_date = _bar_date(bar)
                entry_date = pos.entry_time.date() if hasattr(pos.entry_time, "date") else None
                if bar_date is not None and entry_date is not None and bar_date == entry_date:
                    return False

        # 3. Price limits, tested at execution time (see _blocked_by_limit).
        if _blocked_by_limit(self, symbol, direction, bar, _price_limit(symbol)):
            return False

        return True

    def round_size(self, raw_size: float, price: float) -> float:
        """Round down to 100-share lots."""
        return max(int(raw_size / 100) * 100, 0)

    def calc_commission(self, size: float, price: float, _direction: int, is_open: bool) -> float:
        """A-share fee structure: commission + stamp tax (sell) + transfer fee.

        ``_direction`` is unused today — reserved for future asymmetric
        long/short fee schedules (margin trading, securities lending).
        """
        notional = size * price
        # Commission: 万2.5, min ¥5
        comm = max(notional * self.commission_rate, self.commission_min)
        # Transfer fee: 万0.1 bilateral
        comm += notional * self.transfer_fee
        # Stamp tax: 万5 sell-only
        if not is_open:
            comm += notional * self.stamp_tax
        return comm

    def apply_slippage(self, price: float, direction: int) -> float:
        """A-share slippage (relatively small due to tick size)."""
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
    # Fall back to bar name (index timestamp)
    if hasattr(bar, "name") and hasattr(bar.name, "date"):
        return bar.name.date()
    return None


def _blocked_by_limit(
    engine,
    symbol: str,
    direction: int,
    bar: pd.Series,
    limit: float,
    position_direction: int | None = None,
) -> bool:
    """Whether a price-limit band blocks a fill on this bar.

    Shared by every engine with a daily band (A-share, India, China futures,
    global futures). The band comes from a base price the market knew before
    the order — ``pre_close``, else the prior bar's close — and is compared
    against the price the engine would actually fill at, which is this bar's
    open plus slippage.

    The earlier implementation derived the day's move from the CURRENT bar's
    close, which is lookahead and wrong in both directions: a name that opened
    locked but drifted back by the close was allowed to trade at the locked
    open, and a name that opened freely but closed limit-up was refused a fill
    it would have got.

    Args:
        engine: Engine instance (needs the BaseEngine band helpers).
        symbol: Symbol being traded.
        direction: 1 (buy / open long), -1 (sell short), 0 (close).
        bar: Current bar.
        limit: Band half-width as a fraction (0.1 for +/-10%).
        position_direction: For ``direction == 0``, the direction of the
            position being closed: 1 closes a long (a sell, blocked at the
            lower band), -1 closes a short (a buy, blocked at the upper band).
            Defaults to a long close, which is the cash-equity case.

    Returns:
        True when the band blocks the fill. False when it does not, and also
        when no historical base price is reachable — an unknown band must not
        fabricate a block.
    """
    band = engine.limit_band(symbol, bar, limit)
    if band is None:
        return False
    lower, upper = band
    # BaseEngine books a close with the OPPOSITE of the position's direction,
    # so slippage moves the price the other way. Checking the raw open here
    # would approve a fill that is then booked outside the band.
    fill_direction = -(position_direction or 1) if direction == 0 else direction
    fill = engine.prospective_fill_price(bar, fill_direction)
    if fill is None:
        return False

    # Relative tolerance: a fill within a rounding step of the band counts as
    # touching it, matching the old check's 0.1pp slack in percentage terms.
    tol = 1e-9 * max(abs(lower), abs(upper), 1.0)
    buying = direction == 1 or (direction == 0 and position_direction == -1)
    if buying:
        return fill >= upper - tol
    return fill <= lower + tol


def _price_limit(symbol: str) -> float:
    """Determine price limit based on board.

    Args:
        symbol: Stock code (e.g. 300001.SZ, 688001.SH, 000001.SZ).

    Returns:
        Limit as fraction (0.10, 0.20, or 0.05).
    """
    code = symbol.split(".")[0] if "." in symbol else symbol
    # ChiNext (300xxx) / STAR (688xxx): ±20%
    if code.startswith("300") or code.startswith("688"):
        return 0.20
    # ST stocks: ±5% (heuristic: can't fully detect from code alone)
    # Beijing exchange (8xxxxx): ±30% — simplified to 0.30
    if code.startswith("8") and len(code) == 6:
        return 0.30
    # Main board: ±10%
    return 0.10
