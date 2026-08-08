"""Tests for the linked three-statement projection.

The flagship test (`test_three_period_projection_matches_hand_computation`) is
the important one: it builds a three-period scenario where the revolver never
moves (`minimum_cash` is set, period by period, to exactly the cash the model
would land on with no draw or repayment), which removes the interest/revolver
circularity from the arithmetic entirely and leaves every income-statement,
cash-flow-statement and balance-sheet line as closed-form arithmetic on the
driver inputs. Every expected number below is that closed-form arithmetic,
written out the same way the model itself derives it (revenue -> gross profit
-> EBITDA -> D&A -> EBIT -> interest -> pretax -> tax -> net income, then the
cash bridge, then the balance-sheet rollforwards) -- not copied from a prior
run of the implementation. A regression in the linkage cannot be absorbed by
reusing the implementation's own reasoning.

The remaining tests each isolate one requirement that the flagship test does
not (and structurally cannot, since it is built to avoid the circularity)
exercise: the hard balance check actually raising on a genuinely unbalanced
input (not just staying quiet on a balanced one), multi-iteration convergence,
genuine divergence, the explicit revolver plug, missing-input refusal, and the
three named boundary conditions.
"""

from __future__ import annotations

import pytest

from src.quantlib.valuation.contracts import MissingInputError
from src.quantlib.valuation.threestatement import (
    MAX_CIRCULARITY_ITERATIONS,
    BalanceSheet,
    BalanceSheetError,
    ConvergenceError,
    check_balance_sheet,
    project_three_statement,
)

TOL = 1e-9


def _assert_balances(bs: BalanceSheet) -> None:
    """Independently recompute assets vs. liabilities + equity and assert equality.

    Args:
        bs: The balance sheet to check.
    """
    assets = bs.cash + bs.net_working_capital + bs.ppe
    liab_plus_equity = bs.revolver_balance + bs.paid_in_capital + bs.retained_earnings
    assert assets == pytest.approx(liab_plus_equity, abs=TOL)


# --------------------------------------------------------------------------
# Flagship: three-period hand-computed projection, flat (non-circular) debt.
# --------------------------------------------------------------------------

# Opening balance sheet. Assets = 200,000 + 150,000 + 800,000 = 1,150,000.
# Liabilities = 300,000. Equity must then be 850,000 = paid_in + RE, so
# RE_0 = 850,000 - 500,000 = 350,000.
CASH_0 = 200_000.0
NWC_0 = 150_000.0
PPE_0 = 800_000.0
DEBT_0 = 300_000.0
PAID_IN = 500_000.0
RE_0 = 350_000.0
REVENUE_0 = 1_000_000.0
assert CASH_0 + NWC_0 + PPE_0 == pytest.approx(DEBT_0 + PAID_IN + RE_0)

OPENING = {
    "revenue": REVENUE_0,
    "cash": CASH_0,
    "net_working_capital": NWC_0,
    "ppe": PPE_0,
    "revolver_balance": DEBT_0,
    "paid_in_capital": PAID_IN,
    "retained_earnings": RE_0,
}

# Drivers, period by period. interest_rate is 6% flat and the revolver never
# draws or repays (minimum_cash is set below to the exact break-even cash), so
# interest_1 = interest_2 = interest_3 = 0.06 * 300,000 = 18,000 throughout.
REVENUE_GROWTH = [0.10, 0.08, 0.05]
GROSS_MARGIN = [0.40, 0.42, 0.42]
OPEX_PCT = [0.20, 0.19, 0.18]
CAPEX_PCT = [0.05, 0.05, 0.04]
NWC_PCT = [0.15, 0.15, 0.14]
TAX_RATE = [0.25, 0.25, 0.25]
PAYOUT = [0.30, 0.30, 0.30]
DA = [60_000.0, 65_000.0, 68_000.0]
INTEREST_RATE = [0.06, 0.06, 0.06]

