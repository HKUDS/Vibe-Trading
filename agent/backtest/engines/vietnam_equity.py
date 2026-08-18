"""Vietnam equity (HOSE) backtest engine.

Models the Ho Chi Minh Stock Exchange cash-equity segment on daily bars.
Prices are assumed to be quoted in whole VND — the unit Yahoo's ``.VN`` series
uses — on a coarse tick grid (bước giá) that is modelled explicitly, because a
percentage-only model produces fill prices that cannot exist and mis-identifies
locked-band bars.

Market rules:
  - **Long-only.** Circular 120/2020 defines a covered-short framework, but
    routine cash-equity short selling is not operationally available, so
    ``allow_short=True`` is refused at construction rather than simulated.
    Short exposure in this market is expressed through index futures, which
    this engine does not cover.
  - Settlement is formally **T+2**. Since 2022 shares normally arrive before
    the afternoon session on T+2 and may be sold that afternoon, which is why
    the cycle is informally called T+1.5. A two-bar hold approximates that: a
    daily bar cannot represent the half-day boundary, so the sell is released
    on the second following session. No same-day round trip is possible.
    The hold runs from the **newest** opening fill, so scaling into a position
    re-arms it: the whole holding waits for the added lot rather than riding
    the first lot's clock. ``vn_settlement_bars`` exists for scenario testing
    and to absorb a future rule change; no shorter equity cycle is in force
    today.
  - Price band (biên độ dao động): ±7% on HOSE in normal sessions, measured
    from the reference price (giá tham chiếu — ordinarily the preceding
    session's close, though corporate actions and special sessions adjust it).
    First trading days, resumptions after long suspensions and certain
    ex-right sessions use ±20%; pass ``price_limit`` per run to model those.
    Set it to ``0`` / ``None`` to disable. HNX (±10%) and UPCOM (±15%) are not
    served by this engine's data path.
  - Round lot: 100 shares. HOSE also accepts odd-lot orders of 1-99 shares in
    a separate board that daily bars cannot represent, so odd-lot trading is
    deliberately not modelled and sub-lot orders round to zero.

Cost stack (all config-driven; verify against your broker's current schedule
before trusting absolute cost figures):
  - Brokerage: 0.15% per side, a common online retail rate   [vn_brokerage]
  - Personal income tax: 0.10% of gross sale proceeds, SELL side only, for
    individual investors                                     [vn_tax_sell]
    Levied on proceeds regardless of gain or loss, and unchanged by the 2026
    personal-income-tax overhaul: Nghị định 253/2026/NĐ-CP keeps listed
    securities at ``giá chuyển nhượng x 0,1%``. The 20% gain-based rate that
    took effect 2026-07-01 applies to chuyển nhượng vốn (unlisted capital
    transfers), not to exchange-traded shares. Other taxpayer classes are
    treated differently; override the key if you are not modelling an
    individual investor.

The band arithmetic follows the exchange's published procedure rather than a
naive ``base * 1.07``: the 7% amount is applied to the reference price and the
resulting bound is truncated onto the tick unit of the price it lands on, so
the ceiling (giá trần) and floor (giá sàn) are always tradeable prices.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from backtest.engines.base import BaseEngine

logger = logging.getLogger(__name__)

# HOSE quotation price units (bước giá) for shares and fund certificates:
# (lower bound inclusive, tick) in VND. Every coarser tick is an exact multiple
# of every finer one, which keeps the truncation arithmetic stable across band
# boundaries.
HOSE_TICK_TABLE: tuple[tuple[float, float], ...] = (
    (0.0, 10.0),
    (10_000.0, 50.0),
    (50_000.0, 100.0),
)

# Board lot on HOSE's continuous session.
HOSE_LOT_SIZE = 100

# Tick-grid comparisons only need to survive float representation error: every
# quantized price is a whole number of dong, so 1e-9 is far below one tick.
_PRICE_EPS = 1e-9

# Settlement lag in sessions. Under the T+2 cycle shares normally arrive
# before the afternoon session on T+2, so a buy at bar N releases at bar N+2.
_DEFAULT_SETTLEMENT_BARS = 2

# Fill actions that add quantity to a position. Both start a settlement clock:
# ``increase`` is a same-direction add that BaseEngine folds into the existing
# position without moving its entry index.
_OPENING_ACTIONS = frozenset({"open", "increase"})


def hose_tick_size(price: float) -> float:
    """Return the HOSE tick unit (bước giá) applying at *price*.

    Args:
        price: Price in VND.

    Returns:
        The tick unit in VND. Prices at or below zero take the finest tick.
    """
    tick = HOSE_TICK_TABLE[0][1]
    for lower, unit in HOSE_TICK_TABLE:
        if price >= lower:
            tick = unit
        else:
            break
    return tick


def hose_round_down(price: float) -> float:
    """Quantize *price* down onto the HOSE tick grid."""
    tick = hose_tick_size(price)
    return float(int((price + _PRICE_EPS) / tick) * tick)


def hose_round_up(price: float) -> float:
    """Quantize *price* up onto the HOSE tick grid."""
    tick = hose_tick_size(price)
    floored = hose_round_down(price)
    if abs(floored - price) < _PRICE_EPS:
        return floored
    return float(floored + tick)


def hose_price_limits(base_price: float, band: float) -> tuple[float, float]:
    """Return the (ceiling, floor) prices for *base_price* under *band*.

    Args:
        base_price: Reference price (giá tham chiếu) in VND.
        band: Band as a fraction, e.g. ``0.07`` for HOSE's ±7%.

    Returns:
        ``(giá trần, giá sàn)`` — both quantized onto the tick grid, the
        ceiling truncated down and the floor truncated up so that neither
        bound sits outside the legal band.
    """
    upper = hose_round_down(base_price * (1.0 + band))
    lower = hose_round_up(base_price * (1.0 - band))
    return upper, lower


def newest_opening_bar_idx(engine: BaseEngine, symbol: str) -> Optional[int]:
    """Bar index of the most recent opening fill for *symbol* on *engine*.

    ``Position.entry_bar_idx`` alone is not a sound settlement clock.
    :meth:`BaseEngine._execute_position_increase` folds a same-direction add
    into the open position — updating size and weighted entry price — but
    preserves the original entry index, so counting from it would release
    later-bought shares as soon as the *first* lot settled: a buy on N, an add
    on N+1 and a full sell on N+2 would pass while the added lot is one session
    old.

    The fill ledger is immutable evidence of when each opening delta actually
    executed, so the newest one bounds the hold. Scanning back from the newest
    fill stops at the first match, which belongs to the open position's own
    lifecycle whenever a position exists.

    Args:
        engine: Engine owning the fill ledger — the Vietnam engine in a
            single-market run, the composite in a cross-market one.
        symbol: Symbol whose settlement clock is being read.

    Returns:
        The bar index of the newest opening fill, or ``None`` when the ledger
        holds no opening fill for *symbol*.
    """
    for fill in reversed(getattr(engine, "fill_records", ()) or ()):
        if fill.symbol == symbol and fill.action in _OPENING_ACTIONS:
            return int(fill.bar_idx)
    return None


def hose_is_settled(
    engine: BaseEngine, symbol: str, settlement_bars: int,
) -> Optional[bool]:
    """Return whether *symbol*'s position on *engine* has cleared the hold.

    Settlement is counted in sessions rather than calendar days, because a
    Friday buy settles on Tuesday and a calendar-day comparison would either
    release it a session early or hold it a session late across the weekend.
    The newest opening fill and the engine's bar cursor give the exact count.

    The whole position is held until its newest lot settles, rather than only
    the unsettled quantity being blocked. ``BaseEngine`` keeps one compressed
    position per symbol with a weighted-average entry and no lot identity, so a
    partial reduction cannot be shown to consume settled shares only. Holding
    the position is the conservative reading: it can delay a sell that was
    partly available, but it can never sell stock that has not arrived.

    State is read from the passed engine rather than from ``self`` so that
    :class:`~backtest.engines.composite.CompositeEngine` — which owns the
    positions, fill ledger and bar cursor for every market in a cross-market
    run — applies this identical rule to its Vietnam leg instead of carrying a
    second implementation that could drift.

    Args:
        engine: Engine owning positions, fill ledger and bar cursor.
        symbol: Symbol whose position is being closed.
        settlement_bars: Sessions a buy is held before it may be sold.

    Returns:
        True when the position may be sold on this bar, False while it is still
        held, and ``None`` when the engine's state cannot answer — leaving the
        caller to decide how to report an unenforceable hold.
    """
    pos = engine.positions.get(symbol)
    if pos is None:
        return True

    entry_idx = newest_opening_bar_idx(engine, symbol)
    if entry_idx is None:
        # No fill evidence (a position injected directly, as unit tests do).
        entry_idx = getattr(pos, "entry_bar_idx", None)
    current_idx = getattr(engine, "_bar_idx", None)
    if entry_idx is None or current_idx is None:
        return None
    return (int(current_idx) - int(entry_idx)) >= int(settlement_bars)


def hose_base_price(
    state: BaseEngine, symbol: str, bar: pd.Series,
) -> Optional[float]:
    """Resolve the reference price (giá tham chiếu) for *symbol* on this bar.

    Both sources are strictly historical, so neither leaks the decision bar's
    own close into the pre-fill check:
      1. ``pre_close`` on the bar, when the data source supplies one.
      2. The previous row of the close panel that :class:`BaseEngine`
         pre-extracts for the run.

    An off-grid close is rounded onto the grid, since a reference price is
    always a tradeable price.

    Args:
        state: Engine holding the run's close panel and bar cursor.
        symbol: Symbol whose reference price is wanted.
        bar: Current bar.

    Returns:
        The reference price in VND, or ``None`` when no historical close is
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

    return None if candidate is None else hose_round_down(candidate)


