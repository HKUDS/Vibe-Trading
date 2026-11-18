"""Taiwan equity (TWSE / TPEx) backtest engine.

Models the cash-equity segment of the Taiwan Stock Exchange (TWSE, listed) and
the Taipei Exchange (TPEx, over-the-counter) on daily bars. Prices are in NT$,
the unit Yahoo's ``.TW`` / ``.TWO`` series uses.

Market rules (each constant below repeats its own citation):
  - **Long-only.** Margin and short selling are not modelled, so
    ``allow_short=True`` is refused at construction rather than simulated.
  - Price limit: +/-10% of the reference price. The reference price is the
    previous close; on an ex-rights / ex-dividend day the exchange computes an
    adjusted reference itself, whereas this engine only sees the previous close
    in its data.
    TWSE Operating Rules Art. 63 (limit), Art. 58-3 (opening reference = previous
    close) and Art. 67 (ex-rights / ex-dividend reference), version 2026-08-06:
    https://twse-regulation.twse.com.tw/m/LawContent.aspx?FID=FL007304
    TWSE trading system: https://www.twse.com.tw/zh/products/system/trading.html
    TPEx trading system: https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html
    Set ``price_limit`` to ``None`` / ``0`` to disable it.
  - Limit rounding: the ceiling is ``1.1 x reference`` floored, and the floor is
    ``0.9 x reference`` ceiled, each onto the tick of the candidate price's own
    price range; the lowest price is NT$0.01. The exchange's worked example
    (TWSE trading system page above) turns a reference of 40.60 into 44.65 and
    36.55. The reference is used unrounded (two decimals), not rounded onto a
    tick first. Our own check against the TWSE ex-rights/dividend table
    (``exRight/TWT49U``, fetched 2026-09-24) reproduces all 272 published limit
    pairs: 262 from the single published reference price, and the other 10 (rows
    with a cash capital increase) from a separate base for each side, which a
    single previous close cannot express.
  - Tick size (stocks): 0.01 below 10, 0.05 to 50, 0.1 to 100, 0.5 to 500,
    1 to 1000, 5 from 1000. TWSE Operating Rules Art. 62.
  - Tick size (ETFs): 0.01 below 50, 0.05 from 50. TWSE Beneficiary Certificate
    Trading Rules Art. 7 (version 2025-09-30):
    https://twse-regulation.twse.com.tw/m/LawContent.aspx?FID=FL007114
    https://www.twse.com.tw/zh/products/securities/etf/overview/rules.html
    ETFs are recognised by code (see :func:`tw_is_etf`), which is a heuristic.
  - Board lot: 1000 shares (TWSE Operating Rules Art. 60). Odd-lot orders are
    refused, that is they round to zero shares: odd-lot prints are not counted in
    the official open / high / low / close, and odd-lot trading is a separate
    market that a daily bar cannot fill. TWSE Odd-lot Trading Rules Art. 10
    (version 2026-08-20):
    https://twse-regulation.twse.com.tw/m/LawContent.aspx?FID=FL007115
  - No settlement hold. Payment settles on T+2, but TWSE Operating Rules Art.
    79-1 item 14 exempts "shares bought on the previous business day" from the
    holdings check on sell orders, so shares bought on bar N may be sold on bar
    N+1. Unlike the Vietnam engine, nothing here delays a sell.

Cost stack (all config-driven; verify against your broker's schedule):
  - Brokerage: 0.1425% of the trade value on both legs, times a discount
    (``tw_fee_discount``, default 1.0 = list price), with a NT$20 minimum per
    leg. 0.1425% is the standard rate and the level above which the broker must
    notify the client, not a statutory cap. The discount and the minimum are set
    by each broker. TWSE Operating Rules Art. 94; the NT$20 minimum is broker
    practice, e.g. the SinoPac fee schedule dated 2024-11-28:
    https://www.sinotrade.com.tw/ec/upload/Service-charge.pdf
  - Securities transaction tax, sell leg only: 0.3% for stocks, 0.1% for ETFs.
    Securities Transaction Tax Act Art. 2 (amended 2025-01-02):
    https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=G0340078
    The ETF rate is also stated on the TWSE ETF rules page above.

Slippage is a plain percentage (``slippage``, default 0.1%), not snapped to the
tick grid: Yahoo-derived prices are dividend-adjusted and therefore do not lie
on the grid, and the stock and ETF tick tables differ.

Not modelled: the settlement cash cycle (T+2), the day-trade tax of 0.15%
(Securities Transaction Tax Act Art. 2-2; a daily-bar engine cannot represent a
same-day round trip), the bond-ETF tax exemption (Art. 2-1, currently running to
2026-12-31; bond ETFs are charged 0.1% here, which is conservative), the absence
of a limit in the first 5 listing days (Operating Rules Art. 63 paragraph 2),
disposition and full-delivery stocks, the Emerging board, margin and short
selling, and the different limits of ETFs with foreign underlyings and of
leveraged / inverse ETFs (Beneficiary Certificate Trading Rules Art. 8): the
+/-10% band is applied to every code, so disable it for such runs. Fees and tax
are not rounded to whole NT$.

Unverified or pending: TPEx's own rule text defining its reference price was not
available, so the TPEx band is checked empirically only; TWSE's board approved
on 2026-08-25 a change of the tick from 5 to 1 above NT$1000, which is not yet in
force and not modelled.
"""