# --- Period 1 ---
REVENUE_1 = REVENUE_0 * (1.0 + REVENUE_GROWTH[0])  # 1,100,000
GROSS_PROFIT_1 = REVENUE_1 * GROSS_MARGIN[0]  # 440,000
OPEX_1 = REVENUE_1 * OPEX_PCT[0]  # 220,000
EBITDA_1 = GROSS_PROFIT_1 - OPEX_1  # 220,000
EBIT_1 = EBITDA_1 - DA[0]  # 160,000
INTEREST_1 = INTEREST_RATE[0] * DEBT_0  # flat debt -> avg == 300,000; 18,000
PRETAX_1 = EBIT_1 - INTEREST_1  # 142,000
TAX_1 = PRETAX_1 * TAX_RATE[0]  # 35,500
NI_1 = PRETAX_1 - TAX_1  # 106,500
CAPEX_1 = REVENUE_1 * CAPEX_PCT[0]  # 55,000
NWC_END_1 = REVENUE_1 * NWC_PCT[0]  # 165,000
D_NWC_1 = NWC_END_1 - NWC_0  # 15,000
DIV_1 = max(NI_1, 0.0) * PAYOUT[0]  # 31,950
CFBF_1 = NI_1 + DA[0] - D_NWC_1 - CAPEX_1 - DIV_1  # 64,550
CASH_1 = CASH_0 + CFBF_1  # 264,550 -- also this period's minimum_cash (no draw/repay)
PPE_1 = PPE_0 + CAPEX_1 - DA[0]  # 795,000
RE_1 = RE_0 + NI_1 - DIV_1  # 424,550

# --- Period 2 ---
REVENUE_2 = REVENUE_1 * (1.0 + REVENUE_GROWTH[1])  # 1,188,000
GROSS_PROFIT_2 = REVENUE_2 * GROSS_MARGIN[1]  # 498,960
OPEX_2 = REVENUE_2 * OPEX_PCT[1]  # 225,720
EBITDA_2 = GROSS_PROFIT_2 - OPEX_2  # 273,240
EBIT_2 = EBITDA_2 - DA[1]  # 208,240
INTEREST_2 = INTEREST_RATE[1] * DEBT_0  # 18,000
PRETAX_2 = EBIT_2 - INTEREST_2  # 190,240
TAX_2 = PRETAX_2 * TAX_RATE[1]  # 47,560
NI_2 = PRETAX_2 - TAX_2  # 142,680
CAPEX_2 = REVENUE_2 * CAPEX_PCT[1]  # 59,400
NWC_END_2 = REVENUE_2 * NWC_PCT[1]  # 178,200
D_NWC_2 = NWC_END_2 - NWC_END_1  # 13,200
DIV_2 = max(NI_2, 0.0) * PAYOUT[1]  # 42,804
CFBF_2 = NI_2 + DA[1] - D_NWC_2 - CAPEX_2 - DIV_2  # 92,276
CASH_2 = CASH_1 + CFBF_2  # 356,826
PPE_2 = PPE_1 + CAPEX_2 - DA[1]  # 789,400
RE_2 = RE_1 + NI_2 - DIV_2  # 524,426

# --- Period 3 ---
REVENUE_3 = REVENUE_2 * (1.0 + REVENUE_GROWTH[2])  # 1,247,400
GROSS_PROFIT_3 = REVENUE_3 * GROSS_MARGIN[2]  # 523,908
OPEX_3 = REVENUE_3 * OPEX_PCT[2]  # 224,532
EBITDA_3 = GROSS_PROFIT_3 - OPEX_3  # 299,376
EBIT_3 = EBITDA_3 - DA[2]  # 231,376
INTEREST_3 = INTEREST_RATE[2] * DEBT_0  # 18,000
PRETAX_3 = EBIT_3 - INTEREST_3  # 213,376
TAX_3 = PRETAX_3 * TAX_RATE[2]  # 53,344
NI_3 = PRETAX_3 - TAX_3  # 160,032
CAPEX_3 = REVENUE_3 * CAPEX_PCT[2]  # 49,896
NWC_END_3 = REVENUE_3 * NWC_PCT[2]  # 174,636
D_NWC_3 = NWC_END_3 - NWC_END_2  # -3,564 (NWC shrinks -- a source of cash)
DIV_3 = max(NI_3, 0.0) * PAYOUT[2]  # 48,009.6
CFBF_3 = NI_3 + DA[2] - D_NWC_3 - CAPEX_3 - DIV_3  # 133,690.4
CASH_3 = CASH_2 + CFBF_3  # 490,516.4
PPE_3 = PPE_2 + CAPEX_3 - DA[2]  # 771,296
RE_3 = RE_2 + NI_3 - DIV_3  # 636,448.4

