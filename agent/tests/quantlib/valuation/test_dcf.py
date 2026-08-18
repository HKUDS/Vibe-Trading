"""Tests for src.quantlib.valuation.dcf.

Two rules the assertions here follow, matching the rest of ``tests/quantlib``.

*The main worked example is computed by hand, not by calling the module.*
:func:`test_full_worked_example_matches_hand_calculation` builds one clean
input set, and every expected intermediate (WACC, each year's NOPAT/FCFF,
both terminal values, both discount conventions, enterprise value, equity
value, value per share) is written out as a plain arithmetic expression in
this file using the same numbers -- not derived by calling ``dcf.py``. A wrong
implementation therefore cannot make the test agree with itself.

*Every input this package refuses to default is tested for refusal.* The
missing-input tests are parametrized over every key :data:`DCF_BASE_REQUIRED_FIELDS`
and the structure-basis fields name, not just the four the task called out by
name, and a second block of tests calls the lower-level builders directly with
a required keyword omitted to show that no alternate entry point can slip a
number out when an input is missing.
"""

import math

import numpy as np
import pandas as pd
import pytest

from src.quantlib.valuation.contracts import Assumption, MissingInputError, ValuationError
from src.quantlib.valuation.dcf import (
    DCF_BASE_REQUIRED_FIELDS,
    DCF_CURRENT_STRUCTURE_FIELDS,
    DCF_TARGET_STRUCTURE_FIELDS,
    DEFAULT_LONG_RUN_GDP_GROWTH_CEILING,
    DCFResult,
    DiscountedCashFlow,
    FCFFYear,
    NetDebtBridgeResult,
    TerminalValueResult,
    WACCResult,
    discount_fcff,
    equity_bridge,
    fcff_bridge,
    run_dcf,
    sensitivity_grid,
    terminal_value,
    wacc,
)

# ---------------------------------------------------------------------------
# The worked example
# ---------------------------------------------------------------------------
#
# WACC:
#   cost_of_equity        = 0.04 + 1.2*0.05 + 0.01 + 0.00       = 0.11
#   cost_of_debt_after_tax = 0.06*(1-0.25)                       = 0.045
#   WACC                   = 0.7*0.11 + 0.3*0.045                = 0.0905
#
# FCFF bridge (tax_rate=0.25 every year):
#   Y1: NOPAT=100*0.75=75.00   FCFF=75.00+20-30-5 = 60.00
#   Y2: NOPAT=105*0.75=78.75   FCFF=78.75+21-28-4 = 67.75
#   Y3: NOPAT=110*0.75=82.50   FCFF=82.50+22-26-3 = 75.50
#
# Terminal year EBITDA = EBIT_3 + D&A_3 = 110 + 22 = 132.0
#
# Terminal value (g=0.03, exit_multiple=8.0x):
#   FCFF_4          = 75.50*1.03            = 77.765
#   perpetuity_TV   = 77.765/(0.0905-0.03)  = 1285.3719008264463
#   exit_TV         = 132.0*8.0             = 1056.0
#   implied_multiple= 1285.3719.../132      = 9.737665915351867
#   implied_growth  = (1056*0.0905-75.5)/(1056+75.5) = 0.017735749005744584
#
# Mid-year discounting (t = 0.5, 1.5, 2.5):
#   pv_explicit = 177.7471630647021
#   terminal_discount_factor = (1.0905)**-2.5 = 0.805259440904553
#   pv_of_terminal_value (perpetuity) = 1035.0578582139267
#   enterprise_value = 1212.8050212786288
#
# Year-end discounting (t = 1, 2, 3):
#   pv_explicit = 170.2118699631167
#   terminal_discount_factor = (1.0905)**-3 = 0.7711218163967243
#   pv_of_terminal_value (perpetuity) = 991.1783149105994
#   enterprise_value = 1161.3901848737162
#
# Equity bridge (mid-year, perpetuity method):
#   equity_value = 1212.8050212786288 - 200 + 50 - 10 - 15 + 5 = 1042.8050212786288
#   value_per_share = 1042.8050212786288 / 100 = 10.428050212786289


def base_inputs(*, structure: str = "target") -> dict:
    """Fresh copy of the worked example's ``run_dcf`` inputs mapping.

    Args:
        structure: ``"target"`` supplies ``target_equity_weight``/
            ``target_debt_weight`` (0.7/0.3); ``"current"`` supplies market
            values (700/300) that resolve to the identical weights.
    """
    inputs = {
        "risk_free_rate": 0.04,
        "beta": 1.2,
        "equity_risk_premium": 0.05,
        "size_premium": 0.01,
        "country_risk_premium": 0.0,
        "pretax_cost_of_debt": 0.06,
        "tax_rate": 0.25,
        "ebit": [100.0, 105.0, 110.0],
        "depreciation_amortization": [20.0, 21.0, 22.0],
        "capex": [30.0, 28.0, 26.0],
        "delta_nwc": [5.0, 4.0, 3.0],
        "terminal_growth": Assumption(
            name="terminal_growth",
            value=0.03,
            basis="Long-run nominal GDP proxy for a mature-market perpetuity",
        ),
        "exit_multiple": Assumption(
            name="exit_multiple",
            value=8.0,
            basis="Median EV/EBITDA of the comparable peer set",
        ),
        "total_debt": 200.0,
        "cash_and_equivalents": 50.0,
        "minority_interest": 10.0,
        "preferred_equity": 15.0,
        "associate_investments": 5.0,
        "diluted_shares": 100.0,
    }
    if structure == "target":
        inputs["target_equity_weight"] = 0.7
        inputs["target_debt_weight"] = 0.3
    else:
        inputs["market_value_of_equity"] = 700.0
        inputs["market_value_of_debt"] = 300.0
    return inputs


