"""Vietnam equity (HOSE, HNX, UPCoM) backtest engine.

Models Vietnam's three cash-equity venues on daily bars: the Ho Chi Minh
Stock Exchange (``VIC.VN``, Yahoo's suffix), the Hanoi Stock Exchange
(``PVS.HNX``) and the UPCoM market (``ACV.UPCOM``). Yahoo lists HOSE only, so
HNX and UPCoM bars come from the user's ``local`` files. Prices are assumed to
be quoted in whole VND — the unit Yahoo's ``.VN`` series uses — on a coarse
tick grid (bước giá) that is modelled explicitly, because a percentage-only
model produces fill prices that cannot exist and mis-identifies locked-band
bars.

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
  - Price band (biên độ dao động) in normal sessions: ±7% on HOSE, ±10% on
    HNX and ±15% on UPCoM, measured from the reference price (giá tham chiếu
    — ordinarily the preceding session's close, though corporate actions and
    special sessions adjust it). UPCoM's reference is the preceding session's
    volume-weighted average price, not its close: a bar's ``pre_close`` is
    used when the source supplies the reference, otherwise the close stands
    in for it. First trading days, resumptions after long suspensions and
    certain ex-right sessions use wider bands (±20% on HOSE, ±30% on HNX,
    ±40% on UPCoM); pass ``price_limit`` per run to apply one band to every
    symbol. Set it to ``0`` / ``None`` to disable.
  - A name that moved exchange (UPCoM or HNX to HOSE, or the other way)
    traded under its old exchange's band and tick grid until the move, but its
    suffix names only the exchange it lists on now. ``vn_exchange_history``
    gives the dated listing; the first session after a move lists the shares
    on the new exchange afresh, so it takes that exchange's first-day band.
  - Tick: 10/50/100 VND by price on HOSE; a flat 100 VND on HNX and UPCoM.
    Where the band is narrower than one tick (a low-priced HNX or UPCoM
    share), the rounded ceiling or floor would equal the reference price;
    the exchange then sets it one tick away, so the stock can still move.
  - Round lot: 100 shares. The exchanges also accept odd-lot orders of 1-99
    shares in a separate board that daily bars cannot represent, so odd-lot
    trading is deliberately not modelled and sub-lot orders round to zero.

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
naive ``base * 1.07``: the band amount (7% on HOSE) is applied to the reference
price and the resulting bound is truncated onto the tick unit of the price it
lands on, so the ceiling (giá trần) and floor (giá sàn) are always tradeable
prices.
"""

from __future__ import annotations

import bisect
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

# HNX and UPCoM quote shares on one 100-VND tick at every price.
HNX_UPCOM_TICK_TABLE: tuple[tuple[float, float], ...] = ((0.0, 100.0),)

_TICK_TABLES: dict[str, tuple[tuple[float, float], ...]] = {
    "HOSE": HOSE_TICK_TABLE,
    "HNX": HNX_UPCOM_TICK_TABLE,
    "UPCOM": HNX_UPCOM_TICK_TABLE,
}

# Project symbol suffix -> exchange. ``.VN`` is Yahoo's suffix, and Yahoo
# lists HOSE only; HNX and UPCoM symbols carry their exchange's name.
VN_EXCHANGE_BY_SUFFIX: dict[str, str] = {
    ".VN": "HOSE",
    ".HNX": "HNX",
    ".UPCOM": "UPCOM",
}

# Normal-session daily band (biên độ dao động) per exchange.
VN_PRICE_BANDS: dict[str, float] = {"HOSE": 0.07, "HNX": 0.10, "UPCOM": 0.15}

# First-day band per exchange: a new listing, a resumption after a long halt,
# and the first session after a move to another exchange.
VN_FIRST_DAY_BANDS: dict[str, float] = {"HOSE": 0.20, "HNX": 0.30, "UPCOM": 0.40}