DRIVERS = {
    "revenue_growth": REVENUE_GROWTH,
    "gross_margin": GROSS_MARGIN,
    "opex_pct_revenue": OPEX_PCT,
    "capex_pct_revenue": CAPEX_PCT,
    "nwc_pct_revenue": NWC_PCT,
    "tax_rate": TAX_RATE,
    "dividend_payout_ratio": PAYOUT,
    "depreciation_amortization": DA,
    "interest_rate": INTEREST_RATE,
    # Set to the exact break-even cash each period, so the revolver never
    # draws or repays and debt stays flat at 300,000 -- see module docstring.
    "minimum_cash": [CASH_1, CASH_2, CASH_3],
}


def test_three_period_projection_matches_hand_computation():
    """Every IS/CF/BS line, all three periods, matches the arithmetic above exactly."""
    result = project_three_statement(OPENING, DRIVERS)
    assert len(result.periods) == 3

    p1, p2, p3 = result.periods

    # --- Period 1 income statement ---
    assert p1.income_statement.revenue == pytest.approx(REVENUE_1, abs=TOL)
    assert p1.income_statement.gross_profit == pytest.approx(GROSS_PROFIT_1, abs=TOL)
    assert p1.income_statement.opex == pytest.approx(OPEX_1, abs=TOL)
    assert p1.income_statement.ebitda == pytest.approx(EBITDA_1, abs=TOL)
    assert p1.income_statement.depreciation_amortization == pytest.approx(DA[0], abs=TOL)
    assert p1.income_statement.ebit == pytest.approx(EBIT_1, abs=TOL)
    assert p1.income_statement.interest_expense == pytest.approx(INTEREST_1, abs=TOL)
    assert p1.income_statement.pretax_income == pytest.approx(PRETAX_1, abs=TOL)
    assert p1.income_statement.tax_expense == pytest.approx(TAX_1, abs=TOL)
    assert p1.income_statement.net_income == pytest.approx(NI_1, abs=TOL)
    assert p1.income_statement.cogs == pytest.approx(REVENUE_1 - GROSS_PROFIT_1, abs=TOL)

    # --- Period 1 cash flow statement ---
    assert p1.cash_flow_statement.net_income == pytest.approx(NI_1, abs=TOL)
    assert p1.cash_flow_statement.depreciation_amortization == pytest.approx(DA[0], abs=TOL)
    assert p1.cash_flow_statement.change_in_net_working_capital == pytest.approx(D_NWC_1, abs=TOL)
    assert p1.cash_flow_statement.capex == pytest.approx(CAPEX_1, abs=TOL)
    assert p1.cash_flow_statement.dividends_paid == pytest.approx(DIV_1, abs=TOL)
    assert p1.cash_flow_statement.revolver_draw == pytest.approx(0.0, abs=TOL)
    assert p1.cash_flow_statement.revolver_repayment == pytest.approx(0.0, abs=TOL)
    assert p1.cash_flow_statement.financing_activities == pytest.approx(-DIV_1, abs=TOL)
    assert p1.cash_flow_statement.net_change_in_cash == pytest.approx(CFBF_1, abs=TOL)

    # --- Period 1 balance sheet ---
    assert p1.balance_sheet.cash == pytest.approx(CASH_1, abs=TOL)
    assert p1.balance_sheet.net_working_capital == pytest.approx(NWC_END_1, abs=TOL)
    assert p1.balance_sheet.ppe == pytest.approx(PPE_1, abs=TOL)
    assert p1.balance_sheet.revolver_balance == pytest.approx(DEBT_0, abs=TOL)
    assert p1.balance_sheet.paid_in_capital == pytest.approx(PAID_IN, abs=TOL)
    assert p1.balance_sheet.retained_earnings == pytest.approx(RE_1, abs=TOL)
    assert p1.converged is True
    _assert_balances(p1.balance_sheet)

    # --- Period 2 income statement ---
    assert p2.income_statement.revenue == pytest.approx(REVENUE_2, abs=TOL)
    assert p2.income_statement.gross_profit == pytest.approx(GROSS_PROFIT_2, abs=TOL)
    assert p2.income_statement.opex == pytest.approx(OPEX_2, abs=TOL)
    assert p2.income_statement.ebitda == pytest.approx(EBITDA_2, abs=TOL)
    assert p2.income_statement.depreciation_amortization == pytest.approx(DA[1], abs=TOL)
    assert p2.income_statement.ebit == pytest.approx(EBIT_2, abs=TOL)
    assert p2.income_statement.interest_expense == pytest.approx(INTEREST_2, abs=TOL)
    assert p2.income_statement.pretax_income == pytest.approx(PRETAX_2, abs=TOL)
    assert p2.income_statement.tax_expense == pytest.approx(TAX_2, abs=TOL)
    assert p2.income_statement.net_income == pytest.approx(NI_2, abs=TOL)

    # --- Period 2 cash flow statement ---
    assert p2.cash_flow_statement.change_in_net_working_capital == pytest.approx(D_NWC_2, abs=TOL)
    assert p2.cash_flow_statement.capex == pytest.approx(CAPEX_2, abs=TOL)
    assert p2.cash_flow_statement.dividends_paid == pytest.approx(DIV_2, abs=TOL)
    assert p2.cash_flow_statement.revolver_draw == pytest.approx(0.0, abs=TOL)
    assert p2.cash_flow_statement.revolver_repayment == pytest.approx(0.0, abs=TOL)
    assert p2.cash_flow_statement.financing_activities == pytest.approx(-DIV_2, abs=TOL)
    assert p2.cash_flow_statement.net_change_in_cash == pytest.approx(CFBF_2, abs=TOL)

    # --- Period 2 balance sheet ---
    assert p2.balance_sheet.cash == pytest.approx(CASH_2, abs=TOL)
    assert p2.balance_sheet.net_working_capital == pytest.approx(NWC_END_2, abs=TOL)
    assert p2.balance_sheet.ppe == pytest.approx(PPE_2, abs=TOL)
    assert p2.balance_sheet.revolver_balance == pytest.approx(DEBT_0, abs=TOL)
    assert p2.balance_sheet.retained_earnings == pytest.approx(RE_2, abs=TOL)
    assert p2.converged is True
    _assert_balances(p2.balance_sheet)

    # --- Period 3 income statement ---
    assert p3.income_statement.revenue == pytest.approx(REVENUE_3, abs=TOL)
    assert p3.income_statement.gross_profit == pytest.approx(GROSS_PROFIT_3, abs=TOL)
    assert p3.income_statement.opex == pytest.approx(OPEX_3, abs=TOL)
    assert p3.income_statement.ebitda == pytest.approx(EBITDA_3, abs=TOL)
    assert p3.income_statement.depreciation_amortization == pytest.approx(DA[2], abs=TOL)
    assert p3.income_statement.ebit == pytest.approx(EBIT_3, abs=TOL)
    assert p3.income_statement.interest_expense == pytest.approx(INTEREST_3, abs=TOL)
    assert p3.income_statement.pretax_income == pytest.approx(PRETAX_3, abs=TOL)
    assert p3.income_statement.tax_expense == pytest.approx(TAX_3, abs=TOL)
    assert p3.income_statement.net_income == pytest.approx(NI_3, abs=TOL)

    # --- Period 3 cash flow statement (note the NWC *source* of cash) ---
    assert p3.cash_flow_statement.change_in_net_working_capital == pytest.approx(D_NWC_3, abs=TOL)
    assert D_NWC_3 < 0.0
    assert p3.cash_flow_statement.capex == pytest.approx(CAPEX_3, abs=TOL)
    assert p3.cash_flow_statement.dividends_paid == pytest.approx(DIV_3, abs=TOL)
    assert p3.cash_flow_statement.revolver_draw == pytest.approx(0.0, abs=TOL)
    assert p3.cash_flow_statement.revolver_repayment == pytest.approx(0.0, abs=TOL)
    assert p3.cash_flow_statement.financing_activities == pytest.approx(-DIV_3, abs=TOL)
    assert p3.cash_flow_statement.net_change_in_cash == pytest.approx(CFBF_3, abs=TOL)

    # --- Period 3 balance sheet ---
    assert p3.balance_sheet.cash == pytest.approx(CASH_3, abs=TOL)
    assert p3.balance_sheet.net_working_capital == pytest.approx(NWC_END_3, abs=TOL)
    assert p3.balance_sheet.ppe == pytest.approx(PPE_3, abs=TOL)
    assert p3.balance_sheet.revolver_balance == pytest.approx(DEBT_0, abs=TOL)
    assert p3.balance_sheet.paid_in_capital == pytest.approx(PAID_IN, abs=TOL)
    assert p3.balance_sheet.retained_earnings == pytest.approx(RE_3, abs=TOL)
    assert p3.converged is True
    _assert_balances(p3.balance_sheet)

    # All three periods balance -- assets == liabilities + equity, exactly.
    for period_result in result.periods:
        bs = period_result.balance_sheet
        assert bs.total_assets == pytest.approx(bs.total_liabilities + bs.total_equity, abs=TOL)