# ---------------------------------------------------------------------------
# 1. The full worked example, asserted to 1e-9
# ---------------------------------------------------------------------------


def test_full_worked_example_matches_hand_calculation():
    result = run_dcf(
        base_inputs(),
        capital_structure_basis="target",
        discounting_convention="mid_year",
        terminal_value_method="perpetuity_growth",
    )

    assert isinstance(result, DCFResult)

    # WACC
    assert result.wacc_build.cost_of_equity == pytest.approx(0.11, abs=1e-9)
    assert result.wacc_build.cost_of_debt_after_tax == pytest.approx(0.045, abs=1e-9)
    assert result.wacc_build.wacc == pytest.approx(0.0905, abs=1e-9)

    # FCFF bridge
    expected_nopat = [75.0, 78.75, 82.5]
    expected_fcff = [60.0, 67.75, 75.5]
    for i, year in enumerate(result.fcff_bridge):
        assert year.year == i + 1
        assert year.nopat == pytest.approx(expected_nopat[i], abs=1e-9)
        assert year.fcff == pytest.approx(expected_fcff[i], abs=1e-9)

    # Terminal value
    tv = result.terminal_value
    assert tv.terminal_year_ebitda == pytest.approx(132.0, abs=1e-9)
    assert tv.perpetuity_terminal_value == pytest.approx(1285.3719008264463, abs=1e-6)
    assert tv.exit_terminal_value == pytest.approx(1056.0, abs=1e-9)
    assert tv.implied_ev_ebitda_multiple == pytest.approx(9.737665915351867, abs=1e-6)
    assert tv.implied_perpetuity_growth == pytest.approx(0.017735749005744584, abs=1e-9)

    # Discounting + enterprise value (mid-year)
    assert result.pv_of_explicit_fcff == pytest.approx(177.7471630647021, abs=1e-6)
    assert result.terminal_discount_factor == pytest.approx(0.805259440904553, abs=1e-9)
    assert result.pv_of_terminal_value == pytest.approx(1035.0578582139267, abs=1e-6)
    assert result.enterprise_value == pytest.approx(1212.8050212786288, abs=1e-6)

    # Equity bridge + per share
    assert result.equity_value == pytest.approx(1042.8050212786288, abs=1e-6)
    assert result.value_per_share == pytest.approx(10.428050212786289, abs=1e-6)
    assert result.net_debt_bridge.diluted_shares == 100.0


def test_worked_example_current_basis_matches_target_basis():
    """700/300 market values resolve to the same 0.7/0.3 weights as target."""
    target = run_dcf(
        base_inputs(structure="target"),
        capital_structure_basis="target",
        discounting_convention="mid_year",
        terminal_value_method="perpetuity_growth",
    )
    current = run_dcf(
        base_inputs(structure="current"),
        capital_structure_basis="current",
        discounting_convention="mid_year",
        terminal_value_method="perpetuity_growth",
    )
    assert current.wacc_build.wacc == pytest.approx(target.wacc_build.wacc, abs=1e-12)
    assert current.value_per_share == pytest.approx(target.value_per_share, abs=1e-9)


def test_terminal_value_method_switch_changes_enterprise_value():
    perpetuity = run_dcf(
        base_inputs(),
        capital_structure_basis="target",
        discounting_convention="mid_year",
        terminal_value_method="perpetuity_growth",
    )
    exit_method = run_dcf(
        base_inputs(),
        capital_structure_basis="target",
        discounting_convention="mid_year",
        terminal_value_method="exit_multiple",
    )
    # Both terminal values are always computed regardless of which drives EV.
    assert perpetuity.terminal_value.exit_terminal_value == pytest.approx(1056.0, abs=1e-9)
    assert exit_method.terminal_value.perpetuity_terminal_value == pytest.approx(
        1285.3719008264463, abs=1e-6
    )
    assert perpetuity.enterprise_value != pytest.approx(exit_method.enterprise_value)


# ---------------------------------------------------------------------------
# 2. Missing inputs are not runnable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing_key", DCF_BASE_REQUIRED_FIELDS)
def test_run_dcf_refuses_each_missing_base_field(missing_key):
    inputs = base_inputs()
    del inputs[missing_key]
    with pytest.raises(MissingInputError) as excinfo:
        run_dcf(
            inputs,
            capital_structure_basis="target",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )
    assert missing_key in excinfo.value.missing
    assert excinfo.value.model == "run_dcf"


@pytest.mark.parametrize("missing_key", DCF_TARGET_STRUCTURE_FIELDS)
def test_run_dcf_refuses_each_missing_target_structure_field(missing_key):
    inputs = base_inputs(structure="target")
    del inputs[missing_key]
    with pytest.raises(MissingInputError) as excinfo:
        run_dcf(
            inputs,
            capital_structure_basis="target",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )
    assert missing_key in excinfo.value.missing


