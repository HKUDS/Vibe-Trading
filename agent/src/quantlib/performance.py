"""Portfolio return when the client, not the manager, moves the money.

``backtest/metrics.py`` computes every figure from an equity curve and a single
scalar ``initial_cash``. That is the right model for a backtest, where the only
capital event is the opening deposit. It cannot express a real client account,
where money arrives and leaves on dates the manager did not choose. Feeding such
an account into a scalar-funded metric silently reports the *client's* deposits
as the *manager's* performance.

This module is the parallel path. It takes a valuation series plus an irregular
:class:`~src.entities.cashflow.CashFlowSeries` and reports the two answers that
actually exist, kept deliberately distinct:

``time_weighted_return``
    True daily-valuation TWR. Chain-links the return of each interval between
    valuations, so the size and the date of an external flow cancel out of the
    product entirely. This is the manager-skill number, and it is what GIPS
    composites report.

``modified_dietz_return``
    The classic day-weighted *approximation* to a money-weighted return. It
    needs only an opening value, a closing value, and dated flows -- no interim
    valuations -- which is why it survives in reporting stacks that cannot
    revalue daily. It is NOT a TWR, despite being widely mislabelled as one; it
    weights each flow by the fraction of the period it was invested and is
    therefore sensitive to flow timing.

``money_weighted_return``
    The internal rate of return (XIRR) of the client's own cash: opening value
    out, flows as they fell, closing value back. This is the client-experience
    number, and it moves with how much money was exposed to which stretch of
    the return path.

WHICH FLOWS ARE EXTERNAL
------------------------
Only movements **across the portfolio boundary** are external. A contribution,
capital call, subscription, transfer in, distribution, redemption, withdrawal,
or transfer out changes the capital base without the manager earning or losing
anything, so it must be removed before a return is struck
(:data:`DEFAULT_EXTERNAL_KINDS`).

A dividend, coupon, interest payment, fee, expense, purchase, or sale proceed is
**internal**: it is already inside the valuation series, and netting it out a
second time double-counts it (:data:`DEFAULT_INTERNAL_KINDS`). Valuation marks
(``nav``, ``residual_value``, ``valuation``) are not cash at all and are ignored.

A kind in neither table is an error, not a default. Silently ignoring an
unrecognised kind would understate the flow adjustment and produce a
plausible-looking wrong return; the caller must classify it explicitly through
``external_kinds=`` or ``internal_kinds=``.

SIGN CONVENTION
---------------
``CashFlow.amount`` is holder-perspective: a ``contribution`` is **negative**
because the cash leaves the client's pocket (see ``src.entities.cashflow``).
The portfolio sees the mirror image, so every external flow is negated exactly
once, here, at :func:`external_flows`. The library never asks a caller to flip
a sign, and :func:`money_weighted_return` consumes ``CashFlow.amount`` as-is
because the holder perspective *is* the IRR perspective.

Only the standard library is imported, matching the rest of ``quantlib``: an
optional numerical dependency missing elsewhere cannot break this module.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from src.entities.cashflow import CashFlow, CashFlowSeries, normalize_kind
from src.entities.models import normalize_date

__all__ = [
    "DAYS_PER_YEAR",
    "DEFAULT_EXTERNAL_KINDS",
    "DEFAULT_INTERNAL_KINDS",
    "FLOW_TIMING_END",
    "FLOW_TIMING_START",
    "ModifiedDietzReturn",
    "MoneyWeightedReturn",
    "SubPeriodReturn",
    "TimeWeightedReturn",
    "UnsolvableRateError",
    "external_flows",
    "modified_dietz_return",
    "money_weighted_return",
    "time_weighted_return",
    "xirr",
]

#: Day basis for annualisation and for the XIRR time axis. 365 actual days is
#: the XIRR convention (and the one Excel's ``XIRR`` uses), not 252 trading
#: days: client cash moves on calendar dates, including weekends.
DAYS_PER_YEAR = 365.0

#: Kinds that move cash across the portfolio boundary. See the module docstring.
DEFAULT_EXTERNAL_KINDS: frozenset[str] = frozenset(
    {
        "contribution",
        "capital_call",
        "subscription",
        "transfer_in",
        "distribution",
        "redemption",
        "withdrawal",
        "transfer_out",
    }
)

#: Kinds that occur *inside* the portfolio and are therefore already reflected
#: in the valuation series. Netting them out again double-counts them.
DEFAULT_INTERNAL_KINDS: frozenset[str] = frozenset(
    {
        "dividend",
        "coupon",
        "interest",
        "principal",
        "fee",
        "expense",
        "purchase",
        "proceeds",
    }
)

#: A flow dated on a valuation date is deemed to settle *after* that valuation
#: is struck, so it belongs to the period that ends there.
FLOW_TIMING_END = "end"

#: A flow dated on a valuation date is deemed to settle *before* the next
#: interval begins, so it belongs to the period that starts there.
FLOW_TIMING_START = "start"

_FLOW_TIMINGS = (FLOW_TIMING_END, FLOW_TIMING_START)

#: Bisection floor for the IRR search. A rate at or below -100% would make the
#: discount base non-positive, so the solver stops just short of it.
_IRR_LOWER_BOUND = -0.999999

#: Largest rate the bracket expansion will reach before giving up.
_IRR_UPPER_LIMIT = 1e9

#: Absolute width of the final IRR bracket.
_IRR_TOLERANCE = 1e-12

#: Hard iteration cap for the bisection, so a pathological input cannot spin.
_IRR_MAX_ITERATIONS = 400


class UnsolvableRateError(ValueError):
    """Raised when a cash-flow stream admits no single internal rate of return."""


@dataclass(frozen=True)
class SubPeriodReturn:
    """One interval between two consecutive valuations.

    Attributes:
        start: Date of the opening valuation of the interval.
        end: Date of the closing valuation of the interval.
        start_value: Portfolio value at ``start``.
        end_value: Portfolio value at ``end``.
        external_flow: Net external cash into the portfolio during the
            interval, portfolio-perspective (positive is money arriving).
        period_return: Return of the interval with the external flow removed.
    """

    start: date
    end: date
    start_value: float
    end_value: float
    external_flow: float
    period_return: float


@dataclass(frozen=True)
class TimeWeightedReturn:
    """Chain-linked true time-weighted return over the whole window.

    Attributes:
        total_return: Compounded return, ``prod(1 + r_i) - 1``.
        sub_periods: Every interval's decomposition, in date order.
        start_date: Date of the first valuation.
        end_date: Date of the last valuation.
        start_value: Value at ``start_date``.
        end_value: Value at ``end_date``.
        net_external_flow: Sum of the external flows, portfolio-perspective.
        flow_timing: Which boundary a flow dated on a valuation date was
            assigned to; see :data:`FLOW_TIMING_END` and
            :data:`FLOW_TIMING_START`.
        annualized_return: Geometrically annualised ``total_return``, or
            ``None`` when the window is shorter than a year. Annualising a
            three-month figure states a full-year result that was never
            observed, so it is withheld rather than extrapolated.
    """

    total_return: float
    sub_periods: tuple[SubPeriodReturn, ...]
    start_date: date
    end_date: date
    start_value: float
    end_value: float
    net_external_flow: float
    flow_timing: str
    annualized_return: float | None


@dataclass(frozen=True)
class ModifiedDietzReturn:
    """Day-weighted money-weighted approximation over a single period.

    Attributes:
        total_return: ``(V1 - V0 - F) / (V0 + sum(w_i * F_i))``.
        start_date: Opening date of the period.
        end_date: Closing date of the period.
        start_value: Value at ``start_date``.
        end_value: Value at ``end_date``.
        net_external_flow: ``F``, the sum of external flows.
        weighted_external_flow: ``sum(w_i * F_i)``.
        average_capital: The denominator, ``V0 + sum(w_i * F_i)``.
        flow_weights: ``(date, amount, weight)`` per external flow, in date
            order, so a reported figure can be audited line by line.
        annualized_return: Geometrically annualised ``total_return``, or
            ``None`` for a window shorter than a year.
    """

    total_return: float
    start_date: date
    end_date: date
    start_value: float
    end_value: float
    net_external_flow: float
    weighted_external_flow: float
    average_capital: float
    flow_weights: tuple[tuple[date, float, float], ...]
    annualized_return: float | None


@dataclass(frozen=True)
class MoneyWeightedReturn:
    """Internal rate of return of the client's own cash.

    Attributes:
        annualized_return: The XIRR itself, an annual rate on a
            :data:`DAYS_PER_YEAR` actual-day basis.
        period_return: ``(1 + annualized_return) ** years - 1``, the same rate
            expressed over the observed window rather than per annum.
        start_date: Date of the opening valuation.
        end_date: Date of the closing valuation.
        start_value: Opening value, entered into the IRR as an outflow.
        end_value: Closing value, entered into the IRR as an inflow.
        net_external_flow: Net external cash into the portfolio,
            portfolio-perspective, for reconciliation against the TWR result.
        years: Window length in years on the same actual-day basis.
        iterations: Bisection steps the solver used, exposed so a
            near-degenerate stream is visible rather than silently trusted.
    """

    annualized_return: float
    period_return: float
    start_date: date
    end_date: date
    start_value: float
    end_value: float
    net_external_flow: float
    years: float
    iterations: int


# ─── Input normalisation ───


def _normalize_valuations(
    valuations: Mapping[date | datetime | str, float]
    | Sequence[tuple[date | datetime | str, float]],
) -> tuple[tuple[date, float], ...]:
    """Coerce a valuation series to sorted ``(date, value)`` pairs.

    Args:
        valuations: Either a mapping of date to value, or a sequence of
            two-element ``(date, value)`` pairs. Dates go through
            ``src.entities.models.normalize_date``, so ISO-8601 strings and
            ``datetime`` instances are accepted.

    Returns:
        Pairs sorted by date, with at least two entries.

    Raises:
        ValueError: If fewer than two valuations were supplied, a pair is
            malformed, a value is not finite, or a date repeats. A repeated
            date is rejected rather than deduplicated because two different
            marks for one day have no defensible ordering.
    """
    if isinstance(valuations, Mapping):
        raw_items: list[tuple[object, object]] = list(valuations.items())
    else:
        raw_items = []
        for index, item in enumerate(valuations):
            if isinstance(item, (str, bytes)) or not isinstance(item, Sequence):
                raise ValueError(
                    f"valuations[{index}] must be a (date, value) pair, got "
                    f"{type(item).__name__}"
                )
            pair = tuple(item)
            if len(pair) != 2:
                raise ValueError(
                    f"valuations[{index}] must have exactly two elements "
                    f"(date, value), got {len(pair)}"
                )
            raw_items.append((pair[0], pair[1]))

    if len(raw_items) < 2:
        raise ValueError(
            "a return needs an opening and a closing valuation; got "
            f"{len(raw_items)}"
        )

    resolved: list[tuple[date, float]] = []
    for raw_date, raw_value in raw_items:
        when = normalize_date(raw_date, field_name="valuation date")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"valuation on {when} must be numeric, got {raw_value!r}"
            ) from exc
        if not math.isfinite(value):
            raise ValueError(
                f"valuation on {when} must be finite, got {raw_value!r}; a "
                "missing mark must be fixed at the source, not carried as NaN"
            )
        resolved.append((when, value))

    resolved.sort(key=lambda item: item[0])
    for earlier, later in zip(resolved, resolved[1:], strict=False):
        if earlier[0] == later[0]:
            raise ValueError(
                f"two valuations share the date {earlier[0]}; a single day can "
                "carry only one mark"
            )
    return tuple(resolved)


def external_flows(
    flows: CashFlowSeries | Iterable[CashFlow] | None,
    *,
    external_kinds: Iterable[str] | None = None,
    internal_kinds: Iterable[str] | None = None,
) -> tuple[tuple[date, float], ...]:
    """Select the boundary-crossing flows and restate them portfolio-side.

    The returned amounts are the **negation** of ``CashFlow.amount``: the input
    is holder-perspective (a contribution is cash leaving the client, hence
    negative), the output is portfolio-perspective (a contribution is cash
    arriving, hence positive). This is the only place in the module where that
    flip happens.

    Args:
        flows: A ``CashFlowSeries``, any iterable of ``CashFlow``, or ``None``
            for a period with no client activity.
        external_kinds: Kinds to treat as boundary-crossing. Defaults to
            :data:`DEFAULT_EXTERNAL_KINDS`. Labels are normalised, so
            ``"Capital Call"`` matches ``"capital_call"``.
        internal_kinds: Kinds to treat as already inside the valuation series.
            Defaults to :data:`DEFAULT_INTERNAL_KINDS`.

    Returns:
        ``(date, amount_into_portfolio)`` pairs in date order. Several flows on
        one date stay as several entries; callers that need one number per date
        aggregate themselves.

    Raises:
        ValueError: If a flow's kind appears in both classifications, or in
            neither. An unclassified kind is refused rather than assumed
            internal, because assuming would understate the flow adjustment and
            return a plausible wrong number.
    """
    if flows is None:
        return ()

    external = (
        DEFAULT_EXTERNAL_KINDS
        if external_kinds is None
        else frozenset(normalize_kind(kind) for kind in external_kinds)
    )
    internal = (
        DEFAULT_INTERNAL_KINDS
        if internal_kinds is None
        else frozenset(normalize_kind(kind) for kind in internal_kinds)
    )
    overlap = external & internal
    if overlap:
        raise ValueError(
            "a kind cannot be both external and internal; overlapping: "
            f"{', '.join(sorted(overlap))}"
        )

    selected: list[tuple[date, float]] = []
    for flow in flows:
        if flow.is_valuation:
            continue
        if flow.kind in external:
            selected.append((flow.date, -flow.amount))
        elif flow.kind not in internal:
            raise ValueError(
                f"cash-flow kind {flow.kind!r} on {flow.date} is classified "
                "neither external nor internal, so it cannot be treated as "
                "either. Pass external_kinds=[...] or internal_kinds=[...] to "
                "say which side of the portfolio boundary it crosses. Known "
                f"external: {', '.join(sorted(external))}. Known internal: "
                f"{', '.join(sorted(internal))}."
            )
    selected.sort(key=lambda item: item[0])
    return tuple(selected)


def _annualize(total_return: float, days: int) -> float | None:
    """Annualise a holding-period return, or decline to when the window is short.

    Args:
        total_return: Return over the whole window, as a decimal fraction.
        days: Calendar days spanned by the window.

    Returns:
        The annualised return, or ``None`` when ``days`` is below
        :data:`DAYS_PER_YEAR`. A total wipeout annualises to ``-1.0``, matching
        ``backtest/metrics.py``'s handling of a non-positive growth factor
        rather than raising a negative base to a fractional power.
    """
    if days < DAYS_PER_YEAR:
        return None
    growth = 1.0 + total_return
    if growth <= 0.0:
        return -1.0
    try:
        return float(growth ** (DAYS_PER_YEAR / days) - 1.0)
    except OverflowError:
        return None


# ─── Time-weighted return ───


def _assign_flows_to_periods(
    dates: Sequence[date],
    flows: Sequence[tuple[date, float]],
    flow_timing: str,
) -> list[float]:
    """Bucket external flows into the intervals between valuations.

    With :data:`FLOW_TIMING_END` interval ``k`` covers ``(d[k-1], d[k]]``, so a
    flow dated on a valuation date belongs to the interval ending there and a
    flow dated on the *first* valuation is already inside the opening value.
    With :data:`FLOW_TIMING_START` interval ``k`` covers ``[d[k-1], d[k])``, so
    a flow dated on a valuation date opens the next interval and a flow on the
    *last* valuation falls outside the window.

    Args:
        dates: Valuation dates in ascending order.
        flows: Portfolio-perspective ``(date, amount)`` pairs.
        flow_timing: One of :data:`FLOW_TIMING_END` / :data:`FLOW_TIMING_START`.

    Returns:
        One net flow per interval, so ``len(dates) - 1`` entries.

    Raises:
        ValueError: If a flow falls outside the valuation window. Dropping it
            silently would move the client's money into the manager's return.
    """
    first, last = dates[0], dates[-1]
    buckets = [0.0] * (len(dates) - 1)
    for when, amount in flows:
        if when < first or when > last:
            raise ValueError(
                f"cash flow on {when} lies outside the valuation window "
                f"{first}..{last}; extend the valuations or trim the flows "
                "rather than dropping the flow"
            )
        if flow_timing == FLOW_TIMING_END:
            if when == first:
                raise ValueError(
                    f"cash flow on {when} coincides with the opening valuation "
                    f"and flow_timing={FLOW_TIMING_END!r} places it inside the "
                    "opening value, where it would be counted twice. Use "
                    f"flow_timing={FLOW_TIMING_START!r}, or start the "
                    "valuations one period earlier."
                )
            # First interval whose closing date is at or after the flow.
            index = next(k for k in range(1, len(dates)) if dates[k] >= when) - 1
        else:
            if when == last:
                raise ValueError(
                    f"cash flow on {when} coincides with the closing valuation "
                    f"and flow_timing={FLOW_TIMING_START!r} places it after the "
                    "window ends. Use flow_timing="
                    f"{FLOW_TIMING_END!r}, or extend the valuations."
                )
            # Last interval whose opening date is at or before the flow.
            index = max(k for k in range(len(dates) - 1) if dates[k] <= when)
        buckets[index] += amount
    return buckets


def time_weighted_return(
    valuations: Mapping[date | datetime | str, float]
    | Sequence[tuple[date | datetime | str, float]],
    flows: CashFlowSeries | Iterable[CashFlow] | None = None,
    *,
    flow_timing: str = FLOW_TIMING_END,
    external_kinds: Iterable[str] | None = None,
    internal_kinds: Iterable[str] | None = None,
) -> TimeWeightedReturn:
    """Chain-link the true time-weighted return across a valuation series.

    Each interval's return removes that interval's external flow before
    dividing, so the product telescopes to the return a single unit of capital
    would have earned. Neither the size nor the date of a client contribution
    can move it -- that invariance is the entire reason the measure exists, and
    it is what distinguishes this from :func:`modified_dietz_return`.

    For ``flow_timing=FLOW_TIMING_END`` the interval return is
    ``(V_k - F_k) / V_{k-1} - 1``: the flow arrives after the market has moved,
    so it earns nothing that interval. For ``FLOW_TIMING_START`` it is
    ``V_k / (V_{k-1} + F_k) - 1``: the flow is invested for the whole interval.
    Both are exact given the stated timing; picking the wrong one biases every
    interval that carried a flow.

    Only boundary-crossing flows are removed; dividends, coupons, and fees are
    internal and already sit in the valuations. See the module docstring.

    Args:
        valuations: Portfolio value on each valuation date, as a mapping or as
            ``(date, value)`` pairs. At least two are required, and more
            valuations make the answer more exact -- this is *true* TWR, not an
            approximation, only to the resolution the marks provide.
        flows: Client cash flows over the window. ``None`` means none.
        flow_timing: Which side of a valuation date a flow dated on it settles.
        external_kinds: Override for :data:`DEFAULT_EXTERNAL_KINDS`.
        internal_kinds: Override for :data:`DEFAULT_INTERNAL_KINDS`.

    Returns:
        A :class:`TimeWeightedReturn` carrying the compounded figure and every
        interval that produced it.

    Raises:
        ValueError: If fewer than two valuations were given, ``flow_timing`` is
            not a recognised token, a flow falls outside the window or on a
            boundary the timing cannot represent, a flow's kind is
            unclassified, or an interval's invested base is not strictly
            positive. A non-positive base has no honest percentage: an account
            that reached zero did not "return" anything on the way back.
    """
    if flow_timing not in _FLOW_TIMINGS:
        raise ValueError(
            f"flow_timing must be one of {_FLOW_TIMINGS}, got {flow_timing!r}"
        )

    marks = _normalize_valuations(valuations)
    dates = [when for when, _ in marks]
    values = [value for _, value in marks]
    selected = external_flows(
        flows, external_kinds=external_kinds, internal_kinds=internal_kinds
    )
    buckets = _assign_flows_to_periods(dates, selected, flow_timing)

    sub_periods: list[SubPeriodReturn] = []
    growth = 1.0
    for index, flow_amount in enumerate(buckets):
        opening = values[index]
        closing = values[index + 1]
        if flow_timing == FLOW_TIMING_END:
            base = opening
            numerator = closing - flow_amount
        else:
            base = opening + flow_amount
            numerator = closing
        if not base > 0.0:
            raise ValueError(
                f"interval {dates[index]}..{dates[index + 1]} has an invested "
                f"base of {base!r}; a return is undefined on zero or negative "
                "capital, so the window must start after the account was funded"
            )
        period_return = numerator / base - 1.0
        growth *= 1.0 + period_return
        sub_periods.append(
            SubPeriodReturn(
                start=dates[index],
                end=dates[index + 1],
                start_value=opening,
                end_value=closing,
                external_flow=flow_amount,
                period_return=period_return,
            )
        )

    total_return = growth - 1.0
    return TimeWeightedReturn(
        total_return=total_return,
        sub_periods=tuple(sub_periods),
        start_date=dates[0],
        end_date=dates[-1],
        start_value=values[0],
        end_value=values[-1],
        net_external_flow=math.fsum(buckets),
        flow_timing=flow_timing,
        annualized_return=_annualize(total_return, (dates[-1] - dates[0]).days),
    )


# ─── Modified Dietz ───


def modified_dietz_return(
    valuations: Mapping[date | datetime | str, float]
    | Sequence[tuple[date | datetime | str, float]],
    flows: CashFlowSeries | Iterable[CashFlow] | None = None,
    *,
    external_kinds: Iterable[str] | None = None,
    internal_kinds: Iterable[str] | None = None,
) -> ModifiedDietzReturn:
    """Compute the day-weighted Modified Dietz return over one period.

    ``R = (V1 - V0 - F) / (V0 + sum(w_i * F_i))`` with
    ``w_i = (CD - D_i) / CD``, where ``CD`` is the calendar length of the period
    and ``D_i`` the days from its start to flow ``i``. A flow on the opening day
    carries weight 1 (invested throughout); one on the closing day carries
    weight 0 (invested for none of it).

    This is a **money-weighted** measure. It approximates the IRR by assuming a
    constant rate of return within the period, and it is sensitive to when the
    client moved money -- the opposite property to
    :func:`time_weighted_return`. It is offered because it needs no interim
    valuations, not because it is a cheaper TWR.

    Only the first and last valuations are used; any interim marks are ignored
    by construction. Pass them to :func:`time_weighted_return` instead.

    Args:
        valuations: Portfolio values; the earliest is ``V0`` and the latest is
            ``V1``. At least two are required.
        flows: Client cash flows over the period. ``None`` means none.
        external_kinds: Override for :data:`DEFAULT_EXTERNAL_KINDS`.
        internal_kinds: Override for :data:`DEFAULT_INTERNAL_KINDS`.

    Returns:
        A :class:`ModifiedDietzReturn` carrying the return and every term of
        its denominator.

    Raises:
        ValueError: If fewer than two valuations were given, the opening and
            closing dates coincide, a flow lies outside the period, a flow's
            kind is unclassified, or the average capital is not strictly
            positive (an account funded to zero average capital has no return).
    """
    marks = _normalize_valuations(valuations)
    start_date, start_value = marks[0]
    end_date, end_value = marks[-1]
    calendar_days = (end_date - start_date).days
    if calendar_days <= 0:
        raise ValueError(
            f"Modified Dietz needs a period of at least one day, got "
            f"{start_date}..{end_date}"
        )

    selected = external_flows(
        flows, external_kinds=external_kinds, internal_kinds=internal_kinds
    )
    weights: list[tuple[date, float, float]] = []
    for when, amount in selected:
        if when < start_date or when > end_date:
            raise ValueError(
                f"cash flow on {when} lies outside the period "
                f"{start_date}..{end_date}; trim the flows or widen the period "
                "rather than dropping the flow"
            )
        weight = (calendar_days - (when - start_date).days) / calendar_days
        weights.append((when, amount, weight))

    net_flow = math.fsum(amount for _, amount, _ in weights)
    weighted_flow = math.fsum(amount * weight for _, amount, weight in weights)
    average_capital = start_value + weighted_flow
    if not average_capital > 0.0:
        raise ValueError(
            f"average capital is {average_capital!r}; Modified Dietz is "
            "undefined on a non-positive invested base"
        )

    total_return = (end_value - start_value - net_flow) / average_capital
    return ModifiedDietzReturn(
        total_return=total_return,
        start_date=start_date,
        end_date=end_date,
        start_value=start_value,
        end_value=end_value,
        net_external_flow=net_flow,
        weighted_external_flow=weighted_flow,
        average_capital=average_capital,
        flow_weights=tuple(weights),
        annualized_return=_annualize(total_return, calendar_days),
    )


# ─── Money-weighted return ───


def _npv(rate: float, years: Sequence[float], amounts: Sequence[float]) -> float:
    """Net present value of dated amounts at an annual rate.

    Args:
        rate: Annual discount rate, strictly above -100%.
        years: Time from the first flow, in years, aligned with ``amounts``.
        amounts: Signed amounts.

    Returns:
        The discounted sum. A term whose discount factor overflows to beyond
        the float range contributes ``0.0``, which is its limit, rather than
        raising and aborting the search.
    """
    base = 1.0 + rate
    terms: list[float] = []
    for exponent, amount in zip(years, amounts, strict=True):
        try:
            terms.append(amount / (base**exponent))
        except OverflowError:
            terms.append(0.0)
    return math.fsum(terms)


def _solve_irr(
    years: Sequence[float], amounts: Sequence[float]
) -> tuple[float, int]:
    """Bisect for the annual rate that zeroes the net present value.

    Bisection is used rather than Newton because it cannot diverge and needs no
    guess. The bracket starts just above -100% -- where the NPV is dominated by
    the latest, largest-exponent amount -- and expands upward until the sign
    flips.

    Args:
        years: Time from the first flow, in years, ascending.
        amounts: Signed amounts aligned with ``years``.

    Returns:
        ``(rate, iterations)``.

    Raises:
        UnsolvableRateError: If the stream never changes sign, or if no rate
            below :data:`_IRR_UPPER_LIMIT` brackets a root. Both mean there is
            no single rate to report, which is a real property of the stream and
            not a solver failure to paper over.
    """
    if not any(amount > 0 for amount in amounts) or not any(
        amount < 0 for amount in amounts
    ):
        raise UnsolvableRateError(
            "an internal rate of return needs at least one inflow and one "
            "outflow; this stream is one-directional"
        )

    low = _IRR_LOWER_BOUND
    npv_low = _npv(low, years, amounts)
    if npv_low == 0.0:
        return low, 0
    high = 1.0
    npv_high = _npv(high, years, amounts)
    iterations = 0
    while npv_low * npv_high > 0.0 and high < _IRR_UPPER_LIMIT:
        high *= 2.0
        npv_high = _npv(high, years, amounts)
        iterations += 1
    if npv_low * npv_high > 0.0:
        raise UnsolvableRateError(
            "no internal rate of return between "
            f"{_IRR_LOWER_BOUND:.6f} and {_IRR_UPPER_LIMIT:.0f} explains this "
            "stream; the net present value never changes sign"
        )

    while iterations < _IRR_MAX_ITERATIONS and (high - low) > _IRR_TOLERANCE:
        middle = 0.5 * (low + high)
        npv_middle = _npv(middle, years, amounts)
        if npv_middle == 0.0:
            return middle, iterations
        if npv_low * npv_middle < 0.0:
            high = middle
        else:
            low, npv_low = middle, npv_middle
        iterations += 1
    return 0.5 * (low + high), iterations


def xirr(
    dated_amounts: Sequence[tuple[date | datetime | str, float]],
) -> float:
    """Annual internal rate of return of irregularly dated amounts.

    Amounts are holder-perspective, matching ``CashFlow.amount``: money paid out
    is negative, money received is positive. Several amounts on one date are
    summed. Time is measured in actual days over :data:`DAYS_PER_YEAR`.

    A stream with more than one sign change can admit several mathematically
    valid rates. This returns whichever root the bisection isolates inside its
    initial bracket, and does not enumerate the rest: a stream where that
    matters is one whose "the IRR" is not a well-defined quantity, and no
    solver choice repairs that. Check the sign pattern before quoting the
    number.

    Args:
        dated_amounts: ``(date, amount)`` pairs. Order does not matter.

    Returns:
        The annual rate as a decimal fraction, e.g. ``0.087`` for 8.7%.

    Raises:
        ValueError: If fewer than two amounts were given, a date or amount is
            unusable, or every amount falls on one date.
        UnsolvableRateError: If the stream is one-directional or no rate
            brackets a root.
    """
    if len(dated_amounts) < 2:
        raise ValueError(
            f"an IRR needs at least two dated amounts, got {len(dated_amounts)}"
        )

    totals: dict[date, float] = {}
    for raw_date, raw_amount in dated_amounts:
        when = normalize_date(raw_date, field_name="cash-flow date")
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"amount on {when} must be numeric, got {raw_amount!r}"
            ) from exc
        if not math.isfinite(amount):
            raise ValueError(f"amount on {when} must be finite, got {raw_amount!r}")
        totals[when] = totals.get(when, 0.0) + amount

    ordered = sorted(totals.items())
    if len(ordered) < 2:
        raise ValueError(
            f"every amount falls on {ordered[0][0]}; an IRR needs a time span"
        )

    origin = ordered[0][0]
    years = [(when - origin).days / DAYS_PER_YEAR for when, _ in ordered]
    amounts = [amount for _, amount in ordered]
    rate, _ = _solve_irr(years, amounts)
    return rate


def money_weighted_return(
    valuations: Mapping[date | datetime | str, float]
    | Sequence[tuple[date | datetime | str, float]],
    flows: CashFlowSeries | Iterable[CashFlow] | None = None,
    *,
    external_kinds: Iterable[str] | None = None,
    internal_kinds: Iterable[str] | None = None,
) -> MoneyWeightedReturn:
    """Compute the client's money-weighted return (XIRR) over the window.

    The client's cash stream is the opening value paid in, every external flow
    as it fell, and the closing value taken back out. Because
    ``CashFlow.amount`` is already holder-perspective, the flows enter the IRR
    unchanged; only the two valuations need signs attached, and they get the
    signs a purchase and a sale would carry.

    This answers "what did the client's money earn", so unlike
    :func:`time_weighted_return` it is *supposed* to move when a large
    contribution lands just before a drawdown. Report both, never one as a
    proxy for the other.

    Interim valuations are ignored: an IRR is determined by cash, and marking
    the account midway does not change what the client paid or received.

    Args:
        valuations: Portfolio values; the earliest opens the stream and the
            latest closes it. At least two are required.
        flows: Client cash flows over the window. ``None`` means none, in which
            case the IRR is just the annualised growth of the opening value.
        external_kinds: Override for :data:`DEFAULT_EXTERNAL_KINDS`.
        internal_kinds: Override for :data:`DEFAULT_INTERNAL_KINDS`.

    Returns:
        A :class:`MoneyWeightedReturn` with both the annualised rate and the
        same rate restated over the observed window.

    Raises:
        ValueError: If fewer than two valuations were given, the window has no
            length, a flow lies outside it, or a flow's kind is unclassified.
        UnsolvableRateError: If the resulting stream admits no single rate --
            for instance a closing value of zero with no distributions, where
            every amount points the same way.
    """
    marks = _normalize_valuations(valuations)
    start_date, start_value = marks[0]
    end_date, end_value = marks[-1]
    if (end_date - start_date).days <= 0:
        raise ValueError(
            f"a money-weighted return needs a window of at least one day, got "
            f"{start_date}..{end_date}"
        )

    selected = external_flows(
        flows, external_kinds=external_kinds, internal_kinds=internal_kinds
    )
    for when, _ in selected:
        if when < start_date or when > end_date:
            raise ValueError(
                f"cash flow on {when} lies outside the window "
                f"{start_date}..{end_date}; trim the flows or widen the window "
                "rather than dropping the flow"
            )

    # Portfolio-perspective flows are negated back to the client's perspective:
    # cash arriving in the portfolio is cash the client paid out.
    stream: list[tuple[date, float]] = [(start_date, -start_value)]
    stream.extend((when, -amount) for when, amount in selected)
    stream.append((end_date, end_value))

    totals: dict[date, float] = {}
    for when, amount in stream:
        totals[when] = totals.get(when, 0.0) + amount
    ordered = sorted(totals.items())
    origin = ordered[0][0]
    years = [(when - origin).days / DAYS_PER_YEAR for when, _ in ordered]
    amounts = [amount for _, amount in ordered]
    rate, iterations = _solve_irr(years, amounts)

    window_years = (end_date - start_date).days / DAYS_PER_YEAR
    return MoneyWeightedReturn(
        annualized_return=rate,
        period_return=(1.0 + rate) ** window_years - 1.0,
        start_date=start_date,
        end_date=end_date,
        start_value=start_value,
        end_value=end_value,
        net_external_flow=math.fsum(amount for _, amount in selected),
        years=window_years,
        iterations=iterations,
    )