# --------------------------------------------------------------------------
# Hard balance check: must raise on a genuinely unbalanced input, not just
# stay quiet on a balanced one.
# --------------------------------------------------------------------------


def test_check_balance_sheet_raises_on_broken_retained_earnings():
    """A balance sheet whose retained-earnings rollforward was hand-broken must raise.

    Assets = 1,000 + 200 + 3,000 = 4,200. Liabilities + equity =
    1,000 + 2,000 + 1,000 = 4,000. The 200 gap is a deliberately wrong
    retained_earnings (it should have been 1,200 to balance).
    """
    broken = BalanceSheet(
        period=1,
        cash=1_000.0,
        net_working_capital=200.0,
        ppe=3_000.0,
        revolver_balance=1_000.0,
        paid_in_capital=2_000.0,
        retained_earnings=1_000.0,  # should be 1,200.0 to balance
    )
    with pytest.raises(BalanceSheetError) as excinfo:
        check_balance_sheet(broken)
    assert excinfo.value.residual == pytest.approx(200.0, abs=TOL)
    assert "200" in str(excinfo.value)
    assert excinfo.value.period == 1


def test_check_balance_sheet_does_not_raise_when_balanced():
    """The same construction, with the correct retained earnings, must not raise."""
    balanced = BalanceSheet(
        period=1,
        cash=1_000.0,
        net_working_capital=200.0,
        ppe=3_000.0,
        revolver_balance=1_000.0,
        paid_in_capital=2_000.0,
        retained_earnings=1_200.0,
    )
    check_balance_sheet(balanced)  # must not raise