@pytest.mark.parametrize("missing_key", DCF_CURRENT_STRUCTURE_FIELDS)
def test_run_dcf_refuses_each_missing_current_structure_field(missing_key):
    inputs = base_inputs(structure="current")
    del inputs[missing_key]
    with pytest.raises(MissingInputError) as excinfo:
        run_dcf(
            inputs,
            capital_structure_basis="current",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )
    assert missing_key in excinfo.value.missing


@pytest.mark.parametrize(
    "missing_key", ["tax_rate", "beta", "equity_risk_premium", "diluted_shares"]
)
def test_run_dcf_names_the_four_headline_fields_explicitly(missing_key):
    """The task's own four examples, kept as a standalone named check."""
    inputs = base_inputs()
    del inputs[missing_key]
    with pytest.raises(MissingInputError) as excinfo:
        run_dcf(
            inputs,
            capital_structure_basis="target",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )
    assert excinfo.value.missing == (missing_key,)


def test_no_path_returns_a_number_when_a_required_field_is_missing():
    """Neither the flat-mapping entry point nor any lower-level builder can
    silently substitute a value for a missing required field."""
    # run_dcf: MissingInputError, never a DCFResult.
    inputs = base_inputs()
    del inputs["tax_rate"]
    with pytest.raises(MissingInputError):
        run_dcf(
            inputs,
            capital_structure_basis="target",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )

    # wacc(): a required keyword-only argument with no default cannot be
    # omitted -- Python itself refuses the call before any arithmetic runs.
    with pytest.raises(TypeError):
        wacc(  # missing tax_rate
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06,
            capital_structure_basis="target",
            target_equity_weight=0.7,
            target_debt_weight=0.3,
        )

    # wacc()'s conditional structure inputs: present basis, absent pair.
    with pytest.raises(MissingInputError) as excinfo:
        wacc(
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06,
            tax_rate=0.25,
            capital_structure_basis="current",
        )
    assert set(excinfo.value.missing) == {"market_value_of_equity", "market_value_of_debt"}

    # fcff_bridge(): missing capex.
    with pytest.raises(TypeError):
        fcff_bridge(
            ebit=[100.0],
            tax_rate=0.25,
            depreciation_amortization=[20.0],
            delta_nwc=[5.0],
        )

    # terminal_value(): missing exit_multiple.
    with pytest.raises(TypeError):
        terminal_value(
            final_year_fcff=75.5,
            terminal_year_ebitda=132.0,
            wacc_rate=0.0905,
            terminal_growth=Assumption("terminal_growth", 0.03, "test"),
        )

    # discount_fcff(): missing wacc_rate.
    bridge = fcff_bridge(
        ebit=[100.0],
        tax_rate=0.25,
        depreciation_amortization=[20.0],
        capex=[30.0],
        delta_nwc=[5.0],
    )
    with pytest.raises(TypeError):
        discount_fcff(bridge, discounting_convention="mid_year")

    # equity_bridge(): missing diluted_shares.
    with pytest.raises(TypeError):
        equity_bridge(
            enterprise_value=1000.0,
            total_debt=200.0,
            cash_and_equivalents=50.0,
            minority_interest=10.0,
            preferred_equity=15.0,
            associate_investments=5.0,
        )


def test_run_dcf_refuses_bare_float_terminal_growth():
    inputs = base_inputs()
    inputs["terminal_growth"] = 0.03  # bare float, not an Assumption
    with pytest.raises(ValuationError):
        run_dcf(
            inputs,
            capital_structure_basis="target",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )


def test_run_dcf_refuses_bare_float_exit_multiple():
    inputs = base_inputs()
    inputs["exit_multiple"] = 8.0
    with pytest.raises(ValuationError):
        run_dcf(
            inputs,
            capital_structure_basis="target",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )


def test_run_dcf_refuses_assumption_with_wrong_name():
    inputs = base_inputs()
    inputs["terminal_growth"] = Assumption(name="exit_multiple", value=0.03, basis="mislabelled")
    with pytest.raises(ValuationError):
        run_dcf(
            inputs,
            capital_structure_basis="target",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )


# ---------------------------------------------------------------------------
# 3. Dual terminal value + cross-validation
# ---------------------------------------------------------------------------


def test_implied_ev_ebitda_multiple_flags_an_unrealistic_growth_assumption():
    """g pushed close to WACC implies an absurd EV/EBITDA multiple, even
    though the Gordon-growth arithmetic itself is perfectly correct."""
    result = terminal_value(
        final_year_fcff=75.5,
        terminal_year_ebitda=132.0,
        wacc_rate=0.0905,
        terminal_growth=Assumption("terminal_growth", 0.089, "deliberately aggressive"),
        exit_multiple=Assumption("exit_multiple", 8.0, "median comp"),
    )
    assert result.implied_ev_ebitda_multiple == pytest.approx(415.25, abs=0.01)
    assert result.implied_ev_ebitda_multiple > 50.0  # an unmistakably absurd multiple


def test_implied_perpetuity_growth_flags_an_unrealistic_exit_multiple():
    """A rich exit multiple implies a perpetuity growth rate far above the
    stated 3% growth assumption, surfacing the disagreement between methods."""
    result = terminal_value(
        final_year_fcff=75.5,
        terminal_year_ebitda=132.0,
        wacc_rate=0.0905,
        terminal_growth=Assumption("terminal_growth", 0.03, "base case"),
        exit_multiple=Assumption("exit_multiple", 40.0, "deliberately rich"),
    )
    assert result.implied_perpetuity_growth == pytest.approx(0.0751265054616749, abs=1e-9)
    assert result.implied_perpetuity_growth > 0.06  # far above the stated 3% base case


