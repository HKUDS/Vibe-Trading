"""Comparable-companies (comps) valuation: EV bridge, calendarisation, multiples.

A comps valuation answers "what is this company worth, given what the market
pays for similar companies" -- by building a multiple (EV/EBITDA, P/E, ...) for
each peer and applying the peer set's distribution to the target's own
financials. Two mistakes make that answer wrong before a single multiple is
even computed, and this module exists to make both of them structurally hard
to commit silently.

1. THE EV BRIDGE
   -----------------
   Enterprise value is not market cap. It is the price a buyer of the WHOLE
   operating business would pay, and every EV multiple's numerator must
   represent that same whole-business claim or it is not comparable to the
   denominator (EBITDA/EBIT/Sales), which is also a whole-business number:

       EV = market_cap + total_debt - cash_and_equivalents
            + minority_interest + preferred_stock - investments_in_associates

   Each sign is explained where it is applied (:func:`enterprise_value`), but
   the shape is: things that are a SENIOR or OUTSIDE claim on the operating
   business are ADDED (debt, minority interest, preferred); things that are
   NOT part of what the operating multiple prices are SUBTRACTED (cash sits
   outside operations, an equity-method stake's earnings sit below the
   operating metrics the multiple's denominator uses). Minority interest and
   preferred stock and associate investments are commonly undisclosed or
   genuinely zero -- this module refuses to guess which, and reports every
   omitted component by name (see ``omitted_components`` on
   :class:`EVBridgeResult`) rather than silently treating "not supplied" as
   "zero". An EV bridge missing minority interest is systematically biased
   LOW, exactly the failure mode the caller must be told about.

2. FISCAL-CALENDAR ALIGNMENT (CALENDARISATION)
   ---------------------------------------------
   A peer with a June fiscal year end and a peer with a December fiscal year
   end do not report over the same twelve months. Comparing their raw
   "latest fiscal year" multiples mixes, e.g., one company's Jul-2024..Jun-2025
   performance against another's Jan-2025..Dec-2025 -- six months of look-ahead
   or look-behind bias baked into a number that LOOKS like an apples-to-apples
   ratio. Two conventions fix this, and this module implements both, but a
   single :func:`run_comps` call uses exactly ONE for every peer and the
   target:

   - ``"ltm"`` (last twelve months): ``last_full_fiscal_year + current_ytd -
     prior_year_ytd``. This is always trailing twelve months ending at
     whatever "as of" date the YTD figures were cut at, REGARDLESS of fiscal
     year end -- it needs no month-weighting because the subtraction of
     ``prior_year_ytd`` already cancels out the seasonal stub.
   - ``"calendar_year"``: blends the fiscal year ending IN the target calendar
     year with the one ending in the NEXT calendar year, weighted by what
     fraction of the calendar year each covers, under the explicit
     simplifying assumption that a fiscal year's flow is spread evenly across
     its twelve months (a company disclosing quarterly seasonality could
     calendarise more precisely than this module does; this module's
     assumption is documented here so nobody mistakes the output for a
     seasonality-aware estimate).

   Mixing the two within one run is refused structurally: ``run_comps`` takes
   one ``calendarisation_policy`` for the whole call, and a peer whose data
   does not carry the fields that policy needs is NOT RUNNABLE (see
   :mod:`.contracts`) rather than silently computed from a partial fit.

3. THE MULTIPLE MATRIX
   ---------------------
   A multiple whose denominator is at or below zero is not a small number or
   a large negative number -- it is not a number at all in the sense a
   valuation multiple needs (a company with negative EBITDA is not "worth
   negative EBITDA times anything"). Every multiple in this module is dropped
   for a peer whenever its OWN denominator is non-positive, and the drop is
   reported by name (:class:`ExcludedMultiple`), not silently absorbed into a
   distribution that would otherwise look like ordinary peer dispersion. Note
   this rule is stated on the DENOMINATOR only, matching the task that
   motivated this module; a peer with a non-positive EV but a positive
   denominator (a net-cash-rich, low-multiple company) still produces a
   negative multiple and is NOT excluded by this rule -- see the note on
   :func:`_compute_multiple`.

   Every multiple's cross-sectional distribution is reported as min / p25 /
   median / p75 / max. The MEDIAN, not the mean, is this module's headline
   statistic and the one used to build the target's implied valuation: a
   comps set is small by construction (rarely more than a handful of true
   peers), and a single outlier peer can drag a mean far off-center while
   barely moving a median. Below :data:`MIN_ROBUST_COMPS` peers, even the
   median is flagged with an explicit warning -- a "median" of one or two
   points is just those points, not a statistic.

Import this module directly (``from src.quantlib.valuation.comps import
run_comps``); see :mod:`src.quantlib.valuation` for why submodules are kept
independently importable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from src.quantlib.valuation.contracts import (
    MissingInputError,
    ValuationError,
    require_inputs,
    require_positive,
)

__all__ = [
    "CALENDARISATION_POLICIES",
    "EPS_BASES",
    "MULTIPLE_NAMES",
    "MIN_ROBUST_COMPS",
    "FlowMetricPeriods",
    "CalendarisedMetric",
    "EVBridgeResult",
    "PeerCompany",
    "TargetCompany",
    "ExcludedMultiple",
    "PeerMultiples",
    "MultipleDistribution",
    "ImpliedValuation",
    "CompsResult",
    "enterprise_value",
    "equity_value_from_enterprise_value",
    "calendarise_metric",
    "peer_multiple_set",
    "multiple_distribution",
    "implied_valuation",
    "run_comps",
]

#: The two fiscal-calendar alignment conventions this module implements. A
#: single `run_comps` call uses exactly one for every peer and the target --
#: see the module docstring's section 2 for why mixing them is refused.
CALENDARISATION_POLICIES: tuple[str, ...] = ("ltm", "calendar_year")

#: EPS conventions a caller may declare. Not a preference this module has an
#: opinion on -- it exists purely so the basis is an explicit, recorded fact
#: rather than an assumption baked silently into whatever EPS number arrived.
EPS_BASES: tuple[str, ...] = ("gaap", "adjusted")

#: The five multiples this module computes, in the fixed order used for
#: reporting. The first three price Enterprise Value; the last two price
#: equity value directly and never pass through the EV bridge.
MULTIPLE_NAMES: tuple[str, ...] = ("ev_ebitda", "ev_ebit", "ev_sales", "pe", "pb")

#: Which of `MULTIPLE_NAMES` have EV (not equity) as their numerator.
_EV_MULTIPLES: frozenset[str] = frozenset({"ev_ebitda", "ev_ebit", "ev_sales"})

#: Fewest peers a cross-sectional median needs before it is a statistic
#: rather than an arbitrary pick from 1-2 data points. Below this the
#: distribution is still computed (it is not "wrong"), but every result
#: carries an explicit warning saying so.
MIN_ROBUST_COMPS: int = 3

#: Names of the EV bridge's optional line items, in the order they appear in
#: the formula. A caller who does not supply one of these is NOT asserting it
#: is zero -- see `EVBridgeResult.omitted_components`.
_EV_BRIDGE_OPTIONAL_FIELDS: tuple[str, ...] = (
    "minority_interest",
    "preferred_stock",
    "investments_in_associates",
)


@dataclass(frozen=True)
class FlowMetricPeriods:
    """Raw fiscal-period figures for one flow metric (EBITDA, EBIT, Sales, ...).

    Which fields beyond `last_full_fiscal_year` are required depends on which
    calendarisation policy a run uses -- both need not be populated at once;
    see :func:`calendarise_metric`.

    Attributes:
        fiscal_year_end_month: Month (1-12) the company's fiscal year ends in.
        last_full_fiscal_year: Value for the most recently COMPLETED fiscal
            year. Used by both policies: it is the anchor of the LTM formula,
            and the "fiscal year ending in the earlier calendar year" leg of
            the calendar-year blend.
        current_year_to_date: Value for the stub period since the CURRENT
            fiscal year began, through the analysis "as of" date. Required
            for the `"ltm"` policy.
        prior_year_to_date: Value for the SAME stub period one year earlier
            -- same start month, same length. Required for the `"ltm"`
            policy.
        next_full_fiscal_year: Value for the fiscal year immediately AFTER
            `last_full_fiscal_year` (ending one calendar year later).
            Required for the `"calendar_year"` policy whenever
            `fiscal_year_end_month != 12` -- a December fiscal year end needs
            no second year, because month-weighting already resolves to 100%
            of `last_full_fiscal_year`.

    Raises:
        ValuationError: If `fiscal_year_end_month` is not in 1..12.
    """

    fiscal_year_end_month: int
    last_full_fiscal_year: float
    current_year_to_date: float | None = None
    prior_year_to_date: float | None = None
    next_full_fiscal_year: float | None = None

    def __post_init__(self) -> None:
        if not 1 <= int(self.fiscal_year_end_month) <= 12:
            raise ValuationError(
                "comps.FlowMetricPeriods: fiscal_year_end_month must be 1-12, "
                f"got {self.fiscal_year_end_month!r}"
            )


@dataclass(frozen=True)
class CalendarisedMetric:
    """One flow metric after fiscal-calendar alignment.

    Attributes:
        policy: Which convention produced `value` -- `"ltm"` or
            `"calendar_year"`.
        value: The aligned metric value.
        fiscal_year_end_month: Carried through from the input, for audit.
        weights: For `"calendar_year"`, the `(early_fy_weight,
            late_fy_weight)` used to blend the two fiscal years. `None` for
            `"ltm"`, which has no month-weighting step.
    """

    policy: str
    value: float
    fiscal_year_end_month: int
    weights: tuple[float, float] | None


def calendarise_metric(
    periods: FlowMetricPeriods,
    policy: str,
    *,
    metric_name: str,
    company_name: str,
) -> CalendarisedMetric:
    """Align one company's flow metric onto a comparable twelve-month footing.

    See the module docstring, section 2, for why this step exists and why
    the two policies are not interchangeable within one comps run.

    Args:
        periods: The company's raw fiscal-period figures for this metric.
        policy: `"ltm"` or `"calendar_year"`.
        metric_name: Name of the metric being aligned (e.g. `"ebitda"`), used
            only for error messages.
        company_name: Name of the company being aligned, used only for error
            messages.

    Returns:
        The aligned :class:`CalendarisedMetric`.

    Raises:
        ValuationError: If `policy` is not one of `CALENDARISATION_POLICIES`.
        MissingInputError: If `periods` lacks a field this policy needs.
    """
    if policy not in CALENDARISATION_POLICIES:
        raise ValuationError(
            f"comps.calendarise_metric: unknown policy {policy!r}, must be "
            f"one of {CALENDARISATION_POLICIES}"
        )
    model = f"comps.calendarise_metric[{company_name}.{metric_name}:{policy}]"

    if policy == "ltm":
        require_inputs(
            {
                "last_full_fiscal_year": periods.last_full_fiscal_year,
                "current_year_to_date": periods.current_year_to_date,
                "prior_year_to_date": periods.prior_year_to_date,
            },
            ("last_full_fiscal_year", "current_year_to_date", "prior_year_to_date"),
            model,
        )
        value = (
            periods.last_full_fiscal_year
            + periods.current_year_to_date
            - periods.prior_year_to_date
        )
        return CalendarisedMetric(
            policy="ltm",
            value=value,
            fiscal_year_end_month=periods.fiscal_year_end_month,
            weights=None,
        )

    # policy == "calendar_year"
    month = periods.fiscal_year_end_month
    if month == 12:
        require_inputs(
            {"last_full_fiscal_year": periods.last_full_fiscal_year},
            ("last_full_fiscal_year",),
            model,
        )
        return CalendarisedMetric(
            policy="calendar_year",
            value=periods.last_full_fiscal_year,
            fiscal_year_end_month=month,
            weights=(1.0, 0.0),
        )

    require_inputs(
        {
            "last_full_fiscal_year": periods.last_full_fiscal_year,
            "next_full_fiscal_year": periods.next_full_fiscal_year,
        },
        ("last_full_fiscal_year", "next_full_fiscal_year"),
        model,
    )
    weight_early = month / 12.0
    weight_late = 1.0 - weight_early
    value = weight_early * periods.last_full_fiscal_year + weight_late * periods.next_full_fiscal_year
    return CalendarisedMetric(
        policy="calendar_year",
        value=value,
        fiscal_year_end_month=month,
        weights=(weight_early, weight_late),
    )


@dataclass(frozen=True)
class EVBridgeResult:
    """Enterprise-value bridge for one company, walked in one direction.

    Attributes:
        direction: `"equity_to_ev"` (a known market cap produces EV) or
            `"ev_to_equity"` (a known EV, e.g. one implied by a peer
            multiple, produces an implied equity value). Lets a report tell
            at a glance which side of the bridge was the input.
        equity_value: The equity-side value -- `market_cap` on the forward
            direction, the implied equity value on the reverse direction.
        enterprise_value: The enterprise-side value -- computed on the
            forward direction, supplied as an input on the reverse direction.
        total_debt: Debt component used.
        cash_and_equivalents: Cash component used.
        minority_interest: Component used, or `None` if not supplied.
        preferred_stock: Component used, or `None` if not supplied.
        investments_in_associates: Component used, or `None` if not supplied.
        omitted_components: Names, among `minority_interest`,
            `preferred_stock`, `investments_in_associates`, that were NOT
            supplied. Non-empty means the bridge value excludes their
            (unknown) contribution and is biased in the direction of the
            missing sign -- e.g. an omitted `minority_interest` means
            `enterprise_value` is understated relative to the true bridge.
    """

    direction: str
    equity_value: float
    enterprise_value: float
    total_debt: float
    cash_and_equivalents: float
    minority_interest: float | None
    preferred_stock: float | None
    investments_in_associates: float | None
    omitted_components: tuple[str, ...]


def _bridge_delta(
    total_debt: float,
    cash_and_equivalents: float,
    minority_interest: float | None,
    preferred_stock: float | None,
    investments_in_associates: float | None,
) -> tuple[float, tuple[str, ...]]:
    """Compute the EV-minus-equity-value delta and which optional items were omitted.

    The delta is added to equity value to reach EV, and subtracted from EV to
    reach equity value -- the two public bridge functions differ only in
    which side is the known input.

    Returns:
        `(delta, omitted_components)`.
    """
    omitted: list[str] = []
    total = total_debt - cash_and_equivalents
    for name, value in (
        ("minority_interest", minority_interest),
        ("preferred_stock", preferred_stock),
        ("investments_in_associates", investments_in_associates),
    ):
        if value is None:
            omitted.append(name)
            continue
        sign = -1.0 if name == "investments_in_associates" else 1.0
        total += sign * value
    return total, tuple(omitted)


def enterprise_value(
    *,
    market_cap: float,
    total_debt: float,
    cash_and_equivalents: float,
    minority_interest: float | None = None,
    preferred_stock: float | None = None,
    investments_in_associates: float | None = None,
) -> EVBridgeResult:
    """Bridge a known equity market value to enterprise value.

        EV = market_cap + total_debt - cash_and_equivalents
             + minority_interest + preferred_stock - investments_in_associates

    Sign of each term, in the direction FROM equity value TO enterprise value:

    - `total_debt` (+): an acquirer of the whole enterprise assumes its debt
      on top of paying for the equity -- debtholders are repaid ahead of
      equity, so their claim is an ADDITIONAL cost layered on market cap.
    - `cash_and_equivalents` (-): cash on the balance sheet is not part of
      the OPERATING business the multiple's denominator (EBITDA/EBIT/Sales)
      measures -- it funds part of the purchase price (an acquirer nets it
      against assumed debt, or simply pockets it), so it is subtracted back
      out of what the operating multiple is pricing.
    - `minority_interest` (+): a majority-owned, consolidated subsidiary
      contributes 100% of its EBITDA/EBIT/revenue to the parent's
      consolidated figures (consolidation accounting backs the minority
      holders' share out only at the net-income line, not the operating
      lines). EV must therefore also represent 100% of that subsidiary's
      value -- including the minority claim -- or EV and the operating
      metric price different slices of the same business.
    - `preferred_stock` (+): preferred shares rank senior to common equity
      but junior to debt. `market_cap` prices only the common shares, so the
      preferred claim is an additional cost an acquirer of the whole
      enterprise must also cover, exactly like debt.
    - `investments_in_associates` (-): an equity-method stake (typically
      20-50% owned, not consolidated) contributes only a single "equity in
      earnings" line BELOW the operating metrics -- its own revenue/EBITDA/
      EBIT are NOT included in the consolidated numbers the multiple's
      denominator uses. Its value is therefore not part of what the
      operating multiple prices, and is backed out of EV the same way cash
      is.

    `minority_interest`, `preferred_stock` and `investments_in_associates`
    are genuinely optional -- many companies have none of one or more of
    them. Passing `None` (the default) means "not supplied", NOT "zero": the
    bridge still computes (using no contribution from that term), but the
    omission is named in `EVBridgeResult.omitted_components` so nobody reads
    the result as a complete bridge when it is not. Pass `0.0` explicitly to
    assert a confirmed-zero line item.

    Args:
        market_cap: Equity market value (share price x shares outstanding).
        total_debt: Interest-bearing debt, all maturities.
        cash_and_equivalents: Cash and short-term investments.
        minority_interest: Book or fair value of minority (non-controlling)
            interests in consolidated subsidiaries, or `None` if not
            supplied.
        preferred_stock: Value of preferred equity outstanding, or `None` if
            not supplied.
        investments_in_associates: Value of equity-method (non-consolidated)
            investments, or `None` if not supplied.

    Returns:
        The :class:`EVBridgeResult`, `direction="equity_to_ev"`.

    Raises:
        MissingInputError: If `market_cap`, `total_debt` or
            `cash_and_equivalents` is absent.
    """
    require_inputs(
        {
            "market_cap": market_cap,
            "total_debt": total_debt,
            "cash_and_equivalents": cash_and_equivalents,
        },
        ("market_cap", "total_debt", "cash_and_equivalents"),
        "comps.enterprise_value",
    )
    delta, omitted = _bridge_delta(
        total_debt, cash_and_equivalents, minority_interest, preferred_stock, investments_in_associates
    )
    ev = float(market_cap) + delta
    return EVBridgeResult(
        direction="equity_to_ev",
        equity_value=float(market_cap),
        enterprise_value=ev,
        total_debt=float(total_debt),
        cash_and_equivalents=float(cash_and_equivalents),
        minority_interest=minority_interest,
        preferred_stock=preferred_stock,
        investments_in_associates=investments_in_associates,
        omitted_components=omitted,
    )


def equity_value_from_enterprise_value(
    *,
    enterprise_value: float,
    total_debt: float,
    cash_and_equivalents: float,
    minority_interest: float | None = None,
    preferred_stock: float | None = None,
    investments_in_associates: float | None = None,
) -> EVBridgeResult:
    """Walk the EV bridge backward: a known EV to an implied equity value.

    This is the exact inverse of :func:`enterprise_value` -- same signs, same
    omission handling -- used to turn a target's IMPLIED enterprise value
    (peer multiple x target metric) into an implied equity value, using the
    TARGET's own capital structure:

        equity_value = enterprise_value - total_debt + cash_and_equivalents
                       - minority_interest - preferred_stock
                       + investments_in_associates

    Args:
        enterprise_value: A known or implied enterprise value.
        total_debt: Target's interest-bearing debt.
        cash_and_equivalents: Target's cash and short-term investments.
        minority_interest: Target's minority interest, or `None` if not
            supplied.
        preferred_stock: Target's preferred equity, or `None` if not
            supplied.
        investments_in_associates: Target's equity-method investments, or
            `None` if not supplied.

    Returns:
        The :class:`EVBridgeResult`, `direction="ev_to_equity"`.

    Raises:
        MissingInputError: If `enterprise_value`, `total_debt` or
            `cash_and_equivalents` is absent.
    """
    require_inputs(
        {
            "enterprise_value": enterprise_value,
            "total_debt": total_debt,
            "cash_and_equivalents": cash_and_equivalents,
        },
        ("enterprise_value", "total_debt", "cash_and_equivalents"),
        "comps.equity_value_from_enterprise_value",
    )
    delta, omitted = _bridge_delta(
        total_debt, cash_and_equivalents, minority_interest, preferred_stock, investments_in_associates
    )
    equity = float(enterprise_value) - delta
    return EVBridgeResult(
        direction="ev_to_equity",
        equity_value=equity,
        enterprise_value=float(enterprise_value),
        total_debt=float(total_debt),
        cash_and_equivalents=float(cash_and_equivalents),
        minority_interest=minority_interest,
        preferred_stock=preferred_stock,
        investments_in_associates=investments_in_associates,
        omitted_components=omitted,
    )


def _require_name(name: str, model: str) -> str:
    """Reject a blank company name -- every report keys off it."""
    if not isinstance(name, str) or not name.strip():
        raise ValuationError(f"{model}: name is required and cannot be blank, got {name!r}")
    return name


def _require_eps_basis(eps_basis: str, model: str) -> str:
    """Reject an EPS basis that is not one of the two this module recognises."""
    if eps_basis not in EPS_BASES:
        raise ValuationError(
            f"{model}: eps_basis must be one of {EPS_BASES}, got {eps_basis!r}"
        )
    return eps_basis


@dataclass(frozen=True)
class PeerCompany:
    """One comparable company's raw inputs for the EV bridge and multiple matrix.

    Attributes:
        name: Identifier (ticker or short name), used in every report and
            exclusion message for this peer.
        market_cap: Equity market value.
        total_debt: Interest-bearing debt.
        cash_and_equivalents: Cash and short-term investments.
        ebitda: Fiscal-period figures for EBITDA.
        ebit: Fiscal-period figures for EBIT.
        revenue: Fiscal-period figures for revenue/sales.
        diluted_eps: Fiscal-period figures for diluted EPS.
        price_per_share: Current share price, paired with `diluted_eps` to
            form this peer's own P/E.
        book_value_of_equity: Latest reported book value of common equity (a
            balance-sheet snapshot, not a flow -- it is used as-is, never
            calendarised).
        eps_basis: `"gaap"` or `"adjusted"` -- must match every other peer's
            and the target's basis within one `run_comps` call (see
            `run_comps`).
        minority_interest: Optional EV-bridge component; `None` means not
            supplied (see `enterprise_value`).
        preferred_stock: Optional EV-bridge component; `None` means not
            supplied.
        investments_in_associates: Optional EV-bridge component; `None`
            means not supplied.
    """

    name: str
    market_cap: float
    total_debt: float
    cash_and_equivalents: float
    ebitda: FlowMetricPeriods
    ebit: FlowMetricPeriods
    revenue: FlowMetricPeriods
    diluted_eps: FlowMetricPeriods
    price_per_share: float
    book_value_of_equity: float
    eps_basis: str
    minority_interest: float | None = None
    preferred_stock: float | None = None
    investments_in_associates: float | None = None

    def __post_init__(self) -> None:
        _require_name(self.name, "comps.PeerCompany")
        _require_eps_basis(self.eps_basis, "comps.PeerCompany")


@dataclass(frozen=True)
class TargetCompany:
    """The company being valued: its own fundamentals and capital structure.

    A target does NOT carry `market_cap` or `price_per_share` -- those are
    what a comps run estimates, not an input to it. It DOES carry its own
    capital structure (`total_debt`, `cash_and_equivalents`, and the three
    optional EV-bridge items), because those are needed to walk an EV
    multiple's implied enterprise value back down to an implied equity value
    via `equity_value_from_enterprise_value`.

    Attributes:
        name: Identifier, used in every report for this run.
        total_debt: Target's interest-bearing debt.
        cash_and_equivalents: Target's cash and short-term investments.
        ebitda: Target's fiscal-period figures for EBITDA.
        ebit: Target's fiscal-period figures for EBIT.
        revenue: Target's fiscal-period figures for revenue/sales.
        diluted_eps: Target's fiscal-period figures for diluted EPS.
        diluted_shares_outstanding: Target's diluted share count, used with
            the calendarised `diluted_eps` to recover an aggregate
            "net income to diluted common" figure so a peer P/E (a per-share
            ratio) can be applied to produce an aggregate implied equity
            value rather than a per-share price.
        book_value_of_equity: Target's latest reported book value of common
            equity.
        eps_basis: `"gaap"` or `"adjusted"` -- must match every peer's basis.
        minority_interest: Optional EV-bridge component; `None` means not
            supplied.
        preferred_stock: Optional EV-bridge component; `None` means not
            supplied.
        investments_in_associates: Optional EV-bridge component; `None`
            means not supplied.

    Raises:
        ValuationError: If `diluted_shares_outstanding` is not a finite
            positive number, or `eps_basis` is not recognised, or `name` is
            blank.
    """

    name: str
    total_debt: float
    cash_and_equivalents: float
    ebitda: FlowMetricPeriods
    ebit: FlowMetricPeriods
    revenue: FlowMetricPeriods
    diluted_eps: FlowMetricPeriods
    diluted_shares_outstanding: float
    book_value_of_equity: float
    eps_basis: str
    minority_interest: float | None = None
    preferred_stock: float | None = None
    investments_in_associates: float | None = None

    def __post_init__(self) -> None:
        _require_name(self.name, "comps.TargetCompany")
        _require_eps_basis(self.eps_basis, "comps.TargetCompany")
        require_positive(self.diluted_shares_outstanding, "diluted_shares_outstanding", "comps.TargetCompany")


@dataclass(frozen=True)
class ExcludedMultiple:
    """One peer dropped from one multiple's statistics.

    Attributes:
        peer_name: Which comp was dropped.
        multiple_name: Which multiple (one of `MULTIPLE_NAMES`).
        denominator_value: The denominator at the time of exclusion.
        numerator_value: The numerator at the time of exclusion.
        reason: ``"non_positive_denominator"`` or ``"non_positive_numerator"``.
    """

    peer_name: str
    multiple_name: str
    denominator_value: float
    numerator_value: float = 0.0
    reason: str = "non_positive_denominator"


def _compute_multiple(
    numerator: float, denominator: float, *, peer_name: str, multiple_name: str
) -> tuple[float | None, ExcludedMultiple | None]:
    """Compute one peer's multiple, or explain why it is excluded.

    **Both sides are checked, and that is deliberate.**

    A non-positive DENOMINATOR (a loss-making peer's EBITDA) makes the ratio
    not a valuation multiple at all. So does a non-positive NUMERATOR: a
    net-cash-rich company can have a negative enterprise value while its EBITDA
    is perfectly healthy, and ``EV/EBITDA = -3.2x`` is not a cheap company, it
    is a company the multiple cannot describe. Letting either through drags the
    median toward a number no peer actually trades at.

    An earlier version guarded the denominator only and documented the gap as
    "a one-sided guarantee inherited from the spec". A guarantee a reader has to
    read the source to discover is not one; both sides are now excluded and
    ``ExcludedMultiple.reason`` says which side triggered it.

    Args:
        numerator: Multiple numerator (EV, price, market cap).
        denominator: Multiple denominator (EBITDA, EBIT, revenue, EPS, book).
        peer_name: For the exclusion record.
        multiple_name: For the exclusion record.

    Returns:
        ``(value, None)`` when both sides are positive, else
        ``(None, ExcludedMultiple(...))`` naming the side that failed.
    """
    if denominator <= 0.0:
        return None, ExcludedMultiple(
            peer_name=peer_name,
            multiple_name=multiple_name,
            denominator_value=denominator,
            numerator_value=numerator,
            reason="non_positive_denominator",
        )
    if numerator <= 0.0:
        return None, ExcludedMultiple(
            peer_name=peer_name,
            multiple_name=multiple_name,
            denominator_value=denominator,
            numerator_value=numerator,
            reason="non_positive_numerator",
        )
    return numerator / denominator, None


@dataclass(frozen=True)
class PeerMultiples:
    """One peer's EV bridge, calendarised metrics, and full multiple set.

    Attributes:
        name: The peer's name.
        ev_bridge: This peer's `EVBridgeResult`.
        calendarised_ebitda: EBITDA after fiscal-calendar alignment.
        calendarised_ebit: EBIT after fiscal-calendar alignment.
        calendarised_revenue: Revenue after fiscal-calendar alignment.
        calendarised_diluted_eps: Diluted EPS after fiscal-calendar alignment.
        ev_ebitda: This peer's EV/EBITDA, or `None` if excluded.
        ev_ebit: This peer's EV/EBIT, or `None` if excluded.
        ev_sales: This peer's EV/Sales, or `None` if excluded.
        pe: This peer's P/E, or `None` if excluded.
        pb: This peer's P/B, or `None` if excluded.
        exclusions: Every multiple excluded for this peer, and why.
    """

    name: str
    ev_bridge: EVBridgeResult
    calendarised_ebitda: CalendarisedMetric
    calendarised_ebit: CalendarisedMetric
    calendarised_revenue: CalendarisedMetric
    calendarised_diluted_eps: CalendarisedMetric
    ev_ebitda: float | None
    ev_ebit: float | None
    ev_sales: float | None
    pe: float | None
    pb: float | None
    exclusions: tuple[ExcludedMultiple, ...]


def peer_multiple_set(peer: PeerCompany, policy: str) -> PeerMultiples:
    """Build one peer's EV bridge, calendarised metrics and full multiple set.

    Args:
        peer: The peer's raw inputs.
        policy: `"ltm"` or `"calendar_year"` -- see `calendarise_metric`.

    Returns:
        The peer's :class:`PeerMultiples`.

    Raises:
        MissingInputError: If `peer`'s data lacks a field the chosen policy
            needs.
    """
    ev_bridge = enterprise_value(
        market_cap=peer.market_cap,
        total_debt=peer.total_debt,
        cash_and_equivalents=peer.cash_and_equivalents,
        minority_interest=peer.minority_interest,
        preferred_stock=peer.preferred_stock,
        investments_in_associates=peer.investments_in_associates,
    )
    ebitda = calendarise_metric(peer.ebitda, policy, metric_name="ebitda", company_name=peer.name)
    ebit = calendarise_metric(peer.ebit, policy, metric_name="ebit", company_name=peer.name)
    revenue = calendarise_metric(peer.revenue, policy, metric_name="revenue", company_name=peer.name)
    eps = calendarise_metric(peer.diluted_eps, policy, metric_name="diluted_eps", company_name=peer.name)

    exclusions: list[ExcludedMultiple] = []
    values: dict[str, float | None] = {}
    for multiple_name, numerator, denominator in (
        ("ev_ebitda", ev_bridge.enterprise_value, ebitda.value),
        ("ev_ebit", ev_bridge.enterprise_value, ebit.value),
        ("ev_sales", ev_bridge.enterprise_value, revenue.value),
        ("pe", peer.price_per_share, eps.value),
        ("pb", peer.market_cap, peer.book_value_of_equity),
    ):
        value, excluded = _compute_multiple(
            numerator, denominator, peer_name=peer.name, multiple_name=multiple_name
        )
        values[multiple_name] = value
        if excluded is not None:
            exclusions.append(excluded)

    return PeerMultiples(
        name=peer.name,
        ev_bridge=ev_bridge,
        calendarised_ebitda=ebitda,
        calendarised_ebit=ebit,
        calendarised_revenue=revenue,
        calendarised_diluted_eps=eps,
        ev_ebitda=values["ev_ebitda"],
        ev_ebit=values["ev_ebit"],
        ev_sales=values["ev_sales"],
        pe=values["pe"],
        pb=values["pb"],
        exclusions=tuple(exclusions),
    )


@dataclass(frozen=True)
class MultipleDistribution:
    """Cross-sectional distribution of one multiple across the included peers.

    Attributes:
        name: Which multiple (one of `MULTIPLE_NAMES`).
        included: `{peer_name: value}` for peers whose denominator was
            positive.
        excluded: Peers dropped from this multiple, and why. An empty tuple
            IS the report "nobody was excluded" -- it is always present, not
            omitted when empty.
        minimum: Smallest included value, or `None` if `included` is empty.
        p25: 25th percentile (linear interpolation), or `None`.
        median: 50th percentile, or `None`. The headline statistic this
            module uses for implied valuation -- see module docstring,
            section 3, for why median rather than mean.
        p75: 75th percentile, or `None`.
        maximum: Largest included value, or `None`.
        warning: Set when `included` has fewer than `MIN_ROBUST_COMPS`
            peers (including zero), explaining why the statistics above are
            not, or cannot be, robust. `None` when the sample is adequate.
    """

    name: str
    included: Mapping[str, float]
    excluded: tuple[ExcludedMultiple, ...]
    minimum: float | None
    p25: float | None
    median: float | None
    p75: float | None
    maximum: float | None
    warning: str | None


def multiple_distribution(name: str, peer_multiples: Sequence[PeerMultiples]) -> MultipleDistribution:
    """Build one multiple's cross-sectional distribution across a peer set.

    Args:
        name: Which multiple, one of `MULTIPLE_NAMES`.
        peer_multiples: Every peer's already-computed `PeerMultiples`.

    Returns:
        The :class:`MultipleDistribution` for `name`.
    """
    included: dict[str, float] = {}
    excluded: list[ExcludedMultiple] = []
    for peer in peer_multiples:
        value = getattr(peer, name)
        if value is None:
            excluded.extend(exc for exc in peer.exclusions if exc.multiple_name == name)
        else:
            included[peer.name] = value

    n = len(included)
    if n == 0:
        warning = (
            f"{name}: all {len(peer_multiples)} peer(s) were excluded (non-positive "
            "denominator) -- no min/p25/median/p75/max can be computed"
        )
        return MultipleDistribution(
            name=name,
            included=MappingProxyType(included),
            excluded=tuple(excluded),
            minimum=None,
            p25=None,
            median=None,
            p75=None,
            maximum=None,
            warning=warning,
        )

    values = np.asarray(sorted(included.values()), dtype=float)
    warning = None
    if n < MIN_ROBUST_COMPS:
        warning = (
            f"{name}: only {n} peer(s) contribute to this distribution (fewer than "
            f"{MIN_ROBUST_COMPS}) -- a median of {n} point(s) is just the input(s) "
            "themselves, not a robust cross-sectional statistic"
        )

    return MultipleDistribution(
        name=name,
        included=MappingProxyType(included),
        excluded=tuple(excluded),
        minimum=float(values[0]),
        p25=float(np.percentile(values, 25)),
        median=float(np.percentile(values, 50)),
        p75=float(np.percentile(values, 75)),
        maximum=float(values[-1]),
        warning=warning,
    )


@dataclass(frozen=True)
class ImpliedValuation:
    """The target's implied value range from one multiple's peer distribution.

    Attributes:
        multiple_name: Which multiple (one of `MULTIPLE_NAMES`).
        is_ev_multiple: Whether this multiple's numerator is enterprise
            value (`ev_ebitda`/`ev_ebit`/`ev_sales`) rather than equity value
            (`pe`/`pb`).
        target_metric_value: The target's own metric multiplied against the
            peer distribution -- calendarised EBITDA/EBIT/Revenue for the EV
            multiples, book value of equity for `pb`, and calendarised
            diluted EPS x diluted shares outstanding (an aggregate
            "net income to diluted common" figure) for `pe`.
        implied_ev_by_quantile: `{"minimum"/"p25"/"median"/"p75"/"maximum":
            implied enterprise value}`, one entry per quantile of the peer
            distribution x `target_metric_value`. `None` for `pe`/`pb`,
            which imply equity value directly and never pass through an EV
            bridge. Also `None` when the source distribution had zero
            included peers.
        implied_equity_value_by_quantile: Same quantile keys, implied equity
            value. For the EV multiples this is `implied_ev_by_quantile`
            walked back down through the TARGET's own EV bridge (see
            `equity_value_from_enterprise_value`); for `pe`/`pb` it is
            `target_metric_value * multiple` directly. `None` when the
            source distribution had zero included peers.
        warning: Propagated from the underlying `MultipleDistribution`.
    """

    multiple_name: str
    is_ev_multiple: bool
    target_metric_value: float
    implied_ev_by_quantile: Mapping[str, float] | None
    implied_equity_value_by_quantile: Mapping[str, float] | None
    warning: str | None


_QUANTILE_FIELDS: tuple[str, ...] = ("minimum", "p25", "median", "p75", "maximum")


def implied_valuation(
    multiple_name: str,
    distribution: MultipleDistribution,
    target: TargetCompany,
    calendarised_target: Mapping[str, CalendarisedMetric],
) -> ImpliedValuation:
    """Project one multiple's peer distribution onto the target's own metric.

    Args:
        multiple_name: Which multiple, one of `MULTIPLE_NAMES`.
        distribution: That multiple's peer `MultipleDistribution`.
        target: The target company (for capital structure and share count).
        calendarised_target: `{"ebitda"/"ebit"/"revenue"/"diluted_eps":
            CalendarisedMetric}` -- the target's own metrics, aligned with
            the same policy as the peer set.

    Returns:
        The target's :class:`ImpliedValuation` for `multiple_name`.
    """
    is_ev = multiple_name in _EV_MULTIPLES

    if multiple_name == "pb":
        target_metric_value = target.book_value_of_equity
    elif multiple_name == "pe":
        target_metric_value = (
            calendarised_target["diluted_eps"].value * target.diluted_shares_outstanding
        )
    else:
        source_key = {"ev_ebitda": "ebitda", "ev_ebit": "ebit", "ev_sales": "revenue"}[multiple_name]
        target_metric_value = calendarised_target[source_key].value

    if distribution.median is None:
        return ImpliedValuation(
            multiple_name=multiple_name,
            is_ev_multiple=is_ev,
            target_metric_value=target_metric_value,
            implied_ev_by_quantile=None,
            implied_equity_value_by_quantile=None,
            warning=distribution.warning,
        )

    quantiles = {field: getattr(distribution, field) for field in _QUANTILE_FIELDS}

    if is_ev:
        implied_ev = {label: multiple * target_metric_value for label, multiple in quantiles.items()}
        implied_equity = {
            label: equity_value_from_enterprise_value(
                enterprise_value=ev,
                total_debt=target.total_debt,
                cash_and_equivalents=target.cash_and_equivalents,
                minority_interest=target.minority_interest,
                preferred_stock=target.preferred_stock,
                investments_in_associates=target.investments_in_associates,
            ).equity_value
            for label, ev in implied_ev.items()
        }
        return ImpliedValuation(
            multiple_name=multiple_name,
            is_ev_multiple=True,
            target_metric_value=target_metric_value,
            implied_ev_by_quantile=MappingProxyType(implied_ev),
            implied_equity_value_by_quantile=MappingProxyType(implied_equity),
            warning=distribution.warning,
        )

    implied_equity = {label: multiple * target_metric_value for label, multiple in quantiles.items()}
    return ImpliedValuation(
        multiple_name=multiple_name,
        is_ev_multiple=False,
        target_metric_value=target_metric_value,
        implied_ev_by_quantile=None,
        implied_equity_value_by_quantile=MappingProxyType(implied_equity),
        warning=distribution.warning,
    )


@dataclass(frozen=True)
class CompsResult:
    """Full output of one comparable-companies run: one target against N peers.

    Attributes:
        target_name: The target company's name.
        calendarisation_policy: `"ltm"` or `"calendar_year"` -- the ONE
            convention used for every peer and the target in this run (see
            module docstring, section 2).
        eps_basis: `"gaap"` or `"adjusted"` -- the ONE EPS convention shared
            by every peer's P/E and the target's implied P/E valuation.
        peer_multiples: Every peer's `PeerMultiples`, in the order supplied.
        distributions: `{multiple_name: MultipleDistribution}` for all five
            multiples in `MULTIPLE_NAMES`.
        implied_valuations: `{multiple_name: ImpliedValuation}` for all five
            multiples.
        warnings: Every small-sample / zero-peer warning raised anywhere in
            this run, so a caller reading only `warnings` still sees them
            without walking every distribution.
    """

    target_name: str
    calendarisation_policy: str
    eps_basis: str
    peer_multiples: tuple[PeerMultiples, ...]
    distributions: Mapping[str, MultipleDistribution]
    implied_valuations: Mapping[str, ImpliedValuation]
    warnings: tuple[str, ...]


def run_comps(
    target: TargetCompany,
    peers: Sequence[PeerCompany],
    *,
    calendarisation_policy: str,
) -> CompsResult:
    """Run a full comparable-companies valuation: EV bridge, multiples, implied range.

    Args:
        target: The company being valued.
        peers: The comparable set. Must be non-empty -- see `Raises`. Fewer
            than `MIN_ROBUST_COMPS` peers still runs, but every distribution
            (and the top-level `warnings`) carries an explicit small-sample
            warning.
        calendarisation_policy: `"ltm"` or `"calendar_year"`, applied to
            every peer and the target -- see module docstring, section 2.

    Returns:
        The full :class:`CompsResult`.

    Raises:
        MissingInputError: If `peers` is empty -- with no comparable
            companies at all there is nothing to build a multiple from, so
            the run is not runnable, the same as any other missing required
            input (see :mod:`.contracts`). This is distinct from the
            boundary case where peers were supplied but every one of them
            was later excluded from a given multiple by its own non-positive
            denominator -- that case returns a normal `CompsResult` whose
            `distributions[name]` is empty and carries a warning, because
            the peers themselves were not missing, only their multiples were
            not computable.
        ValuationError: If `calendarisation_policy` is not recognised, if
            two peers share a name, or if peers/target do not all declare
            the same `eps_basis` (mixing GAAP and adjusted EPS across the
            comp set would skew the P/E distribution by whatever one-time
            items the adjustment removes, the same kind of silent distortion
            the calendarisation-policy rule exists to prevent).
        MissingInputError: (propagated from `calendarise_metric`) if any
            peer's or the target's fiscal-period data lacks a field
            `calendarisation_policy` needs.
    """
    if calendarisation_policy not in CALENDARISATION_POLICIES:
        raise ValuationError(
            f"comps.run_comps: unknown calendarisation_policy {calendarisation_policy!r}, "
            f"must be one of {CALENDARISATION_POLICIES}"
        )
    if len(peers) == 0:
        raise MissingInputError(("peers",), "comps.run_comps")

    names = [peer.name for peer in peers]
    if len(set(names)) != len(names):
        raise ValuationError(f"comps.run_comps: duplicate peer names in {names}")

    all_bases = {peer.eps_basis for peer in peers} | {target.eps_basis}
    if len(all_bases) > 1:
        raise ValuationError(
            "comps.run_comps: mixed eps_basis across the comp set "
            f"{sorted(all_bases)} -- every peer and the target must declare the "
            "same EPS basis, or the P/E distribution mixes GAAP and adjusted "
            "earnings"
        )

    peer_multiples = tuple(peer_multiple_set(peer, calendarisation_policy) for peer in peers)
    distributions = {
        name: multiple_distribution(name, peer_multiples) for name in MULTIPLE_NAMES
    }

    calendarised_target = {
        "ebitda": calendarise_metric(
            target.ebitda, calendarisation_policy, metric_name="ebitda", company_name=target.name
        ),
        "ebit": calendarise_metric(
            target.ebit, calendarisation_policy, metric_name="ebit", company_name=target.name
        ),
        "revenue": calendarise_metric(
            target.revenue, calendarisation_policy, metric_name="revenue", company_name=target.name
        ),
        "diluted_eps": calendarise_metric(
            target.diluted_eps, calendarisation_policy, metric_name="diluted_eps", company_name=target.name
        ),
    }

    implied = {
        name: implied_valuation(name, distributions[name], target, calendarised_target)
        for name in MULTIPLE_NAMES
    }

    warnings = tuple(
        distributions[name].warning for name in MULTIPLE_NAMES if distributions[name].warning is not None
    )
    if len(peers) < MIN_ROBUST_COMPS:
        warnings = (
            f"comps.run_comps: only {len(peers)} peer(s) supplied (fewer than "
            f"{MIN_ROBUST_COMPS}) -- every multiple in this run is built from a "
            "sample too small for its median to be a robust statistic",
        ) + warnings

    return CompsResult(
        target_name=target.name,
        calendarisation_policy=calendarisation_policy,
        eps_basis=target.eps_basis,
        peer_multiples=peer_multiples,
        distributions=MappingProxyType(distributions),
        implied_valuations=MappingProxyType(implied),
        warnings=warnings,
    )
