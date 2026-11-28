"""Tests for the quantlib_call tool.

The load-bearing tests are the three structural limits. A tool that can reach
arbitrary modules, private helpers, or file writers would be a shell by another
name, which is precisely what this tool exists to avoid.
"""

from __future__ import annotations

from src.tools.path_utils import FileRoots


from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import json

import pytest

from src.tools import build_registry
from src.tools.quantlib_tool import ALLOWED_MODULES, QuantlibCallTool


@pytest.fixture
def tool():
    return QuantlibCallTool(roots=FileRoots.from_config(get_env_config().api))


def call(tool, **kwargs):
    return json.loads(tool.execute(**kwargs))


# --- structural limits: this must not be a shell ---


def test_a_module_outside_the_allowlist_is_unreachable(tool):
    for module in ("os", "subprocess", "builtins", "src.agent.runtime", "sys"):
        result = call(tool, action="call", module=module, function="system", kwargs={})
        assert result["ok"] is False
        assert "unknown module" in result["error"]


def test_the_module_string_never_reaches_importlib(tool):
    # A dotted path that WOULD import if passed through is still refused,
    # because resolution is a dict lookup and not an import.
    result = call(tool, action="call", module="src.quantlib.risk", function="historical_var", kwargs={})
    assert result["ok"] is False
    assert "unknown module" in result["error"]


def test_private_helpers_are_not_callable(tool):
    for name in ("_clean_returns", "_validate_confidence", "_tail_index"):
        result = call(tool, action="call", module="risk", function=name, kwargs={})
        assert result["ok"] is False
        assert "not a public function" in result["error"]


def test_dunders_are_not_callable(tool):
    for name in ("__builtins__", "__loader__", "__class__"):
        result = call(tool, action="call", module="risk", function=name, kwargs={})
        assert result["ok"] is False


def test_file_writing_exporters_are_refused_with_a_reason(tool):
    result = call(tool, action="call", module="valuation.artifact",
                  function="export_dcf_workbook", kwargs={})
    assert result["ok"] is False
    assert "writes to a path" in result["error"]


def test_exporters_are_absent_from_the_listing_too(tool):
    listed = call(tool, action="list", module="valuation.artifact")
    names = {f["name"] for f in listed["functions"]}
    assert not any(n.startswith("export_") for n in names)


def test_every_allowlisted_module_actually_imports(tool):
    for short in ALLOWED_MODULES:
        result = call(tool, action="list", module=short)
        assert result["ok"] is True, f"{short} failed to list: {result}"


def test_every_allowlisted_module_exposes_at_least_one_function(tool):
    """An allowlisted module that lists nothing is unreachable, not merely empty.

    Importing cleanly is not the same as being callable: dispatch is
    ``__all__``-only, so a module without ``__all__`` lists zero functions while
    still passing the import check above. `attribution` and `impact` shipped
    that way — allowlisted, documented in the package docstring, and reachable
    from nowhere. Asserting `ok is True` could never catch it; asserting the
    listing is non-empty does.
    """
    empty = [
        short
        for short in ALLOWED_MODULES
        if not call(tool, action="list", module=short)["functions"]
    ]
    assert not empty, (
        f"allowlisted but exposing no callables: {empty}. Add `__all__` to the "
        f"module, or drop it from ALLOWED_MODULES — advertising a module the "
        f"tool cannot dispatch to is worse than not listing it."
    )


# --- discovery ---


def test_list_without_a_module_returns_the_module_set(tool):
    result = call(tool, action="list")
    assert result["ok"] is True
    assert set(result["modules"]) == set(ALLOWED_MODULES)


def test_list_a_module_returns_functions_with_summaries(tool):
    result = call(tool, action="list", module="risk")
    names = {f["name"] for f in result["functions"]}
    assert {"historical_var", "historical_cvar", "max_drawdown_analysis"} <= names
    assert all(isinstance(f["summary"], str) for f in result["functions"])