def test_implied_perpetuity_growth_is_not_blocked_by_the_g_vs_wacc_guard():
    """The g>=WACC guard applies to the caller's stated terminal_growth
    Assumption, not to the reverse-engineered implied growth -- an implied
    growth is a diagnostic, and blocking it would hide exactly the
    unrealistic assumption the cross-check exists to surface."""
    result = terminal_value(
        final_year_fcff=75.5,
        terminal_year_ebitda=132.0,
        wacc_rate=0.0905,
        terminal_growth=Assumption("terminal_growth", 0.03, "base case"),
        exit_multiple=Assumption("exit_multiple", 60.0, "extreme"),
    )
    # No exception raised even though the implied growth sits close to WACC.
    assert result.implied_perpetuity_growth == pytest.approx(0.08020261397035833, abs=1e-9)


def test_terminal_growth_at_or_above_wacc_raises():
    with pytest.raises(ValuationError):
        terminal_value(
            final_year_fcff=75.5,
            terminal_year_ebitda=132.0,
            wacc_rate=0.0905,
            terminal_growth=Assumption("terminal_growth", 0.0905, "equal to WACC"),
            exit_multiple=Assumption("exit_multiple", 8.0, "median comp"),
        )
    with pytest.raises(ValuationError):
        terminal_value(
            final_year_fcff=75.5,
            terminal_year_ebitda=132.0,
            wacc_rate=0.0905,
            terminal_growth=Assumption("terminal_growth", 0.10, "above WACC"),
            exit_multiple=Assumption("exit_multiple", 8.0, "median comp"),
        )


def test_terminal_value_blows_up_near_wacc_without_silent_truncation():
    """As g approaches WACC the terminal value must explode, not be capped
    or silently truncated to a merely-large number."""
    near_far = terminal_value(
        final_year_fcff=75.5,
        terminal_year_ebitda=132.0,
        wacc_rate=0.0905,
        terminal_growth=Assumption("terminal_growth", 0.03, "base case"),
        exit_multiple=Assumption("exit_multiple", 8.0, "median comp"),
    )
    near_close = terminal_value(
        final_year_fcff=75.5,
        terminal_year_ebitda=132.0,
        wacc_rate=0.0905,
        terminal_growth=Assumption("terminal_growth", 0.0905 - 1e-6, "pathologically close to WACC"),
        exit_multiple=Assumption("exit_multiple", 8.0, "median comp"),
    )
    assert near_close.perpetuity_terminal_value > 1_000_000
    assert near_close.perpetuity_terminal_value > 100 * near_far.perpetuity_terminal_value


def test_growth_exceeds_gdp_ceiling_is_a_flag_not_an_error():
    below = terminal_value(
        final_year_fcff=75.5,
        terminal_year_ebitda=132.0,
        wacc_rate=0.0905,
        terminal_growth=Assumption("terminal_growth", 0.03, "below the 4% ceiling"),
        exit_multiple=Assumption("exit_multiple", 8.0, "median comp"),
    )
    assert below.growth_exceeds_gdp_ceiling is False
    assert below.gdp_growth_ceiling == DEFAULT_LONG_RUN_GDP_GROWTH_CEILING

    above = terminal_value(
        final_year_fcff=75.5,
        terminal_year_ebitda=132.0,
        wacc_rate=0.0905,
        terminal_growth=Assumption("terminal_growth", 0.05, "above the 4% ceiling"),
        exit_multiple=Assumption("exit_multiple", 8.0, "median comp"),
    )
    # No error raised despite exceeding the ceiling -- a judgment call, not a refusal.
    assert above.growth_exceeds_gdp_ceiling is True
    assert above.perpetuity_terminal_value > 0.0

    custom_ceiling = terminal_value(
        final_year_fcff=75.5,
        terminal_year_ebitda=132.0,
        wacc_rate=0.0905,
        terminal_growth=Assumption("terminal_growth", 0.03, "below default ceiling"),
        exit_multiple=Assumption("exit_multiple", 8.0, "median comp"),
        gdp_growth_ceiling=0.02,
    )
    assert custom_ceiling.growth_exceeds_gdp_ceiling is True  # 0.03 > custom 0.02 ceiling


# ---------------------------------------------------------------------------
# 4. Mid-year vs year-end discounting
# ---------------------------------------------------------------------------


def test_mid_year_discounting_is_higher_by_exactly_sqrt_1_plus_wacc():
    bridge = fcff_bridge(
        ebit=[100.0, 105.0, 110.0],
        tax_rate=0.25,
        depreciation_amortization=[20.0, 21.0, 22.0],
        capex=[30.0, 28.0, 26.0],
        delta_nwc=[5.0, 4.0, 3.0],
    )
    wacc_rate = 0.0905
    growth = Assumption("terminal_growth", 0.03, "base case")
    multiple = Assumption("exit_multiple", 8.0, "median comp")
    tv = terminal_value(
        final_year_fcff=bridge[-1].fcff,
        terminal_year_ebitda=bridge[-1].ebit + bridge[-1].depreciation_amortization,
        wacc_rate=wacc_rate,
        terminal_growth=growth,
        exit_multiple=multiple,
    )

    def enterprise_value(convention: str) -> float:
        discounted = discount_fcff(bridge, wacc_rate=wacc_rate, discounting_convention=convention)
        pv_explicit = sum(entry.present_value for entry in discounted)
        pv_terminal = tv.perpetuity_terminal_value * discounted[-1].discount_factor
        return pv_explicit + pv_terminal

    ev_mid_year = enterprise_value("mid_year")
    ev_year_end = enterprise_value("year_end")

    assert ev_mid_year > ev_year_end
    ratio = ev_mid_year / ev_year_end
    assert ratio == pytest.approx(math.sqrt(1.0 + wacc_rate), rel=1e-9)