def test_project_three_statement_raises_on_broken_opening_balance_sheet():
    """An opening balance sheet that does not balance must refuse to project at all.

    Reuses the flagship OPENING dict but bumps retained_earnings by 1.0, which
    breaks the identity by exactly 1.0 (residual = -1.0, since equity is now
    1.0 too large).
    """
    broken_opening = dict(OPENING)
    broken_opening["retained_earnings"] = OPENING["retained_earnings"] + 1.0
    with pytest.raises(BalanceSheetError) as excinfo:
        project_three_statement(broken_opening, DRIVERS)
    assert excinfo.value.period == 0
    assert excinfo.value.residual == pytest.approx(-1.0, abs=TOL)


# --------------------------------------------------------------------------
# Interest/revolver circularity: convergent (multi-iteration) and divergent.
# --------------------------------------------------------------------------

_CIRC_OPENING = {
    "revenue": 1_000_000.0,
    "cash": 50_000.0,
    "net_working_capital": 100_000.0,
    "ppe": 500_000.0,
    "revolver_balance": 200_000.0,
    "paid_in_capital": 300_000.0,
    "retained_earnings": 150_000.0,
}
_CIRC_DRIVERS = {
    "revenue_growth": [0.05],
    "gross_margin": [0.35],
    "opex_pct_revenue": [0.20],
    "capex_pct_revenue": [0.06],
    "nwc_pct_revenue": [0.12],
    "tax_rate": [0.25],
    "dividend_payout_ratio": [0.20],
    "depreciation_amortization": [40_000.0],
    "interest_rate": [0.20],  # 20% -- forces a real draw, hence real circularity
    "minimum_cash": [300_000.0],  # well above the natural cash balance -> shortfall
}