def hose_can_execute(
    state: BaseEngine,
    rules: "VietnamEquityEngine",
    symbol: str,
    direction: int,
    bar: pd.Series,
) -> bool:
    """Apply the HOSE execution rules, reading state and rules separately.

    A single-market run passes the same engine as both arguments. A composite
    run cannot: it owns the positions, fill ledger, bar cursor and close panel
    for every market, while the rule parameters (band, tick-quantized slippage,
    settlement lag) live on the Vietnam sub-engine, which ``CompositeEngine``
    holds as a stateless rule book. Splitting the two lets the composite apply
    these rules in full rather than degrading to whichever of them a stateless
    sub-engine could still answer — which, for the band and the hold, is
    neither.

    Args:
        state: Engine owning positions, fill ledger, bar cursor, close panel.
        rules: Vietnam engine supplying band, slippage and settlement lag.
        symbol: HOSE symbol (e.g. ``VIC.VN``).
        direction: 1 (buy), -1 (short — always blocked), 0 (sell/close).
        bar: Current bar.

    Returns:
        True if the trade is allowed.
    """
    # 1. Short selling: structurally unavailable (see class docstring).
    if direction == -1:
        return False

    # 2. T+2 settlement: shares normally arrive before the afternoon of
    #    T+2, so the position cannot be sold before that session.
    if direction == 0 and not hose_settlement_ok(state, rules, symbol):
        return False

    # 3. Daily price band ±7% (disabled when falsy).
    if not rules.price_limit:
        return True

    base_price = hose_base_price(state, symbol, bar)
    if base_price is None:
        if not rules._limit_base_warned:
            rules._limit_base_warned = True
            logger.warning(
                "%s: no reference price available (no 'pre_close' column and "
                "no prior close panel row) — the HOSE ±%.0f%% band check is "
                "inactive for this run",
                symbol,
                float(rules.price_limit) * 100,
            )
        return True

    open_price = float(bar.get("open", bar.get("close", 0.0)) or 0.0)
    if open_price <= 0:
        return True  # order sizing rejects non-positive prices downstream

    upper, lower = hose_price_limits(base_price, float(rules.price_limit))
    fill_price = rules.apply_slippage(open_price, direction if direction else -1)
    if direction == 1 and fill_price >= upper - _PRICE_EPS:
        return False  # giá trần: no ask to buy from
    if direction == 0 and fill_price <= lower + _PRICE_EPS:
        return False  # giá sàn: no bid to sell into
    return True


