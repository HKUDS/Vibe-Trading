"""Three-market rule matrix for ``paper_trade_step`` (pt-v1.1 Step 3 / T3).

REQUIREMENTS §4 frozen semantics (values are the registered defaults; any
micro-adjustment is a delivery-note item, VD-9):

* **Fees (Decimal, ROUND_HALF_UP, quantized 2dp — never the builtin rounding
  function, never float arithmetic on money)** — cn_a: commission 0.025% min
  ¥5 + stamp tax sell-only 0.05% + transfer fee 0.001%; hk: commission 0.03%
  min HK$3 + stamp duty 0.1% per order per side quantized to WHOLE HKD
  ROUND_HALF_UP (HALF_UP vs HKEX ceil is the registered VD-9 delivery-note
  choice) + regulatory levy 0.003%; us: $0.0049/share min $0.99, SEC fee
  simplified to 0.  Effective values come from
  :func:`state_hash.effective_fee_model` (RM always injects fee_model, AM-4-3).
* **Lots** — cn_a 100 shares (reuses ``ChinaAEngine.round_size`` by import,
  VD-2); hk per-symbol board lot via ``GlobalEquityEngine._hk_board_lot``
  (lot table + fallback 100 + ``lot_assumptions`` diagnostic, DD-4); us whole
  shares (§4 lot = 1 share).  A violating qty is REJECTED ``lot_size`` — the
  paper engine never silently rounds a user-stated qty.
* **Settlement** — cn_a T+1 on SELLS only (available = total − bought_today);
  hk/us T+0 (same-day buy→sell passes).
* **AM-7 limit orders** — buy fills only when close ≤ limit, sell only when
  close ≥ limit; fill price = close; violation → ``limit_not_marketable``.
  cn_a price-limit bands (limit_up/limit_down) are checked BEFORE the limit
  order check (AM-14 order).

:data:`REJECTION_ORDER` is the AM-14 frozen decision sequence (first match
wins); the engine walks it, this module supplies the per-slot rule checks.

VD-2: engine primitives are reused BY IMPORT (``ChinaAEngine.round_size``,
``GlobalEquityEngine._hk_board_lot``); ``agent/backtest/`` is never modified.
``china_a_can_execute`` is deliberately NOT consumed: it tests bands against
the bar OPEN plus slippage (backtest fill semantics), while the paper contract
fills at the CLOSE with zero slippage (§4) — the band derivation primitive
(``_price_limit`` via limits_cn_a) is the reused half.  Determinism: no clock,
no randomness, no I/O; every input is injected.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Mapping

# VD-2: reuse engine primitives by import; agent/backtest/ is never modified.
from backtest.engines.china_a import ChinaAEngine
from backtest.engines.global_equity import GlobalEquityEngine

from . import state_hash

__all__ = [
    "CN_A_LOT_SHARES",
    "REJECTION_ORDER",
    "US_LOT_SHARES",
    "MarketRules",
    "money",
    "quantize_money",
]

#: AM-14 frozen rejection decision order — first match wins (REQUIREMENTS §2
#: hard semantics 3a).  ``limit_up``/``limit_down`` share one frozen slot and
#: sit adjacent: a buy can only hit the upper band, a sell only the lower one,
#: so adjacency preserves the frozen semantics exactly.
REJECTION_ORDER: tuple[str, ...] = (
    "unknown_symbol",
    "non_trading_day",
    "suspended",
    "corporate_action_unresolved",
    "lot_size",
    "limit_up",
    "limit_down",
    "limit_not_marketable",
    "t_plus_1",  # cn_a sells only
    "insufficient_position",
    "insufficient_cash",
)

#: §4 lot rules: cn_a 100 shares/lot; us 1 share (whole-share orders).
CN_A_LOT_SHARES = 100
US_LOT_SHARES = 1

_CENT = Decimal("0.01")
_ONE = Decimal("1")
_ZERO = Decimal("0")


def money(value: object) -> Decimal:
    """Money-path entry conversion: ``Decimal(str(x))`` (VD-9)."""
    return Decimal(str(value))


def quantize_money(value: Decimal) -> Decimal:
    """Quantize to 2dp ROUND_HALF_UP — the frozen money discipline (VD-9)."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