from __future__ import annotations

import logging
import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import pandas as pd

from backtest.engines.base import BaseEngine

logger = logging.getLogger(__name__)

# Stock tick table: (lower bound inclusive, tick) in NT$.
# TWSE Operating Rules Art. 62. Every coarser tick is a whole multiple of every
# finer one, which keeps the floor / ceiling arithmetic stable across boundaries.
TW_STOCK_TICK_TABLE: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0"), Decimal("0.01")),
    (Decimal("10"), Decimal("0.05")),
    (Decimal("50"), Decimal("0.1")),
    (Decimal("100"), Decimal("0.5")),
    (Decimal("500"), Decimal("1")),
    (Decimal("1000"), Decimal("5")),
)

# ETF tick table. TWSE Beneficiary Certificate Trading Rules Art. 7.
TW_ETF_TICK_TABLE: tuple[tuple[Decimal, Decimal], ...] = (
    (Decimal("0"), Decimal("0.01")),
    (Decimal("50"), Decimal("0.05")),
)

# Lowest price the limit floor can reach (TWSE Operating Rules Art. 63).
_MIN_PRICE = Decimal("0.01")

# Board lot: 1000 shares. TWSE Operating Rules Art. 60.
TW_LOT_SIZE = 1000

# Daily price limit as a fraction of the reference price.
# TWSE Operating Rules Art. 63; TPEx trading system page.
_DEFAULT_PRICE_LIMIT = 0.10

# Slippage per side. A modelling choice, not an exchange rule.
_DEFAULT_SLIPPAGE = 0.001

# Standard brokerage rate, 0.1425% of the trade value. TWSE Operating Rules Art. 94:
# a standard rate and a notification threshold, not a statutory cap.
_DEFAULT_FEE_RATE = 0.001425

# Multiplier on the brokerage rate; 1.0 = list price. Discounts are set by each
# broker (TWSE Operating Rules Art. 94).
_DEFAULT_FEE_DISCOUNT = 1.0

# Minimum brokerage per leg in NT$. Broker practice, e.g. the SinoPac fee schedule
# dated 2024-11-28; TWSE Operating Rules Art. 94 lets each broker set it.
_DEFAULT_FEE_MIN = 20.0

# Securities transaction tax on the sell leg, stocks: 0.3%.
# Securities Transaction Tax Act Art. 2.
_DEFAULT_TAX_STOCK = 0.003

# Securities transaction tax on the sell leg, ETFs: 0.1%.
# Securities Transaction Tax Act Art. 2; TWSE ETF rules page.
_DEFAULT_TAX_ETF = 0.001

# Comparisons only need to survive float representation error: quoted prices sit
# on a 0.01 grid, so 1e-9 is far below one tick.
_PRICE_EPS = 1e-9
_PRICE_EPS_DECIMAL = Decimal("1e-9")

# Share counts are quotient results (notional / price) and can land a hair under a
# whole number of lots; 1e-6 of a share is far below anything tradable.
_SIZE_EPS = 1e-6