def test_discount_fcff_requires_a_recognised_convention():
    bridge = fcff_bridge(
        ebit=[100.0],
        tax_rate=0.25,
        depreciation_amortization=[20.0],
        capex=[30.0],
        delta_nwc=[5.0],
    )
    with pytest.raises(ValuationError):
        discount_fcff(bridge, wacc_rate=0.09, discounting_convention="quarterly")


# ---------------------------------------------------------------------------
# 5. Sensitivity grid
# ---------------------------------------------------------------------------


def test_sensitivity_grid_nan_where_growth_at_or_above_wacc():
    bridge = fcff_bridge(
        ebit=[100.0, 105.0, 110.0],
        tax_rate=0.25,
        depreciation_amortization=[20.0, 21.0, 22.0],
        capex=[30.0, 28.0, 26.0],
        delta_nwc=[5.0, 4.0, 3.0],
    )
    grid = sensitivity_grid(
        bridge,
        wacc_values=[0.07, 0.08, 0.09, 0.10, 0.11],
        growth_values=[0.00, 0.02, 0.04, 0.08, 0.095],
        discounting_convention="mid_year",
        total_debt=200.0,
        cash_and_equivalents=50.0,
        minority_interest=10.0,
        preferred_equity=15.0,
        associate_investments=5.0,
        diluted_shares=100.0,
    )
    assert isinstance(grid, pd.DataFrame)
    assert grid.index.name == "wacc"
    assert grid.columns.name == "terminal_growth"

    # g=0.095 >= every wacc value except 0.10 and 0.11 -> NaN there.
    assert math.isnan(grid.loc[0.07, 0.095])
    assert math.isnan(grid.loc[0.08, 0.095])
    assert math.isnan(grid.loc[0.09, 0.095])
    assert not math.isnan(grid.loc[0.10, 0.095])
    assert not math.isnan(grid.loc[0.11, 0.095])

    # g=0.08 == wacc=0.08 -> NaN at the boundary too.
    assert math.isnan(grid.loc[0.08, 0.08])
    assert math.isnan(grid.loc[0.07, 0.08])  # 0.08 > 0.07
    assert not math.isnan(grid.loc[0.09, 0.08])


def test_sensitivity_grid_matches_hand_calculation_at_one_cell():
    bridge = fcff_bridge(
        ebit=[100.0, 105.0, 110.0],
        tax_rate=0.25,
        depreciation_amortization=[20.0, 21.0, 22.0],
        capex=[30.0, 28.0, 26.0],
        delta_nwc=[5.0, 4.0, 3.0],
    )
    grid = sensitivity_grid(
        bridge,
        wacc_values=[0.10],
        growth_values=[0.03],
        discounting_convention="mid_year",
        total_debt=200.0,
        cash_and_equivalents=50.0,
        minority_interest=10.0,
        preferred_equity=15.0,
        associate_investments=5.0,
        diluted_shares=100.0,
    )
    # Hand-computed via the same formula, independently of sensitivity_grid:
    # pv_explicit=175.42529663702476, tv=1110.9285714285713,
    # ev=1050.8210257123903, equity=880.8210257123903, vps=8.808210257123903
    assert grid.loc[0.10, 0.03] == pytest.approx(8.808210257123903, abs=1e-6)


def test_sensitivity_grid_monotonic_decreasing_in_wacc_increasing_in_growth():
    bridge = fcff_bridge(
        ebit=[100.0, 105.0, 110.0],
        tax_rate=0.25,
        depreciation_amortization=[20.0, 21.0, 22.0],
        capex=[30.0, 28.0, 26.0],
        delta_nwc=[5.0, 4.0, 3.0],
    )
    wacc_values = [0.07, 0.08, 0.09, 0.10, 0.11]
    growth_values = [0.00, 0.01, 0.02, 0.03, 0.04]
    grid = sensitivity_grid(
        bridge,
        wacc_values=wacc_values,
        growth_values=growth_values,
        discounting_convention="mid_year",
        total_debt=200.0,
        cash_and_equivalents=50.0,
        minority_interest=10.0,
        preferred_equity=15.0,
        associate_investments=5.0,
        diluted_shares=100.0,
    )
    values = grid.to_numpy()
    assert not np.isnan(values).any()  # every g here is below every wacc

    # Strictly decreasing down each column (increasing WACC).
    for col in range(values.shape[1]):
        column = values[:, col]
        assert np.all(np.diff(column) < 0.0)

    # Strictly increasing across each row (increasing growth).
    for row in range(values.shape[0]):
        line = values[row, :]
        assert np.all(np.diff(line) > 0.0)