def test_describe_returns_a_signature_and_docstring(tool):
    result = call(tool, action="describe", module="options", function="bs_price")
    assert result["ok"] is True
    assert "S" in result["signature"] and "sigma" in result["signature"]
    assert "Black-Scholes" in result["doc"]


def test_describe_and_call_require_both_module_and_function(tool):
    for action in ("describe", "call"):
        assert call(tool, action=action, module="risk")["ok"] is False
        assert call(tool, action=action, function="historical_var")["ok"] is False


def test_unknown_action_rejected(tool):
    assert call(tool, action="exec")["ok"] is False


# --- computation matches the library ---


def test_bs_price_matches_the_textbook_value(tool):
    result = call(tool, action="call", module="options", function="bs_price",
                  kwargs={"S": 100, "K": 100, "T": 1.0, "r": 0.05, "sigma": 0.2,
                          "option_type": "call"})
    assert result["result"] == pytest.approx(10.4506, abs=1e-4)


def test_result_matches_a_direct_import(tool):
    from src.quantlib.risk import historical_var

    returns = [0.01, -0.02, -0.05, 0.03, -0.01, 0.02, -0.03, 0.04, -0.06, 0.01]
    through_tool = call(tool, action="call", module="risk", function="historical_var",
                        kwargs={"returns": returns, "confidence": 0.9})["result"]
    assert through_tool == pytest.approx(historical_var(returns, confidence=0.9))


def test_a_dataclass_result_serializes_field_by_field(tool):
    result = call(tool, action="call", module="var_backtest", function="kupiec_pof",
                  kwargs={"violations": 10, "observations": 1000, "confidence": 0.99})
    assert result["ok"] is True
    assert result["result"]["violations"] == 10
    assert result["result"]["p_value"] == pytest.approx(1.0)
    assert result["result"]["rejected"] is False


# --- pandas envelopes ---


def test_a_series_envelope_reaches_the_function_with_its_index(tool):
    # compute_half_life lazy-imports statsmodels; without the 'stats' extra the
    # envelope would be judged on an ImportError, not on decoding. The series
    # envelope stays covered on a base install via the dataframe test below,
    # whose `holdings` argument is also a `__series__` envelope.
    pytest.importorskip("statsmodels", reason="the optional 'statsmodels' package is not installed")
    result = call(
        tool, action="call", module="timeseries", function="compute_half_life",
        kwargs={"spread": {"__series__": {
            "index": list(range(200)),
            "values": [((-1) ** i) * (0.9 ** i) for i in range(200)],
        }}},
    )
    assert result["ok"] is True
    assert isinstance(result["result"], (int, float))


def test_a_dataframe_envelope_is_decoded(tool):
    result = call(
        tool, action="call", module="factormodel", function="portfolio_style_exposure",
        kwargs={
            "holdings": {"__series__": {"index": ["A", "B"], "values": [0.5, 0.5]}},
            "exposures": {"__dataframe__": {
                "index": ["A", "B"], "columns": ["value"], "data": [[1.0], [-1.0]]}},
        },
    )
    assert result["ok"] is True
    assert result["result"]["__series__"]["values"][0] == pytest.approx(0.0)


def test_a_plain_list_stays_a_list(tool):
    # Most functions take a sequence; coercing every list into a Series would
    # break the ones that do not.
    result = call(tool, action="call", module="risk", function="historical_cvar",
                  kwargs={"returns": [0.01, -0.02, -0.05, 0.03, -0.01,
                                      0.02, -0.03, 0.04, -0.06, 0.01]})
    assert result["ok"] is True


def test_a_malformed_envelope_is_reported_not_crashed(tool):
    result = call(tool, action="call", module="risk", function="historical_var",
                  kwargs={"returns": {"__series__": {"index": [1, 2]}}})
    assert result["ok"] is False
    assert "envelope" in result["error"]


# --- error surfaces are informative, never raised ---


def test_a_wrong_argument_returns_the_signature_to_fix_it_with(tool):
    result = call(tool, action="call", module="options", function="bs_price",
                  kwargs={"S": 100})
    assert result["ok"] is False
    assert "signature" in result


