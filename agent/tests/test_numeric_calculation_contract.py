"""Numeric interpretation inputs are computed by tools, never by a prose gate."""

import asyncio
import json
import math

import pytest
from fastmcp import Client
from scipy.stats import genpareto

from src.agent.result_artifacts import deliver_tool_result
from src.agent.tools import ToolRegistry
from src.quantlib.risk import fit_gpd_tail
from src.quantlib.units import compare_rates
from src.tools.options_payoff_tool import OptionsPayoffTool
from src.tools.quantlib_tool import QuantlibCallTool


@pytest.mark.parametrize(
    "unit,left,right", [("decimal", 0.0434, 0.042737), ("percent", 4.34, 4.2737), ("bp", 434, 427.37)]
)
def test_rate_comparison_preserves_units_and_sign(unit, left, right):
    result = compare_rates(left, right, unit)
    assert result["difference_bps"] == pytest.approx(6.63)
    assert result["difference_percentage_points"] == pytest.approx(0.0663)
    assert compare_rates(right, left, unit)["difference_bps"] == pytest.approx(-6.63)
    assert compare_rates(left, left, unit)["difference_bps"] == 0


@pytest.mark.parametrize(
    "left,right,unit",
    [(True, 0, "decimal"), (math.inf, 0, "decimal"), (0, math.nan, "decimal"), (1, 0, "guessed"), ("4%", 0, "percent")],
)
def test_rate_comparison_does_not_guess_units_or_accept_non_numbers(left, right, unit):
    with pytest.raises(ValueError):
        compare_rates(left, right, unit)


def test_gpd_reports_scale_and_both_means_separately():
    returns = -genpareto.rvs(0.3, scale=0.02, size=2000, random_state=32)
    result = fit_gpd_tail(returns)
    tail = result["threshold"] - returns[returns < result["threshold"]]
    assert result["n_observations"] == len(returns)
    assert result["sample_mean_excess"] == pytest.approx(tail.mean())
    assert result["fitted_mean_excess"] == pytest.approx(
        genpareto.mean(result["shape_xi"], scale=result["scale_sigma"])
    )
    assert not math.isclose(result["scale_sigma"], result["sample_mean_excess"], rel_tol=0.01)


def test_infinite_fitted_mean_is_explicit_over_tool_transport(monkeypatch):
    monkeypatch.setattr("src.quantlib.risk.genpareto.fit", lambda *a, **kw: (1.2, 0, 0.02))
    result = json.loads(
        QuantlibCallTool().execute(
            action="call", module="risk", function="fit_gpd_tail", kwargs={"returns": list(range(-100, 1))}
        )
    )
    assert result["ok"]
    assert result["result"]["fitted_mean_excess"] == "Infinity"
    assert math.isfinite(result["result"]["sample_mean_excess"])


def collar(**kwargs):
    return dict(
        legs=[
            {"option_type": "put", "strike": 150, "qty": 1, "premium": 7.3},
            {"option_type": "call", "strike": 200, "qty": -1, "premium": 4.3},
        ],
        entry_spot=166.19,
        underlying_qty=1,
        multiplier=100,
        expiry_days=63,
        commission_rate=0.001,
        **kwargs,
    )


