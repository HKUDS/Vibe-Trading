"""Discounted cash flow valuation: WACC, the FCFF bridge, dual terminal value,
discounting, and the bridge from enterprise value to value per share.

This module is the executable form of the DCF walkthrough that used to live as
markdown in valuation write-ups -- a WACC formula, an FCFF formula, a Gordon
growth terminal value, all typed out fresh (and inconsistently) on every run.
Several design choices are deliberate and are exactly the places a hand-rolled
DCF usually goes wrong silently.

**No valuation parameter defaults to anything.** This follows
:mod:`src.quantlib.valuation.contracts` to the letter: the risk-free rate,
beta, the equity risk premium, the cost of debt, the tax rate, the terminal
growth rate, the exit multiple and the diluted share count are all required
arguments with no fallback value anywhere in this file. :func:`run_dcf` takes
them as a flat mapping and refuses to run with :class:`~..contracts.MissingInputError`
if any is absent, so a caller assembling a model from filings learns exactly
what is still missing rather than getting a number built on a guess.

**Terminal growth and the exit multiple are Assumptions, not bare floats.**
``contracts.py``'s own docstring names "terminal growth quietly defaulted to
2.5%" as the canonical example of a valuation opinion wearing a constant's
clothes. Both terminal-value drivers here must therefore arrive as
:class:`~..contracts.Assumption` objects carrying a ``basis`` -- the model
refuses a bare number for either one, and the justification travels through to
:class:`TerminalValueResult` so it can be checked, not just the output.

**Terminal value is always computed two ways, and the two are cross-checked.**
:func:`terminal_value` never runs the perpetuity-growth method alone: it also
runs the exit-multiple method and reports each one's implied version of the
other's driver -- the perpetuity value's implied EV/EBITDA multiple, and the
exit value's implied perpetuity growth rate. This is the only mechanism that
catches a terminal assumption that is arithmetically fine but economically
detached from reality (a growth rate that implies a 35x EBITDA multiple is
wrong even though the Gordon growth formula was applied correctly). ``growth
>= WACC`` is refused outright -- the terminal value is undefined there, not
merely large -- while growth above a long-run nominal GDP reference is only
flagged, because that is a judgment call the model has no standing to veto.

**``delta_nwc`` sign convention.** An *increase* in net working capital is a
*use* of cash: ``delta_nwc > 0`` means working capital grew period over
period and is subtracted from FCFF; a working-capital release
(``delta_nwc < 0``) adds cash back. This is the ordinary balance-sheet
convention, stated explicitly because the alternative reading (delta_nwc as
"cash contribution") is exactly as common in the wild and the two disagree on
every sign.

**Discounting convention is exact, not approximate, at the enterprise-value
level.** Mid-year discounting multiplies every present value by exactly
``(1 + WACC) ** 0.5`` relative to year-end discounting, for one reason: this
module discounts the terminal value using the *same* time index as the final
explicit forecast year (``t = n - 0.5`` under mid-year, ``t = n`` under
year-end), so every dollar in the model -- explicit FCFF or terminal value --
is scaled by the identical constant when the convention flips. That makes the
mid-year/year-end enterprise-value ratio equal to ``sqrt(1 + WACC)`` exactly,
not approximately, which is a strong assertion the test suite checks bit for
bit. The equality does *not* extend to equity value or value per share, since
the net-debt bridge below enterprise value is a fixed balance-sheet fact that
does not scale with the discounting convention.

**Equity bridge sign convention.** Every line between enterprise value and
equity value is supplied as a **non-negative magnitude**; the formula itself
applies the sign::

    equity_value = EV - total_debt + cash_and_equivalents - minority_interest
                   - preferred_equity + associate_investments

Passing a negative magnitude is refused rather than silently flipping the
formula's intent, because that is the single most common sign error in a
hand-built bridge.

**Capital-structure basis is a required, explicit argument.** WACC weights can
come from *current* market values (``E / (D + E)``, ``D / (D + E)`` off
today's market value of equity and debt) or from a *target* structure the
analyst believes the firm is moving toward. The two are not interchangeable:
current weights are only the theoretically correct WACC weights if the firm
intends to hold that mix going forward, and a firm expected to lever up or
delever needs target weights instead (Copeland/Koller enterprise-DCF
convention). Nothing here picks one silently -- see
``capital_structure_basis`` on :func:`wacc` and :func:`run_dcf`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.quantlib.valuation.contracts import (
    Assumption,
    MissingInputError,
    ValuationError,
    require_inputs,
    require_positive,
)

__all__ = [
    "CAPITAL_STRUCTURE_BASES",
    "DISCOUNTING_CONVENTIONS",
    "TERMINAL_VALUE_METHODS",
    "DEFAULT_LONG_RUN_GDP_GROWTH_CEILING",
    "DCF_BASE_REQUIRED_FIELDS",
    "DCF_CURRENT_STRUCTURE_FIELDS",
    "DCF_TARGET_STRUCTURE_FIELDS",
    "WACCResult",
    "FCFFYear",
    "TerminalValueResult",
    "DiscountedCashFlow",
    "NetDebtBridgeResult",
    "DCFResult",
    "wacc",
    "fcff_bridge",
    "terminal_value",
    "discount_fcff",
    "equity_bridge",
    "run_dcf",
    "sensitivity_grid",
]

#: How WACC's capital-structure weights are sourced. ``"current"`` derives
#: ``E / (D + E)`` and ``D / (D + E)`` from today's market values; ``"target"``
#: takes the weights directly as the analyst's view of the structure the firm
#: is moving toward. See the module docstring for why the two are not
#: interchangeable.
CAPITAL_STRUCTURE_BASES: tuple[str, ...] = ("current", "target")

#: Timing convention for discounting a cash flow that arrives sometime during
#: year ``t``. ``"mid_year"`` assumes it lands on average at ``t - 0.5``;
#: ``"year_end"`` assumes it lands at ``t``.
DISCOUNTING_CONVENTIONS: tuple[str, ...] = ("mid_year", "year_end")

#: Which terminal-value estimate feeds the enterprise-value bridge. Both
#: methods are always computed and cross-checked (see :func:`terminal_value`);
#: this only selects which one is discounted into ``DCFResult.enterprise_value``.
TERMINAL_VALUE_METHODS: tuple[str, ...] = ("perpetuity_growth", "exit_multiple")

#: Reference ceiling used only to FLAG a perpetuity growth assumption, never to
#: block or alter one -- a terminal growth rate above long-run nominal GDP
#: growth is not mathematically wrong, only worth a second look. This is a
#: diagnostic threshold, not a valuation input: it never appears in any formula
#: that produces a price. 4% approximates long-run US real GDP growth
#: (~2%) plus a long-run inflation target (~2%); callers valuing a business
#: against a different economy should pass their own ``gdp_growth_ceiling``.
DEFAULT_LONG_RUN_GDP_GROWTH_CEILING: float = 0.04

#: Flat input-mapping keys :func:`run_dcf` requires regardless of
#: ``capital_structure_basis``.
DCF_BASE_REQUIRED_FIELDS: tuple[str, ...] = (
    "risk_free_rate",
    "beta",
    "equity_risk_premium",
    "pretax_cost_of_debt",
    "tax_rate",
    "ebit",
    "depreciation_amortization",
    "capex",
    "delta_nwc",
    "terminal_growth",
    "exit_multiple",
    "total_debt",
    "cash_and_equivalents",
    "minority_interest",
    "preferred_equity",
    "associate_investments",
    "diluted_shares",
)

#: Additional keys :func:`run_dcf` requires when ``capital_structure_basis="current"``.
DCF_CURRENT_STRUCTURE_FIELDS: tuple[str, ...] = (
    "market_value_of_equity",
    "market_value_of_debt",
)

#: Additional keys :func:`run_dcf` requires when ``capital_structure_basis="target"``.
DCF_TARGET_STRUCTURE_FIELDS: tuple[str, ...] = (
    "target_equity_weight",
    "target_debt_weight",
)

#: Slack allowed when checking that capital-structure weights sum to 1, and
#: when re-checking a dataclass's own internal arithmetic in ``__post_init__``.
_RECONCILIATION_TOLERANCE: float = 1e-6


# ---------------------------------------------------------------------------
# small private helpers
# ---------------------------------------------------------------------------


def _require_assumption(value: Any, expected_name: str, model: str) -> Assumption:
    """Check that a terminal-value driver arrived as a justified Assumption.

    Args:
        value: Candidate supplied by the caller.
        expected_name: The :attr:`Assumption.name` this slot expects.
        model: Name used in the error message.

    Returns:
        ``value``, unchanged.

    Raises:
        ValuationError: If ``value`` is not an :class:`Assumption`, or if its
            ``name`` does not match ``expected_name`` (which usually means two
            assumptions were passed under swapped keys).
    """
    if not isinstance(value, Assumption):
        raise ValuationError(
            f"{model}: {expected_name!r} must be supplied as an Assumption("
            f"name=..., value=..., basis=...) carrying its justification, not "
            f"a bare {type(value).__name__}. A terminal growth rate or exit "
            "multiple chosen without a stated reason is exactly the kind of "
            "silent default this package refuses to make on your behalf."
        )
    if value.name != expected_name:
        raise ValuationError(
            f"{model}: expected an Assumption named {expected_name!r}, got "
            f"{value.name!r}; check that assumptions were not passed under "
            "swapped keys."
        )
    return value


def _require_nonnegative(value: float, name: str, model: str) -> float:
    """Check a value that is a signed formula's magnitude, so must be >= 0.

    Args:
        value: The candidate magnitude.
        name: Field name for the error message.
        model: Model name for the error message.

    Returns:
        ``value`` as a float.

    Raises:
        ValuationError: If the value is negative or not a finite number. A
            negative magnitude here would silently flip the sign the bridge
            formula already applies.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValuationError(f"{model}: {name} must be a number, got {value!r}") from exc
    if not math.isfinite(numeric) or numeric < 0.0:
        raise ValuationError(
            f"{model}: {name} must be supplied as a non-negative magnitude "
            f"(its sign is applied by the bridge formula), got {numeric!r}"
        )
    return numeric