def test_circularity_converges_in_more_than_one_iteration():
    """A real cash shortfall forces the interest/revolver fixed point to iterate.

    The initial guess (no revolver movement) is not the fixed point here --
    minimum_cash is set far above the cash the company would otherwise land
    on, so the first pass computes a large draw, which changes the average
    debt balance, which changes interest, which changes net income and hence
    the draw again. The solve must still converge and say so.
    """
    result = project_three_statement(_CIRC_OPENING, _CIRC_DRIVERS)
    period = result.periods[0]
    assert period.converged is True
    assert period.iterations > 1
    assert period.cash_flow_statement.revolver_draw > 0.0
    _assert_balances(period.balance_sheet)


def test_divergent_circularity_raises_convergence_error():
    """A loop gain above 1 makes the fixed point explode; the model must refuse to answer.

    With dividend_payout_ratio=0 and tax_rate=0, the fixed-point gain on the
    ending debt balance is ``interest_rate / 2`` (see the module docstring's
    derivation). At interest_rate=5.0 (500%) that gain is 2.5, comfortably
    above 1: each iteration's debt guess moves *further* from the last, not
    closer, so no finite iteration budget converges it.
    """
    diverging_opening = dict(_CIRC_OPENING)
    diverging_drivers = dict(_CIRC_DRIVERS)
    diverging_drivers["interest_rate"] = [5.0]
    diverging_drivers["dividend_payout_ratio"] = [0.0]
    diverging_drivers["tax_rate"] = [0.0]
    diverging_drivers["minimum_cash"] = [10_000_000.0]  # stays in the shortfall regime throughout

    with pytest.raises(ConvergenceError) as excinfo:
        project_three_statement(diverging_opening, diverging_drivers)
    assert excinfo.value.iterations == MAX_CIRCULARITY_ITERATIONS
    assert excinfo.value.period == 1
    # A genuinely diverging (not just slowly converging) loop leaves the last
    # step's change many orders of magnitude larger than the tolerance.
    assert excinfo.value.last_delta > 1e30


# --------------------------------------------------------------------------
# Explicit plug: the revolver balance is a visible, reported field, and the
# balance sheet still balances exactly once it has been applied.
# --------------------------------------------------------------------------


def test_revolver_plug_is_explicit_and_balance_sheet_still_balances():
    """The revolver draw and the resulting balance are visible result fields."""
    result = project_three_statement(_CIRC_OPENING, _CIRC_DRIVERS)
    period = result.periods[0]

    # The plug is not hidden inside a residual -- it is a named field on both
    # the cash flow statement (the movement) and the balance sheet (the level).
    assert period.cash_flow_statement.revolver_draw > 0.0
    assert period.cash_flow_statement.revolver_repayment == 0.0
    expected_balance = _CIRC_OPENING["revolver_balance"] + period.cash_flow_statement.revolver_draw
    assert period.balance_sheet.revolver_balance == pytest.approx(expected_balance, abs=TOL)

    # Cash was brought exactly up to the minimum_cash floor by the draw.
    assert period.balance_sheet.cash == pytest.approx(_CIRC_DRIVERS["minimum_cash"][0], abs=TOL)

    _assert_balances(period.balance_sheet)