def _to_decimal(value: float, name: str) -> Decimal:
    """Convert *value* to an exact Decimal of its shortest float repr.

    Args:
        value: A finite number.
        name: What the value is, for the error message.

    Returns:
        The decimal the float was written as (``40.6`` gives ``Decimal("40.6")``).

    Raises:
        ValueError: When *value* is NaN or infinite.
    """
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return Decimal(repr(number))


def _tick_for(price: Decimal, etf: bool) -> Decimal:
    """Return the tick of the price range *price* falls in."""
    table = TW_ETF_TICK_TABLE if etf else TW_STOCK_TICK_TABLE
    tick = table[0][1]
    for lower, unit in table:
        if price >= lower:
            tick = unit
        else:
            break
    return tick


def tw_is_etf(symbol: str) -> bool:
    """Return whether *symbol* should use the ETF columns (tick table, tax rate).

    Heuristic: a code that starts with ``0`` (a ``.TW`` / ``.TWO`` suffix does
    not matter) is treated as an ETF. This matches every ETF, active ETF and REIT
    row of the TWSE ex-rights/dividend table (fetched 2026-09-24) but is verified
    only there, and is unverified as a rule. Warrants and ETNs also start with
    ``0``; they are not modelled.

    Args:
        symbol: Yahoo-style symbol such as ``0050.TW``, or a bare code.

    Returns:
        True when the code starts with ``0``.
    """
    return symbol.strip().startswith("0")


def tw_tick_size(price: float, *, etf: bool = False) -> float:
    """Return the tick applying at *price*.

    Args:
        price: Price in NT$. Prices at or below zero take the finest tick.
        etf: Use the ETF table instead of the stock table.

    Returns:
        The tick in NT$.

    Raises:
        ValueError: When *price* is NaN or infinite.
    """
    return float(_tick_for(_to_decimal(price, "price"), etf))


def tw_price_limits(ref: float, band: float = _DEFAULT_PRICE_LIMIT, *, etf: bool = False) -> tuple[float, float]:
    """Return the (upper, lower) limit prices for reference price *ref*.

    The ceiling is ``ref x (1 + band)`` floored, and the floor is
    ``ref x (1 - band)`` ceiled, each onto the tick of the range that candidate
    price falls in, so neither bound lies outside the legal band. The floor never
    goes below NT$0.01. *ref* is used as given: it is not rounded onto a tick
    first (a rounded reference gives different limits).

    Args:
        ref: Reference price in NT$ (the previous close).
        band: Band as a fraction, e.g. ``0.10`` for +/-10%.
        etf: Use the ETF tick table instead of the stock table.

    Returns:
        ``(upper, lower)``, both on the tick grid, with ``upper >= lower``.

    Raises:
        ValueError: When *ref* is not a positive finite number, or *band* is not
            a non-negative finite number, or when *band* is narrower than the tick
            grid can represent at *ref* — flooring the ceiling and ceiling the floor
            would then cross, which is a config problem (an unrealistically tight
            ``price_limit``), not a data problem, so it is raised rather than
            silently returning a physically inverted band. TWSE's own +/-10% band is
            always wide enough not to hit this; it can only be reached with a custom
            ``price_limit`` far narrower than any real Taiwan trading rule.
    """
    ref_value = _to_decimal(ref, "reference price")
    band_value = _to_decimal(band, "band")
    if ref_value <= 0:
        raise ValueError(f"reference price must be positive, got {ref!r}")
    if band_value < 0:
        raise ValueError(f"band must not be negative, got {band!r}")

    upper_candidate = ref_value * (1 + band_value)
    upper_tick = _tick_for(upper_candidate, etf)
    upper = ((upper_candidate + _PRICE_EPS_DECIMAL) / upper_tick).to_integral_value(ROUND_FLOOR) * upper_tick

    lower_candidate = ref_value * (1 - band_value)
    lower_tick = _tick_for(lower_candidate, etf)
    lower = ((lower_candidate - _PRICE_EPS_DECIMAL) / lower_tick).to_integral_value(ROUND_CEILING) * lower_tick
    lower = max(lower, _MIN_PRICE)

    if upper < lower:
        raise ValueError(
            f"price_limit={band!r} is too narrow to represent on the tick grid at "
            f"reference price {ref!r}: the rounded ceiling {float(upper)!r} would sit "
            f"below the rounded floor {float(lower)!r}. TWSE's own +/-10% band never hits "
            "this; use a wider price_limit, or 0/None to disable the check."
        )
    return float(upper), float(lower)