@pytest.mark.parametrize("entry,fee", [(166.19, 0.001), (173.73, 0.003)])
def test_exact_scenarios_reuse_payoff_and_do_not_depend_on_chart(entry, fee, tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    args = collar(expiry_spot_values=[180, 0, 160, 180, 1000], spot_min=165, spot_max=170)
    args.update(entry_spot=entry, commission_rate=fee)
    raw = OptionsPayoffTool().execute(**args)
    result = json.loads(raw)
    assert result["status"] == "ok"
    assert len(result["expiry_curve"]["spot"]) == 121
    assert len(result["scenario_grid"]["pnl"][0]) == 121
    for row in result["expiry_scenarios"]:
        spot = row["spot"]
        pnl = (spot - entry + max(150 - spot, 0) - max(spot - 200, 0) - 3 - 11.6 * fee) * 100
        assert row["pnl"] == pytest.approx(pnl)
        assert row["return_fraction"] == pytest.approx(pnl / (entry * 100))
        assert row["return_percent"] == pytest.approx(pnl / entry)
    from src.tools.read_file_tool import ReadFileTool

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    delivered = json.loads(deliver_tool_result(raw, tmp_path, registry))
    assert delivered["expiry_scenarios"] == result["expiry_scenarios"]
    assert delivered["calculation_basis"]["entry_spot"] == entry


def test_options_only_scenarios_do_not_invent_a_return_denominator():
    args = collar(expiry_spot_values=[160, 180])
    args["underlying_qty"] = 0
    result = json.loads(OptionsPayoffTool().execute(**args))
    assert all(r["return_fraction"] is None and r["return_percent"] is None for r in result["expiry_scenarios"])


@pytest.mark.parametrize("spots", [[], [True], [-1], [math.nan], [math.inf], "160,180", list(range(502))])
def test_invalid_expiry_prices_are_input_errors(spots):
    assert json.loads(OptionsPayoffTool().execute(**collar(expiry_spot_values=spots)))["status"] == "error"


def test_mcp_real_tool_supports_exact_prices_and_rate_comparison(monkeypatch, tmp_path):
    import mcp_server

    registry = ToolRegistry()
    registry.register(OptionsPayoffTool())
    registry.register(QuantlibCallTool())
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: registry)

    async def run():
        async with Client(mcp_server.mcp) as client:
            result = await client.call_tool("analyze_options_payoff", {**collar(), "expiry_spot_values": "[160,180]"})
            data = json.loads(result.content[0].text)
            assert data["expiry_scenarios"][0]["return_percent"] == pytest.approx(-5.536795234370298)
            result = await client.call_tool(
                "quantlib_call",
                {
                    "action": "call",
                    "module": "units",
                    "function": "compare_rates",
                    "kwargs": {"left": 0.0434, "right": 0.042737, "left_label": "B", "right_label": "A"},
                    "run_dir": str(tmp_path),
                },
            )
            comparison = json.loads(result.content[0].text)["result"]
            assert comparison["difference_bps"] == pytest.approx(6.63)
            assert (comparison["left_label"], comparison["relation"], comparison["right_label"]) == ("B", "higher", "A")

    asyncio.run(run())


@pytest.mark.parametrize(
    "left,right,relation,delta",
    [(0.21, 0.18, "higher", 3), (0.18, 0.21, "lower", -3), (-0.09, -0.12, "higher", 3), (0.18, 0.18, "equal", 0)],
)
def test_named_comparison_reports_numeric_direction(left, right, relation, delta):
    result = compare_rates(left, right, left_label="B", right_label="A")
    assert (result["left_label"], result["right_label"]) == ("B", "A")
    assert result["relation"] == relation
    assert result["difference_percentage_points"] == pytest.approx(delta)


def test_saved_payoffs_flow_into_named_comparison_without_transcribing(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    from src.tools.read_file_tool import ReadFileTool

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    args_a = collar()
    args_b = collar()
    args_b["legs"] = [
        {"option_type": "put", "strike": 160, "qty": 1, "premium": 11.6},
        {"option_type": "call", "strike": 210, "qty": -1, "premium": 2.98},
    ]
    receipts = [
        json.loads(deliver_tool_result(OptionsPayoffTool().execute(**a), tmp_path, registry)) for a in (args_a, args_b)
    ]

    def operand(receipt):
        source = receipt["_result_file"]
        return {
            "__data_ref__": {
                "path": source["path"],
                "sha256": source["sha256"],
                "pointer": "/calculation_basis/max_profit_return",
            }
        }

    kwargs = {
        "left": operand(receipts[1]),
        "right": operand(receipts[0]),
        "left_label": "B",
        "right_label": "A",
        "input_unit": "decimal",
    }
    result = json.loads(
        QuantlibCallTool().execute(
            action="call", module="units", function="compare_rates", kwargs=kwargs, run_dir=str(tmp_path)
        )
    )
    assert result["ok"]
    assert result["result"]["relation"] == "higher"
    assert result["result"]["difference_percentage_points"] == pytest.approx(2.633744509296587)
    assert [s["sha256"] for s in result["input_sources"]] == [
        receipts[1]["_result_file"]["sha256"],
        receipts[0]["_result_file"]["sha256"],
    ]
    kwargs["left"], kwargs["right"] = kwargs["right"], kwargs["left"]
    kwargs["left_label"], kwargs["right_label"] = "A", "B"
    reverse = json.loads(
        QuantlibCallTool().execute(
            action="call", module="units", function="compare_rates", kwargs=kwargs, run_dir=str(tmp_path)
        )
    )
    assert reverse["result"]["relation"] == "lower"
    assert reverse["result"]["difference_percentage_points"] == pytest.approx(-2.633744509296587)