# --------------------------------------------------------------------------
# Missing inputs: no defaults, ever.
# --------------------------------------------------------------------------


def test_missing_opening_field_raises_missing_input_error():
    """Dropping a required opening-balance field refuses to run, naming the field."""
    incomplete_opening = dict(OPENING)
    del incomplete_opening["retained_earnings"]
    with pytest.raises(MissingInputError) as excinfo:
        project_three_statement(incomplete_opening, DRIVERS)
    assert excinfo.value.missing == ("retained_earnings",)


def test_missing_driver_field_raises_missing_input_error():
    """Dropping a required driver sequence refuses to run, naming the field.

    ``tax_rate`` is deliberately chosen: it is downstream of every other line
    in the income statement, so if the model silently defaulted it, the
    resulting net income would look plausible rather than obviously wrong.
    """
    incomplete_drivers = dict(DRIVERS)
    del incomplete_drivers["tax_rate"]
    with pytest.raises(MissingInputError) as excinfo:
        project_three_statement(OPENING, incomplete_drivers)
    assert excinfo.value.missing == ("tax_rate",)


def test_missing_multiple_fields_are_all_named_at_once():
    """MissingInputError reports every missing field in one pass, not just the first."""
    incomplete_drivers = dict(DRIVERS)
    del incomplete_drivers["tax_rate"]
    del incomplete_drivers["interest_rate"]
    with pytest.raises(MissingInputError) as excinfo:
        project_three_statement(OPENING, incomplete_drivers)
    assert set(excinfo.value.missing) == {"tax_rate", "interest_rate"}


# --------------------------------------------------------------------------
# Structural validation beyond missingness: mismatched / empty driver lengths.
# --------------------------------------------------------------------------


def test_mismatched_driver_lengths_raise():
    """Driver sequences of different lengths cannot be zipped into periods safely."""
    mismatched = dict(DRIVERS)
    mismatched["tax_rate"] = [0.25, 0.25]  # length 2 vs. 3 everywhere else
    with pytest.raises(Exception, match=r"(?i)length"):
        project_three_statement(OPENING, mismatched)


def test_empty_driver_sequences_raise():
    """Zero-length driver sequences mean zero periods, which is not a projection."""
    empty_drivers = {field: [] for field in DRIVERS}
    with pytest.raises(Exception, match=r"(?i)period"):
        project_three_statement(OPENING, empty_drivers)


# --------------------------------------------------------------------------
# Boundary conditions.
# --------------------------------------------------------------------------


def test_zero_revenue_boundary():
    """A pre-revenue company still produces a linked, balanced projection.

    With revenue pinned at zero, every revenue-scaled line (gross profit,
    opex, capex, NWC) is zero too, but D&A is a direct dollar input and keeps
    accruing, so EBIT, pretax income and net income are all driven purely
    negative by D&A -- and the model must not divide by revenue anywhere to
    get there.
    """
    opening = {
        "revenue": 0.0,
        "cash": 100_000.0,
        "net_working_capital": 0.0,
        "ppe": 200_000.0,
        "revolver_balance": 0.0,
        "paid_in_capital": 250_000.0,
        "retained_earnings": 50_000.0,
    }
    drivers = {
        "revenue_growth": [0.0, 0.0],
        "gross_margin": [0.40, 0.40],
        "opex_pct_revenue": [0.20, 0.20],
        "capex_pct_revenue": [0.0, 0.0],
        "nwc_pct_revenue": [0.10, 0.10],
        "tax_rate": [0.25, 0.25],
        "dividend_payout_ratio": [0.5, 0.5],
        "depreciation_amortization": [10_000.0, 10_000.0],
        "interest_rate": [0.05, 0.05],
        "minimum_cash": [0.0, 0.0],
    }
    result = project_three_statement(opening, drivers)
    for period in result.periods:
        assert period.income_statement.revenue == 0.0
        assert period.income_statement.gross_profit == 0.0
        assert period.income_statement.opex == 0.0
        assert period.income_statement.ebitda == 0.0
        assert period.income_statement.ebit == pytest.approx(-10_000.0, abs=TOL)
        assert period.income_statement.net_income == pytest.approx(-7_500.0, abs=TOL)
        assert period.cash_flow_statement.capex == 0.0
        assert period.balance_sheet.net_working_capital == 0.0
        _assert_balances(period.balance_sheet)