def test_a_domain_refusal_is_surfaced_verbatim(tool):
    # The library refuses a confidence outside (0,1); that refusal is the
    # answer, and must reach the caller instead of becoming a crash.
    result = call(tool, action="call", module="risk", function="historical_var",
                  kwargs={"returns": [0.01, -0.02, 0.03], "confidence": 1.5})
    assert result["ok"] is False
    assert "confidence" in result["error"]


def test_kwargs_must_be_an_object(tool):
    result = call(tool, action="call", module="risk", function="historical_var", kwargs=[1, 2])
    assert result["ok"] is False


def test_execute_never_raises_whatever_it_is_given(tool):
    for bad in (
        {"action": "call", "module": None, "function": None},
        {"action": None},
        {"action": "call", "module": "risk", "function": "historical_var", "kwargs": None},
    ):
        assert json.loads(tool.execute(**bad))["ok"] in (True, False)


# --- serialization conventions ---


def test_non_finite_floats_are_explicit_strings_not_null(tool):
    # A NaN arriving as JSON null reads as "absent", which is a different claim.
    result = call(tool, action="call", module="options", function="implied_volatility",
                  kwargs={"market_price": 1e-9, "S": 100, "K": 200, "T": 0.01,
                          "r": 0.05, "option_type": "call"})
    if result["ok"]:
        assert result["result"] in ("NaN", "Infinity", "-Infinity") or isinstance(
            result["result"], (int, float)
        )


def test_registry_exposes_the_tool_without_shell_tools_enabled():
    # The whole point: reachable on a registry built the way the API and MCP
    # transports build it, with shell tools off.
    registry = build_registry(policy=ToolPolicy.from_config(get_env_config()), include_shell_tools=False)
    assert "quantlib_call" in registry.tool_names
    assert "bash" not in registry.tool_names


def test_the_tool_is_read_only(tool):
    assert tool.is_readonly is True


def _dcf_inputs() -> dict:
    """The worked example of tests/quantlib/valuation/test_dcf.py, as JSON."""
    return {
        "risk_free_rate": 0.04, "beta": 1.2, "equity_risk_premium": 0.05, "size_premium": 0.01,
        "country_risk_premium": 0.0, "pretax_cost_of_debt": 0.06, "tax_rate": 0.25,
        "ebit": [100.0, 105.0, 110.0], "depreciation_amortization": [20.0, 21.0, 22.0],
        "capex": [30.0, 28.0, 26.0], "delta_nwc": [5.0, 4.0, 3.0],
        "terminal_growth": {"__assumption__": {"name": "terminal_growth", "value": 0.03,
                                               "basis": "Long-run nominal GDP proxy"}},
        "exit_multiple": {"__assumption__": {"name": "exit_multiple", "value": 8.0,
                                             "basis": "Median EV/EBITDA of the peer set"}},
        "total_debt": 200.0, "cash_and_equivalents": 50.0, "minority_interest": 10.0,
        "preferred_equity": 15.0, "associate_investments": 5.0, "diluted_shares": 100.0,
        "target_equity_weight": 0.7, "target_debt_weight": 0.3,
    }


def test_a_dcf_runs_through_the_tool_with_assumption_envelopes(tool):
    result = call(tool, action="call", module="valuation.dcf", function="run_dcf", kwargs={
        "inputs": _dcf_inputs(), "capital_structure_basis": "target",
        "discounting_convention": "mid_year", "terminal_value_method": "perpetuity_growth",
    })
    assert result["ok"] is True, result
    assert result["result"]["value_per_share"] == pytest.approx(10.428050212786289, abs=1e-9)


def test_an_assumption_without_its_basis_is_refused(tool):
    inputs = _dcf_inputs()
    del inputs["terminal_growth"]["__assumption__"]["basis"]
    result = call(tool, action="call", module="valuation.dcf", function="run_dcf", kwargs={
        "inputs": inputs, "capital_structure_basis": "target",
        "discounting_convention": "mid_year", "terminal_value_method": "perpetuity_growth",
    })
    assert result["ok"] is False and "basis" in json.dumps(result), result
