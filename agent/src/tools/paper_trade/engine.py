"""Deterministic day-loop matching engine for ``paper_trade_step`` (Step 3 / T3).

Frozen surfaces: per-day atomicity (R1-2), AM-14 rejection order
(:data:`rules.REJECTION_ORDER`, first match wins), VD-10 ordering (input
order = matching order; fills/rejected day-ascending then input index;
nav_series day-ascending), AM-3 orders-mode single-day gate, AM-9 readiness
on the merged frame, AM-6 calendar matrix (cn_a = injected calendar truth,
hk/us = zero-calendar fail-closed).  ``strategy_path`` (T7, :mod:`strategy_exec`) generates orders from prior bars and the current private ledger, then drives :func:`run_day_loop` via the public plan/readiness/error seams.
Step 4 (T4) threads :mod:`corporate_actions`: simulated-day boundaries only
(note 2), unverified split-like discontinuities stop the call; unresolved moves reject orders.
Step-3 interpretations (R-V3 → ``suspended``; empty-universe short-circuit;
unknown band skips the check + warns; rejected qty echoed; avg_cost
fee-exclusive 4dp; positions symbol-sorted) live in the STEP3 receipt and
the comments below.  Determinism: no clock, no randomness, dates injected;
unexpected exceptions propagate (transport = engine-internal fault, AM-5) so
a half-day is never observable — the call aborts with no partial result.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Collection, Mapping

import numpy as np
import pandas as pd

from . import calendar, corporate_actions, data, state_hash, wire
from .limits_cn_a import (
    PROV_LIMITS_HEURISTIC, CnALimitsClient, get_limit_status, heuristic_limit_prices)
from .rules import MarketRules, money, quantize_money
from .schema import (
    AccountState, DataProvenance, Fill, NavPoint, Order, PaperTradeStepRequest,
    Position, RejectedOrder, SkippedDay,
)

__all__ = ["DayPlan", "EngineError", "MatchOutcome", "build_day_plan",
           "error_outcome", "match_orders", "readiness_error", "run_day_loop"]

_Q4 = Decimal("0.0001")
_ZERO = Decimal("0")
_SKIP_NON_TRADING = "non_trading_day"
_SKIP_MARKET_CLOSED = "market_closed_inferred"


@dataclass(frozen=True, slots=True)
class EngineError:
    # In-band error material (AM-5); T6 maps it to the wire ErrorEnvelope.
    code: str
    message: str


@dataclass(frozen=True)
class MatchOutcome:
    # Engine result, consumable by T5 (hash/fee echo closure) and T6 (wire).
    # ``error`` set ⇒ in-band error material; arrays empty, ``end_state`` the
    # untouched input state.  ``limit_provenance`` carries the VD-11
    # table/heuristic tokens (wire mapping is T5's schema-closure call).
    end_state: AccountState
    fills: tuple[Fill, ...] = ()
    rejected_orders: tuple[RejectedOrder, ...] = ()
    nav_series: tuple[NavPoint, ...] = ()
    skipped_days: tuple[SkippedDay, ...] = ()
    warnings: tuple[str, ...] = ()
    data_provenance: DataProvenance = field(default_factory=lambda: DataProvenance(source=""))
    effective_fee_model: dict[str, float] = field(default_factory=dict)
    limit_provenance: tuple[str, ...] = ()
    error: EngineError | None = None


@dataclass(frozen=True, slots=True)
class DayPlan:
    date: str
    skip_reason: str | None  # None ⇒ matching day
    warning: str | None


@dataclass
class _LedgerPosition:
    qty: Decimal
    avg_cost: Decimal


def _calendar_days(from_date: str, to_date: str) -> list[str]:
    # Every Gregorian day of the inclusive range (injected dates, no clock).
    start = dt.date.fromisoformat(from_date)
    end = dt.date.fromisoformat(to_date)
    if start > end:
        raise ValueError(f"from_date ({from_date}) > to_date ({to_date})")
    days: list[str] = []
    day = start
    while day <= end:
        days.append(day.isoformat())
        day += dt.timedelta(days=1)
    return days


def build_day_plan(
    market: str,
    from_date: str,
    to_date: str,
    market_data: data.MarketDataResult,
    calendar_client: calendar.TradeCalendarClient | None,
) -> list[DayPlan]:
    # Day enumeration per the AM-6 matrix.  cn_a: the injected CH calendar is
    # the truth — a missing client RAISES (weekdays are never silently treated
    # as cn_a trading days); closed dates become non_trading_day skips.
    if market == calendar.CN_A_MARKET:
        if calendar_client is None:
            raise ValueError(
                "cn_a day enumeration requires an injected TradeCalendarClient "
                "(ClickHouse trade_calendar is the AM-6 truth source); refusing "
                "to treat weekdays as cn_a trading days"
            )
        trading = set(calendar.trading_days_in_range(calendar_client, market, from_date, to_date))
        return [
            DayPlan(day, None if day in trading else _SKIP_NON_TRADING, None)
            for day in _calendar_days(from_date, to_date)
        ]

    candidates = calendar.hk_us_candidate_days(from_date, to_date)
    if not market_data.symbols:
        # Empty-universe short-circuit (T2 handoff): classify_zero_calendar_day
        # reads an empty universe literally as all-market zero bar, which would
        # break a cash-only account; with nothing to classify, every candidate
        # weekday is a cash-only matching day.
        return [DayPlan(day, None, None) for day in candidates]

    # hk/us zero-calendar fail-closed: mid-range all-market zero bar →
    # market_closed_inferred + mandatory warning (never non_trading_day —
    # that reason is cn_a-only vocabulary); any bar → matching day, and the
    # zero-bar symbols reject `suspended` per-order via ladder slot 3.
    availability = data.day_bar_availability(market_data, candidates)
    plan: list[DayPlan] = []
    for day in candidates:
        verdict = calendar.classify_zero_calendar_day(
            market, day, is_target_day=(day == to_date),
            symbols=market_data.symbols, symbols_with_bars=availability[day])
        if verdict.kind == calendar.VERDICT_NOT_READY:
            # Target-day all-market zero bar (AM-6①).  The AM-9 readiness
            # gate in run_day_loop runs BEFORE the loop over the same bar
            # facts (assess_readiness ⇔ this verdict) and returns the in-band
            # PAPER_DATA_NOT_READY material; this entry is a placeholder the
            # loop never reaches.  Never a transport-class raise — a not-ready
            # target day is a retryable data fact, not an engine fault (AM-5).
            plan.append(DayPlan(day, None, None))
        elif verdict.kind == calendar.VERDICT_MARKET_CLOSED_INFERRED:
            plan.append(DayPlan(day, _SKIP_MARKET_CLOSED, verdict.warning))
        else:
            plan.append(DayPlan(day, None, None))
    return plan


class _MatchSession:
    # Mutable ledger + caches for one run_day_loop call (single-threaded).

    def __init__(
        self,
        market: str,
        rules: MarketRules,
        market_data: data.MarketDataResult,
        account_state: AccountState,
        limits_client: CnALimitsClient | None,
        corporate_action_unresolved_by_day: Mapping[str, Collection[str]],
        ca_plan: corporate_actions.CorporateActionPlan,
    ) -> None:
        self.market = market
        self.rules = rules
        self.market_data = market_data
        self.limits_client = limits_client
        self.ca_by_day = corporate_action_unresolved_by_day
        self.cash = quantize_money(money(account_state.cash))
        self.positions: dict[str, _LedgerPosition] = {}
        for position in account_state.positions:
            self._merge_input_position(position.symbol, money(position.qty), money(position.avg_cost))
        self.bought_today: dict[str, Decimal] = {}
        self.fills: list[Fill] = []
        self.rejected: list[RejectedOrder] = []
        self.nav_series: list[NavPoint] = []
        self.skipped: list[SkippedDay] = []
        self.warnings: list[str] = list(market_data.warnings) + list(ca_plan.warnings)
        self.limit_provenance: list[str] = []
        self._band_cache: dict[tuple[str, str], tuple[float | None, float | None]] = {}

    def _merge_input_position(self, symbol: str, qty: Decimal, avg_cost: Decimal) -> None:
        # Duplicate input symbols merge additively (trusted RM ledger; the
        # merge keeps the invariant deterministic instead of crashing).
        existing = self.positions.get(symbol)
        if existing is None:
            self.positions[symbol] = _LedgerPosition(qty, avg_cost.quantize(_Q4, rounding=ROUND_HALF_UP))
            return
        new_qty = existing.qty + qty
        merged = existing.qty * existing.avg_cost + qty * avg_cost
        basis = merged / new_qty if new_qty > _ZERO else avg_cost
        self.positions[symbol] = _LedgerPosition(
            new_qty, basis.quantize(_Q4, rounding=ROUND_HALF_UP))

    def match_order(self, day: DayPlan, order: Order) -> None:
        # The AM-14 ladder: first match wins, one reason per order.
        symbol = order.symbol
        sym_data = self.market_data.data.get(symbol)
        # Slot 1 unknown_symbol: no served data at all in the fetch window.
        if sym_data is None or not sym_data.bar_dates:
            self._reject(day, order, "unknown_symbol", f"no market data for {symbol} in the fetch window")
            return
        # Slot 2 non_trading_day: cn_a calendar truth (AM-6).
        if day.skip_reason == _SKIP_NON_TRADING:
            self._reject(day, order, "non_trading_day", f"{self.market} calendar closed on {day.date}")
            return
        # Slot 3 suspended: zero bar today, or an R-V3 untradable bar
        # (documented mapping: suspended is the closest frozen code).
        if not sym_data.has_bar(day.date):
            self._reject(day, order, "suspended", f"no bar for {symbol} on {day.date}; position valued carry-forward")
            return
        if day.date in sym_data.untradable_dates:
            self._reject(day, order, "suspended", f"bar for {symbol} on {day.date} failed the price sanity gate (R-V3)")
            return
        # Slot 4 corporate_action_unresolved: T4 detector union + injected seam.
        if symbol in self.ca_by_day.get(day.date, ()):
            self._reject(day, order, "corporate_action_unresolved",
                         f"unexplained price discontinuity for {symbol} on {day.date}; "
                         "fail-closed rejection (no clean split ratio resolved)")
            return
        # Slot 5 lot_size.
        if self.rules.lot_violation(symbol, order.qty):
            self._reject(day, order, "lot_size", f"qty {order.qty} violates the "
                         f"{self.rules.lot_size(symbol)}-share lot rule for {symbol}")
            return
        close = float(sym_data.frame.loc[pd.Timestamp(day.date), "close"])
        # Slot 6 limit_up / limit_down: cn_a bands, BEFORE the AM-7 check.
        if self.rules.has_price_limits:
            up, down = self._band(symbol, day.date, sym_data)
            code = self.rules.band_rejection(order.side, close, up, down)
            if code == "limit_up":
                self._reject(day, order, code, f"close {close:.2f} at or above up limit {up:.2f}; buy rejected")
                return
            if code == "limit_down":
                self._reject(day, order, code, f"close {close:.2f} at or below down limit {down:.2f}; sell rejected")
                return
        # Slot 7 limit_not_marketable (AM-7: buy fills only close ≤ limit,
        # sell only close ≥ limit; fill price = close).
        if self.rules.limit_order_violation(order.side, close, order.limit):
            detail = (
                f"close {close:.2f} > limit {order.limit:.2f}"
                if order.side == "buy"
                else f"close {close:.2f} < limit {order.limit:.2f}"
            )
            self._reject(day, order, "limit_not_marketable", detail)
            return
        # Slots 8/9 t_plus_1 → insufficient_position (disjoint conditions;
        # available = total − bought_today, cn_a sells only).
        total = self.positions[symbol].qty if symbol in self.positions else _ZERO
        bought = self.bought_today.get(symbol, _ZERO)
        code = self.rules.sell_position_rejection(order.side, order.qty, total, bought)
        if code == "t_plus_1":
            self._reject(day, order, code, f"sell qty {order.qty} exceeds available position "
                         f"{total - bought} (T+1: {bought} share(s) bought today are not sellable)")
            return
        if code == "insufficient_position":
            self._reject(day, order, code, f"sell qty {order.qty} exceeds position {total}")
            return
        # Slot 10 insufficient_cash (§4: qty×price+fee ≤ cash).
        code = self.rules.cash_rejection(order.side, order.qty, close, self.cash)
        if code == "insufficient_cash":
            cost = self.rules.buy_cost(order.qty, close)
            self._reject(day, order, code, f"buy cost {cost} exceeds cash {self.cash}")
            return
        self._fill(day.date, order, close)

    def _reject(self, day: DayPlan, order: Order, code: str, detail: str) -> None:
        self.rejected.append(
            RejectedOrder(trade_date=day.date, symbol=order.symbol, side=order.side,
                          qty=order.qty, reason_code=code, detail=detail)
        )

    def _fill(self, day: str, order: Order, close: float) -> None:
        # Decimal settlement (VD-9): 2dp notional ± 2dp fee; avg_cost is the
        # fee-exclusive weighted average fill price, quantized 4dp HALF_UP at
        # every mutation so internal chaining equals the RM round-trip.
        qty = money(order.qty)
        price = money(close)
        fee = self.rules.fee(order.side, order.qty, close)
        notional = quantize_money(qty * price)
        if order.side == "buy":
            self.cash -= notional + fee
            existing = self.positions.get(order.symbol)
            if existing is None or existing.qty == _ZERO:
                basis = price
            else:
                basis = (existing.qty * existing.avg_cost + qty * price) / (existing.qty + qty)
            self.positions[order.symbol] = _LedgerPosition(
                qty if existing is None or existing.qty == _ZERO else existing.qty + qty,
                basis.quantize(_Q4, rounding=ROUND_HALF_UP))
            self.bought_today[order.symbol] = self.bought_today.get(order.symbol, _ZERO) + qty
        else:
            self.cash += notional - fee
            self.positions[order.symbol].qty -= qty
        # VD-15/B2 dual mode at the fill boundary: plain Orders → ""; StrategyOrders → ≤200 chars.
        self.fills.append(Fill(trade_date=day, symbol=order.symbol, side=order.side,
                               qty=order.qty, price=close, fee=float(fee),
                               reason=wire.strategy_fill_reason(getattr(order, "reason", None))))

    def _band(self, symbol: str, day: str, sym_data: data.SymbolData) -> tuple[float | None, float | None]:
        # VD-11: CH table first (injected client), heuristic board-ratio
        # fallback (china_a._price_limit via limits_cn_a), provenance tokens
        # recorded per symbol-day.  A band is never fabricated: with no table
        # row and no previous close the check is SKIPPED with a warning —
        # the reused _blocked_by_limit primitive's unknown-band semantics.
        key = (symbol, day)
        if key in self._band_cache:
            return self._band_cache[key]
        prev_close = _prev_close(sym_data, day)
        up: float | None
        down: float | None
        if self.limits_client is not None:
            status = get_limit_status(self.limits_client, symbol, day, prev_close)
            up, down = status.up_limit, status.down_limit
            self.limit_provenance.extend(f"{symbol}@{day}:{token}" for token in status.provenance)
        elif prev_close is not None:
            up, down = heuristic_limit_prices(symbol, prev_close, is_st=False)
            self.limit_provenance.append(f"{symbol}@{day}:{PROV_LIMITS_HEURISTIC}")
        else:
            up, down = None, None
        if up is None and down is None:
            self.warnings.append(f"limit band unavailable for {symbol} on {day}: no table row "
                                 "and no previous close in the fetch window; price-limit check skipped")
        self._band_cache[key] = (up, down)
        return up, down

    def add_nav_row(self, day: str) -> None:
        # §4 NAV row: close × positions + cash.  Per-position values quantize
        # 2dp; suspended symbols value carry-forward (last positive close on
        # or before the day), falling back to avg_cost with a warning (B3).
        position_value = _ZERO
        for symbol in sorted(self.positions):
            position = self.positions[symbol]
            if position.qty == _ZERO:
                continue
            price = self._valuation_price(symbol, day, position.avg_cost)
            position_value += quantize_money(position.qty * price)
        position_value = quantize_money(position_value)
        self.nav_series.append(NavPoint(date=day, nav=float(self.cash + position_value),
                                        cash=float(self.cash), position_value=float(position_value)))

    def _valuation_price(self, symbol: str, day: str, avg_cost: Decimal) -> Decimal:
        sym_data = self.market_data.data.get(symbol)
        if sym_data is not None:
            if sym_data.has_bar(day) and day not in sym_data.untradable_dates:
                return money(float(sym_data.frame.loc[pd.Timestamp(day), "close"]))
            if not sym_data.frame.empty:
                prior = sym_data.frame.loc[: pd.Timestamp(day), "close"].dropna()
                prior = prior[np.isfinite(prior) & (prior > 0)]
                if not prior.empty:
                    return money(float(prior.iloc[-1]))
        self.warnings.append(f"valuation: {symbol} has no usable close on or before {day}; "
                             "position valued at avg_cost")
        return avg_cost

    def end_state(self) -> AccountState:
        # Symbol-sorted (deterministic), zero-qty rows dropped.
        return AccountState(
            cash=float(self.cash),
            positions=tuple(
                Position(symbol=symbol, qty=float(position.qty), avg_cost=float(position.avg_cost))
                for symbol, position in sorted(self.positions.items()) if position.qty != _ZERO))


def _prev_close(sym_data: data.SymbolData, day: str) -> float | None:
    # Last positive close strictly before the day (heuristic band base).
    if sym_data.frame.empty:
        return None
    prior = sym_data.frame.loc[: pd.Timestamp(day), "close"]
    prior = prior.iloc[:-1] if sym_data.has_bar(day) else prior
    prior = prior.dropna()
    prior = prior[np.isfinite(prior) & (prior > 0)]
    return float(prior.iloc[-1]) if not prior.empty else None


def error_outcome(
    error: EngineError,
    account_state: AccountState,
    market_data: data.MarketDataResult,
    market: str,
    fee_model: Mapping[str, float] | None,
) -> MatchOutcome:
    return MatchOutcome(
        end_state=account_state,
        data_provenance=market_data.provenance,
        effective_fee_model=state_hash.effective_fee_model(market, dict(fee_model or {})),
        error=error,
    )


def readiness_error(to_date: str, market_data: data.MarketDataResult, plan: Collection[DayPlan]) -> EngineError | None:
    # AM-9 gate unless the cn_a calendar truth says to_date is closed; an empty
    # universe is vacuously ready (T2).  T7 runs this BEFORE any strategy day so
    # a retryable data fact is never masked by a non-retryable strategy failure.
    target = next((entry for entry in plan if entry.date == to_date), None)
    if target is None or target.skip_reason != _SKIP_NON_TRADING:
        verdict = data.assess_readiness(market_data, to_date)
        if not verdict.ready:
            return EngineError(verdict.code or data.NOT_READY_CODE, verdict.message or "")
    return None


def match_orders(
    request: PaperTradeStepRequest,
    *,
    market_data: data.MarketDataResult,
    calendar_client: calendar.TradeCalendarClient | None = None,
    limits_client: CnALimitsClient | None = None,
    corporate_action_unresolved_by_day: Mapping[str, Collection[str]] | None = None,
    hk_lot_sizes: Mapping[str, int] | None = None,
) -> MatchOutcome:
    # Orders-mode entry (AM-3 single-day); strategy_path mode bypasses this and
    # drives run_day_loop through strategy_exec (T7).  Contract violations
    # return stable INVALID_REQUEST material — no matching, no half-day.
    if market_data.market != request.market:
        raise ValueError(
            f"market_data was fetched for {market_data.market!r}, request says {request.market!r}"
        )
    if request.from_date != request.to_date:
        error = EngineError("INVALID_REQUEST", "orders mode requires from_date == to_date "
                            f"(AM-3 single-day); got from_date={request.from_date} to_date={request.to_date}")
        return error_outcome(error, request.account_state, market_data, request.market, request.fee_model)
    if request.orders is None:
        error = EngineError("INVALID_REQUEST", "orders mode requires the orders array; "
                            "strategy_path execution lands in Step 7")
        return error_outcome(error, request.account_state, market_data, request.market, request.fee_model)
    return run_day_loop(
        market=request.market, account_state=request.account_state,
        from_date=request.from_date, to_date=request.to_date, market_data=market_data,
        orders_by_day={request.from_date: request.orders}, fee_model=request.fee_model,
        calendar_client=calendar_client, limits_client=limits_client, hk_lot_sizes=hk_lot_sizes,
        corporate_action_unresolved_by_day=corporate_action_unresolved_by_day)


def run_day_loop(
    *,
    market: str,
    account_state: AccountState,
    from_date: str,
    to_date: str,
    orders_by_day: Mapping[str, Collection[Order]],
    order_provider: Callable[[str, AccountState], Collection[Order]] | None = None,
    market_data: data.MarketDataResult,
    fee_model: Mapping[str, float] | None = None,
    calendar_client: calendar.TradeCalendarClient | None = None,
    limits_client: CnALimitsClient | None = None,
    corporate_action_unresolved_by_day: Mapping[str, Collection[str]] | None = None,
    hk_lot_sizes: Mapping[str, int] | None = None,
) -> MatchOutcome:
    # Day-loop core: enumerate [from, to], gate readiness (AM-9), match
    # serially (VD-10).  Multi-day ranges are only reachable through this
    # seam (orders mode is single-day, AM-3).  Day k's ledger state carries
    # into day k+1 (R1-2: previous end_state = next day's input).
    if market_data.market != market:
        raise ValueError(f"market_data was fetched for {market_data.market!r}, market says {market!r}")
    rules = MarketRules(market, fee_model, hk_lot_sizes)
    plan = build_day_plan(market, from_date, to_date, market_data, calendar_client)

    # Readiness gate (AM-9) — shared with the T7 strategy seam.
    if (error := readiness_error(to_date, market_data, plan)) is not None:
        return error_outcome(error, account_state, market_data, market, fee_model)

    # OHLC/volume ratios identify discontinuities, not authoritative actions.
    # All production execution series are raw, including A-shares. Never
    # multiply a holding based only on a price crash that resembles a split.
    ca_plan = corporate_actions.build_plan(
        market_data, [e.date for e in plan if e.skip_reason is None], account_state.positions)
    if ca_plan.clean_by_day:
        day = min(ca_plan.clean_by_day)
        symbols = ", ".join(event.symbol for event in ca_plan.clean_by_day[day])
        return error_outcome(EngineError(
            "PAPER_DATA_NOT_READY",
            f"Unverified corporate action on {day} for {symbols}; "
            "price/volume ratios cannot establish a split. Reconcile against an authoritative action record."),
            account_state, market_data, market, fee_model)
    session = _MatchSession(
        market, rules, market_data, account_state, limits_client,
        corporate_actions.merge_unresolved(
            corporate_action_unresolved_by_day, ca_plan.unresolved_by_day),
        ca_plan)
    for entry in plan:
        session.bought_today = {}  # T+1 availability resets each day
        if entry.skip_reason is not None:
            session.skipped.append(SkippedDay(date=entry.date, reason=entry.skip_reason))
            if entry.warning:
                session.warnings.append(entry.warning)
        # Orders run the ladder on EVERY day: a cn_a non-trading day rejects
        # at slot 2; an inferred-closed hk/us day rejects at slot 3
        # (suspended — never non_trading_day, which is cn_a-only vocabulary).
        orders = (order_provider(entry.date, session.end_state())
                  if order_provider is not None and entry.skip_reason is None
                  else orders_by_day.get(entry.date, ()))
        for order in tuple(orders):
            session.match_order(entry, order)
        if entry.skip_reason is None:
            session.add_nav_row(entry.date)  # per-day commit: fills + one nav row

    for symbol, lot in sorted(rules.lot_assumptions.items()):
        session.warnings.append(f"lot assumption: {symbol} sized on the default {lot}-share "
                                "board lot (no lot table entry)")
    return MatchOutcome(
        end_state=session.end_state(),
        fills=tuple(session.fills),
        rejected_orders=tuple(session.rejected),
        nav_series=tuple(session.nav_series),
        skipped_days=tuple(session.skipped),
        warnings=tuple(dict.fromkeys(session.warnings)),
        data_provenance=replace(market_data.provenance, corporate_actions=(
            tuple(market_data.provenance.corporate_actions) + ca_plan.provenance)),
        effective_fee_model=rules.effective_fee_model,
        limit_provenance=tuple(dict.fromkeys(session.limit_provenance)),
    )
