"""Multi-strategy requests compute comparisons without a second tool call."""

import asyncio
import json

import pytest
from fastmcp import Client

from src.agent.result_artifacts import deliver_tool_result
from src.agent.tools import ToolRegistry
from src.tools.options_payoff_tool import OptionsPayoffTool
from src.tools.read_file_tool import ReadFileTool

A = [dict(option_type="put", strike=150, qty=1, premium=7.3), dict(option_type="call", strike=200, qty=-1, premium=4.3)]
B = [
    dict(option_type="put", strike=160, qty=1, premium=11.6),
    dict(option_type="call", strike=210, qty=-1, premium=2.98),
]


def request(**overrides):
    return dict(
        legs=A,
        label="A",
        alternatives=[{"label": "B", "legs": B}],
        entry_spot=166.19,
        expiry_days=63,
        underlying_qty=1,
        multiplier=100,
        commission_rate=0.001,
        **overrides,
    )


@pytest.mark.parametrize("entry,fee", [(166.19, 0.001), (173.73, 0.003)])
def test_joint_results_match_independent_cap_floor_cost_arithmetic(entry, fee):
    params = request()
    params.update(entry_spot=entry, commission_rate=fee)
    output = json.loads(OptionsPayoffTool().execute(**params))
    assert output["status"] == "ok"
    a_cost = 3 + 11.6 * fee
    b_cost = 8.62 + 14.58 * fee
    expected = {
        "max_profit_return": ((210 - entry - b_cost) / entry, (200 - entry - a_cost) / entry),
        "max_loss_return": ((160 - entry - b_cost) / entry, (150 - entry - a_cost) / entry),
        "entry_cost_return": (b_cost / entry, a_cost / entry),
    }
    comparison = output["comparisons"][0]
    assert (comparison["left_label"], comparison["right_label"]) == ("B", "A")
    for metric, (b, a) in expected.items():
        row = comparison["metrics"][metric]
        assert row["left_decimal"] == pytest.approx(b)
        assert row["right_decimal"] == pytest.approx(a)
        assert row["difference_percentage_points"] == pytest.approx((b - a) * 100)
        assert row["relation"] == "higher"
    # Same financial implementation as separate calls, including full curves.
    for legs, observed in [(A, output), (B, output["alternatives"][0])]:
        single = json.loads(OptionsPayoffTool().execute(**{**params, "legs": legs, "alternatives": []}))
        for key in ("summary", "expiry_curve", "calculation_basis", "scenario_grid"):
            assert observed[key] == single[key]


def test_reordering_and_equal_strategies_do_not_change_label_meaning():
    params = request()
    params.update(legs=B, label="B", alternatives=[{"label": "A", "legs": A}, {"label": "same", "legs": B}])
    result = json.loads(OptionsPayoffTool().execute(**params))
    assert result["comparisons"][0]["metrics"]["max_profit_return"]["relation"] == "lower"
    assert result["comparisons"][0]["left_label"] == "A"
    assert all(v["relation"] == "equal" for v in result["comparisons"][1]["metrics"].values())


def test_bad_alternative_preserves_good_calculations():
    params = request()
    params["alternatives"].append({"label": "bad", "legs": [dict(option_type="call", strike=200, qty=0)]})
    result = json.loads(OptionsPayoffTool().execute(**params))
    assert result["status"] == "ok"
    assert result["alternatives"][0]["status"] == "ok"
    assert result["alternatives"][1]["status"] == "error"
    assert result["comparisons"][1]["status"] == "unavailable"
    assert result["comparisons"][1]["reason"]


def test_no_stock_denominator_and_unbounded_values_are_not_zero():
    params = request()
    params["underlying_qty"] = 0
    output = json.loads(OptionsPayoffTool().execute(**params))
    assert output["comparisons"][0]["status"] == "unavailable"
    params = request()
    params["alternatives"] = [{"label": "uncapped", "legs": [A[0]]}]
    output = json.loads(OptionsPayoffTool().execute(**params))
    assert output["comparisons"][0]["metrics"]["max_profit_return"]["status"] == "unavailable"
    assert output["comparisons"][0]["metrics"]["max_loss_return"]["relation"] == "lower"


@pytest.mark.parametrize(
    "alternatives",
    [
        False,
        "B",
        [{"label": "A", "legs": B}],
        [{"label": "B", "legs": B, "entry_spot": 200}],
        [{"label": "", "legs": B}],
        [{"label": str(i), "legs": B} for i in range(6)],
    ],
)
def test_invalid_or_ambiguous_requests_are_input_errors(alternatives):
    params = request()
    params["alternatives"] = alternatives
    assert json.loads(OptionsPayoffTool().execute(**params))["status"] == "error"


def test_all_five_comparisons_reach_the_model_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    params = request()
    params["alternatives"] = [{"label": f"candidate {i}", "legs": B} for i in range(5)]
    raw = OptionsPayoffTool().execute(**params)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    receipt = json.loads(deliver_tool_result(raw, tmp_path, registry))
    assert receipt["comparisons"] == json.loads(raw)["comparisons"]
    assert len(receipt["comparisons"]) == 5


def test_http_and_mcp_use_the_same_single_call_comparison(monkeypatch):
    import api_server
    import mcp_server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(api_server, "_API_KEY", "")
    monkeypatch.delenv("API_AUTH_KEY", raising=False)
    expected = json.loads(OptionsPayoffTool().execute(**request()))["comparisons"]
    client = TestClient(api_server.app, client=("127.0.0.1", 50000))
    result = client.post("/options/payoff", json=request())
    assert result.status_code == 200
    assert result.json()["comparisons"] == expected
    registry = ToolRegistry()
    registry.register(OptionsPayoffTool())
    monkeypatch.setattr(mcp_server, "_get_registry", lambda: registry)

    async def call():
        async with Client(mcp_server.mcp) as client:
            params = request()
            params["alternatives"] = json.dumps(params["alternatives"])
            output = await client.call_tool("analyze_options_payoff", params)
            assert json.loads(output.content[0].text)["comparisons"] == expected

    asyncio.run(call())