# Exchange names accepted in ``vn_exchange_history``. Vietnamese data sources
# label HOSE "HSX" as often as "HOSE".
_EXCHANGE_NAMES: dict[str, str] = {
    "HOSE": "HOSE",
    "HSX": "HOSE",
    "HNX": "HNX",
    "UPCOM": "UPCOM",
}

# Board lot on the continuous session, the same on all three exchanges.
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


def vn_exchange(symbol: str) -> str:
    """Return the exchange *symbol* lists on: ``HOSE``, ``HNX`` or ``UPCOM``.

    Args:
        symbol: Project symbol, e.g. ``VIC.VN``, ``PVS.HNX`` or ``ACV.UPCOM``.

    Returns:
        The exchange name. A symbol with no Vietnamese suffix (the engine
        driven directly, as unit tests do) reads as HOSE, the engine's
        original venue.
    """
    upper = (symbol or "").strip().upper()
    for suffix, exchange in VN_EXCHANGE_BY_SUFFIX.items():
        if upper.endswith(suffix):
            return exchange
    return "HOSE"


def _session_day(ts: object) -> Optional[pd.Timestamp]:
    """Return *ts* as a tz-naive midnight timestamp, or ``None`` for no date.

    A tz-aware bar keeps its local wall-clock date: converting a Vietnamese
    session stamped at local midnight to UTC would move it to the day before.
    """
    if ts is None:
        return None
    day = pd.Timestamp(ts)
    if pd.isna(day):
        return None
    if day.tzinfo is not None:
        day = day.tz_localize(None)
    return day.normalize()


def parse_exchange_history(
    history: object,
) -> dict[str, tuple[tuple[pd.Timestamp, ...], tuple[str, ...]]]:
    """Validate the ``vn_exchange_history`` config value.

    Args:
        history: ``{symbol: {date: exchange}}``, keyed by the run's codes,
            where each date is the first session on that exchange (the
            earliest only has to precede the data), e.g.
            ``{"ACB.VN": {"2018-01-02": "HNX", "2020-12-09": "HOSE"}}``.
            Exchanges are ``HOSE`` (or ``HSX``), ``HNX`` and ``UPCOM``, in any
            letter case. ``None`` or an empty mapping means no history.

    Returns:
        Per symbol, its dates in ascending order and the exchange from each.

    Raises:
        ValueError: When the value is not a mapping of non-empty mappings, a
            date does not parse, an exchange is unknown, or two entries fall
            on the same day.
    """
    if not history:
        return {}
    if not isinstance(history, dict):
        raise ValueError(
            "vn_exchange_history must map each symbol to {date: exchange}, "
            f"got {type(history).__name__}"
        )
    parsed: dict[str, tuple[tuple[pd.Timestamp, ...], tuple[str, ...]]] = {}
    for symbol, listings in history.items():
        if not isinstance(listings, dict) or not listings:
            raise ValueError(
                f"vn_exchange_history[{symbol!r}] must be a non-empty "
                "{date: exchange} mapping"
            )
        by_day: dict[pd.Timestamp, str] = {}
        for raw_day, raw_exchange in listings.items():
            try:
                day = _session_day(raw_day)
            except (TypeError, ValueError):
                day = None
            if day is None:
                raise ValueError(
                    f"vn_exchange_history[{symbol!r}]: {raw_day!r} is not a date"
                )
            exchange = _EXCHANGE_NAMES.get(str(raw_exchange).strip().upper())
            if exchange is None:
                raise ValueError(
                    f"vn_exchange_history[{symbol!r}][{raw_day!r}]: unknown "
                    f"exchange {raw_exchange!r}; use HOSE, HNX or UPCOM"
                )
            if day in by_day:
                raise ValueError(
                    f"vn_exchange_history[{symbol!r}]: two entries on {day.date()}"
                )
            by_day[day] = exchange
        days = tuple(sorted(by_day))
        parsed[str(symbol)] = (days, tuple(by_day[d] for d in days))
    return parsed


