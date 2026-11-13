"""Observed files remain usable by shell-free computation and downstream roles."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.options_payoff import OptionLeg, expiry_payoff, scenario_grid
from src.agent.result_artifacts import persist_calculation_result
from src.quantlib.risk import fit_gpd_tail
from src.swarm.evidence_handoff import prepare_handoff
from src.swarm.models import SwarmTask
from src.swarm.task_store import TaskStore
from src.swarm.worker import agent_artifact_dir
from src.tools.data_refs import resolve_data_refs
from src.tools.options_payoff_tool import OptionsPayoffTool
from src.tools.quantlib_tool import QuantlibCallTool


@pytest.fixture(autouse=True)
def readable(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))


def reference(path, **kwargs):
    return {"__data_ref__": {"path": str(path), **kwargs}}


def test_full_market_file_to_real_gpd_and_missing_bar_returns(tmp_path):
    rng = np.random.default_rng(42)
    prices = 100 * np.cumprod(1 + rng.normal(0, .02, 600))
    rows = [{"trade_date": str(d.date()), "close": float(p)}
            for d, p in zip(pd.bdate_range("2024-01-01", periods=600), prices)]
    rows[50]["close"] = None
    response = json.loads(persist_calculation_result(json.dumps({"NVDA.US": rows}), tmp_path))
    path = response["_result_file"]["path"]
    result = json.loads(QuantlibCallTool().execute(
        action="call", module="risk", function="fit_gpd_tail", run_dir=str(tmp_path),
        kwargs={"returns": reference(path, pointer="/NVDA.US", column="close",
                                     index="trade_date", transform="pct_change")}))
    expected = fit_gpd_tail(pd.Series([r["close"] for r in rows]).pct_change(fill_method=None).dropna())
    assert result["result"] == expected
    assert result["input_sources"][0]["input_rows"] == 600
    assert result["input_sources"][0]["output_rows"] == 597
    assert result["input_sources"][0]["missing_returns"] == 2
    assert Path(result["_result_file"]["path"]).is_file()


@pytest.mark.parametrize("pointer", ["/X", "/X/data"])
def test_sampled_rows_are_not_reinterpreted_as_consecutive_prices(tmp_path, pointer):
    path = tmp_path / "sampled.json"
    path.write_text(json.dumps({"X": {"truncated": True, "data": [{"close": 10}, {"close": 11}]}}))
    with pytest.raises(ValueError, match="max_rows=0"):
        resolve_data_refs(reference(path, pointer=pointer, column="close", transform="pct_change"), str(tmp_path), [])


def test_data_boundaries_hashes_csv_and_pointer_escaping(tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    outside = tmp_path / "other.json"
    outside.write_text('{"x": 42}')
    (root / "escape.json").symlink_to(outside)
    for path in (outside, root / "escape.json"):
        with pytest.raises(ValueError, match="escapes"):
            resolve_data_refs(reference(path), str(root), [])
    file = root / "prices.csv"
    file.write_text("date,close\n2026-11-11,173.73\n2026-11-12,166.19\n")
    sources = []
    assert resolve_data_refs(reference(file, column="close", index="date", select="last"), str(root), sources) == 166.19
    assert "2026-11-12" in sources[0]["selected_index"]
    with pytest.raises(ValueError, match="changed"):
        resolve_data_refs(reference(file, sha256="0" * 64), str(root), [])
    file = root / "quote.json"
    file.write_text('{"BRK/B~USD": {"close": 450}}')
    assert resolve_data_refs(reference(file, pointer="/BRK~1B~0USD/close"), str(root), []) == 450


def test_large_quantlib_output_is_saved_before_presentation_limits(tmp_path):
    receipt = json.loads(QuantlibCallTool().execute(
        action="call", module="risk", function="drawdown_series", run_dir=str(tmp_path),
        kwargs={"equity": list(np.linspace(100, 200, 6000))}))
    saved = json.loads(Path(receipt["_result_file"]["path"]).read_text())
    assert len(saved["result"]["__series__"]["values"]) == 6000
    assert len(saved["result"]["__series__"]["index"]) == 6000
    assert "truncated" not in saved
    assert len(json.dumps(receipt)) < 10000


@pytest.mark.parametrize("spot", [173.73, 166.19])
def test_covered_collar_uses_joint_pnl_fees_and_explicit_basis(spot):
    legs = [OptionLeg("put", 150, 1, 7.2), OptionLeg("call", 200, -1, 4.35)]
    grid = np.array([0, 149, 150, 173, 200, 10000.])
    net_cost = 7.2 - 4.35 + .001 * (7.2 + 4.35)
    report = expiry_payoff(legs, grid, entry_spot=spot, time_to_expiry=0,
                           underlying_qty=1, multiplier=100)
    expected = (np.clip(grid, 150, 200) - spot - net_cost) * 100
    np.testing.assert_allclose(report.payoff, expected, atol=1e-9)
    np.testing.assert_allclose(scenario_grid(legs, grid, np.array([.3]), entry_spot=spot,
                               time_to_expiry=0, underlying_qty=1, multiplier=100)[0], expected)
    assert not report.loss_unbounded and not report.profit_unbounded
    assert report.breakevens == pytest.approx([spot + net_cost])
    result = json.loads(OptionsPayoffTool().execute(
        legs=[{"option_type": "put", "strike": 150, "qty": 1, "premium": 7.2},
              {"option_type": "call", "strike": 200, "qty": -1, "premium": 4.35}],
        entry_spot=spot, expiry_days=63, underlying_qty=1, price_as_of="2026-11-12"))
    basis = result["calculation_basis"]
    assert basis["max_loss_return"] == pytest.approx((150 - spot - net_cost) / spot)
    assert basis["max_profit_return"] == pytest.approx((200 - spot - net_cost) / spot)
    assert basis["price_as_of"] == "2026-11-12"


def test_short_stock_keeps_unbounded_loss_and_default_keeps_naked_call():
    legs = [OptionLeg("call", 200, -1, 4.35)]
    for qty in (0, -1):
        result = expiry_payoff(legs, np.array([100., 200.]), entry_spot=166.19,
                               time_to_expiry=.1, underlying_qty=qty)
        assert result.loss_unbounded


def test_handoff_copies_actual_observations_and_preserves_transitive_origin(tmp_path):
    store = TaskStore(tmp_path)
    source_task = SwarmTask(id="bull", agent_id="bull", prompt_template="research")
    risk = SwarmTask(id="risk", agent_id="risk", prompt_template="risk", input_from={"bull": "bull"})
    pm = SwarmTask(id="pm", agent_id="pm", prompt_template="decision", input_from={"risk": "risk"})
    for task in (source_task, risk, pm):
        store.save_task(task)
    source = agent_artifact_dir(tmp_path, "bull", "bull")
    source.mkdir(parents=True)
    raw = json.dumps({"NVDA.US": [{"trade_date": "2026-11-12", "close": 166.19}]})
    receipt = json.loads(persist_calculation_result(raw, source))
    # Simulate an unchanged saved log copied from a different run.
    receipt["_result_file"]["path"] = "/old/run/result.json"
    messages = [{"role": "assistant", "tool_calls": [{"id": "q1", "function": {
        "name": "get_market_data", "arguments": '{"codes":["NVDA.US"]}'}}]},
        {"role": "tool", "tool_call_id": "q1", "content": json.dumps(receipt)}]
    (source / "messages.json").write_text(json.dumps(messages))
    risk_dir = agent_artifact_dir(tmp_path, "risk", "risk")
    note = prepare_handoff(tmp_path, risk, risk_dir)
    assert "not fresh" in note
    from src.tools.read_file_tool import ReadFileTool
    page = json.loads(ReadFileTool().execute(path="upstream/index-parts/1.txt", run_dir=str(risk_dir)))
    assert page["status"] == "ok"
    assert "get_market_data" in page["content"]
    pm_dir = agent_artifact_dir(tmp_path, "pm", "pm")
    prepare_handoff(tmp_path, pm, pm_dir)
    entries = json.loads((pm_dir / "upstream/index.json").read_text())["observations"]
    assert len(entries) == 1
    assert entries[0]["source_task"] == "bull"
    copied = pm_dir / entries[0]["path"]
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == entries[0]["sha256"]
    assert resolve_data_refs(reference(copied, pointer="/NVDA.US", column="close", select="last"), str(pm_dir), []) == 166.19
    # Retry is stable; no duplicated evidence or new freshness claim.
    assert prepare_handoff(tmp_path, risk, risk_dir) == note


def test_large_payoff_keeps_basis_visible_and_paths_workspace_relative(tmp_path):
    from src.agent.result_artifacts import deliver_tool_result
    from src.agent.tools import ToolRegistry
    from src.tools.read_file_tool import ReadFileTool
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    raw = OptionsPayoffTool().execute(
        legs=[{"option_type": "call", "strike": 180, "qty": -1, "premium": 3.55}],
        underlying_qty=1, entry_spot=166.19, expiry_days=7, spot_points=501,
        price_as_of="2026-11-12")
    receipt = json.loads(deliver_tool_result(raw, tmp_path, registry))
    assert receipt["calculation_basis"] == json.loads(raw)["calculation_basis"]
    assert receipt["summary"] == json.loads(raw)["summary"]
    ref = receipt["_result_file"]
    assert (tmp_path / ref["relative_path"]).read_text() == raw
    page = json.loads(ReadFileTool().execute(path=ref["parts_relative_dir"] + "/1.txt", run_dir=str(tmp_path)))
    assert page["status"] == "ok"