def test_sensitivity_grid_requires_nonempty_axes_and_positive_shares():
    bridge = fcff_bridge(
        ebit=[100.0],
        tax_rate=0.25,
        depreciation_amortization=[20.0],
        capex=[30.0],
        delta_nwc=[5.0],
    )
    with pytest.raises(ValuationError):
        sensitivity_grid(
            bridge,
            wacc_values=[],
            growth_values=[0.03],
            discounting_convention="mid_year",
            total_debt=0.0,
            cash_and_equivalents=0.0,
            minority_interest=0.0,
            preferred_equity=0.0,
            associate_investments=0.0,
            diluted_shares=100.0,
        )
    with pytest.raises(ValuationError):
        sensitivity_grid(
            bridge,
            wacc_values=[0.09],
            growth_values=[0.03],
            discounting_convention="mid_year",
            total_debt=0.0,
            cash_and_equivalents=0.0,
            minority_interest=0.0,
            preferred_equity=0.0,
            associate_investments=0.0,
            diluted_shares=0.0,  # not positive
        )


# ---------------------------------------------------------------------------
# 6. Net-debt bridge: one sign-direction test per line item
# ---------------------------------------------------------------------------


def _bridge(**overrides) -> NetDebtBridgeResult:
    base = dict(
        enterprise_value=1000.0,
        total_debt=0.0,
        cash_and_equivalents=0.0,
        minority_interest=0.0,
        preferred_equity=0.0,
        associate_investments=0.0,
        diluted_shares=100.0,
    )
    base.update(overrides)
    return equity_bridge(**base)


def test_total_debt_reduces_equity_value():
    baseline = _bridge()
    with_debt = _bridge(total_debt=120.0)
    assert with_debt.equity_value == pytest.approx(baseline.equity_value - 120.0, abs=1e-9)


def test_cash_and_equivalents_increases_equity_value():
    baseline = _bridge()
    with_cash = _bridge(cash_and_equivalents=80.0)
    assert with_cash.equity_value == pytest.approx(baseline.equity_value + 80.0, abs=1e-9)


def test_minority_interest_reduces_equity_value():
    baseline = _bridge()
    with_minority = _bridge(minority_interest=40.0)
    assert with_minority.equity_value == pytest.approx(baseline.equity_value - 40.0, abs=1e-9)


def test_preferred_equity_reduces_equity_value():
    baseline = _bridge()
    with_preferred = _bridge(preferred_equity=25.0)
    assert with_preferred.equity_value == pytest.approx(baseline.equity_value - 25.0, abs=1e-9)


def test_associate_investments_increases_equity_value():
    baseline = _bridge()
    with_associates = _bridge(associate_investments=15.0)
    assert with_associates.equity_value == pytest.approx(
        baseline.equity_value + 15.0, abs=1e-9
    )


def test_equity_bridge_refuses_negative_magnitudes():
    for field in (
        "total_debt",
        "cash_and_equivalents",
        "minority_interest",
        "preferred_equity",
        "associate_investments",
    ):
        with pytest.raises(ValuationError):
            _bridge(**{field: -1.0})


def test_equity_bridge_requires_positive_diluted_shares():
    with pytest.raises(ValuationError):
        _bridge(diluted_shares=0.0)
    with pytest.raises(ValuationError):
        _bridge(diluted_shares=-50.0)


# ---------------------------------------------------------------------------
# 7. WACC guards
# ---------------------------------------------------------------------------


def test_wacc_current_basis_zero_market_value_raises():
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06,
            tax_rate=0.25,
            capital_structure_basis="current",
            market_value_of_equity=0.0,
            market_value_of_debt=0.0,
        )


def test_wacc_target_weights_must_sum_to_one():
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06,
            tax_rate=0.25,
            capital_structure_basis="target",
            target_equity_weight=0.7,
            target_debt_weight=0.4,  # sums to 1.1
        )


def test_wacc_target_weights_must_be_nonnegative():
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06,
            tax_rate=0.25,
            capital_structure_basis="target",
            target_equity_weight=1.1,
            target_debt_weight=-0.1,
        )


def test_wacc_rejects_unknown_capital_structure_basis():
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06,
            tax_rate=0.25,
            capital_structure_basis="hybrid",
        )


def test_wacc_rejects_tax_rate_outside_unit_interval():
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04,
            beta=1.2,
            equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06,
            tax_rate=1.25,
            capital_structure_basis="target",
            target_equity_weight=0.7,
            target_debt_weight=0.3,
        )


def test_wacc_optional_premiums_default_to_zero_when_absent():
    result = wacc(
        risk_free_rate=0.04,
        beta=1.2,
        equity_risk_premium=0.05,
        pretax_cost_of_debt=0.06,
        tax_rate=0.25,
        capital_structure_basis="target",
        target_equity_weight=0.7,
        target_debt_weight=0.3,
    )
    assert result.size_premium == 0.0
    assert result.country_risk_premium == 0.0
    assert result.cost_of_equity == pytest.approx(0.04 + 1.2 * 0.05, abs=1e-9)


# ---------------------------------------------------------------------------
# 8. FCFF bridge: delta_nwc sign convention + shape guards
# ---------------------------------------------------------------------------


def test_delta_nwc_increase_is_a_cash_outflow():
    baseline = fcff_bridge(
        ebit=[100.0], tax_rate=0.25, depreciation_amortization=[20.0], capex=[30.0],
        delta_nwc=[0.0],
    )[0]
    nwc_increase = fcff_bridge(
        ebit=[100.0], tax_rate=0.25, depreciation_amortization=[20.0], capex=[30.0],
        delta_nwc=[5.0],
    )[0]
    nwc_release = fcff_bridge(
        ebit=[100.0], tax_rate=0.25, depreciation_amortization=[20.0], capex=[30.0],
        delta_nwc=[-5.0],
    )[0]
    assert nwc_increase.fcff == pytest.approx(baseline.fcff - 5.0, abs=1e-9)
    assert nwc_release.fcff == pytest.approx(baseline.fcff + 5.0, abs=1e-9)


