"""Kenya equity (Nairobi Securities Exchange) backtest engine.

Models the NSE cash-equity Normal Board on daily bars, under the NSE Equity
Trading Rules as amended in July 2025 (in force from 8 August 2025). Prices are
quoted in Kenya shillings (KES) to two decimals on a price-tiered tick grid
that is modelled explicitly, so every fill lands on a price that can trade.

Market rules:
  - **Long-only.** The Capital Markets (Securities Lending, Borrowing and
    Short-selling) Regulations 2017 make covered shorting legal, but the CDSC
    lending platform has not concluded a single transaction since 2024, so a
    retail short book is not operationally available. ``allow_short=True`` is
    refused at construction rather than simulated.
  - Settlement is **T+3** (Rule 6.7.1). Shares bought on session N may be sold
    from session N+3. The CMA-approved day-trading window (a same-security,
    same-day, same-account round trip) is intraday and cannot be represented
    on a daily bar, so it is not modelled. The hold runs from the **newest**
    opening fill, so scaling into a position re-arms it. ``ke_settlement_bars``
    exists for scenario testing.
  - Price band: **±10%** per session (Rule 5.10.1), measured from the previous
    session's *average price* — the volume-weighted average, which is also
    the NSE's official closing price (Rules 7.6.1, 7.6.4). The engine takes the
    reference from ``pre_close`` when the source supplies it, else from the
    previous bar's close. A source whose close is the session VWAP (as the NSE
    daily price list is) therefore reproduces the exchange's reference exactly;
    a source whose close is a last-trade price only approximates it.
    The band is lifted on a listing's first session, after results or other
    material announcements, on the first ex-entitlement session, for
    securities untraded for more than three months, and for block trades
    (Rules 5.10.4-5.10.5, 7.7.2). A daily bar carries none of those flags, so
    pass ``price_limit`` per run to model such a session, or ``0`` / ``None`` to
    disable the band. The Recovery Board's ±5% band is not modelled.
  - Board lot: **1 share** (Rule 6.3.1, from 8 August 2025). Before that date the
    Normal Board traded in 100-share lots with a separate odd-lot board; set
    ``ke_lot_size=100`` to backtest the older regime faithfully.

Cost stack, per side (all config-driven; verify against your broker's current
schedule before trusting absolute cost figures):
  - Brokerage: 1.76% on trades of up to KES 100,000 of consideration, and
    1.50% above it — a negotiable ceiling that is the common quoted rate
                                                  [ke_brokerage_small / ke_brokerage,
                                                   tier at ke_brokerage_tier]
  - Statutory levies: 0.34% — NSE 0.12%, CMA 0.12%, CDSC 0.08%, Investor
    Compensation Fund 0.01%, CDSC Guarantee Fund 0.01%    [ke_levies]
  That is 2.10% per side on small tickets and 1.84% on large ones, identical on
  both sides. Two components are disputed in public sources and are left out of
  the default: some calculators apply a 0.08% CMA levy rather than 0.12%, and
  some add 16% VAT on brokerage, which a 2023 Tax Appeals Tribunal ruling
  treated as exempt. Override the keys to model either reading.
  Capital gains on NSE-listed shares are exempt from Kenya's 15% CGT, and
  dividend withholding tax falls on income rather than on trades, so neither is
  part of the transaction cost.

The band arithmetic keeps both bounds tradeable and inside the legal band: the
ceiling is truncated down and the floor rounded up onto the tick grid.
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import pandas as pd

from backtest.engines.base import BaseEngine
from backtest.engines.vietnam_equity import newest_opening_bar_idx

logger = logging.getLogger(__name__)

# NSE price spreads (Rule 5.9): (lower bound inclusive, tick) in KES. Every
# tier boundary is a whole multiple of the ticks on both sides of it, so
# truncating inside a tier can never cross into the tier below.
NSE_TICK_TABLE: tuple[tuple[float, float], ...] = (
    (0.0, 0.01),
    (5.0, 0.02),
    (10.0, 0.05),
    (50.0, 0.25),
    (500.0, 1.00),
    (1_000.0, 5.00),
)

# Board lot on the Normal Board since 8 August 2025 (Rule 6.3.1).
NSE_LOT_SIZE = 1

# Settlement lag in sessions: a buy on session N settles on N+3 (Rule 6.7.1).
_DEFAULT_SETTLEMENT_BARS = 3

# Per-side cost defaults (see module docstring).
_DEFAULT_BROKERAGE_SMALL = 0.0176
_DEFAULT_BROKERAGE = 0.015
_DEFAULT_BROKERAGE_TIER_KES = 100_000.0
_DEFAULT_LEVIES = 0.0034

# Prices are carried in integer hundredths of a shilling for the grid
# arithmetic. Every NSE tick is a whole number of cents, so working in cents
# removes binary float error from the floor/ceil steps; the epsilon only has to
# absorb the rounding of ``price * 100`` itself.
_CENTS_EPS = 1e-6
_PRICE_EPS = 1e-9


def nse_tick_size(price: float) -> float:
    """Return the NSE tick applying at *price*.

    Args:
        price: Price in KES.

    Returns:
        The tick in KES. Prices at or below zero take the finest tick.
    """
    tick = NSE_TICK_TABLE[0][1]
    for lower, unit in NSE_TICK_TABLE:
        if price >= lower - _PRICE_EPS:
            tick = unit
        else:
            break
    return tick


def _tick_cents(price: float) -> int:
    return int(round(nse_tick_size(price) * 100))


def nse_round_down(price: float) -> float:
    """Quantize *price* down onto the NSE tick grid."""
    step = _tick_cents(price)
    cents = math.floor(price * 100 + _CENTS_EPS)
    return (cents // step) * step / 100.0


def nse_round_up(price: float) -> float:
    """Quantize *price* up onto the NSE tick grid."""
    step = _tick_cents(price)
    cents = math.ceil(price * 100 - _CENTS_EPS)
    return -((-cents) // step) * step / 100.0


def nse_price_limits(base_price: float, band: float) -> tuple[float, float]:
    """Return the (ceiling, floor) prices for *base_price* under *band*.

    Args:
        base_price: Reference (previous average) price in KES.
        band: Band as a fraction, e.g. ``0.10`` for the Normal Board's ±10%.

    Returns:
        ``(ceiling, floor)`` quantized onto the tick grid — the ceiling
        truncated down and the floor rounded up, so neither bound sits outside
        the legal band.
    """
    upper = nse_round_down(base_price * (1.0 + band))
    lower = nse_round_up(base_price * (1.0 - band))
    return upper, lower


def nse_is_settled(
    engine: BaseEngine, symbol: str, settlement_bars: int,
) -> Optional[bool]:
    """Return whether *symbol*'s position on *engine* has cleared settlement.

    Settlement is counted in sessions, not calendar days, so a Friday buy is
    released on the following Wednesday rather than on Monday. The whole
    position is held until its newest lot settles: ``BaseEngine`` keeps one
    compressed position per symbol with no lot identity, so a partial sale
    cannot be shown to consume settled shares only. Holding it is the
    conservative reading — it can delay a sale that was partly available, but
    never sells stock that has not arrived.

    State is read from the passed engine so a cross-market
    :class:`~backtest.engines.composite.CompositeEngine` applies this same rule
    to its Kenya leg.

    Args:
        engine: Engine owning positions, fill ledger and bar cursor.
        symbol: Symbol whose position is being closed.
        settlement_bars: Sessions a buy is held before it may be sold.

    Returns:
        True when the position may be sold on this bar, False while held, and
        ``None`` when the engine's state cannot answer.
    """
    pos = engine.positions.get(symbol)
    if pos is None:
        return True

    entry_idx = newest_opening_bar_idx(engine, symbol)
    if entry_idx is None:
        entry_idx = getattr(pos, "entry_bar_idx", None)
    current_idx = getattr(engine, "_bar_idx", None)
    if entry_idx is None or current_idx is None:
        return None
    return (int(current_idx) - int(entry_idx)) >= int(settlement_bars)


def nse_base_price(
    state: BaseEngine, symbol: str, bar: pd.Series,
) -> Optional[float]:
    """Resolve the band reference price for *symbol* on this bar.

    Both sources are strictly historical, so neither leaks the decision bar's
    own close into the pre-fill check:
      1. ``pre_close`` on the bar, when the data source supplies one.
      2. The previous row of the close panel that :class:`BaseEngine`
         pre-extracts for the run.

    Args:
        state: Engine holding the run's close panel and bar cursor.
        symbol: Symbol whose reference price is wanted.
        bar: Current bar.

    Returns:
        The reference price in KES, or ``None`` when no historical close is
        reachable (first bar of a run, or a rule book with no panel).
    """
    candidate: Optional[float] = None
    if "pre_close" in bar.index:
        raw = bar["pre_close"]
        if pd.notna(raw) and float(raw) > 0:
            candidate = float(raw)

    if candidate is None:
        close_arr = getattr(state, "_close_arr", None)
        col = getattr(state, "_code_to_col", {}).get(symbol)
        row = getattr(state, "_bar_idx", 0) - 1
        if close_arr is not None and col is not None and row >= 0:
            raw = close_arr[row, col]
            if pd.notna(raw) and float(raw) > 0:
                candidate = float(raw)

    return candidate


def nse_settlement_ok(
    state: BaseEngine, rules: "KenyaEquityEngine", symbol: str,
) -> bool:
    """Return whether *symbol* may be sold, warning once if unenforceable."""
    settled = nse_is_settled(state, symbol, rules.settlement_bars)
    if settled is None:
        if not rules._settlement_warned:
            rules._settlement_warned = True
            logger.warning(
                "%s: no bar cursor available — the NSE T+%d settlement hold is "
                "inactive for this run",
                symbol,
                rules.settlement_bars,
            )
        return True
    return settled


def nse_can_execute(
    state: BaseEngine,
    rules: "KenyaEquityEngine",
    symbol: str,
    direction: int,
    bar: pd.Series,
) -> bool:
    """Apply the NSE execution rules, reading state and rules separately.

    A single-market run passes the same engine twice. A composite run passes
    itself as *state* (positions, fill ledger, bar cursor, close panel for
    every market) and the Kenya sub-engine as *rules* (band, slippage,
    settlement lag).

    Args:
        state: Engine owning positions, fill ledger, bar cursor, close panel.
        rules: Kenya engine supplying band, slippage and settlement lag.
        symbol: NSE symbol (e.g. ``SCOM.NR``).
        direction: 1 (buy), -1 (short — always blocked), 0 (sell/close).
        bar: Current bar.

    Returns:
        True if the trade is allowed.
    """
    if direction == -1:
        return False

    if direction == 0 and not nse_settlement_ok(state, rules, symbol):
        return False

    if not rules.price_limit:
        return True

    base_price = nse_base_price(state, symbol, bar)
    if base_price is None:
        if not rules._limit_base_warned:
            rules._limit_base_warned = True
            logger.warning(
                "%s: no reference price available (no 'pre_close' column and "
                "no prior close panel row) — the NSE ±%.0f%% band check is "
                "inactive for this run",
                symbol,
                float(rules.price_limit) * 100,
            )
        return True

    open_price = float(bar.get("open", bar.get("close", 0.0)) or 0.0)
    if open_price <= 0:
        return True  # order sizing rejects non-positive prices downstream

    upper, lower = nse_price_limits(base_price, float(rules.price_limit))
    fill_price = rules.apply_slippage(open_price, direction if direction else -1)
    # A counter opening at its ceiling is locked limit-up, and one at its
    # floor locked limit-down: the same conservative reading as the HOSE and
    # A-share engines, since a daily bar cannot show whether the other side
    # of the book had any size at the bound.
    if direction == 1 and fill_price >= upper - _PRICE_EPS:
        return False
    if direction == 0 and fill_price <= lower + _PRICE_EPS:
        return False
    return True


class KenyaEquityEngine(BaseEngine):
    """NSE (Kenya) cash-equity engine — long-only, T+3 settled, KES.

    Config keys (all optional; defaults shown in the module docstring):
      - price_limit: float fraction or None, default 0.10
      - slippage: default 0.002 — twice the HOSE default, because most NSE
        counters trade thinly and a market order walks the book further
      - ke_brokerage_small / ke_brokerage / ke_brokerage_tier
      - ke_levies
      - ke_lot_size: default 1 (the post-August-2025 rule); 100 for older
        periods
      - ke_settlement_bars: sessions a buy is held before it may be sold,
        default 3

    Raises:
        ValueError: When ``allow_short`` is truthy, or ``ke_lot_size`` is not a
            positive integer.
    """

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}  # cash equity: no leverage
        super().__init__(config)
        if config.get("allow_short"):
            raise ValueError(
                "KenyaEquityEngine is long-only: short selling is legal on the "
                "NSE but no securities-lending transaction has been concluded "
                "since 2024, so a retail short book cannot be modelled. Remove "
                "'allow_short' instead of running a mis-modelled short book."
            )
        self.price_limit = config.get("price_limit", 0.10)
        self.slippage_rate: float = config.get("slippage", 0.002)
        self.ke_brokerage_small: float = config.get(
            "ke_brokerage_small", _DEFAULT_BROKERAGE_SMALL
        )
        self.ke_brokerage: float = config.get("ke_brokerage", _DEFAULT_BROKERAGE)
        self.ke_brokerage_tier: float = float(
            config.get("ke_brokerage_tier", _DEFAULT_BROKERAGE_TIER_KES)
        )
        self.ke_levies: float = config.get("ke_levies", _DEFAULT_LEVIES)
        lot = config.get("ke_lot_size", NSE_LOT_SIZE)
        if not isinstance(lot, int) or isinstance(lot, bool) or lot < 1:
            raise ValueError(
                f"ke_lot_size must be a positive integer, got {lot!r}"
            )
        self.lot_size: int = lot
        self.settlement_bars: int = int(
            config.get("ke_settlement_bars", _DEFAULT_SETTLEMENT_BARS)
        )
        self._limit_base_warned = False
        self._settlement_warned = False

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """NSE execution rules.

        The band test compares the prospective fill price — this bar's open
        plus slippage — against bounds derived from the previous session, so
        the decision bar's own close never leaks into the pre-fill check.

        Args:
            symbol: NSE symbol (e.g. ``SCOM.NR``).
            direction: 1 (buy), -1 (short — always blocked), 0 (sell/close).
            bar: Current bar.

        Returns:
            True if the trade is allowed.
        """
        return nse_can_execute(self, self, symbol, direction, bar)

    def _is_settled(self, symbol: str) -> bool:
        return nse_settlement_ok(self, self, symbol)

    def _base_price(self, symbol: str, bar: pd.Series) -> Optional[float]:
        return nse_base_price(self, symbol, bar)

    def round_size(self, raw_size: float, price: float) -> float:
        """Floor the order to whole board lots (1 share by default).

        Args:
            raw_size: Unrounded share count.
            price: Fill price in KES (unused; lot size is price-independent).

        Returns:
            Share count as a whole multiple of the board lot.
        """
        lots = int(max(raw_size, 0) // self.lot_size)
        return float(lots * self.lot_size)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """NSE cost stack: tiered brokerage plus statutory levies, each side.

        The brokerage tier is chosen by the consideration of this leg, as a
        Kenyan contract note does: a leg of up to ``ke_brokerage_tier`` pays the
        small-ticket rate on its whole value, a larger leg the standard rate.

        Args:
            size: Share count.
            price: Fill price in KES.
            direction: 1 for a long book, -1 for a short book (unused — the
                cost stack is identical on both sides).
            is_open: True for the opening leg, False for the closing leg
                (unused, for the same reason).

        Returns:
            Total cost in KES for this leg.
        """
        notional = abs(size * price)
        brokerage = (
            self.ke_brokerage_small
            if notional <= self.ke_brokerage_tier
            else self.ke_brokerage
        )
        return notional * (brokerage + self.ke_levies)

    def apply_slippage(self, price: float, direction: int) -> float:
        """NSE slippage (configurable), quantized onto the NSE tick grid.

        A slipped price is snapped away from the trader — buys up to the next
        valid ask, sells down to the next valid bid.

        Args:
            price: Reference price in KES.
            direction: 1 to buy, -1 to sell.

        Returns:
            A valid NSE price, never below one tick.
        """
        slipped = price * (1 + direction * self.slippage_rate)
        if direction > 0:
            return nse_round_up(slipped)
        return max(nse_round_down(slipped), nse_tick_size(slipped))
