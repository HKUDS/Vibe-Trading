"""India equity (NSE / BSE) backtest engine.

Models the Indian cash-equity **delivery** segment on daily bars. Intraday
(MIS) mechanics are not represented by a daily-bar engine, so the defaults
reflect overnight delivery rules; the knobs below let advanced users approximate
intraday behaviour.

Market rules:
  - T+1 settlement: shares bought today cannot be sold the same bar (delivery).
  - No short selling by default: retail cannot hold overnight short delivery
    positions. Set ``allow_short=True`` to model intraday (MIS) shorting.
  - Circuit bands: per-scrip price bands vary (2/5/10/20%); the exact band is
    not derivable from the symbol alone, so a single configurable band applies
    (default ±20%, the widest common band). Set ``price_limit`` to ``0`` /
    ``None`` to disable.
  - Lot size: 1 share for cash equity (F&O lot sizes are not modelled here).

Cost stack (delivery, discount-broker defaults; all config-driven). NOTE: SEBI/
exchange tariffs change periodically — verify ``in_*`` rates against a current
broker schedule before relying on absolute cost figures:
  - Brokerage: ₹0 (delivery on discount brokers)            [in_brokerage]
  - STT: 0.1% on buy + 0.1% on sell (bilateral)             [in_stt]
  - Exchange transaction charge: NSE ~0.00297% (bilateral)  [in_exchange_txn]
  - SEBI turnover fee: ₹10/crore = 0.0001% (bilateral)      [in_sebi_fee]
  - Stamp duty: 0.015% on buy only                          [in_stamp_duty]
  - GST: 18% on (brokerage + exchange txn + SEBI fee)       [in_gst]
  - DP charge: flat per-scrip on sell (default ₹0)          [in_dp_charge]
"""

from __future__ import annotations

import pandas as pd

from backtest.engines.base import BaseEngine


class IndiaEquityEngine(BaseEngine):
    """NSE / BSE cash-equity (delivery) engine.

    Config keys (all optional; defaults shown in the module docstring):
      - allow_short: bool, default False
      - price_limit: float fraction or None, default 0.20
      - slippage: default 0.001
      - in_brokerage / in_stt / in_exchange_txn / in_sebi_fee /
        in_stamp_duty / in_gst / in_dp_charge
    """

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}  # cash delivery: no leverage
        super().__init__(config)
        self.allow_short: bool = bool(config.get("allow_short", False))
        self.price_limit = config.get("price_limit", 0.20)
        self.slippage_rate: float = config.get("slippage", 0.001)
        # Cost stack
        self.in_brokerage: float = config.get("in_brokerage", 0.0)
        self.in_stt: float = config.get("in_stt", 0.001)
        self.in_exchange_txn: float = config.get("in_exchange_txn", 0.0000297)
        self.in_sebi_fee: float = config.get("in_sebi_fee", 0.000001)
        self.in_stamp_duty: float = config.get("in_stamp_duty", 0.00015)
        self.in_gst: float = config.get("in_gst", 0.18)
        self.in_dp_charge: float = config.get("in_dp_charge", 0.0)

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """India delivery execution rules.

        Args:
            symbol: NSE/BSE symbol (e.g. ``RELIANCE.NS``).
            direction: 1 (buy), -1 (short), 0 (sell/close).
            bar: Current bar (needs ``close`` + ``pre_close``/``pct_chg`` for
                circuit checks).

        Returns:
            True if the trade is allowed.
        """
        return india_can_execute(self, self, symbol, direction, bar)

    def round_size(self, raw_size: float, price: float) -> float:
        """Cash equity trades in 1-share lots."""
        return float(max(int(raw_size), 0))

    def calc_commission(
        self, size: float, price: float, _direction: int, is_open: bool
    ) -> float:
        """India delivery cost stack (see module docstring).

        ``_direction`` is unused — reserved for future asymmetric long/short
        (intraday MIS) schedules.
        """
        notional = size * price
        brokerage = notional * self.in_brokerage
        exchange_txn = notional * self.in_exchange_txn  # bilateral
        sebi_fee = notional * self.in_sebi_fee  # bilateral
        gst = (brokerage + exchange_txn + sebi_fee) * self.in_gst
        stt = notional * self.in_stt  # bilateral (delivery)
        comm = brokerage + exchange_txn + sebi_fee + gst + stt
        if is_open:
            comm += notional * self.in_stamp_duty  # stamp duty: buy-only
        else:
            comm += self.in_dp_charge  # DP charge: sell-only, flat
        return comm

    def apply_slippage(self, price: float, direction: int) -> float:
        """India slippage (configurable)."""
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


def _blocked_with_state(
    state, rules, symbol: str, direction: int, bar: pd.Series, limit: float
) -> bool:
    """Limit check reading base price from *state* and slippage from *rules*."""

    band = state.limit_band(symbol, bar, limit)
    if band is None:
        return False
    lower, upper = band
    pos = state.positions.get(symbol) if direction == 0 else None
    pos_dir = pos.direction if pos is not None else None
    fill_direction = -(pos_dir or 1) if direction == 0 else direction
    raw = bar.get("open", bar.get("close"))
    if raw is None or pd.isna(raw):
        return False
    price = float(raw)
    if price <= 0 and not getattr(rules, "allow_nonpositive_prices", False):
        return False
    fill = rules.apply_slippage(price, fill_direction)
    if fill is None or pd.isna(fill):
        return False
    tol = 1e-9 * max(abs(lower), abs(upper), 1.0)
    buying = direction == 1 or (direction == 0 and pos_dir == -1)
    if buying:
        return fill >= upper - tol
    return fill <= lower + tol


def india_can_execute(
    state, rules, symbol: str, direction: int, bar: pd.Series
) -> bool:
    """India delivery rules reading state from *state* and params from *rules*.

    Splitting the two lets :class:`CompositeEngine` enforce the same rules in
    a cross-market run: the composite owns the shared positions and close
    panel, while the India sub-engine supplies ``allow_short``/``price_limit``
    and slippage. A single-market run passes the same engine as both arguments.

    Args:
        state: Engine owning positions, close panel and bar cursor.
        rules: India engine supplying ``allow_short``, ``price_limit`` and
            slippage.
        symbol: NSE/BSE symbol.
        direction: 1 (buy), -1 (short), 0 (sell/close).
        bar: Current bar.

    Returns:
        True if the trade is allowed.
    """
    if direction == -1 and not getattr(rules, "allow_short", False):
        return False
    if direction == 0:
        pos = state.positions.get(symbol)
        if pos is not None:
            bar_date = _bar_date(bar)
            entry_date = (
                pos.entry_time.date() if hasattr(pos.entry_time, "date") else None
            )
            if (
                bar_date is not None
                and entry_date is not None
                and bar_date == entry_date
            ):
                return False
    limit = getattr(rules, "price_limit", 0.20)
    if limit and _blocked_with_state(
        state, rules, symbol, direction, bar, float(limit)
    ):
        return False
    return True