def test_fcff_bridge_rejects_empty_forecast():
    with pytest.raises(ValuationError):
        fcff_bridge(
            ebit=[], tax_rate=0.25, depreciation_amortization=[], capex=[], delta_nwc=[]
        )


def test_fcff_bridge_rejects_mismatched_lengths():
    with pytest.raises(ValuationError):
        fcff_bridge(
            ebit=[100.0, 105.0],
            tax_rate=0.25,
            depreciation_amortization=[20.0],  # wrong length
            capex=[30.0, 28.0],
            delta_nwc=[5.0, 4.0],
        )


def test_fcff_bridge_rejects_tax_rate_outside_unit_interval():
    with pytest.raises(ValuationError):
        fcff_bridge(
            ebit=[100.0], tax_rate=-0.1, depreciation_amortization=[20.0], capex=[30.0],
            delta_nwc=[5.0],
        )


# ---------------------------------------------------------------------------
# 9. run_dcf: methodology switches are required and validated
# ---------------------------------------------------------------------------


def test_run_dcf_rejects_unknown_capital_structure_basis():
    with pytest.raises(ValuationError):
        run_dcf(
            base_inputs(),
            capital_structure_basis="hybrid",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )


def test_run_dcf_rejects_unknown_discounting_convention():
    with pytest.raises(ValuationError):
        run_dcf(
            base_inputs(),
            capital_structure_basis="target",
            discounting_convention="quarterly",
            terminal_value_method="perpetuity_growth",
        )


def test_run_dcf_rejects_unknown_terminal_value_method():
    with pytest.raises(ValuationError):
        run_dcf(
            base_inputs(),
            capital_structure_basis="target",
            discounting_convention="mid_year",
            terminal_value_method="dividend_discount",
        )


def test_run_dcf_requires_explicit_methodology_arguments():
    """capital_structure_basis, discounting_convention and terminal_value_method
    have no defaults -- omitting any of them is a TypeError, not a silently
    chosen convention."""
    with pytest.raises(TypeError):
        run_dcf(
            base_inputs(),
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )
    with pytest.raises(TypeError):
        run_dcf(
            base_inputs(),
            capital_structure_basis="target",
            terminal_value_method="perpetuity_growth",
        )
    with pytest.raises(TypeError):
        run_dcf(
            base_inputs(),
            capital_structure_basis="target",
            discounting_convention="mid_year",
        )


# ---------------------------------------------------------------------------
# 10. Dataclass repr sanity (result shape stays visible, not collapsed)
# ---------------------------------------------------------------------------


def test_dcf_result_exposes_every_intermediate_object():
    result = run_dcf(
        base_inputs(),
        capital_structure_basis="target",
        discounting_convention="mid_year",
        terminal_value_method="perpetuity_growth",
    )
    assert isinstance(result.wacc_build, WACCResult)
    assert all(isinstance(year, FCFFYear) for year in result.fcff_bridge)
    assert all(isinstance(entry, DiscountedCashFlow) for entry in result.discounted_fcff)
    assert isinstance(result.terminal_value, TerminalValueResult)
    assert isinstance(result.net_debt_bridge, NetDebtBridgeResult)
    assert len(result.fcff_bridge) == 3
    assert len(result.discounted_fcff) == 3


# ---------------------------------------------------------------------------
# 11. Non-finite inputs are refused, never silently propagated
# ---------------------------------------------------------------------------


def test_wacc_refuses_non_finite_rates():
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=math.inf, beta=1.2, equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06, tax_rate=0.25, capital_structure_basis="target",
            target_equity_weight=0.7, target_debt_weight=0.3,
        )
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04, beta=math.nan, equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06, tax_rate=0.25, capital_structure_basis="target",
            target_equity_weight=0.7, target_debt_weight=0.3,
        )
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04, beta=1.2, equity_risk_premium=math.inf,
            pretax_cost_of_debt=0.06, tax_rate=0.25, capital_structure_basis="target",
            target_equity_weight=0.7, target_debt_weight=0.3,
        )
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04, beta=1.2, equity_risk_premium=0.05,
            pretax_cost_of_debt=math.nan, tax_rate=0.25, capital_structure_basis="target",
            target_equity_weight=0.7, target_debt_weight=0.3,
        )


def test_wacc_accepts_negative_but_finite_rates():
    """A negative beta or a negative risk-free rate is legitimate; the guard
    must refuse only non-finite values, not flip the sign semantics."""
    result = wacc(
        risk_free_rate=-0.01, beta=-0.5, equity_risk_premium=0.05,
        pretax_cost_of_debt=0.06, tax_rate=0.25, capital_structure_basis="target",
        target_equity_weight=0.7, target_debt_weight=0.3,
    )
    assert math.isfinite(result.wacc)