def tw_can_execute(
    state: BaseEngine,
    rules: "TaiwanEquityEngine",
    symbol: str,
    direction: int,
    bar: pd.Series,
) -> bool:
    """Apply the Taiwan execution rules, reading state and rules separately.

    A single-market run passes the same engine as both arguments. A cross-market
    composite run cannot: it owns the close panel and bar cursor for every
    market, while the rule parameters (band, slippage) live on the Taiwan
    sub-engine, which ``CompositeEngine`` holds as a stateless rule book. The
    same contract as ``hose_can_execute`` in the Vietnam engine.

    The band test compares the *prospective fill price* (this bar's open plus
    slippage, which is what :class:`BaseEngine` fills at) against limits derived
    from the previous close. Deriving them from the current bar's close would be
    lookahead: the check runs before the fill, when that close is not known.

    Args:
        state: Engine owning the close panel and bar cursor.
        rules: Taiwan engine supplying the band and the slippage model.
        symbol: Yahoo-style symbol (e.g. ``2330.TW``).
        direction: 1 (buy), -1 (short, always blocked), 0 (sell / close).
        bar: Current bar (needs ``open``; the reference price comes from
            ``pre_close`` when the source supplies it, else from the previous
            close of the run's panel).

    Returns:
        True if the trade is allowed.

    Raises:
        ValueError: When ``rules.price_limit`` is narrower than the tick grid can
            represent at the resolved reference price (see :func:`tw_price_limits`).
            This is a config problem, not a data problem, so it propagates rather
            than being caught here: TWSE's own +/-10% band never hits it.
    """
    # 1. Short selling is not modelled.
    if direction == -1:
        return False

    # 2. Daily price limit (disabled when falsy). No settlement hold: shares
    #    bought on the previous business day may be sold (see module docstring).
    if not rules.price_limit:
        return True

    base_price = state.historical_base_price(symbol, bar)
    if base_price is None or not math.isfinite(base_price) or base_price <= 0:
        if not rules._limit_base_warned:
            rules._limit_base_warned = True
            logger.warning(
                "%s: no reference price available (no 'pre_close' column and "
                "no prior close panel row); the Taiwan +/-%.0f%% price limit "
                "check is inactive for this run",
                symbol,
                float(rules.price_limit) * 100,
            )
        return True

    raw_open = bar.get("open", bar.get("close"))
    open_price = float(raw_open) if raw_open is not None and pd.notna(raw_open) else 0.0
    if not (0 < open_price < math.inf):
        return True  # order sizing rejects unusable prices downstream

    upper, lower = tw_price_limits(base_price, float(rules.price_limit), etf=tw_is_etf(symbol))
    fill_price = rules.apply_slippage(open_price, direction if direction else -1)
    if direction == 1 and fill_price >= upper - _PRICE_EPS:
        return False  # locked at the ceiling: no ask to buy from
    if direction == 0 and fill_price <= lower + _PRICE_EPS:
        return False  # locked at the floor: no bid to sell into
    return True


