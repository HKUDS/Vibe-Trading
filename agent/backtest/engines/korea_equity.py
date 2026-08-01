"""Korea equity (KRX: KOSPI / KOSDAQ) backtest engine.

Models the Korean cash-equity segment on daily bars. Prices are assumed to be
quoted in KRW, which KRX prints as whole won on a coarse tick grid — the grid is
modelled explicitly below because a percentage-only model produces fill prices
that cannot exist and mis-identifies locked-limit bars.

Market rules:
  - Same-day round trips are allowed: shares bought today CAN be sold the same
    day (unlike China A-share T+1 or India delivery), so there is no same-bar
    sell block.
  - **Long-only by construction.** KRX short selling is covered-only and
    uptick-constrained (차입공매도 / 업틱룰), and neither constraint is
    representable on daily bars, so ``allow_short=True`` is *refused* at
    construction rather than silently mis-modelled.
  - Price limit: ±30% daily band on both KOSPI and KOSDAQ (since June 2015),
    measured from the base price (기준가격 — normally the previous trading
    day's close) and quantized to the tick grid. Set ``price_limit`` to ``0`` /
    ``None`` to disable.
  - Lot size: 1 share (KRX abolished the 10-share odd-lot rule in 2014).

Cost stack (discount-broker defaults; all config-driven):
  - Brokerage: 0.015% per side (typical online rate)        [kr_brokerage]
  - Securities transaction tax: 0.20% on the SELL side      [kr_tax_sell]
    From transfers on/after 2026-01-01 the aggregate sell-side rate is 0.20%
    on both boards, restored after the financial-investment-income tax was
    scrapped: KOSPI = 0.05% 증권거래세 + 0.15% 농어촌특별세, KOSDAQ = 0.20%
    증권거래세 with no surtax (증권거래세법 시행령 제5조 탄력세율 as amended
    by 대통령령 제36001호; 농어촌특별세법 제5조). KONEX stays at 0.10% — pass
    ``kr_tax_sell=0.001`` for KONEX names. Rates are revised periodically;
    verify ``kr_*`` against the current schedule before trusting absolute cost
    figures.

Tick grid source: KRX regulation portal (호가가격단위) —
https://regulation.krx.co.kr/contents/RGL/03/03010100/RGL03010100T3.jsp (KOSPI)
and https://regulation.krx.co.kr/contents/RGL/03/03020100/RGL03020100.jsp
(KOSDAQ). The 2023-01-25 reform **unified** the two boards' tables and removed
the old high-price divergence, so one table now serves both. Note that KRX's
English "Guide to Trading in the Korean Stock Market" PDF still prints the
pre-2023 bands (1,000 / 10,000 / 100,000 boundaries, KOSDAQ capped at 100 KRW)
— it is stale; the Korean regulation portal above is authoritative.

Price-limit arithmetic follows the published KRX procedure rather than a naive
``base * 1.3``: the 30% band amount is truncated to the *base price's* tick
unit, then added to / subtracted from the base, then truncated again to the
resulting price's own tick unit. KRX worked example (기준가격 9,980):
9,980 x 0.3 = 2,994 -> 2,990 -> upper 12,970 / lower 6,990.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from backtest.engines.base import BaseEngine

logger = logging.getLogger(__name__)

# KRX quotation price units (호가가격단위): (lower bound inclusive, tick).
# Unified across KOSPI / KOSDAQ / KONEX since 2023-01-25. Every coarser tick is
# an exact multiple of every finer one, which is what makes the truncation
# arithmetic below stable across band boundaries.
KRX_TICK_TABLE: tuple[tuple[float, float], ...] = (
    (0.0, 1.0),
    (2_000.0, 5.0),
    (5_000.0, 10.0),
    (20_000.0, 50.0),
    (50_000.0, 100.0),
    (200_000.0, 500.0),
    (500_000.0, 1_000.0),
)

# Tick-grid comparisons only need to survive float representation error: every
# quantized price is a whole number of won, so 1e-9 is far below one tick.
_PRICE_EPS = 1e-9


def krx_tick_size(price: float) -> float:
    """Return the KRX tick unit applicable at *price*.

    Args:
        price: Price in KRW. Non-positive input returns the finest tick.

    Returns:
        The tick unit (KRW) for the band containing *price*; bands are
        lower-bound inclusive (``이상`` / ``미만``), so 2,000 KRW -> 5 KRW.
    """
    tick = KRX_TICK_TABLE[0][1]
    for lower, unit in KRX_TICK_TABLE:
        if price >= lower:
            tick = unit
        else:
            break
    return tick


def krx_round_down(price: float) -> float:
    """Truncate *price* down onto the tick grid (KRX ``절사``)."""
    tick = krx_tick_size(price)
    return float(int((price + _PRICE_EPS) / tick) * tick)


def krx_round_up(price: float) -> float:
    """Round *price* up onto the tick grid (KRX ``절상``), never below one tick."""
    tick = krx_tick_size(price)
    steps = int((price - _PRICE_EPS) / tick)
    if steps * tick < price - _PRICE_EPS:
        steps += 1
    return float(max(steps, 1) * tick)


def krx_price_limits(base_price: float, limit: float) -> tuple[float, float]:
    """Return the (upper, lower) KRX limit prices for a base price.

    Implements the published three-step procedure: the band amount is
    ``base * limit`` truncated to the base price's tick unit, and each limit
    price is then truncated to its own tick unit (the lower limit is already
    grid-aligned because coarser ticks are multiples of finer ones, so only the
    upper limit can move).

    Args:
        base_price: Base price (기준가격), normally the previous close, already
            snapped onto the tick grid by the caller.
        limit: Band width as a fraction (0.30 for the standard ±30%).

    Returns:
        ``(upper_limit, lower_limit)`` in KRW.
    """
    base_tick = krx_tick_size(base_price)
    band_amount = max(int((base_price * limit + _PRICE_EPS) / base_tick), 1) * base_tick
    return (
        krx_round_down(base_price + band_amount),
        krx_round_down(max(base_price - band_amount, base_tick)),
    )


class KoreaEquityEngine(BaseEngine):
    """KRX (KOSPI / KOSDAQ) cash-equity engine — long-only.

    Config keys (all optional; defaults shown in the module docstring):
      - price_limit: float fraction or None, default 0.30
      - slippage: default 0.001
      - kr_brokerage / kr_tax_sell

    Raises:
        ValueError: When ``allow_short`` is truthy. KRX covered-short and
            uptick rules are not modelled, so shorting is refused instead of
            being simulated incorrectly. A cross-market composite run shares one
            config across its sub-engines, so pairing ``allow_short`` with a KRX
            symbol fails the whole run — deliberately, since the alternative is
            a KRX leg that silently never shorts while the rest of the book
            does.
    """

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}  # cash equity: no leverage
        super().__init__(config)
        if config.get("allow_short"):
            raise ValueError(
                "KoreaEquityEngine is long-only: KRX short selling is "
                "covered-only (차입공매도) and uptick-constrained, and neither "
                "rule can be enforced on daily bars. Remove 'allow_short' "
                "instead of running a mis-modelled short book."
            )
        self.price_limit = config.get("price_limit", 0.30)
        self.slippage_rate: float = config.get("slippage", 0.001)
        # Cost stack
        self.kr_brokerage: float = config.get("kr_brokerage", 0.00015)
        self.kr_tax_sell: float = config.get("kr_tax_sell", 0.0020)
        # One warning per engine when no base price is derivable (see _base_price).
        self._limit_base_warned = False

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """KRX execution rules.

        The price-limit test compares the *prospective fill price* — this bar's
        open plus slippage, which is what :class:`BaseEngine` fills at — against
        limit prices derived from the previous bar's close. Deriving the move
        from the current bar's close instead (the china_a/india pattern) would
        be lookahead: ``BaseEngine`` calls this hook before the fill, and the
        decision bar's close is not known then.

        Args:
            symbol: KRX symbol (e.g. ``005930.KS``, ``247540.KQ``).
            direction: 1 (buy), -1 (short), 0 (sell/close).
            bar: Current bar (needs ``open``; the base price comes from
                ``pre_close`` when the source supplies it, else from the prior
                bar of the run's own close panel).

        Returns:
            True if the trade is allowed.
        """
        # 1. Short selling: structurally unavailable (see class docstring).
        if direction == -1:
            return False

        # 2. Same-day sell is allowed on KRX — no T+1 interception.

        # 3. Daily price limit ±30% (disabled when falsy).
        if not self.price_limit:
            return True

        base_price = self._base_price(symbol, bar)
        if base_price is None:
            if not self._limit_base_warned:
                self._limit_base_warned = True
                logger.warning(
                    "%s: no base price available (no 'pre_close' column and no "
                    "prior close panel row) — the KRX ±%.0f%% limit check is "
                    "inactive for this run",
                    symbol,
                    float(self.price_limit) * 100,
                )
            return True

        open_price = float(bar.get("open", bar.get("close", 0.0)) or 0.0)
        if open_price <= 0:
            return True  # order sizing rejects non-positive prices downstream

        upper, lower = krx_price_limits(base_price, float(self.price_limit))
        fill_price = self.apply_slippage(open_price, direction if direction else -1)
        if direction == 1 and fill_price >= upper - _PRICE_EPS:
            return False  # limit-up (상한가): no ask to buy from
        if direction == 0 and fill_price <= lower + _PRICE_EPS:
            return False  # limit-down (하한가): no bid to sell into
        return True

    def _base_price(self, symbol: str, bar: pd.Series) -> Optional[float]:
        """Resolve the KRX base price (기준가격) for *symbol* on this bar.

        Both sources are strictly historical, so neither leaks the decision
        bar's own close into the pre-fill check:
          1. ``pre_close`` on the bar, when the data source supplies one.
          2. The previous row of the close panel that :class:`BaseEngine`
             pre-extracts for the run (unavailable in a cross-market composite
             run, whose sub-engines are stateless rule books).

        An off-grid close (pykrx's adjusted series is Naver-rebased and need not
        land on a tick) is rounded up onto the grid, which is KRX's own rule for
        a base price that falls between ticks (``절상``).

        Args:
            symbol: Symbol whose base price is wanted.
            bar: Current bar.

        Returns:
            The base price in KRW, or ``None`` when no historical close is
            reachable (first bar of a run, or a composite sub-engine).
        """
        candidate: Optional[float] = None
        if "pre_close" in bar.index:
            raw = bar["pre_close"]
            if pd.notna(raw) and float(raw) > 0:
                candidate = float(raw)

        if candidate is None:
            close_arr = getattr(self, "_close_arr", None)
            col = getattr(self, "_code_to_col", {}).get(symbol)
            row = getattr(self, "_bar_idx", 0) - 1
            if close_arr is not None and col is not None and row >= 0:
                raw = close_arr[row, col]
                if pd.notna(raw) and float(raw) > 0:
                    candidate = float(raw)

        return None if candidate is None else krx_round_up(candidate)

    def round_size(self, raw_size: float, price: float) -> float:
        """Cash equity trades in 1-share lots."""
        return float(max(int(raw_size), 0))

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """Korea cost stack: bilateral brokerage + transaction tax on sells.

        The tax follows the actual trade side rather than open/close: a closing
        trade on a long book is a sell (taxable), while an opening short would
        be the taxable leg and its buy-to-cover would not be. ``BaseEngine``
        passes the position direction on both hooks, so the side is derivable
        even though this engine is long-only today.

        Args:
            size: Share count.
            price: Fill price in KRW.
            direction: 1 for a long book, -1 for a short book.
            is_open: True for the opening leg, False for the closing leg.

        Returns:
            Total cost in KRW for this leg.
        """
        notional = size * price
        comm = notional * self.kr_brokerage
        is_sell = (direction < 0) if is_open else (direction > 0)
        if is_sell:
            comm += notional * self.kr_tax_sell
        return comm

    def apply_slippage(self, price: float, direction: int) -> float:
        """Korea slippage (configurable), quantized onto the KRX tick grid.

        A slipped price is snapped away from the trader — buys up to the next
        valid ask, sells down to the next valid bid — because no fill can land
        between ticks. The residual rounding is bounded by one tick unit
        (<= 0.25% of price across the whole table).

        Args:
            price: Reference price in KRW.
            direction: 1 to buy, -1 to sell.

        Returns:
            A valid KRX price, never below one tick.
        """
        slipped = price * (1 + direction * self.slippage_rate)
        if direction > 0:
            return krx_round_up(slipped)
        return max(krx_round_down(slipped), krx_tick_size(slipped))