def vn_tick_size(price: float, exchange: str = "HOSE") -> float:
    """Return the tick unit (bước giá) applying at *price* on *exchange*.

    Args:
        price: Price in VND.
        exchange: ``HOSE``, ``HNX`` or ``UPCOM``.

    Returns:
        The tick unit in VND. Prices at or below zero take the finest tick.
    """
    table = _TICK_TABLES[exchange]
    tick = table[0][1]
    for lower, unit in table:
        if price >= lower:
            tick = unit
        else:
            break
    return tick


def vn_round_down(price: float, exchange: str = "HOSE") -> float:
    """Quantize *price* down onto *exchange*'s tick grid."""
    tick = vn_tick_size(price, exchange)
    return float(int((price + _PRICE_EPS) / tick) * tick)


def vn_round_up(price: float, exchange: str = "HOSE") -> float:
    """Quantize *price* up onto *exchange*'s tick grid."""
    tick = vn_tick_size(price, exchange)
    floored = vn_round_down(price, exchange)
    if abs(floored - price) < _PRICE_EPS:
        return floored
    return float(floored + tick)


def vn_price_limits(
    base_price: float, band: float, exchange: str = "HOSE"
) -> tuple[float, float]:
    """Return the (ceiling, floor) prices for *base_price* under *band*.

    Args:
        base_price: Reference price (giá tham chiếu) in VND.
        band: Band as a fraction, e.g. ``0.07`` for HOSE's ±7%.
        exchange: ``HOSE``, ``HNX`` or ``UPCOM``; selects the tick grid.

    Returns:
        ``(giá trần, giá sàn)`` — both quantized onto the tick grid, the
        ceiling truncated down and the floor truncated up so that neither
        bound sits outside the legal band. When the band is narrower than one
        tick, rounding would put a bound on the reference price itself; the
        exchange then sets it one tick away, and so does this function.
    """
    upper = vn_round_down(base_price * (1.0 + band), exchange)
    lower = vn_round_up(base_price * (1.0 - band), exchange)
    tick = vn_tick_size(base_price, exchange)
    if upper <= base_price + _PRICE_EPS:
        upper = base_price + tick
    if lower >= base_price - _PRICE_EPS and base_price - tick > _PRICE_EPS:
        lower = base_price - tick
    return upper, lower


# HOSE-only spellings from before HNX and UPCoM were modelled; HOSE is the
# default exchange of the functions they name.
hose_tick_size = vn_tick_size
hose_round_down = vn_round_down
hose_round_up = vn_round_up
hose_price_limits = vn_price_limits


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
    state: BaseEngine,
    symbol: str,
    bar: pd.Series,
    exchange: Optional[str] = None,
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
        exchange: Exchange whose tick grid the price is rounded onto; defaults
            to the symbol's suffix (``vn_exchange``).

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

    if candidate is None:
        return None
    return vn_round_down(candidate, exchange or vn_exchange(symbol))


