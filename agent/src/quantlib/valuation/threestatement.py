"""Linked three-statement projection: P&L, cash flow and balance sheet, one model.

A three-statement model is only as good as its linkage. It is trivial to build
three spreadsheets that each look plausible in isolation and disagree the moment
you check whether assets equal liabilities plus equity -- that disagreement is
usually smoothed over with a hidden "plug" cell nobody labelled. This module
makes that failure mode structurally unreachable:

* Every line on the balance sheet is *derived* from the income statement and
  cash flow statement of the same period, never entered independently. Cash
  rolls forward by the cash flow statement's net change; retained earnings
  rolls forward by net income less dividends; PP&E rolls forward by capex less
  depreciation. There is nothing left to plug.
* :func:`check_balance_sheet` asserts ``assets == liabilities + equity`` after
  the opening balance sheet and after every projected period, and raises
  :class:`BalanceSheetError` naming the exact residual if it does not. Nothing
  catches or downgrades that exception -- an unbalanced period is not a
  projection, it is a bug.
* The one place this model deliberately keeps a balancing account is the
  **revolving credit facility**: if cash flow before financing would push cash
  below ``minimum_cash``, the revolver draws exactly the shortfall; if there is
  excess cash and an outstanding balance, the revolver sweeps exactly the
  excess (capped at what is owed). This is a plug in the sense that it exists
  to make the cash line come out right -- but it is *declared*, reported as its
  own field (:attr:`BalanceSheet.revolver_balance`, plus
  :attr:`CashFlowStatement.revolver_draw` / ``revolver_repayment``) and governed
  by an explicit, inspectable policy (``minimum_cash``). A silent plug hides
  what moved and why; this one names it on every period.

CIRCULARITY
-----------
Interest expense is charged on the *average* of the beginning and ending
revolver balance, which is standard practice (it does not reward or penalise a
company for exactly when in the period it drew or repaid). But the ending
balance depends on net income (through the cash available to repay or the
shortfall to cover), and net income depends on interest expense -- so a
period's own ending debt balance is defined in terms of itself. This module
resolves that with fixed-point iteration (see :func:`_project_period`): guess
an ending balance, price interest off it, run the statements through to a new
ending balance, and repeat until the guess stops moving. Every
:class:`PeriodResult` reports ``converged`` and ``iterations`` so a caller can
see the solve actually happened rather than trusting it silently. A period that
fails to converge within :data:`MAX_CIRCULARITY_ITERATIONS` raises
:class:`ConvergenceError` instead of returning the last guess dressed up as an
answer.

SCOPE, STATED PLAINLY
----------------------
* Dividends are paid only out of positive net income (``max(net_income, 0) *
  dividend_payout_ratio``); a loss-making period pays no dividend and receives
  no offsetting "negative dividend". The payout ratio itself is still a
  required, caller-supplied input -- this is a rule about how it applies, not a
  default value for it.
* Net working capital is carried as one net line (its ratio to revenue is a
  required driver); this model does not decompose it into receivables,
  inventory and payables. A negative NWC balance is valid and simply reduces
  total assets, which is mathematically identical to carrying the same net
  liability on the other side of the ledger.
* Paid-in capital never moves: this model has no share-issuance or buyback
  driver, so the only equity account that changes is retained earnings.
* Depreciation and interest rate are required per-period inputs, not derived
  from a ratio driver -- see :data:`DRIVER_REQUIRED_FIELDS`. A model that
  invented a depreciation-to-revenue ratio nobody asked for would be exactly
  the kind of silently-chosen assumption :mod:`.contracts` exists to prevent.

Every required input across the opening balance sheet and every driver is
checked with :func:`~src.quantlib.valuation.contracts.require_inputs` before
any arithmetic runs -- a missing field stops the model, never gets a default.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from src.quantlib.valuation.contracts import (
    MissingInputError,  # noqa: F401 -- re-exported for callers that catch it here
    ValuationError,
    require_inputs,
    require_positive,
)

__all__ = [
    "MODEL_NAME",
    "BALANCE_TOLERANCE_REL",
    "CIRCULARITY_TOLERANCE_REL",
    "MAX_CIRCULARITY_ITERATIONS",
    "OPENING_REQUIRED_FIELDS",
    "DRIVER_REQUIRED_FIELDS",
    "BalanceSheetError",
    "ConvergenceError",
    "IncomeStatement",
    "CashFlowStatement",
    "BalanceSheet",
    "PeriodResult",
    "ThreeStatementProjection",
    "check_balance_sheet",
    "project_three_statement",
]

#: Name used in every error message raised by this module.
MODEL_NAME = "three_statement_projection"

#: How far ``assets - (liabilities + equity)`` may drift, as a fraction of total
#: assets, before a balance sheet is refused. Scaled by assets (not an absolute
#: dollar amount) so the same tolerance is equally strict for a $10k projection
#: and a $10bn one. 1e-9 is far looser than the ~1e-12..1e-10 floating-point
#: noise a correctly-linked model accumulates over a handful of chained
#: arithmetic operations, and far tighter than any real accounting break, so it
#: catches genuine plugs without ever flagging rounding.
BALANCE_TOLERANCE_REL: float = 1e-9

#: Fixed-point convergence tolerance for the interest/revolver circularity,
#: expressed relative to the ending debt balance being solved for. Set an order
#: of magnitude tighter than BALANCE_TOLERANCE_REL because the balance-sheet
#: check is downstream of this solve: a loosely-converged debt balance would
#: still make the accounting identity hold exactly (it holds for any
#: self-consistent snapshot, converged or not -- see the module docstring), but
#: it would report a period whose interest was not actually priced off its own
#: ending balance. The tightness here is about answering the right economic
#: question, not about balancing.
CIRCULARITY_TOLERANCE_REL: float = 1e-10

#: Iteration budget for the revolver/interest fixed point. Realistic financing
#: rates put the loop's contraction factor -- roughly
#: ``(1 - payout) * (1 - tax) * interest_rate / 2`` from averaging the two debt
#: balances -- well under 0.5 per period, which reaches CIRCULARITY_TOLERANCE_REL
#: in well under 10 passes. 100 leaves an order of magnitude of headroom for
#: unusually high-yield financing before a genuinely non-convergent (contraction
#: factor >= 1) input is refused instead of silently truncated.
MAX_CIRCULARITY_ITERATIONS: int = 100

#: Required keys of the ``opening`` mapping passed to :func:`project_three_statement`.
OPENING_REQUIRED_FIELDS: tuple[str, ...] = (
    "revenue",
    "cash",
    "net_working_capital",
    "ppe",
    "revolver_balance",
    "paid_in_capital",
    "retained_earnings",
)

#: Required keys of the ``drivers`` mapping passed to :func:`project_three_statement`.
#: Every value must be a sequence of the same length -- one entry per projected
#: period. ``depreciation_amortization``, ``interest_rate`` and ``minimum_cash``
#: are required alongside the seven ratio/rate drivers because the linkage the
#: model exists to enforce (D&A into the PP&E rollforward, interest into the
#: revolver circularity, minimum_cash into the revolver policy) has no
#: economically defensible ratio to default them from; see the module docstring.
DRIVER_REQUIRED_FIELDS: tuple[str, ...] = (
    "revenue_growth",
    "gross_margin",
    "opex_pct_revenue",
    "capex_pct_revenue",
    "nwc_pct_revenue",
    "tax_rate",
    "dividend_payout_ratio",
    "depreciation_amortization",
    "interest_rate",
    "minimum_cash",
)


class BalanceSheetError(ValuationError):
    """Raised when a balance sheet fails ``assets == liabilities + equity``.

    Attributes:
        period: The period index that failed (0 is the opening balance sheet).
        assets: Total assets computed for that period.
        liabilities: Total liabilities computed for that period.
        equity: Total equity computed for that period.
        residual: ``assets - liabilities - equity``. Non-zero is the failure.
        tolerance: The relative tolerance that was exceeded.
    """

    def __init__(self, period: int, assets: float, liabilities: float, equity: float, tolerance: float) -> None:
        self.period = period
        self.assets = assets
        self.liabilities = liabilities
        self.equity = equity
        self.residual = assets - liabilities - equity
        self.tolerance = tolerance
        super().__init__(
            f"{MODEL_NAME}: period {period} balance sheet does not balance -- "
            f"assets {assets!r} != liabilities {liabilities!r} + equity {equity!r} "
            f"(residual {self.residual!r}, tolerance {tolerance!r} of assets). "
            "This model derives every balance-sheet line from the income "
            "statement and cash flow statement; a non-zero residual means an "
            "input or a rollforward was overridden by hand, not that the model "
            "chose to plug it."
        )


class ConvergenceError(ValuationError):
    """Raised when the interest/revolver circularity fails to converge.

    Attributes:
        period: The period whose fixed-point solve failed.
        iterations: How many iterations were attempted (equals the budget).
        last_delta: The absolute change in the ending debt balance on the final
            iteration -- still larger than ``tolerance`` allowed.
        tolerance: The relative convergence tolerance that was not met.
    """

    def __init__(self, period: int, iterations: int, last_delta: float, tolerance: float) -> None:
        self.period = period
        self.iterations = iterations
        self.last_delta = last_delta
        self.tolerance = tolerance
        super().__init__(
            f"{MODEL_NAME}: period {period} interest/revolver circularity did not "
            f"converge in {iterations} iteration(s) (last change in ending debt "
            f"{last_delta!r}, tolerance {tolerance!r}). Refusing to return the "
            "last iteration's numbers as if they were a solved period -- widen "
            "max_circularity_iterations only after confirming the loop is "
            "actually contracting, not just slow."
        )


@dataclass(frozen=True)
class IncomeStatement:
    """One period's income statement, linked end to end.

    The chain is ``revenue -> gross_profit -> ebitda -> (less D&A) -> ebit ->
    (less interest) -> pretax_income -> (less tax) -> net_income``.

    Attributes:
        period: 1-indexed projection period.
        revenue: Period revenue.
        gross_profit: ``revenue * gross_margin``.
        opex: Operating expense, ``revenue * opex_pct_revenue``.
        ebitda: ``gross_profit - opex``.
        depreciation_amortization: D&A for the period (a required input, not a
            derived ratio -- see the module docstring).
        ebit: ``ebitda - depreciation_amortization``.
        interest_expense: Interest on the average revolver balance for the
            period; the output of the circularity solve.
        pretax_income: ``ebit - interest_expense``.
        tax_expense: ``pretax_income * tax_rate``. Negative when pretax income
            is negative -- this model does not model a tax-loss carryforward,
            so a loss period shows a tax benefit at the same rate.
        net_income: ``pretax_income - tax_expense``.
    """

    period: int
    revenue: float
    gross_profit: float
    opex: float
    ebitda: float
    depreciation_amortization: float
    ebit: float
    interest_expense: float
    pretax_income: float
    tax_expense: float
    net_income: float

    @property
    def cogs(self) -> float:
        """Return cost of goods sold, implied by revenue and gross profit.

        Returns:
            ``revenue - gross_profit``.
        """
        return self.revenue - self.gross_profit


@dataclass(frozen=True)
class CashFlowStatement:
    """One period's cash flow statement, bridging net income to the cash change.

    Implements ``net_income + D&A - change_in_net_working_capital - capex +
    financing_activities = net_change_in_cash`` exactly.

    Attributes:
        period: 1-indexed projection period.
        net_income: Copied from the period's :class:`IncomeStatement`.
        depreciation_amortization: Added back as a non-cash expense.
        change_in_net_working_capital: ``nwc_end - nwc_begin``. A positive
            value (NWC grew) is a use of cash and is subtracted.
        capex: Capital expenditure, a use of cash.
        dividends_paid: Cash dividends for the period (zero in a loss period;
            see the module docstring).
        revolver_draw: Cash drawn on the revolver this period (>= 0). This is
            the explicit, reported plug that keeps cash from falling below
            ``minimum_cash``.
        revolver_repayment: Cash used to pay down the revolver this period
            (>= 0), capped at the balance outstanding.
        financing_activities: ``revolver_draw - revolver_repayment -
            dividends_paid``.
        net_change_in_cash: The full bridge total; matches
            ``BalanceSheet.cash - previous BalanceSheet.cash`` exactly.
    """

    period: int
    net_income: float
    depreciation_amortization: float
    change_in_net_working_capital: float
    capex: float
    dividends_paid: float
    revolver_draw: float
    revolver_repayment: float
    financing_activities: float
    net_change_in_cash: float

    @property
    def cash_flow_from_operations(self) -> float:
        """Return operating cash flow, before investing and financing.

        Returns:
            ``net_income + depreciation_amortization - change_in_net_working_capital``.
        """
        return self.net_income + self.depreciation_amortization - self.change_in_net_working_capital

    @property
    def free_cash_flow(self) -> float:
        """Return free cash flow, before financing activities.

        Returns:
            :attr:`cash_flow_from_operations` minus :attr:`capex`.
        """
        return self.cash_flow_from_operations - self.capex


@dataclass(frozen=True)
class BalanceSheet:
    """One period's balance sheet. Every field is a rollforward, never an input.

    ``period=0`` is the opening balance sheet supplied by the caller; every
    other period is derived: cash rolls forward by the cash flow statement's
    net change, PP&E by capex less D&A, the revolver by its draws and
    repayments, and retained earnings by net income less dividends. Paid-in
    capital never moves (see the module docstring).

    Attributes:
        period: 0 for the opening balance sheet, 1-indexed thereafter.
        cash: Ending cash balance.
        net_working_capital: Ending net working capital (a single net line;
            see the module docstring).
        ppe: Ending net property, plant and equipment.
        revolver_balance: Ending balance on the revolving credit facility --
            the model's one explicit, reported plug.
        paid_in_capital: Contributed capital. Constant across every period.
        retained_earnings: Ending retained earnings; may be negative.
    """

    period: int
    cash: float
    net_working_capital: float
    ppe: float
    revolver_balance: float
    paid_in_capital: float
    retained_earnings: float

    @property
    def total_assets(self) -> float:
        """Return total assets.

        Returns:
            ``cash + net_working_capital + ppe``.
        """
        return self.cash + self.net_working_capital + self.ppe

    @property
    def total_liabilities(self) -> float:
        """Return total liabilities.

        Returns:
            ``revolver_balance`` -- the only liability this model carries.
        """
        return self.revolver_balance

    @property
    def total_equity(self) -> float:
        """Return total equity.

        Returns:
            ``paid_in_capital + retained_earnings``.
        """
        return self.paid_in_capital + self.retained_earnings


@dataclass(frozen=True)
class PeriodResult:
    """One projected period's linked statements plus circularity diagnostics.

    Attributes:
        period: 1-indexed projection period.
        income_statement: The period's :class:`IncomeStatement`.
        cash_flow_statement: The period's :class:`CashFlowStatement`.
        balance_sheet: The period's :class:`BalanceSheet`, already checked by
            :func:`check_balance_sheet` before this object is returned.
        converged: Whether the interest/revolver fixed point converged. Always
            ``True`` on a returned :class:`PeriodResult` -- a non-convergent
            period raises :class:`ConvergenceError` instead of being returned;
            the field is kept on the result so a caller inspecting a completed
            projection does not have to take convergence on faith.
        iterations: Number of fixed-point iterations the circularity solve
            took. ``1`` means the initial guess (no revolver movement) was
            already the fixed point -- for example, a period with zero
            beginning debt and no shortfall.
    """

    period: int
    income_statement: IncomeStatement
    cash_flow_statement: CashFlowStatement
    balance_sheet: BalanceSheet
    converged: bool
    iterations: int


@dataclass(frozen=True)
class ThreeStatementProjection:
    """A full multi-period projection: the opening balance sheet plus every period.

    Attributes:
        opening_balance_sheet: The caller-supplied opening balance sheet
            (``period=0``), already checked by :func:`check_balance_sheet`.
        periods: Projected periods in chronological order, 1-indexed.
    """

    opening_balance_sheet: BalanceSheet
    periods: tuple[PeriodResult, ...]


def check_balance_sheet(balance_sheet: BalanceSheet, tolerance: float = BALANCE_TOLERANCE_REL) -> None:
    """Assert that a balance sheet balances, or raise naming the residual.

    Args:
        balance_sheet: The balance sheet to check.
        tolerance: Largest tolerated ``|residual| / max(total_assets, 1.0)``.
            Defaults to :data:`BALANCE_TOLERANCE_REL`.

    Raises:
        BalanceSheetError: If ``assets != liabilities + equity`` beyond
            ``tolerance``. The exception carries the exact residual.
    """
    assets = balance_sheet.total_assets
    liabilities = balance_sheet.total_liabilities
    equity = balance_sheet.total_equity
    residual = assets - liabilities - equity
    scale = max(abs(assets), 1.0)
    if abs(residual) > tolerance * scale:
        raise BalanceSheetError(balance_sheet.period, assets, liabilities, equity, tolerance)


def _resolve_period_count(drivers: Mapping[str, Sequence[float]]) -> int:
    """Validate every driver sequence shares one non-zero length and return it.

    Args:
        drivers: The driver mapping already checked by
            :func:`~src.quantlib.valuation.contracts.require_inputs`.

    Returns:
        The number of periods to project.

    Raises:
        ValuationError: If the driver sequences disagree in length, or all are
            empty.
    """
    lengths = {field: len(drivers[field]) for field in DRIVER_REQUIRED_FIELDS}
    distinct = set(lengths.values())
    if len(distinct) > 1:
        detail = ", ".join(f"{field}={n}" for field, n in lengths.items())
        raise ValuationError(
            f"{MODEL_NAME}: every driver sequence must share one length (one entry "
            f"per projected period); got {detail}"
        )
    periods = distinct.pop()
    if periods < 1:
        raise ValuationError(
            f"{MODEL_NAME}: driver sequences are empty; at least one projection "
            "period is required"
        )
    return periods


def _project_period(
    period: int,
    prior_bs: BalanceSheet,
    prior_revenue: float,
    revenue_growth: float,
    gross_margin: float,
    opex_pct_revenue: float,
    capex_pct_revenue: float,
    nwc_pct_revenue: float,
    tax_rate: float,
    dividend_payout_ratio: float,
    depreciation_amortization: float,
    interest_rate: float,
    minimum_cash: float,
    circularity_tolerance: float,
    max_circularity_iterations: int,
) -> PeriodResult:
    """Project one period, solving the interest/revolver circularity by iteration.

    See the module docstring for the fixed-point scheme: the ending revolver
    balance is guessed, interest is priced on the average of the beginning and
    guessed ending balance, the statements are run through to a freshly
    computed ending balance, and the guess is replaced by that value until it
    stops moving.

    Args:
        period: 1-indexed period being projected.
        prior_bs: The previous period's (or the opening) balance sheet.
        prior_revenue: The previous period's (or the opening) revenue.
        revenue_growth: This period's revenue growth rate.
        gross_margin: This period's gross margin.
        opex_pct_revenue: This period's operating expense as a fraction of revenue.
        capex_pct_revenue: This period's capex as a fraction of revenue.
        nwc_pct_revenue: This period's net working capital as a fraction of revenue.
        tax_rate: This period's tax rate.
        dividend_payout_ratio: This period's dividend payout ratio (applied to
            positive net income only).
        depreciation_amortization: This period's D&A, in currency units.
        interest_rate: This period's interest rate on the average revolver balance.
        minimum_cash: This period's minimum cash the revolver policy targets.
        circularity_tolerance: Relative convergence tolerance on the ending
            revolver balance.
        max_circularity_iterations: Iteration budget before refusing to answer.

    Returns:
        The period's :class:`PeriodResult`, with a balance sheet that has
        already passed :func:`check_balance_sheet`.

    Raises:
        ConvergenceError: If the fixed point does not converge within
            ``max_circularity_iterations``.
        BalanceSheetError: If the resulting balance sheet does not balance
            (this should be unreachable given the rollforwards below, and its
            presence here is a deliberate defensive check, not the primary
            guard -- see the module docstring).
    """
    revenue = prior_revenue * (1.0 + revenue_growth)
    gross_profit = revenue * gross_margin
    opex = revenue * opex_pct_revenue
    ebitda = gross_profit - opex
    ebit = ebitda - depreciation_amortization
    capex = revenue * capex_pct_revenue
    nwc_end = revenue * nwc_pct_revenue
    change_in_nwc = nwc_end - prior_bs.net_working_capital

    debt_begin = prior_bs.revolver_balance
    debt_end_guess = debt_begin

    interest_expense = pretax_income = tax_expense = net_income = 0.0
    dividends_paid = revolver_draw = revolver_repayment = 0.0
    debt_end_actual = debt_end_guess
    cash_end = prior_bs.cash
    delta = float("inf")
    converged = False
    iterations = 0

    for iterations in range(1, max_circularity_iterations + 1):
        avg_debt = (debt_begin + debt_end_guess) / 2.0
        interest_expense = interest_rate * avg_debt
        pretax_income = ebit - interest_expense
        tax_expense = pretax_income * tax_rate
        net_income = pretax_income - tax_expense
        dividends_paid = max(net_income, 0.0) * dividend_payout_ratio

        cash_flow_before_financing = net_income + depreciation_amortization - change_in_nwc - capex - dividends_paid
        cash_before_revolver = prior_bs.cash + cash_flow_before_financing

        if cash_before_revolver >= minimum_cash:
            surplus = cash_before_revolver - minimum_cash
            revolver_repayment = min(surplus, debt_begin)
            revolver_draw = 0.0
        else:
            revolver_draw = minimum_cash - cash_before_revolver
            revolver_repayment = 0.0

        debt_end_actual = debt_begin + revolver_draw - revolver_repayment
        cash_end = cash_before_revolver + revolver_draw - revolver_repayment

        scale = max(abs(debt_end_actual), 1.0)
        delta = abs(debt_end_actual - debt_end_guess)
        if delta <= circularity_tolerance * scale:
            converged = True
            break
        debt_end_guess = debt_end_actual

    if not converged:
        raise ConvergenceError(period, iterations, delta, circularity_tolerance)

    financing_activities = revolver_draw - revolver_repayment - dividends_paid
    net_change_in_cash = net_income + depreciation_amortization - change_in_nwc - capex + financing_activities

    income_statement = IncomeStatement(
        period=period,
        revenue=revenue,
        gross_profit=gross_profit,
        opex=opex,
        ebitda=ebitda,
        depreciation_amortization=depreciation_amortization,
        ebit=ebit,
        interest_expense=interest_expense,
        pretax_income=pretax_income,
        tax_expense=tax_expense,
        net_income=net_income,
    )
    cash_flow_statement = CashFlowStatement(
        period=period,
        net_income=net_income,
        depreciation_amortization=depreciation_amortization,
        change_in_net_working_capital=change_in_nwc,
        capex=capex,
        dividends_paid=dividends_paid,
        revolver_draw=revolver_draw,
        revolver_repayment=revolver_repayment,
        financing_activities=financing_activities,
        net_change_in_cash=net_change_in_cash,
    )
    balance_sheet = BalanceSheet(
        period=period,
        cash=cash_end,
        net_working_capital=nwc_end,
        ppe=prior_bs.ppe + capex - depreciation_amortization,
        revolver_balance=debt_end_actual,
        paid_in_capital=prior_bs.paid_in_capital,
        retained_earnings=prior_bs.retained_earnings + net_income - dividends_paid,
    )
    check_balance_sheet(balance_sheet)

    return PeriodResult(
        period=period,
        income_statement=income_statement,
        cash_flow_statement=cash_flow_statement,
        balance_sheet=balance_sheet,
        converged=converged,
        iterations=iterations,
    )


def project_three_statement(
    opening: Mapping[str, float],
    drivers: Mapping[str, Sequence[float]],
    circularity_tolerance: float = CIRCULARITY_TOLERANCE_REL,
    max_circularity_iterations: int = MAX_CIRCULARITY_ITERATIONS,
    balance_tolerance: float = BALANCE_TOLERANCE_REL,
) -> ThreeStatementProjection:
    """Project linked income, cash flow and balance-sheet statements forward.

    Args:
        opening: The opening balance sheet plus trailing revenue. Must contain
            every field in :data:`OPENING_REQUIRED_FIELDS`.
        drivers: Per-period driver sequences. Must contain every field in
            :data:`DRIVER_REQUIRED_FIELDS`, each a sequence of the same length
            (one entry per projected period, chronological order).
        circularity_tolerance: Relative convergence tolerance for the
            interest/revolver fixed point. Defaults to
            :data:`CIRCULARITY_TOLERANCE_REL`.
        max_circularity_iterations: Iteration budget for that fixed point.
            Defaults to :data:`MAX_CIRCULARITY_ITERATIONS`.
        balance_tolerance: Relative tolerance for the hard balance-sheet check.
            Defaults to :data:`BALANCE_TOLERANCE_REL`.

    Returns:
        A :class:`ThreeStatementProjection` whose opening and every projected
        balance sheet has passed :func:`check_balance_sheet`, and whose every
        :class:`PeriodResult` converged.

    Raises:
        MissingInputError: If ``opening`` or ``drivers`` is missing a required
            field.
        ValuationError: If the driver sequences disagree in length, are empty,
            or if ``circularity_tolerance`` / ``balance_tolerance`` /
            ``max_circularity_iterations`` are not usable.
        BalanceSheetError: If the opening balance sheet, or any projected
            period's balance sheet, does not balance.
        ConvergenceError: If any period's interest/revolver circularity fails
            to converge within ``max_circularity_iterations``.
    """
    require_inputs(opening, OPENING_REQUIRED_FIELDS, MODEL_NAME)
    require_inputs(drivers, DRIVER_REQUIRED_FIELDS, MODEL_NAME)
    circularity_tolerance = require_positive(circularity_tolerance, "circularity_tolerance", MODEL_NAME)
    balance_tolerance = require_positive(balance_tolerance, "balance_tolerance", MODEL_NAME)
    if max_circularity_iterations < 1:
        raise ValuationError(
            f"{MODEL_NAME}: max_circularity_iterations must be >= 1, got "
            f"{max_circularity_iterations!r}"
        )

    periods = _resolve_period_count(drivers)

    opening_balance_sheet = BalanceSheet(
        period=0,
        cash=float(opening["cash"]),
        net_working_capital=float(opening["net_working_capital"]),
        ppe=float(opening["ppe"]),
        revolver_balance=float(opening["revolver_balance"]),
        paid_in_capital=float(opening["paid_in_capital"]),
        retained_earnings=float(opening["retained_earnings"]),
    )
    check_balance_sheet(opening_balance_sheet, balance_tolerance)

    prior_bs = opening_balance_sheet
    prior_revenue = float(opening["revenue"])
    results: list[PeriodResult] = []
    for index in range(periods):
        result = _project_period(
            period=index + 1,
            prior_bs=prior_bs,
            prior_revenue=prior_revenue,
            revenue_growth=float(drivers["revenue_growth"][index]),
            gross_margin=float(drivers["gross_margin"][index]),
            opex_pct_revenue=float(drivers["opex_pct_revenue"][index]),
            capex_pct_revenue=float(drivers["capex_pct_revenue"][index]),
            nwc_pct_revenue=float(drivers["nwc_pct_revenue"][index]),
            tax_rate=float(drivers["tax_rate"][index]),
            dividend_payout_ratio=float(drivers["dividend_payout_ratio"][index]),
            depreciation_amortization=float(drivers["depreciation_amortization"][index]),
            interest_rate=float(drivers["interest_rate"][index]),
            minimum_cash=float(drivers["minimum_cash"][index]),
            circularity_tolerance=circularity_tolerance,
            max_circularity_iterations=max_circularity_iterations,
        )
        # Defensive re-check with the caller's tolerance: _project_period already
        # checked with the module default, but a caller-widened balance_tolerance
        # must not be allowed to let a period through unchecked at its own bar.
        check_balance_sheet(result.balance_sheet, balance_tolerance)
        results.append(result)
        prior_bs = result.balance_sheet
        prior_revenue = result.income_statement.revenue

    return ThreeStatementProjection(opening_balance_sheet=opening_balance_sheet, periods=tuple(results))