def test_negative_net_income_drives_retained_earnings_negative():
    """A sustained loss must be allowed to push retained earnings below zero.

    Opex is set to 50% of revenue against a 10% gross margin, guaranteeing a
    large operating loss; the payout clamp means loss periods pay no dividend
    (max(net_income, 0) * payout == 0), so the loss flows straight through to
    retained earnings.
    """
    opening = {
        "revenue": 100_000.0,
        "cash": 50_000.0,
        "net_working_capital": 10_000.0,
        "ppe": 100_000.0,
        "revolver_balance": 0.0,
        "paid_in_capital": 155_000.0,
        "retained_earnings": 5_000.0,
    }
    drivers = {
        "revenue_growth": [0.0, 0.0],
        "gross_margin": [0.10, 0.10],
        "opex_pct_revenue": [0.50, 0.50],
        "capex_pct_revenue": [0.0, 0.0],
        "nwc_pct_revenue": [0.10, 0.10],
        "tax_rate": [0.25, 0.25],
        "dividend_payout_ratio": [0.3, 0.3],
        "depreciation_amortization": [5_000.0, 5_000.0],
        "interest_rate": [0.05, 0.05],
        "minimum_cash": [0.0, 0.0],
    }
    result = project_three_statement(opening, drivers)
    period1 = result.periods[0]
    assert period1.income_statement.net_income < 0.0
    assert period1.cash_flow_statement.dividends_paid == 0.0
    assert period1.balance_sheet.retained_earnings < 0.0
    _assert_balances(period1.balance_sheet)

    period2 = result.periods[1]
    assert period2.balance_sheet.retained_earnings < period1.balance_sheet.retained_earnings
    _assert_balances(period2.balance_sheet)


def test_capex_exceeding_depreciation_grows_ppe():
    """When capex outpaces D&A, net PP&E must increase by exactly the difference."""
    opening = {
        "revenue": 100_000.0,
        "cash": 100_000.0,
        "net_working_capital": 10_000.0,
        "ppe": 50_000.0,
        "revolver_balance": 0.0,
        "paid_in_capital": 100_000.0,
        "retained_earnings": 60_000.0,
    }
    drivers = {
        "revenue_growth": [0.0],
        "gross_margin": [0.40],
        "opex_pct_revenue": [0.20],
        "capex_pct_revenue": [0.10],  # capex = 10,000
        "nwc_pct_revenue": [0.10],
        "tax_rate": [0.25],
        "dividend_payout_ratio": [0.0],
        "depreciation_amortization": [2_000.0],  # da = 2,000 << capex
        "interest_rate": [0.0],
        "minimum_cash": [0.0],
    }
    result = project_three_statement(opening, drivers)
    period = result.periods[0]
    assert period.cash_flow_statement.capex == pytest.approx(10_000.0, abs=TOL)
    assert period.income_statement.depreciation_amortization == pytest.approx(2_000.0, abs=TOL)
    assert period.balance_sheet.ppe == pytest.approx(opening["ppe"] + 10_000.0 - 2_000.0, abs=TOL)
    assert period.balance_sheet.ppe > opening["ppe"]
    _assert_balances(period.balance_sheet)