class TaiwanEquityEngine(BaseEngine):
    """TWSE / TPEx cash-equity engine: long-only, board lots, +/-10% limit.

    Config keys (all optional):
      - price_limit: float fraction or None, default 0.10
      - slippage: default 0.001
      - tw_fee_rate: default 0.001425
      - tw_fee_discount: default 1.0 (list price)
      - tw_fee_min: default 20.0 (NT$ per leg)
      - tw_tax_stock: default 0.003 (sell leg)
      - tw_tax_etf: default 0.001 (sell leg)

    Raises:
        ValueError: When ``allow_short`` is truthy. Short selling is not
            modelled. A cross-market composite run shares one config across its
            sub-engines, so pairing ``allow_short`` with a Taiwan symbol fails the
            whole run, deliberately: the alternative is a Taiwan leg that
            silently never shorts while the rest of the book does.
    """

    def __init__(self, config: dict):
        config = {**config, "leverage": 1.0}  # cash equity: no leverage
        super().__init__(config)
        if config.get("allow_short"):
            raise ValueError(
                "TaiwanEquityEngine is long-only: margin and short selling are not "
                "modelled, so a short book cannot be simulated. Remove 'allow_short' "
                "instead of running a mis-modelled short book."
            )
        self.price_limit = config.get("price_limit", _DEFAULT_PRICE_LIMIT)
        self.slippage_rate: float = float(config.get("slippage", _DEFAULT_SLIPPAGE))
        # Cost stack
        self.tw_fee_rate: float = float(config.get("tw_fee_rate", _DEFAULT_FEE_RATE))
        self.tw_fee_discount: float = float(config.get("tw_fee_discount", _DEFAULT_FEE_DISCOUNT))
        self.tw_fee_min: float = float(config.get("tw_fee_min", _DEFAULT_FEE_MIN))
        self.tw_tax_stock: float = float(config.get("tw_tax_stock", _DEFAULT_TAX_STOCK))
        self.tw_tax_etf: float = float(config.get("tw_tax_etf", _DEFAULT_TAX_ETF))
        # One warning per engine when no reference price is derivable.
        self._limit_base_warned = False

    def can_execute(self, symbol: str, direction: int, bar: pd.Series) -> bool:
        """Taiwan execution rules: no shorts, and the daily price limit.

        Args:
            symbol: Yahoo-style symbol (e.g. ``2330.TW``).
            direction: 1 (buy), -1 (short, always blocked), 0 (sell / close).
            bar: Current bar (see :func:`tw_can_execute`).

        Returns:
            True if the trade is allowed.
        """
        # This engine owns both the run state and the rule parameters. A
        # composite run splits them; see :func:`tw_can_execute`.
        return tw_can_execute(self, self, symbol, direction, bar)

    def round_size(self, raw_size: float, price: float) -> float:
        """Floor the order to whole 1000-share board lots.

        Odd-lot trading is a separate market that a daily bar cannot fill (see
        the module docstring), so a sub-lot order rounds to zero rather than
        being filled at the continuous-session price.

        Args:
            raw_size: Unrounded share count.
            price: Fill price in NT$ (unused; the lot is price-independent).

        Returns:
            Share count as a whole multiple of the board lot.
        """
        if not (raw_size > 0 and math.isfinite(raw_size)):
            return 0.0
        lots = int((raw_size + _SIZE_EPS) // TW_LOT_SIZE)
        return float(lots * TW_LOT_SIZE)

    def calc_commission(self, size: float, price: float, direction: int, is_open: bool) -> float:
        """Taiwan cost stack: brokerage on both legs, transaction tax on the sell leg.

        The tax follows the actual trade side rather than open/close: a closing
        trade on a long book is a sell (taxable). The rate depends on the symbol,
        which this hook does not receive; :class:`BaseEngine` sets
        ``self._active_symbol`` before calling it (and ``CompositeEngine``
        forwards it), so the ETF or stock rate is picked from that.

        Args:
            size: Share count.
            price: Fill price in NT$.
            direction: 1 for a long book, -1 for a short book.
            is_open: True for the opening leg, False for the closing leg.

        Returns:
            Total cost in NT$ for this leg; zero for an empty trade.
        """
        notional = size * price
        if notional <= 0:
            return 0.0
        cost = max(notional * self.tw_fee_rate * self.tw_fee_discount, self.tw_fee_min)
        is_sell = (direction < 0) if is_open else (direction > 0)
        if is_sell:
            rate = self.tw_tax_etf if tw_is_etf(self._active_symbol) else self.tw_tax_stock
            cost += notional * rate
        return cost

    def apply_slippage(self, price: float, direction: int) -> float:
        """Taiwan slippage: a plain percentage of the price (configurable).

        Not snapped to the tick grid: Yahoo-derived prices are dividend-adjusted
        and so already off the grid, and the stock and ETF tick tables differ.

        Args:
            price: Reference price in NT$.
            direction: 1 to buy, -1 to sell.

        Returns:
            The price moved against the trader by ``slippage``.
        """
        return price * (1 + direction * self.slippage_rate)