def hose_settlement_ok(
    state: BaseEngine, rules: "VietnamEquityEngine", symbol: str,
) -> bool:
    """Return whether *symbol* may be sold, warning once if unenforceable.

    Args:
        state: Engine owning positions, fill ledger and bar cursor.
        rules: Vietnam engine supplying the settlement lag and warning latch.
        symbol: Symbol whose position is being closed.

    Returns:
        True when the position may be sold on this bar. An engine whose state
        cannot answer reports True and warns once, rather than blocking every
        exit for the rest of the run.
    """
    settled = hose_is_settled(state, symbol, rules.settlement_bars)
    if settled is None:
        if not rules._settlement_warned:
            rules._settlement_warned = True
            logger.warning(
                "%s: no bar cursor available — the HOSE settlement hold is "
                "inactive for this run",
                symbol,
            )
        return True
    return settled


class VietnamEquityEngine(BaseEngine):
    """HOSE cash-equity engine — long-only, T+2 settled.

    Config keys (all optional; defaults shown in the module docstring):
      - price_limit: float fraction or None, default 0.07
      - slippage: default 0.001
      - vn_brokerage / vn_tax_sell
      - vn_settlement_bars: sessions a buy is held before it may be sold,
        default 2 (approximates the T+2 cycle on daily bars)

    Raises:
        ValueError: When ``allow_short`` is truthy. Routine short selling is
            not operationally available in the Vietnamese cash market, so
            shorting is refused instead of being simulated. A cross-market
            composite run shares one config across its sub-engines, so pairing
            ``allow_short`` with a HOSE symbol fails the whole run —
            deliberately, since the alternative is a HOSE leg that silently
            never shorts while the rest of the book does.
    """

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}  # cash equity: no leverage
        super().__init__(config)
        if config.get("allow_short"):
            raise ValueError(
                "VietnamEquityEngine is long-only: routine short selling is not "
                "operationally available in the Vietnamese cash market, so a short "
                "book cannot be modelled. Remove 'allow_short' instead of running "
                "a mis-modelled short book."
            )
        self.price_limit = config.get("price_limit", 0.07)
        self.slippage_rate: float = config.get("slippage", 0.001)
        # Cost stack
        self.vn_brokerage: float = config.get("vn_brokerage", 0.0015)
        self.vn_tax_sell: float = config.get("vn_tax_sell", 0.001)
        self.settlement_bars: int = int(
            config.get("vn_settlement_bars", _DEFAULT_SETTLEMENT_BARS)
        )
        # One warning per engine when no reference price is derivable.
        self._limit_base_warned = False
        self._settlement_warned = False

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """HOSE execution rules.

        The band test compares the *prospective fill price* — this bar's open
        plus slippage, which is what :class:`BaseEngine` fills at — against
        bounds derived from the previous bar's close. Deriving the move from the
        current bar's close instead would be lookahead: ``BaseEngine`` calls this
        hook before the fill, and the decision bar's close is not known then.

        Args:
            symbol: HOSE symbol (e.g. ``VIC.VN``).
            direction: 1 (buy), -1 (short — always blocked), 0 (sell/close).
            bar: Current bar (needs ``open``; the reference price comes from
                ``pre_close`` when the source supplies it, else from the prior
                bar of the run's own close panel).

        Returns:
            True if the trade is allowed.
        """
        # This engine owns both the run state and the rule parameters. A
        # composite run splits them; see :func:`hose_can_execute`.
        return hose_can_execute(self, self, symbol, direction, bar)

    def _is_settled(self, symbol: str) -> bool:
        """Return whether *symbol*'s open position has cleared settlement.

        Args:
            symbol: Symbol whose position is being closed.

        Returns:
            True when the position may be sold on this bar.
        """
        return hose_settlement_ok(self, self, symbol)

    def _base_price(self, symbol: str, bar: pd.Series) -> Optional[float]:
        """Resolve this run's reference price (giá tham chiếu) for *symbol*.

        Args:
            symbol: Symbol whose reference price is wanted.
            bar: Current bar.

        Returns:
            The reference price in VND, or ``None`` when no historical close is
            reachable (first bar of a run, or a composite sub-engine).
        """
        return hose_base_price(self, symbol, bar)

    def round_size(self, raw_size: float, price: float) -> float:
        """Floor the order to whole 100-share board lots.

        HOSE accepts odd-lot orders of 1-99 shares on a separate board that a
        daily bar cannot represent, so odd-lot trading is deliberately not
        modelled: a sub-lot order rounds to zero rather than being filled at
        the continuous-session price.

        Args:
            raw_size: Unrounded share count.
            price: Fill price in VND (unused; lot size is price-independent).

        Returns:
            Share count as a whole multiple of the board lot.
        """
        lots = int(max(raw_size, 0) // HOSE_LOT_SIZE)
        return float(lots * HOSE_LOT_SIZE)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """Vietnam cost stack: bilateral brokerage + sell-side personal income tax.

        The tax follows the actual trade side rather than open/close: a closing
        trade on a long book is a sell (taxable). ``BaseEngine`` passes the
        position direction on both hooks, so the side is derivable even though
        this engine is long-only.

        Args:
            size: Share count.
            price: Fill price in VND.
            direction: 1 for a long book, -1 for a short book.
            is_open: True for the opening leg, False for the closing leg.

        Returns:
            Total cost in VND for this leg.
        """
        notional = size * price
        comm = notional * self.vn_brokerage
        is_sell = (direction < 0) if is_open else (direction > 0)
        if is_sell:
            comm += notional * self.vn_tax_sell
        return comm

    def apply_slippage(self, price: float, direction: int) -> float:
        """Vietnam slippage (configurable), quantized onto the HOSE tick grid.

        A slipped price is snapped away from the trader — buys up to the next
        valid ask, sells down to the next valid bid — because no fill can land
        between ticks.

        Args:
            price: Reference price in VND.
            direction: 1 to buy, -1 to sell.

        Returns:
            A valid HOSE price, never below one tick.
        """
        slipped = price * (1 + direction * self.slippage_rate)
        if direction > 0:
            return hose_round_up(slipped)
        return max(hose_round_down(slipped), hose_tick_size(slipped))