class MarketRules:
    """Per-market fee / lot / band / gate rules for one matching run.

    Constructed per run (cheap, side-effect free); ``hk_lot_sizes`` injects
    the board-lot table consumed by the reused ``_hk_board_lot`` mechanism
    (live per-symbol lots are a T9b concern; the fallback chain — table, then
    100, then ``lot_assumptions`` diagnostic — is mandatory either way).
    """

    def __init__(
        self,
        market: str,
        fee_model: Mapping[str, float] | None = None,
        hk_lot_sizes: Mapping[str, int] | None = None,
    ) -> None:
        if market not in state_hash.FEE_MODEL_MARKETS:
            raise ValueError(f"unknown market for paper rules: {market!r}")
        self.market = market
        #: Effective fee values (R7-3 echo source; T5 finalizes the wire field).
        self.effective_fee_model: dict[str, float] = state_hash.effective_fee_model(
            market, dict(fee_model or {})
        )
        self._fm = {key: money(value) for key, value in self.effective_fee_model.items()}
        #: §4 settlement row: T+1 applies to cn_a sells only.
        self.t_plus_1 = market == "cn_a"
        #: §4 price-limit row: bands exist for cn_a only (hk/us: none).
        self.has_price_limits = market == "cn_a"
        self._cn_a = ChinaAEngine({}) if market == "cn_a" else None
        self._hk = (
            GlobalEquityEngine({"hk_lot_sizes": dict(hk_lot_sizes or {})}, market="hk")
            if market == "hk"
            else None
        )

    # ── Lots (§4 手数 row) ──

    def lot_size(self, symbol: str) -> int:
        """Board lot for one symbol: cn_a 100 / hk per-symbol / us 1."""
        if self.market == "hk":
            return int(self._hk._hk_board_lot(symbol))
        return CN_A_LOT_SHARES if self.market == "cn_a" else US_LOT_SHARES

    @property
    def lot_assumptions(self) -> dict[str, int]:
        """HK symbols sized on the fallback lot (DD-4 diagnostic surface)."""
        return dict(self._hk.lot_assumptions) if self._hk is not None else {}

    def lot_violation(self, symbol: str, qty: float) -> bool:
        """Whether ``qty`` violates the market lot rule (→ ``lot_size``).

        Non-positive qty is always a violation (the frozen vocabulary has no
        dedicated code; ``lot_size`` is the closest frozen slot).  cn_a reuses
        ``ChinaAEngine.round_size`` (VD-2): a qty that does not survive the
        100-share floor is not a valid lot.
        """
        q = money(qty)
        if q <= _ZERO:
            return True
        if self.market == "cn_a":
            return money(self._cn_a.round_size(float(q), 0.0)) != q
        if self.market == "hk":
            return q % Decimal(self.lot_size(symbol)) != _ZERO
        return q != q.to_integral_value()  # us: whole shares

    # ── Fees (§4 费用默认 row; Decimal end-to-end, VD-9) ──

    def fee(self, side: str, qty: float, price: float) -> Decimal:
        """Total fee for one fill, quantized to 2dp ROUND_HALF_UP."""
        q = money(qty)
        notional = q * money(price)
        if self.market == "cn_a":
            commission = max(notional * self._fm["commission_rate"], self._fm["commission_min"])
            total = commission + notional * self._fm["transfer_fee"]
            if side == "sell":
                total += notional * self._fm["stamp_tax_sell"]
        elif self.market == "hk":
            commission = max(notional * self._fm["commission_rate"], self._fm["commission_min"])
            # Per order per side, whole HKD, ROUND_HALF_UP (VD-9 registered
            # choice; HKEX itself ceils — delivery-note item #7).
            stamp = (notional * self._fm["stamp_tax_rate"]).quantize(_ONE, rounding=ROUND_HALF_UP)
            total = commission + stamp + notional * self._fm["regulatory_levy_rate"]
        else:
            commission = max(q * self._fm["commission_per_share"], self._fm["commission_min"])
            total = commission + notional * self._fm["sec_fee_rate"]  # SEC fee: 0 (§4)
        return quantize_money(total)

    def buy_cost(self, qty: float, price: float) -> Decimal:
        """Settled buy cost = 2dp notional + fee (§4 cash gate: qty×price+fee ≤ cash)."""
        return quantize_money(money(qty) * money(price)) + self.fee("buy", qty, price)

    # ── Price bands + limit orders (§4 成交价/涨跌停 rows) ──

    def band_rejection(
        self, side: str, close: float, up_limit: float | None, down_limit: float | None
    ) -> str | None:
        """``limit_up``/``limit_down`` at the close-fill price, else None.

        cn_a only (§4: hk/us have no bands; us circuit breakers are NOT
        simulated).  Both sides of the comparison quantize to the 0.01 tick
        (cn_a prices are 2dp; heuristic bands already quantize there) so the
        verdict is exact Decimal equality-or-beyond, deterministic across
        platforms.  A ``None`` band never fabricates a rejection — mirroring
        the reused ``_blocked_by_limit`` primitive's unknown-band semantics.
        """
        if not self.has_price_limits:
            return None
        close_q = money(close).quantize(_CENT, rounding=ROUND_HALF_UP)
        if side == "buy" and up_limit is not None:
            if close_q >= money(up_limit).quantize(_CENT, rounding=ROUND_HALF_UP):
                return "limit_up"
        if side == "sell" and down_limit is not None:
            if close_q <= money(down_limit).quantize(_CENT, rounding=ROUND_HALF_UP):
                return "limit_down"
        return None

    def limit_order_violation(self, side: str, close: float, limit: float | None) -> bool:
        """AM-7 frozen semantics: buy fills only when close ≤ limit; sell only
        when close ≥ limit (fill price = close either way)."""
        if limit is None:
            return False
        close_d, limit_d = money(close), money(limit)
        return close_d > limit_d if side == "buy" else close_d < limit_d

    # ── Financial gates (§4 资金/持仓 row; AM-14 slots 8-10) ──

    def sell_position_rejection(
        self, side: str, qty: float, total: Decimal, bought_today: Decimal
    ) -> str | None:
        """AM-14 slots ``t_plus_1`` → ``insufficient_position``.

        Discrimination note (frozen): available = total − bought_today;
        qty > total → ``insufficient_position``; total ≥ qty > available →
        ``t_plus_1`` (cn_a sells only).  The two conditions are disjoint, so
        the frozen slot order is preserved literally: the ``t_plus_1`` test
        requires ``total >= qty`` and can never steal an
        ``insufficient_position`` case.
        """
        if side != "sell":
            return None
        q = money(qty)
        if self.t_plus_1 and total >= q > total - bought_today:
            return "t_plus_1"
        if q > total:
            return "insufficient_position"
        return None

    def cash_rejection(self, side: str, qty: float, price: float, cash: Decimal) -> str | None:
        """AM-14 slot ``insufficient_cash`` (buys only; §4: qty×price+fee ≤ cash)."""
        if side != "buy":
            return None
        return "insufficient_cash" if self.buy_cost(qty, price) > cash else None