def test_wacc_refuses_non_finite_structure_inputs():
    # current basis: non-finite market values
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04, beta=1.2, equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06, tax_rate=0.25, capital_structure_basis="current",
            market_value_of_equity=math.nan, market_value_of_debt=300.0,
        )
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04, beta=1.2, equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06, tax_rate=0.25, capital_structure_basis="current",
            market_value_of_equity=700.0, market_value_of_debt=math.inf,
        )
    # target basis: non-finite weights
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04, beta=1.2, equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06, tax_rate=0.25, capital_structure_basis="target",
            target_equity_weight=math.nan, target_debt_weight=0.3,
        )
    with pytest.raises(ValuationError):
        wacc(
            risk_free_rate=0.04, beta=1.2, equity_risk_premium=0.05,
            pretax_cost_of_debt=0.06, tax_rate=0.25, capital_structure_basis="target",
            target_equity_weight=0.7, target_debt_weight=math.inf,
        )


def test_fcff_bridge_refuses_non_finite_forecast_entries():
    with pytest.raises(ValuationError):
        fcff_bridge(
            ebit=[100.0, math.inf], tax_rate=0.25,
            depreciation_amortization=[20.0, 21.0], capex=[30.0, 28.0],
            delta_nwc=[5.0, 4.0],
        )
    with pytest.raises(ValuationError):
        fcff_bridge(
            ebit=[100.0, 105.0], tax_rate=0.25,
            depreciation_amortization=[20.0, math.nan], capex=[30.0, 28.0],
            delta_nwc=[5.0, 4.0],
        )


def test_terminal_value_refuses_non_finite_inputs():
    with pytest.raises(ValuationError):
        terminal_value(
            final_year_fcff=math.nan, terminal_year_ebitda=132.0, wacc_rate=0.0905,
            terminal_growth=Assumption("terminal_growth", 0.03, "b"),
            exit_multiple=Assumption("exit_multiple", 8.0, "b"),
        )
    with pytest.raises(ValuationError):
        terminal_value(
            final_year_fcff=75.5, terminal_year_ebitda=math.inf, wacc_rate=0.0905,
            terminal_growth=Assumption("terminal_growth", 0.03, "b"),
            exit_multiple=Assumption("exit_multiple", 8.0, "b"),
        )
    with pytest.raises(ValuationError):
        terminal_value(
            final_year_fcff=75.5, terminal_year_ebitda=132.0, wacc_rate=math.inf,
            terminal_growth=Assumption("terminal_growth", 0.03, "b"),
            exit_multiple=Assumption("exit_multiple", 8.0, "b"),
        )
    with pytest.raises(ValuationError):
        terminal_value(
            final_year_fcff=75.5, terminal_year_ebitda=132.0, wacc_rate=0.0905,
            terminal_growth=Assumption("terminal_growth", math.nan, "b"),
            exit_multiple=Assumption("exit_multiple", 8.0, "b"),
        )
    with pytest.raises(ValuationError):
        terminal_value(
            final_year_fcff=75.5, terminal_year_ebitda=132.0, wacc_rate=0.0905,
            terminal_growth=Assumption("terminal_growth", 0.03, "b"),
            exit_multiple=Assumption("exit_multiple", math.inf, "b"),
        )


def test_equity_bridge_refuses_non_finite_enterprise_value():
    with pytest.raises(ValuationError):
        equity_bridge(
            enterprise_value=math.inf, total_debt=200.0, cash_and_equivalents=50.0,
            minority_interest=10.0, preferred_equity=15.0, associate_investments=5.0,
            diluted_shares=100.0,
        )


def test_discount_fcff_refuses_non_finite_wacc_rate():
    bridge = fcff_bridge(
        ebit=[100.0], tax_rate=0.25, depreciation_amortization=[20.0], capex=[30.0],
        delta_nwc=[5.0],
    )
    with pytest.raises(ValuationError):
        discount_fcff(bridge, wacc_rate=math.nan, discounting_convention="mid_year")


def test_sensitivity_grid_refuses_non_finite_axis_values():
    bridge = fcff_bridge(
        ebit=[100.0], tax_rate=0.25, depreciation_amortization=[20.0], capex=[30.0],
        delta_nwc=[5.0],
    )
    common = dict(
        total_debt=200.0, cash_and_equivalents=50.0, minority_interest=10.0,
        preferred_equity=15.0, associate_investments=5.0, diluted_shares=100.0,
    )
    with pytest.raises(ValuationError):
        sensitivity_grid(
            bridge, wacc_values=[0.09, math.nan], growth_values=[0.02, 0.03],
            discounting_convention="mid_year", **common,
        )
    with pytest.raises(ValuationError):
        sensitivity_grid(
            bridge, wacc_values=[0.09, 0.10], growth_values=[0.02, math.inf],
            discounting_convention="mid_year", **common,
        )


def test_run_dcf_never_returns_a_silently_wrong_share_price():
    """A non-finite WACC or FCFF input must raise, not produce a negative or
    non-finite per-share value an agent would take as a real valuation."""
    for field, bad in (("beta", math.inf), ("risk_free_rate", math.nan)):
        inputs = base_inputs()
        inputs[field] = bad
        with pytest.raises(ValuationError):
            run_dcf(
                inputs,
                capital_structure_basis="target",
                discounting_convention="mid_year",
                terminal_value_method="perpetuity_growth",
            )

    inputs = base_inputs()
    inputs["ebit"] = [100.0, math.inf, 110.0]
    with pytest.raises(ValuationError):
        run_dcf(
            inputs,
            capital_structure_basis="target",
            discounting_convention="mid_year",
            terminal_value_method="perpetuity_growth",
        )