def hose_can_execute(
    state: BaseEngine,
    rules: "VietnamEquityEngine",
    symbol: str,
    direction: int,
    bar: pd.Series,
) -> bool:
    """Apply the Vietnam execution rules, reading state and rules separately.

    The hold, the short ban and the board lot are the same on all three
    exchanges; the band and tick grid are those of the exchange the symbol
    trades on that day: ±7% on HOSE's grid, ±10% and ±15% on HNX's and UPCoM's
    flat 100-VND grid. That exchange is the suffix's (``vn_exchange``) unless
    the run's ``vn_exchange_history`` dates a move (see
    :meth:`VietnamEquityEngine.listing_on`).

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
        symbol: Vietnamese symbol (e.g. ``VIC.VN``, ``PVS.HNX``).
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

    # 3. Daily price band: ±7% HOSE, ±10% HNX, ±15% UPCoM (disabled when falsy),
    #    on the exchange the symbol trades on at the state's bar.
    ts = getattr(state, "_bar_ts", None)
    band = rules.band_for(symbol, ts)
    if not band:
        return True

    exchange = rules.exchange_on(symbol, ts)
    base_price = hose_base_price(state, symbol, bar, exchange)
    if base_price is None:
        if not rules._limit_base_warned:
            rules._limit_base_warned = True
            logger.warning(
                "%s: no reference price available (no 'pre_close' column and "
                "no prior close panel row) — the %s ±%.0f%% band check is "
                "inactive for this run",
                symbol,
                exchange,
                band * 100,
            )
        return True

    open_price = float(bar.get("open", bar.get("close", 0.0)) or 0.0)
    if open_price <= 0:
        return True  # order sizing rejects non-positive prices downstream

    upper, lower = vn_price_limits(base_price, band, exchange)
    # A composite's rule book was last synced to whichever symbol and bar it
    # served before, so the fill is priced for this symbol's grid explicitly.
    fill_price = rules.slipped_price(
        symbol, open_price, direction if direction else -1, ts
    )
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
                "%s: no bar cursor available — the T+2 settlement hold is "
                "inactive for this run",
                symbol,
            )
        return True
    return settled


class VietnamEquityEngine(BaseEngine):
    """Vietnam cash-equity engine (HOSE, HNX, UPCoM) — long-only, T+2 settled.

    Config keys (all optional; defaults shown in the module docstring):
      - price_limit: float fraction or None. Absent, each symbol takes its
        exchange's normal band (0.07 HOSE, 0.10 HNX, 0.15 UPCoM); present, it
        applies to every symbol, and ``0`` / ``None`` disables the check
      - slippage: default 0.001
      - vn_brokerage / vn_tax_sell
      - vn_settlement_bars: sessions a buy is held before it may be sold,
        default 2 (approximates the T+2 cycle on daily bars)
      - vn_exchange_history: ``{symbol: {date: exchange}}`` for names that
        moved exchange, each date being the first session there. A bar takes
        the band and tick grid of the exchange in force on its date, and the
        first session after a move takes that exchange's first-day band (0.20
        HOSE, 0.30 HNX, 0.40 UPCoM). Unlisted symbols, and bars before a
        symbol's earliest date, use the suffix's exchange. ``price_limit``
        still sets the band of every bar; the history then moves only the
        tick grid

    Raises:
        ValueError: When ``allow_short`` is truthy. Routine short selling is
            not operationally available in the Vietnamese cash market, so
            shorting is refused instead of being simulated. A cross-market
            composite run shares one config across its sub-engines, so pairing
            ``allow_short`` with a Vietnamese symbol fails the whole run —
            deliberately, since the alternative is a Vietnam leg that silently
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
        # No configured band: every symbol takes its own exchange's.
        self._band_per_exchange = "price_limit" not in config
        self.slippage_rate: float = config.get("slippage", 0.001)
        # Cost stack
        self.vn_brokerage: float = config.get("vn_brokerage", 0.0015)
        self.vn_tax_sell: float = config.get("vn_tax_sell", 0.001)
        self.settlement_bars: int = int(
            config.get("vn_settlement_bars", _DEFAULT_SETTLEMENT_BARS)
        )
        # Dated listing exchange for names that moved exchange.
        self.exchange_history = parse_exchange_history(
            config.get("vn_exchange_history")
        )
        # One warning per engine when no reference price is derivable.
        self._limit_base_warned = False
        self._settlement_warned = False

    def listing_on(self, symbol: str, ts: object = None) -> tuple[str, bool]:
        """Return the exchange *symbol* trades on at *ts*, and whether it moved.

        Args:
            symbol: Vietnamese symbol (``VIC.VN``, ``PVS.HNX``, ``ACV.UPCOM``).
            ts: Bar timestamp; ``None`` (no bar, as outside a run) reads the
                suffix.

        Returns:
            ``(exchange, moved)``. The exchange is the one the run's
            ``vn_exchange_history`` dates on or before *ts*, and the suffix's
            (``vn_exchange``) when the symbol has no history or *ts* falls
            before its earliest date. ``moved`` is True only on a bar dated on
            a later entry's own date: the first session on the new exchange.
        """
        history = self.exchange_history.get(symbol)
        day = _session_day(ts)
        if history is None or day is None:
            return vn_exchange(symbol), False
        days, exchanges = history
        k = bisect.bisect_right(days, day) - 1
        if k < 0:
            return vn_exchange(symbol), False
        return exchanges[k], k > 0 and days[k] == day

    def exchange_on(self, symbol: str, ts: object = None) -> str:
        """Return the exchange *symbol* trades on at *ts* (see :meth:`listing_on`)."""
        return self.listing_on(symbol, ts)[0]

    def band_for(self, symbol: str, ts: object = None) -> Optional[float]:
        """Return the daily price band applying to *symbol* on the bar at *ts*.

        Args:
            symbol: Vietnamese symbol (``VIC.VN``, ``PVS.HNX``, ``ACV.UPCOM``).
            ts: Bar timestamp; with a ``vn_exchange_history`` it selects the
                exchange (see :meth:`listing_on`).

        Returns:
            The configured band for every symbol when the run set
            ``price_limit``, and ``None`` when that band is ``0`` / ``None``.
            Otherwise the band of the exchange the symbol trades on at *ts*:
            its first-day band on the first session after a move, its
            normal-session band on every other bar.
        """
        if not self._band_per_exchange:
            return float(self.price_limit) if self.price_limit else None
        exchange, moved = self.listing_on(symbol, ts)
        return (VN_FIRST_DAY_BANDS if moved else VN_PRICE_BANDS)[exchange]

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Vietnam execution rules (HOSE, HNX, UPCoM).

        The band test compares the *prospective fill price* — this bar's open
        plus slippage, which is what :class:`BaseEngine` fills at — against
        bounds derived from the previous bar's close. Deriving the move from the
        current bar's close instead would be lookahead: ``BaseEngine`` calls this
        hook before the fill, and the decision bar's close is not known then.

        Args:
            symbol: Vietnamese symbol (e.g. ``VIC.VN``, ``PVS.HNX``).
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
        return hose_base_price(
            self, symbol, bar, self.exchange_on(symbol, self._bar_ts)
        )

    def round_size(self, raw_size: float, price: float) -> float:
        """Floor the order to whole 100-share board lots.

        The exchanges accept odd-lot orders of 1-99 shares on a separate board
        that a daily bar cannot represent, so odd-lot trading is deliberately not
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

    def slipped_price(
        self, symbol: str, price: float, direction: int, ts: object = None
    ) -> float:
        """Slip *price* against the trader onto *symbol*'s exchange tick grid.

        A slipped price is snapped away from the trader — buys up to the next
        valid ask, sells down to the next valid bid — because no fill can land
        between ticks.

        Args:
            symbol: Vietnamese symbol; its exchange selects the tick grid.
            price: Reference price in VND.
            direction: 1 to buy, -1 to sell.
            ts: Bar timestamp; with a ``vn_exchange_history`` it selects the
                exchange (see :meth:`listing_on`).

        Returns:
            A valid price on the symbol's exchange, never below one tick.
        """
        exchange = self.exchange_on(symbol, ts)
        slipped = price * (1 + direction * self.slippage_rate)
        if direction > 0:
            return vn_round_up(slipped, exchange)
        return max(vn_round_down(slipped, exchange), vn_tick_size(slipped, exchange))

    def apply_slippage(self, price: float, direction: int) -> float:
        """Vietnam slippage (configurable), quantized onto the tick grid.

        Args:
            price: Reference price in VND.
            direction: 1 to buy, -1 to sell.

        Returns:
            A valid price on the exchange of the symbol being filled
            (``BaseEngine`` sets ``_active_symbol`` before every fill, and
            ``_bar_ts`` on every bar).
        """
        return self.slipped_price(self._active_symbol, price, direction, self._bar_ts)
