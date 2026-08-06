"""Tests for the quantlib_call tool.

The load-bearing tests are the three structural limits. A tool that can reach
arbitrary modules, private helpers, or file writers would be a shell by another
name, which is precisely what this tool exists to avoid.
"""

from __future__ import annotations

import json

import pytest

from src.tools import build_registry
from src.tools.quantlib_tool import ALLOWED_MODULES, QuantlibCallTool


@pytest.fixture
def tool():
    return QuantlibCallTool()


def call(tool, **kwargs):
    return json.loads(tool.execute(**kwargs))


# --- structural limits: this must not be a shell ---


def test_a_module_outside_the_allowlist_is_unreachable(tool):
    for module in ("os", "subprocess", "builtins", "src.agent.loop", "sys"):
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
    registry = build_registry(include_shell_tools=False)
    assert "quantlib_call" in registry.tool_names
    assert "bash" not in registry.tool_names


def test_the_tool_is_read_only(tool):
    assert tool.is_readonly is True