def _require_finite(value: float, name: str, model: str) -> float:
    """Check a value is a finite number, refusing NaN and infinity.

    Args:
        value: The candidate value.
        name: Field name for the error message.
        model: Model name for the error message.

    Returns:
        ``value`` as a float.

    Raises:
        ValuationError: If the value is not a finite number. A non-finite
            input here would otherwise flow through the valuation arithmetic
            and surface as a silently wrong per-share number, which is exactly
            the outcome the package's no-silent-defaults rule exists to prevent.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValuationError(f"{model}: {name} must be a number, got {value!r}") from exc
    if not math.isfinite(numeric):
        raise ValuationError(
            f"{model}: {name} must be a finite number, got {numeric!r}"
        )
    return numeric


def _validate_weights(equity_weight: float, debt_weight: float, *, model: str) -> None:
    """Check that a pair of capital-structure weights is usable.

    Args:
        equity_weight: Proposed ``E / (D + E)``.
        debt_weight: Proposed ``D / (D + E)``.
        model: Model name for the error message.

    Raises:
        ValuationError: If either weight is negative, or if they do not sum to
            1 within :data:`_RECONCILIATION_TOLERANCE`.
    """
    if equity_weight < 0.0 or debt_weight < 0.0:
        raise ValuationError(
            f"{model}: capital-structure weights must be non-negative, got "
            f"equity_weight={equity_weight!r} debt_weight={debt_weight!r}"
        )
    total = equity_weight + debt_weight
    if abs(total - 1.0) > _RECONCILIATION_TOLERANCE:
        raise ValuationError(
            f"{model}: capital-structure weights must sum to 1 (within "
            f"{_RECONCILIATION_TOLERANCE:g}), got equity_weight={equity_weight!r} "
            f"+ debt_weight={debt_weight!r} = {total!r}"
        )


# ---------------------------------------------------------------------------
# WACC
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WACCResult:
    """The WACC build, with every component that fed it kept visible.

    Attributes:
        risk_free_rate: ``rf`` used in CAPM.
        beta: Levered beta used in CAPM.
        equity_risk_premium: ``ERP`` used in CAPM.
        size_premium: Additive small-cap premium, ``0.0`` if not supplied.
        country_risk_premium: Additive sovereign/country premium, ``0.0`` if
            not supplied.
        cost_of_equity: ``Re = rf + beta * ERP + size_premium + country_risk_premium``.
        pretax_cost_of_debt: ``Rd`` before the tax shield.
        tax_rate: Marginal tax rate applied to the debt tax shield (and, in
            :func:`fcff_bridge`, to EBIT -- the same statutory rate drives both).
        cost_of_debt_after_tax: ``Rd * (1 - tax_rate)``.
        capital_structure_basis: ``"current"`` or ``"target"``; see the module
            docstring for the difference.
        equity_weight: ``E / (D + E)``.
        debt_weight: ``D / (D + E)``.
        wacc: The blended discount rate,
            ``equity_weight * cost_of_equity + debt_weight * cost_of_debt_after_tax``.
    """

    risk_free_rate: float
    beta: float
    equity_risk_premium: float
    size_premium: float
    country_risk_premium: float
    cost_of_equity: float
    pretax_cost_of_debt: float
    tax_rate: float
    cost_of_debt_after_tax: float
    capital_structure_basis: str
    equity_weight: float
    debt_weight: float
    wacc: float

    def __post_init__(self) -> None:
        """Re-check the blend arithmetic and the weight identity.

        Raises:
            ValueError: If the weights do not sum to 1, or ``wacc`` is not the
                stated weighted blend of the two costs of capital.
        """
        _validate_weights(self.equity_weight, self.debt_weight, model="WACCResult")
        expected = (
            self.equity_weight * self.cost_of_equity
            + self.debt_weight * self.cost_of_debt_after_tax
        )
        if not math.isclose(
            self.wacc, expected, rel_tol=_RECONCILIATION_TOLERANCE, abs_tol=1e-12
        ):
            raise ValueError(
                f"WACCResult.wacc={self.wacc!r} does not match the weighted "
                f"blend {expected!r} of cost_of_equity and cost_of_debt_after_tax"
            )


def wacc(
    *,
    risk_free_rate: float,
    beta: float,
    equity_risk_premium: float,
    pretax_cost_of_debt: float,
    tax_rate: float,
    capital_structure_basis: str,
    market_value_of_equity: float | None = None,
    market_value_of_debt: float | None = None,
    target_equity_weight: float | None = None,
    target_debt_weight: float | None = None,
    size_premium: float = 0.0,
    country_risk_premium: float = 0.0,
) -> WACCResult:
    """Build the weighted average cost of capital.

    ``Re`` is CAPM plus two optional additive premiums; ``Rd`` is the pretax
    cost of debt shielded by the tax rate; the two are blended by
    capital-structure weights sourced per ``capital_structure_basis``.

    Args:
        risk_free_rate: ``rf``, as a decimal.
        beta: Levered equity beta.
        equity_risk_premium: ``ERP``, as a decimal.
        pretax_cost_of_debt: ``Rd`` before the tax shield, as a decimal.
        tax_rate: Marginal tax rate in ``[0, 1]``.
        capital_structure_basis: One of :data:`CAPITAL_STRUCTURE_BASES`.
            ``"current"`` derives weights from today's market values;
            ``"target"`` takes the weights directly. Required, no default --
            see the module docstring for why the two are not interchangeable.
        market_value_of_equity: Market value of equity. Required (and only
            used) when ``capital_structure_basis="current"``.
        market_value_of_debt: Market value of debt. Required (and only used)
            when ``capital_structure_basis="current"``.
        target_equity_weight: Target ``E / (D + E)``. Required (and only used)
            when ``capital_structure_basis="target"``.
        target_debt_weight: Target ``D / (D + E)``. Required (and only used)
            when ``capital_structure_basis="target"``.
        size_premium: Additive small-cap premium on cost of equity. Optional --
            absence means "not applying one", which is a structural choice, not
            a guessed magnitude standing in for an unknown rate.
        country_risk_premium: Additive sovereign/country premium on cost of
            equity. Same optionality rationale as ``size_premium``.

    Returns:
        A :class:`WACCResult` with every intermediate figure visible.

    Raises:
        MissingInputError: If the market-value or target-weight pair matching
            ``capital_structure_basis`` is not fully supplied.
        ValuationError: If ``capital_structure_basis`` is unrecognised, if
            ``tax_rate`` is outside ``[0, 1]``, if a market value is negative
            or not finite, if the market value of equity plus debt is zero
            (weights undefined), if the resulting weights are negative or do
            not sum to 1, or if ``risk_free_rate``, ``beta``,
            ``equity_risk_premium``, ``pretax_cost_of_debt``, ``size_premium``,
            ``country_risk_premium`` or a target weight is not a finite number.
    """
    if capital_structure_basis not in CAPITAL_STRUCTURE_BASES:
        raise ValuationError(
            f"wacc: capital_structure_basis must be one of "
            f"{CAPITAL_STRUCTURE_BASES}, got {capital_structure_basis!r}"
        )
    if not 0.0 <= tax_rate <= 1.0:
        raise ValuationError(f"wacc: tax_rate must be within [0, 1], got {tax_rate!r}")

    if capital_structure_basis == "current":
        missing = [
            name
            for name, value in (
                ("market_value_of_equity", market_value_of_equity),
                ("market_value_of_debt", market_value_of_debt),
            )
            if value is None
        ]
        if missing:
            raise MissingInputError(missing, "wacc")
        equity_mv = _require_nonnegative(
            market_value_of_equity, "market_value_of_equity", "wacc"
        )
        debt_mv = _require_nonnegative(
            market_value_of_debt, "market_value_of_debt", "wacc"
        )
        total_mv = equity_mv + debt_mv
        if total_mv <= 0.0:
            raise ValuationError(
                "wacc: market value of equity plus debt is zero (D + E = 0); "
                "capital-structure weights are undefined"
            )
        equity_weight = equity_mv / total_mv
        debt_weight = debt_mv / total_mv
    else:
        missing = [
            name
            for name, value in (
                ("target_equity_weight", target_equity_weight),
                ("target_debt_weight", target_debt_weight),
            )
            if value is None
        ]
        if missing:
            raise MissingInputError(missing, "wacc")
        equity_weight = _require_finite(
            target_equity_weight, "target_equity_weight", "wacc"
        )
        debt_weight = _require_finite(target_debt_weight, "target_debt_weight", "wacc")

    _validate_weights(equity_weight, debt_weight, model="wacc")

    risk_free_rate = _require_finite(risk_free_rate, "risk_free_rate", "wacc")
    beta = _require_finite(beta, "beta", "wacc")
    equity_risk_premium = _require_finite(equity_risk_premium, "equity_risk_premium", "wacc")
    pretax_cost_of_debt = _require_finite(pretax_cost_of_debt, "pretax_cost_of_debt", "wacc")
    size_premium = _require_finite(size_premium, "size_premium", "wacc")
    country_risk_premium = _require_finite(country_risk_premium, "country_risk_premium", "wacc")

    cost_of_equity = (
        risk_free_rate + beta * equity_risk_premium + size_premium + country_risk_premium
    )
    cost_of_debt_after_tax = pretax_cost_of_debt * (1.0 - tax_rate)
    blended = equity_weight * cost_of_equity + debt_weight * cost_of_debt_after_tax

    return WACCResult(
        risk_free_rate=float(risk_free_rate),
        beta=float(beta),
        equity_risk_premium=float(equity_risk_premium),
        size_premium=float(size_premium),
        country_risk_premium=float(country_risk_premium),
        cost_of_equity=cost_of_equity,
        pretax_cost_of_debt=float(pretax_cost_of_debt),
        tax_rate=float(tax_rate),
        cost_of_debt_after_tax=cost_of_debt_after_tax,
        capital_structure_basis=capital_structure_basis,
        equity_weight=equity_weight,
        debt_weight=debt_weight,
        wacc=blended,
    )


# ---------------------------------------------------------------------------
# FCFF bridge
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FCFFYear:
    """One projection year's bridge from EBIT to free cash flow to the firm.

    ``FCFF = NOPAT + depreciation_amortization - capex - delta_nwc``. Every
    step is a field so a reader can see which one consumed the cash, not just
    the final number.

    Attributes:
        year: 1-indexed projection year (1 is the first forecast year).
        ebit: Earnings before interest and tax.
        tax_rate: Marginal tax rate applied to EBIT.
        nopat: ``ebit * (1 - tax_rate)``.
        depreciation_amortization: Non-cash D&A added back.
        capex: Capital expenditure, a positive magnitude representing a cash
            outflow.
        delta_nwc: Change in net working capital. **Positive means working
            capital increased and cash was used**; negative means working
            capital was released and cash was returned. See the module
            docstring.
        fcff: ``nopat + depreciation_amortization - capex - delta_nwc``.
    """

    year: int
    ebit: float
    tax_rate: float
    nopat: float
    depreciation_amortization: float
    capex: float
    delta_nwc: float
    fcff: float

    def __post_init__(self) -> None:
        """Re-check the NOPAT and FCFF arithmetic.

        Raises:
            ValueError: If ``nopat`` or ``fcff`` do not match their formulas,
                or ``year`` is not a positive integer.
        """
        if self.year < 1:
            raise ValueError(f"FCFFYear.year must be >= 1, got {self.year!r}")
        expected_nopat = self.ebit * (1.0 - self.tax_rate)
        if not math.isclose(
            self.nopat, expected_nopat, rel_tol=_RECONCILIATION_TOLERANCE, abs_tol=1e-9
        ):
            raise ValueError(
                f"FCFFYear(year={self.year}).nopat={self.nopat!r} does not match "
                f"ebit * (1 - tax_rate) = {expected_nopat!r}"
            )
        expected_fcff = (
            self.nopat + self.depreciation_amortization - self.capex - self.delta_nwc
        )
        if not math.isclose(
            self.fcff, expected_fcff, rel_tol=_RECONCILIATION_TOLERANCE, abs_tol=1e-9
        ):
            raise ValueError(
                f"FCFFYear(year={self.year}).fcff={self.fcff!r} does not match the "
                f"bridge total {expected_fcff!r}"
            )


def fcff_bridge(
    *,
    ebit: Sequence[float],
    tax_rate: float,
    depreciation_amortization: Sequence[float],
    capex: Sequence[float],
    delta_nwc: Sequence[float],
) -> tuple[FCFFYear, ...]:
    """Build the EBIT -> FCFF bridge for every projection year.

    Args:
        ebit: EBIT forecast, one entry per projection year, oldest first.
        tax_rate: Marginal tax rate in ``[0, 1]``, applied to every year.
        depreciation_amortization: D&A forecast, same length as ``ebit``.
        capex: Capital expenditure forecast (positive = cash outflow), same
            length as ``ebit``.
        delta_nwc: Net-working-capital change forecast (positive = cash
            outflow; see the module docstring), same length as ``ebit``.

    Returns:
        One :class:`FCFFYear` per projection year, in order.

    Raises:
        ValuationError: If ``tax_rate`` is outside ``[0, 1]``, if ``ebit`` is
            empty, if the other three forecasts are not the same length as
            ``ebit``, or if any forecast entry is not a finite number.
    """
    if not 0.0 <= tax_rate <= 1.0:
        raise ValuationError(f"fcff_bridge: tax_rate must be within [0, 1], got {tax_rate!r}")

    ebit_list = list(ebit)
    horizon = len(ebit_list)
    if horizon == 0:
        raise ValuationError(
            "fcff_bridge: ebit forecast is empty; at least one projection year "
            "is required"
        )
    forecasts = {
        "depreciation_amortization": list(depreciation_amortization),
        "capex": list(capex),
        "delta_nwc": list(delta_nwc),
    }
    for name, values in forecasts.items():
        if len(values) != horizon:
            raise ValuationError(
                f"fcff_bridge: {name} has {len(values)} year(s), expected "
                f"{horizon} to match ebit"
            )

    years = []
    for index in range(horizon):
        ebit_value = _require_finite(ebit_list[index], f"ebit[{index}]", "fcff_bridge")
        da_value = _require_finite(
            forecasts["depreciation_amortization"][index],
            f"depreciation_amortization[{index}]",
            "fcff_bridge",
        )
        capex_value = _require_finite(
            forecasts["capex"][index], f"capex[{index}]", "fcff_bridge"
        )
        delta_nwc_value = _require_finite(
            forecasts["delta_nwc"][index], f"delta_nwc[{index}]", "fcff_bridge"
        )
        nopat = ebit_value * (1.0 - tax_rate)
        fcff_value = nopat + da_value - capex_value - delta_nwc_value
        years.append(
            FCFFYear(
                year=index + 1,
                ebit=ebit_value,
                tax_rate=tax_rate,
                nopat=nopat,
                depreciation_amortization=da_value,
                capex=capex_value,
                delta_nwc=delta_nwc_value,
                fcff=fcff_value,
            )
        )
    return tuple(years)


# ---------------------------------------------------------------------------
# Dual terminal value
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TerminalValueResult:
    """Both terminal-value estimates, each cross-checked against the other.

    Attributes:
        wacc_rate: Discount rate used by the perpetuity-growth method.
        terminal_growth: The :class:`Assumption` behind the perpetuity-growth
            method, carrying its ``basis``.
        perpetuity_terminal_value: ``FCFF_{n+1} / (wacc_rate - g)`` where
            ``FCFF_{n+1} = FCFF_n * (1 + g)``.
        terminal_year_ebitda: ``EBITDA`` of the final explicit forecast year,
            used by the exit-multiple method.
        exit_multiple: The :class:`Assumption` behind the exit-multiple
            method, carrying its ``basis``.
        exit_terminal_value: ``terminal_year_ebitda * exit_multiple.value``.
        implied_ev_ebitda_multiple: What EV/EBITDA multiple
            ``perpetuity_terminal_value`` implies -- the perpetuity method's
            result, restated in the exit method's units, so a reader can judge
            whether the growth assumption is realistic on its face.
        implied_perpetuity_growth: What perpetuity growth rate
            ``exit_terminal_value`` implies -- the exit method's result,
            restated in the perpetuity method's units.
        gdp_growth_ceiling: Reference ceiling used for ``growth_exceeds_gdp_ceiling``.
        growth_exceeds_gdp_ceiling: ``True`` if ``terminal_growth.value`` is
            above ``gdp_growth_ceiling``. A flag, never an error -- see the
            module docstring.
    """

    wacc_rate: float
    terminal_growth: Assumption
    perpetuity_terminal_value: float
    terminal_year_ebitda: float
    exit_multiple: Assumption
    exit_terminal_value: float
    implied_ev_ebitda_multiple: float
    implied_perpetuity_growth: float
    gdp_growth_ceiling: float
    growth_exceeds_gdp_ceiling: bool

    def __post_init__(self) -> None:
        """Re-check that the stored growth rate is still below WACC.

        Raises:
            ValueError: If ``terminal_growth.value >= wacc_rate``. This should
                already have been refused by :func:`terminal_value` before
                construction; this is a second, independent check.
        """
        if float(self.terminal_growth.value) >= self.wacc_rate:
            raise ValueError(
                f"TerminalValueResult.terminal_growth.value="
                f"{self.terminal_growth.value!r} is not below wacc_rate="
                f"{self.wacc_rate!r}"
            )


def terminal_value(
    *,
    final_year_fcff: float,
    terminal_year_ebitda: float,
    wacc_rate: float,
    terminal_growth: Assumption,
    exit_multiple: Assumption,
    gdp_growth_ceiling: float = DEFAULT_LONG_RUN_GDP_GROWTH_CEILING,
) -> TerminalValueResult:
    """Compute both terminal-value estimates and cross-validate them.

    Args:
        final_year_fcff: ``FCFF_n``, the last explicit forecast year's free
            cash flow to the firm.
        terminal_year_ebitda: ``EBITDA`` of the final explicit forecast year.
        wacc_rate: The discount rate, as a decimal.
        terminal_growth: An :class:`Assumption` naming the perpetuity growth
            rate ``g`` and its basis.
        exit_multiple: An :class:`Assumption` naming the EV/EBITDA exit
            multiple and its basis.
        gdp_growth_ceiling: Reference ceiling used only to flag
            ``terminal_growth`` -- see :data:`DEFAULT_LONG_RUN_GDP_GROWTH_CEILING`.

    Returns:
        A :class:`TerminalValueResult` carrying both terminal values and both
        cross-checks.

    Raises:
        ValuationError: If either argument is not the matching
            :class:`Assumption`; if ``wacc_rate``, ``final_year_fcff``,
            ``terminal_year_ebitda``, ``terminal_growth.value`` or
            ``exit_multiple.value`` is not a finite number; if ``wacc_rate <= -1``;
            if ``terminal_growth.value >= wacc_rate`` (the perpetuity terminal
            value is negative or infinite there, not merely large); if
            ``terminal_year_ebitda <= 0`` (an EV/EBITDA multiple is undefined);
            if ``exit_multiple.value <= 0``; or if the exit terminal value
            happens to equal ``-final_year_fcff`` exactly, which makes the
            implied-growth reverse-solve's denominator zero.
    """
    _require_assumption(terminal_growth, "terminal_growth", "terminal_value")
    _require_assumption(exit_multiple, "exit_multiple", "terminal_value")

    final_year_fcff = _require_finite(final_year_fcff, "final_year_fcff", "terminal_value")
    terminal_year_ebitda = _require_finite(
        terminal_year_ebitda, "terminal_year_ebitda", "terminal_value"
    )
    wacc_rate = _require_finite(wacc_rate, "wacc_rate", "terminal_value")

    if wacc_rate <= -1.0:
        raise ValuationError(
            f"terminal_value: wacc_rate must exceed -1, got {wacc_rate!r}"
        )
    growth = _require_finite(terminal_growth.value, "terminal_growth.value", "terminal_value")
    if growth >= wacc_rate:
        raise ValuationError(
            f"terminal_value: terminal_growth ({growth!r}) must be strictly "
            f"less than WACC ({wacc_rate!r}); at or above WACC the Gordon-growth "
            "terminal value is negative or infinite, not merely a large number. "
            "Lower the growth assumption or check the WACC build."
        )
    if terminal_year_ebitda <= 0.0:
        raise ValuationError(
            f"terminal_value: terminal_year_ebitda must be positive to derive "
            f"an implied EV/EBITDA multiple, got {terminal_year_ebitda!r}"
        )
    multiple = _require_finite(exit_multiple.value, "exit_multiple.value", "terminal_value")
    if multiple <= 0.0:
        raise ValuationError(
            f"terminal_value: exit_multiple.value must be positive, got {multiple!r}"
        )

    next_year_fcff = final_year_fcff * (1.0 + growth)
    perpetuity_tv = next_year_fcff / (wacc_rate - growth)
    exit_tv = terminal_year_ebitda * multiple

    implied_ev_ebitda_multiple = perpetuity_tv / terminal_year_ebitda

    denominator = exit_tv + final_year_fcff
    if denominator == 0.0:
        raise ValuationError(
            "terminal_value: cannot solve the exit multiple's implied perpetuity "
            "growth because exit_terminal_value and final_year_fcff are equal "
            "and opposite, making the reverse-solve denominator zero"
        )
    implied_perpetuity_growth = (exit_tv * wacc_rate - final_year_fcff) / denominator

    return TerminalValueResult(
        wacc_rate=float(wacc_rate),
        terminal_growth=terminal_growth,
        perpetuity_terminal_value=perpetuity_tv,
        terminal_year_ebitda=float(terminal_year_ebitda),
        exit_multiple=exit_multiple,
        exit_terminal_value=exit_tv,
        implied_ev_ebitda_multiple=implied_ev_ebitda_multiple,
        implied_perpetuity_growth=implied_perpetuity_growth,
        gdp_growth_ceiling=float(gdp_growth_ceiling),
        growth_exceeds_gdp_ceiling=growth > gdp_growth_ceiling,
    )


# ---------------------------------------------------------------------------
# Discounting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscountedCashFlow:
    """One projection year's FCFF, discounted to present value.

    Attributes:
        year: 1-indexed projection year, matching :attr:`FCFFYear.year`.
        fcff: The undiscounted free cash flow to the firm for this year.
        wacc_rate: Discount rate used.
        time_period: The exponent ``t`` actually used --
            ``year - 0.5`` under ``"mid_year"``, ``year`` under ``"year_end"``.
        discount_factor: ``(1 + wacc_rate) ** -time_period``.
        present_value: ``fcff * discount_factor``.
    """

    year: int
    fcff: float
    wacc_rate: float
    time_period: float
    discount_factor: float
    present_value: float

    def __post_init__(self) -> None:
        """Re-check the discount factor and present-value arithmetic.

        Raises:
            ValueError: If ``discount_factor`` or ``present_value`` do not
                match their formulas.
        """
        expected_factor = (1.0 + self.wacc_rate) ** (-self.time_period)
        if not math.isclose(
            self.discount_factor, expected_factor, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise ValueError(
                f"DiscountedCashFlow(year={self.year}).discount_factor="
                f"{self.discount_factor!r} does not match "
                f"(1 + wacc_rate) ** -time_period = {expected_factor!r}"
            )
        expected_pv = self.fcff * self.discount_factor
        if not math.isclose(self.present_value, expected_pv, rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError(
                f"DiscountedCashFlow(year={self.year}).present_value="
                f"{self.present_value!r} does not match fcff * discount_factor "
                f"= {expected_pv!r}"
            )


def discount_fcff(
    fcff_years: Sequence[FCFFYear],
    *,
    wacc_rate: float,
    discounting_convention: str,
) -> tuple[DiscountedCashFlow, ...]:
    """Discount every projection year's FCFF to present value.

    Args:
        fcff_years: The FCFF bridge, e.g. from :func:`fcff_bridge`.
        wacc_rate: Discount rate, as a decimal, strictly greater than -1.
        discounting_convention: One of :data:`DISCOUNTING_CONVENTIONS`.
            Required, no default -- see the module docstring for why mid-year
            and year-end are not interchangeable.

    Returns:
        One :class:`DiscountedCashFlow` per input year, in the same order.

    Raises:
        ValuationError: If ``discounting_convention`` is unrecognised, if
            ``fcff_years`` is empty, if ``wacc_rate`` is not a finite number,
            or if ``wacc_rate <= -1``.
    """
    if discounting_convention not in DISCOUNTING_CONVENTIONS:
        raise ValuationError(
            f"discount_fcff: discounting_convention must be one of "
            f"{DISCOUNTING_CONVENTIONS}, got {discounting_convention!r}"
        )
    if not fcff_years:
        raise ValuationError("discount_fcff: fcff_years is empty")
    wacc_rate = _require_finite(wacc_rate, "wacc_rate", "discount_fcff")
    if wacc_rate <= -1.0:
        raise ValuationError(f"discount_fcff: wacc_rate must exceed -1, got {wacc_rate!r}")

    results = []
    for entry in fcff_years:
        time_period = (
            entry.year - 0.5 if discounting_convention == "mid_year" else float(entry.year)
        )
        discount_factor_value = (1.0 + wacc_rate) ** (-time_period)
        results.append(
            DiscountedCashFlow(
                year=entry.year,
                fcff=entry.fcff,
                wacc_rate=float(wacc_rate),
                time_period=time_period,
                discount_factor=discount_factor_value,
                present_value=entry.fcff * discount_factor_value,
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# Net-debt bridge to value per share
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NetDebtBridgeResult:
    """The bridge from enterprise value to value per share.

    Every balance-sheet item is a non-negative magnitude; the sign each one
    carries in the formula is fixed and documented here, not inferred from the
    number's own sign.

    Attributes:
        enterprise_value: EV entering the bridge.
        total_debt: Subtracted -- debt is a claim ahead of equity.
        cash_and_equivalents: Added -- cash is equity value EV does not price.
        minority_interest: Subtracted -- non-controlling interests' claim on
            consolidated value.
        preferred_equity: Subtracted -- senior to common equity.
        associate_investments: Added -- equity-method investments EV does not
            capture (their earnings are typically excluded from EBIT/EBITDA).
        equity_value: ``enterprise_value - total_debt + cash_and_equivalents -
            minority_interest - preferred_equity + associate_investments``.
        diluted_shares: Fully diluted share count.
        value_per_share: ``equity_value / diluted_shares``.
    """

    enterprise_value: float
    total_debt: float
    cash_and_equivalents: float
    minority_interest: float
    preferred_equity: float
    associate_investments: float
    equity_value: float
    diluted_shares: float
    value_per_share: float

    def __post_init__(self) -> None:
        """Re-check the bridge and per-share arithmetic.

        Raises:
            ValueError: If ``equity_value`` or ``value_per_share`` do not
                match their formulas.
        """
        expected_equity = (
            self.enterprise_value
            - self.total_debt
            + self.cash_and_equivalents
            - self.minority_interest
            - self.preferred_equity
            + self.associate_investments
        )
        if not math.isclose(
            self.equity_value, expected_equity, rel_tol=_RECONCILIATION_TOLERANCE, abs_tol=1e-6
        ):
            raise ValueError(
                f"NetDebtBridgeResult.equity_value={self.equity_value!r} does not "
                f"match the bridge total {expected_equity!r}"
            )
        expected_per_share = self.equity_value / self.diluted_shares
        if not math.isclose(
            self.value_per_share,
            expected_per_share,
            rel_tol=_RECONCILIATION_TOLERANCE,
            abs_tol=1e-9,
        ):
            raise ValueError(
                f"NetDebtBridgeResult.value_per_share={self.value_per_share!r} "
                f"does not match equity_value / diluted_shares = {expected_per_share!r}"
            )


def equity_bridge(
    *,
    enterprise_value: float,
    total_debt: float,
    cash_and_equivalents: float,
    minority_interest: float,
    preferred_equity: float,
    associate_investments: float,
    diluted_shares: float,
) -> NetDebtBridgeResult:
    """Bridge enterprise value to equity value and value per share.

    Args:
        enterprise_value: EV entering the bridge.
        total_debt: Non-negative magnitude of total debt; subtracted.
        cash_and_equivalents: Non-negative magnitude of cash and equivalents;
            added.
        minority_interest: Non-negative magnitude of non-controlling
            interests; subtracted.
        preferred_equity: Non-negative magnitude of preferred equity;
            subtracted.
        associate_investments: Non-negative magnitude of equity-method
            investments in associates/joint ventures; added.
        diluted_shares: Fully diluted share count; must be strictly positive.

    Returns:
        A :class:`NetDebtBridgeResult`.

    Raises:
        ValuationError: If ``enterprise_value`` is not a finite number, if any
            of the five balance-sheet items is negative or not finite, or if
            ``diluted_shares`` is not a finite positive number.
    """
    debt = _require_nonnegative(total_debt, "total_debt", "equity_bridge")
    cash = _require_nonnegative(cash_and_equivalents, "cash_and_equivalents", "equity_bridge")
    minority = _require_nonnegative(minority_interest, "minority_interest", "equity_bridge")
    preferred = _require_nonnegative(preferred_equity, "preferred_equity", "equity_bridge")
    associates = _require_nonnegative(
        associate_investments, "associate_investments", "equity_bridge"
    )
    shares = require_positive(diluted_shares, "diluted_shares", "equity_bridge")
    enterprise_value = _require_finite(enterprise_value, "enterprise_value", "equity_bridge")

    equity_value = enterprise_value - debt + cash - minority - preferred + associates
    value_per_share = equity_value / shares

    return NetDebtBridgeResult(
        enterprise_value=enterprise_value,
        total_debt=debt,
        cash_and_equivalents=cash,
        minority_interest=minority,
        preferred_equity=preferred,
        associate_investments=associates,
        equity_value=equity_value,
        diluted_shares=shares,
        value_per_share=value_per_share,
    )


# ---------------------------------------------------------------------------
# Sensitivity grid
# ---------------------------------------------------------------------------


def sensitivity_grid(
    fcff_years: Sequence[FCFFYear],
    *,
    wacc_values: Sequence[float],
    growth_values: Sequence[float],
    discounting_convention: str,
    total_debt: float,
    cash_and_equivalents: float,
    minority_interest: float,
    preferred_equity: float,
    associate_investments: float,
    diluted_shares: float,
) -> pd.DataFrame:
    """Value-per-share sensitivity to WACC and perpetuity terminal growth.

    Every cell re-runs the full model (discount the explicit FCFFs at that
    WACC, build the perpetuity-growth terminal value at that WACC and growth,
    discount it at the same timing as the final explicit year, then bridge
    through the same fixed balance-sheet items) rather than perturbing the
    published enterprise value, so the grid is internally consistent at every
    point. Only the perpetuity-growth method is swept -- the exit-multiple
    method has no growth axis.

    Args:
        fcff_years: The FCFF bridge, e.g. from :func:`fcff_bridge`. WACC- and
            growth-independent, so it is reused unchanged at every cell.
        wacc_values: WACC values forming the grid's rows, each strictly
            greater than -1.
        growth_values: Perpetuity growth values forming the grid's columns.
        discounting_convention: One of :data:`DISCOUNTING_CONVENTIONS`.
        total_debt: Non-negative magnitude; subtracted at every cell.
        cash_and_equivalents: Non-negative magnitude; added at every cell.
        minority_interest: Non-negative magnitude; subtracted at every cell.
        preferred_equity: Non-negative magnitude; subtracted at every cell.
        associate_investments: Non-negative magnitude; added at every cell.
        diluted_shares: Fully diluted share count; must be strictly positive.

    Returns:
        A ``pandas.DataFrame`` indexed by ``wacc_values`` (index name
        ``"wacc"``) with columns ``growth_values`` (columns name
        ``"terminal_growth"``). Cells where ``growth >= wacc`` are ``NaN``
        rather than a large number, because the perpetuity terminal value is
        undefined there, not merely large -- see the module docstring.

    Raises:
        ValuationError: If ``fcff_years``, ``wacc_values`` or
            ``growth_values`` is empty, if ``discounting_convention`` is
            unrecognised, if any ``wacc_values`` or ``growth_values`` entry is
            not a finite number, if any ``wacc_values`` entry is at or below
            -1, or if any balance-sheet item is negative or ``diluted_shares``
            is not positive.
    """
    if discounting_convention not in DISCOUNTING_CONVENTIONS:
        raise ValuationError(
            f"sensitivity_grid: discounting_convention must be one of "
            f"{DISCOUNTING_CONVENTIONS}, got {discounting_convention!r}"
        )
    if not fcff_years:
        raise ValuationError("sensitivity_grid: fcff_years is empty")
    wacc_list = list(wacc_values)
    growth_list = list(growth_values)
    if not wacc_list:
        raise ValuationError("sensitivity_grid: wacc_values is empty")
    if not growth_list:
        raise ValuationError("sensitivity_grid: growth_values is empty")
    wacc_list = [
        _require_finite(v, f"wacc_values[{i}]", "sensitivity_grid")
        for i, v in enumerate(wacc_list)
    ]
    growth_list = [
        _require_finite(v, f"growth_values[{i}]", "sensitivity_grid")
        for i, v in enumerate(growth_list)
    ]

    debt = _require_nonnegative(total_debt, "total_debt", "sensitivity_grid")
    cash = _require_nonnegative(cash_and_equivalents, "cash_and_equivalents", "sensitivity_grid")
    minority = _require_nonnegative(minority_interest, "minority_interest", "sensitivity_grid")
    preferred = _require_nonnegative(preferred_equity, "preferred_equity", "sensitivity_grid")
    associates = _require_nonnegative(
        associate_investments, "associate_investments", "sensitivity_grid"
    )
    shares = require_positive(diluted_shares, "diluted_shares", "sensitivity_grid")

    final_fcff = fcff_years[-1].fcff
    grid = np.full((len(wacc_list), len(growth_list)), np.nan, dtype=float)

    for row, wacc_value in enumerate(wacc_list):
        if wacc_value <= -1.0:
            raise ValuationError(
                f"sensitivity_grid: wacc_values must exceed -1, got {wacc_value!r}"
            )
        discounted = discount_fcff(
            fcff_years, wacc_rate=wacc_value, discounting_convention=discounting_convention
        )
        pv_explicit = sum(entry.present_value for entry in discounted)
        terminal_factor = discounted[-1].discount_factor
        for col, growth_value in enumerate(growth_list):
            if growth_value >= wacc_value:
                continue  # left as NaN: the perpetuity terminal value is undefined here
            tv = final_fcff * (1.0 + growth_value) / (wacc_value - growth_value)
            enterprise_value = pv_explicit + tv * terminal_factor
            equity_value = (
                enterprise_value - debt + cash - minority - preferred + associates
            )
            grid[row, col] = equity_value / shares

    return pd.DataFrame(
        grid,
        index=pd.Index(wacc_list, name="wacc"),
        columns=pd.Index(growth_list, name="terminal_growth"),
    )


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DCFResult:
    """The full DCF: every bridge, both terminal values, and the final price.

    Attributes:
        wacc_build: The WACC build, with every component visible.
        fcff_bridge: One :class:`FCFFYear` per projection year.
        discounted_fcff: One :class:`DiscountedCashFlow` per projection year.
        pv_of_explicit_fcff: Sum of ``discounted_fcff[*].present_value``.
        terminal_value: Both terminal-value estimates and their cross-checks.
        terminal_value_method: Which of :data:`TERMINAL_VALUE_METHODS` was
            discounted into ``enterprise_value``. The other method's estimate
            is still fully computed and visible on ``terminal_value``.
        discounting_convention: Which of :data:`DISCOUNTING_CONVENTIONS` was used.
        terminal_discount_factor: Discount factor applied to the chosen
            terminal value -- the same factor used for the final explicit
            year, per the module docstring.
        pv_of_terminal_value: The chosen terminal value, discounted.
        enterprise_value: ``pv_of_explicit_fcff + pv_of_terminal_value``.
        net_debt_bridge: The full enterprise-value-to-equity-value bridge.
        equity_value: ``net_debt_bridge.equity_value``.
        value_per_share: ``net_debt_bridge.value_per_share``.
    """

    wacc_build: WACCResult
    fcff_bridge: tuple[FCFFYear, ...]
    discounted_fcff: tuple[DiscountedCashFlow, ...]
    pv_of_explicit_fcff: float
    terminal_value: TerminalValueResult
    terminal_value_method: str
    discounting_convention: str
    terminal_discount_factor: float
    pv_of_terminal_value: float
    enterprise_value: float
    net_debt_bridge: NetDebtBridgeResult
    equity_value: float
    value_per_share: float

    def __post_init__(self) -> None:
        """Re-check that the top-level rollups match their components.

        Raises:
            ValueError: If ``enterprise_value``, ``equity_value`` or
                ``value_per_share`` do not match the components they are
                built from.
        """
        expected_pv_explicit = sum(entry.present_value for entry in self.discounted_fcff)
        if not math.isclose(
            self.pv_of_explicit_fcff, expected_pv_explicit, rel_tol=1e-9, abs_tol=1e-6
        ):
            raise ValueError(
                f"DCFResult.pv_of_explicit_fcff={self.pv_of_explicit_fcff!r} does "
                f"not match sum(discounted_fcff.present_value)={expected_pv_explicit!r}"
            )
        expected_ev = self.pv_of_explicit_fcff + self.pv_of_terminal_value
        if not math.isclose(self.enterprise_value, expected_ev, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(
                f"DCFResult.enterprise_value={self.enterprise_value!r} does not "
                f"match pv_of_explicit_fcff + pv_of_terminal_value = {expected_ev!r}"
            )
        if not math.isclose(
            self.enterprise_value, self.net_debt_bridge.enterprise_value, rel_tol=1e-9, abs_tol=1e-6
        ):
            raise ValueError(
                f"DCFResult.enterprise_value={self.enterprise_value!r} does not "
                f"match net_debt_bridge.enterprise_value="
                f"{self.net_debt_bridge.enterprise_value!r}"
            )
        if self.equity_value != self.net_debt_bridge.equity_value:
            raise ValueError(
                f"DCFResult.equity_value={self.equity_value!r} does not match "
                f"net_debt_bridge.equity_value={self.net_debt_bridge.equity_value!r}"
            )
        if self.value_per_share != self.net_debt_bridge.value_per_share:
            raise ValueError(
                f"DCFResult.value_per_share={self.value_per_share!r} does not "
                f"match net_debt_bridge.value_per_share="
                f"{self.net_debt_bridge.value_per_share!r}"
            )


def run_dcf(
    inputs: Mapping[str, Any],
    *,
    capital_structure_basis: str,
    discounting_convention: str,
    terminal_value_method: str,
    gdp_growth_ceiling: float = DEFAULT_LONG_RUN_GDP_GROWTH_CEILING,
) -> DCFResult:
    """Run a complete DCF from a flat mapping of named inputs.

    This is the entry point :mod:`contracts` was written for: every required
    field is named, checked for presence up front, and the model refuses to
    run rather than substitute anything for one that is missing.

    Args:
        inputs: Flat mapping of raw inputs. Required keys are
            :data:`DCF_BASE_REQUIRED_FIELDS` plus
            :data:`DCF_CURRENT_STRUCTURE_FIELDS` (if
            ``capital_structure_basis="current"``) or
            :data:`DCF_TARGET_STRUCTURE_FIELDS` (if ``"target"``).
            ``inputs["terminal_growth"]`` and ``inputs["exit_multiple"]`` must
            each be an :class:`Assumption` (named ``"terminal_growth"`` /
            ``"exit_multiple"`` respectively), not a bare number. Optional
            keys ``"size_premium"`` and ``"country_risk_premium"`` default to
            ``0.0`` when absent (an explicit "not applying one", not a guessed
            magnitude). ``"ebit"``, ``"depreciation_amortization"``,
            ``"capex"`` and ``"delta_nwc"`` are equal-length sequences, one
            entry per projection year.
        capital_structure_basis: One of :data:`CAPITAL_STRUCTURE_BASES`.
            Required, no default.
        discounting_convention: One of :data:`DISCOUNTING_CONVENTIONS`.
            Required, no default.
        terminal_value_method: One of :data:`TERMINAL_VALUE_METHODS`, selecting
            which terminal-value estimate is discounted into
            ``enterprise_value``. Required, no default. Both estimates are
            always computed and cross-checked regardless of which is chosen --
            see ``DCFResult.terminal_value``.
        gdp_growth_ceiling: Reference ceiling used only to flag (never block)
            ``terminal_growth`` -- see :data:`DEFAULT_LONG_RUN_GDP_GROWTH_CEILING`.

    Returns:
        A :class:`DCFResult` with every intermediate figure visible.

    Raises:
        MissingInputError: If any required key is absent from ``inputs``.
        ValuationError: If ``capital_structure_basis``,
            ``discounting_convention`` or ``terminal_value_method`` is
            unrecognised; if ``terminal_growth`` or ``exit_multiple`` is not
            the matching :class:`Assumption`; if ``terminal_growth.value >=``
            the built WACC; if any capital-structure, FCFF-bridge or
            balance-sheet input fails its own guard (see :func:`wacc`,
            :func:`fcff_bridge`, :func:`terminal_value`, :func:`equity_bridge`).
    """
    if capital_structure_basis not in CAPITAL_STRUCTURE_BASES:
        raise ValuationError(
            f"run_dcf: capital_structure_basis must be one of "
            f"{CAPITAL_STRUCTURE_BASES}, got {capital_structure_basis!r}"
        )
    if discounting_convention not in DISCOUNTING_CONVENTIONS:
        raise ValuationError(
            f"run_dcf: discounting_convention must be one of "
            f"{DISCOUNTING_CONVENTIONS}, got {discounting_convention!r}"
        )
    if terminal_value_method not in TERMINAL_VALUE_METHODS:
        raise ValuationError(
            f"run_dcf: terminal_value_method must be one of "
            f"{TERMINAL_VALUE_METHODS}, got {terminal_value_method!r}"
        )

    structure_fields = (
        DCF_CURRENT_STRUCTURE_FIELDS
        if capital_structure_basis == "current"
        else DCF_TARGET_STRUCTURE_FIELDS
    )
    require_inputs(inputs, (*DCF_BASE_REQUIRED_FIELDS, *structure_fields), model="run_dcf")

    terminal_growth = _require_assumption(inputs["terminal_growth"], "terminal_growth", "run_dcf")
    exit_multiple = _require_assumption(inputs["exit_multiple"], "exit_multiple", "run_dcf")

    wacc_build = wacc(
        risk_free_rate=inputs["risk_free_rate"],
        beta=inputs["beta"],
        equity_risk_premium=inputs["equity_risk_premium"],
        pretax_cost_of_debt=inputs["pretax_cost_of_debt"],
        tax_rate=inputs["tax_rate"],
        capital_structure_basis=capital_structure_basis,
        market_value_of_equity=inputs.get("market_value_of_equity"),
        market_value_of_debt=inputs.get("market_value_of_debt"),
        target_equity_weight=inputs.get("target_equity_weight"),
        target_debt_weight=inputs.get("target_debt_weight"),
        size_premium=inputs.get("size_premium", 0.0),
        country_risk_premium=inputs.get("country_risk_premium", 0.0),
    )

    bridge = fcff_bridge(
        ebit=inputs["ebit"],
        tax_rate=inputs["tax_rate"],
        depreciation_amortization=inputs["depreciation_amortization"],
        capex=inputs["capex"],
        delta_nwc=inputs["delta_nwc"],
    )
    final_year = bridge[-1]
    terminal_year_ebitda = final_year.ebit + final_year.depreciation_amortization

    tv = terminal_value(
        final_year_fcff=final_year.fcff,
        terminal_year_ebitda=terminal_year_ebitda,
        wacc_rate=wacc_build.wacc,
        terminal_growth=terminal_growth,
        exit_multiple=exit_multiple,
        gdp_growth_ceiling=gdp_growth_ceiling,
    )

    discounted = discount_fcff(
        bridge, wacc_rate=wacc_build.wacc, discounting_convention=discounting_convention
    )
    pv_explicit = sum(entry.present_value for entry in discounted)

    chosen_tv = (
        tv.perpetuity_terminal_value
        if terminal_value_method == "perpetuity_growth"
        else tv.exit_terminal_value
    )
    # Discounted at the same timing as the final explicit year -- see the
    # module docstring for why this makes the mid-year/year-end enterprise
    # value ratio exactly sqrt(1 + WACC).
    terminal_discount_factor = discounted[-1].discount_factor
    pv_of_terminal_value = chosen_tv * terminal_discount_factor
    enterprise_value = pv_explicit + pv_of_terminal_value

    net_debt = equity_bridge(
        enterprise_value=enterprise_value,
        total_debt=inputs["total_debt"],
        cash_and_equivalents=inputs["cash_and_equivalents"],
        minority_interest=inputs["minority_interest"],
        preferred_equity=inputs["preferred_equity"],
        associate_investments=inputs["associate_investments"],
        diluted_shares=inputs["diluted_shares"],
    )

    return DCFResult(
        wacc_build=wacc_build,
        fcff_bridge=bridge,
        discounted_fcff=discounted,
        pv_of_explicit_fcff=pv_explicit,
        terminal_value=tv,
        terminal_value_method=terminal_value_method,
        discounting_convention=discounting_convention,
        terminal_discount_factor=terminal_discount_factor,
        pv_of_terminal_value=pv_of_terminal_value,
        enterprise_value=enterprise_value,
        net_debt_bridge=net_debt,
        equity_value=net_debt.equity_value,
        value_per_share=net_debt.value_per_share,
    )
