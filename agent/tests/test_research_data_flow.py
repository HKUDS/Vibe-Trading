"""Observed files remain usable by shell-free computation and downstream roles."""

from src.tools.path_utils import FileRoots


from src.product.tool_policy import ToolPolicy
from src.config.accessor import get_env_config


import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.options_payoff import OptionLeg, expiry_payoff, scenario_grid
from src.product.result_artifacts import persist_calculation_result
from src.quantlib.risk import fit_gpd_tail
from src.session.thread import ThreadLog
from src.swarm.evidence_handoff import prepare_handoff
from src.swarm.models import SwarmTask
from src.swarm.task_store import TaskStore
from src.swarm.artifacts import agent_artifact_dir, node_thread
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
    response = json.loads(persist_calculation_result(json.dumps({"NVDA.US": rows}), tmp_path, roots=FileRoots.from_config(get_env_config().api)))
    path = response["_result_file"]["path"]
    result = json.loads(QuantlibCallTool(roots=FileRoots.from_config(get_env_config().api)).execute(
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
        resolve_data_refs(reference(path, pointer=pointer, column="close", transform="pct_change"), str(tmp_path), [], roots=FileRoots.from_config(get_env_config().api))


def test_data_boundaries_hashes_csv_and_pointer_escaping(tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    outside = tmp_path / "other.json"
    outside.write_text('{"x": 42}')
    (root / "escape.json").symlink_to(outside)
    for path in (outside, root / "escape.json"):
        with pytest.raises(ValueError, match="escapes"):
            resolve_data_refs(reference(path), str(root), [], roots=FileRoots.from_config(get_env_config().api))
    file = root / "prices.csv"
    file.write_text("date,close\n2026-11-11,173.73\n2026-11-12,166.19\n")
    sources = []
    assert resolve_data_refs(reference(file, column="close", index="date", select="last"), str(root), sources, roots=FileRoots.from_config(get_env_config().api)) == 166.19
    assert "2026-11-12" in sources[0]["selected_index"]
    with pytest.raises(ValueError, match="changed"):
        resolve_data_refs(reference(file, sha256="0" * 64), str(root), [], roots=FileRoots.from_config(get_env_config().api))
    file = root / "quote.json"
    file.write_text('{"BRK/B~USD": {"close": 450}}')
    assert resolve_data_refs(reference(file, pointer="/BRK~1B~0USD/close"), str(root), [], roots=FileRoots.from_config(get_env_config().api)) == 450


def test_large_quantlib_output_is_saved_before_presentation_limits(tmp_path):
    receipt = json.loads(QuantlibCallTool(roots=FileRoots.from_config(get_env_config().api)).execute(
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


@pytest.mark.parametrize("canonical", [False, True], ids=["legacy", "child-thread"])
def test_handoff_copies_actual_observations_and_preserves_transitive_origin(tmp_path, canonical):
    store = TaskStore(tmp_path)
    source_task = SwarmTask(id="bull", agent_id="bull", prompt_template="research")
    risk = SwarmTask(id="risk", agent_id="risk", prompt_template="risk", input_from={"bull": "bull"})
    pm = SwarmTask(id="pm", agent_id="pm", prompt_template="decision", input_from={"risk": "risk"})
    for task in (source_task, risk, pm):
        store.save_task(task)
    source = agent_artifact_dir(tmp_path, "bull", "bull")
    source.mkdir(parents=True)
    raw = json.dumps({"source": "market fixture", "as_of": "2026-11-12",
                      "NVDA.US": [{"trade_date": "2026-11-12", "close": 166.19}]})
    result_root = source / "workspace" if canonical else source
    result_root.mkdir(exist_ok=True)
    receipt = json.loads(persist_calculation_result(raw, result_root, roots=FileRoots.from_config(get_env_config().api)))
    # Simulate an unchanged saved log copied from a different run.
    receipt["_result_file"]["path"] = "/old/run/result.json"
    call = {"id": "q1", "type": "function", "function": {
        "name": "get_market_data", "arguments": '{"codes":["NVDA.US"],"end_date":"2026-11-12"}'}}
    malformed_call = {**call, "id": "bad-receipt"}
    malformed_receipt = '{"_result_file":"not a receipt object"}'
    if canonical:
        thread = ThreadLog(node_thread(tmp_path, "bull", "bull"))
        thread.append("assistant", "malformed-turn", content="", phase="commentary",
                      tool_calls=[malformed_call])
        thread.append("tool_result", "malformed-turn", name="get_market_data",
                      tool_call_id="bad-receipt", content=malformed_receipt, status="ok")
        thread.append("assistant", "first-turn", content="", phase="commentary", tool_calls=[call])
        thread.append("assistant", "second-turn", content="", phase="commentary", tool_calls=[
            {**call, "function": {**call["function"], "arguments": '{"codes":["OTHER.US"]}'}},
        ])
        thread.append("tool_result", "first-turn", name="get_market_data", tool_call_id="q1",
                      content=json.dumps(receipt), status="ok")
        thread.append("tool_result", "second-turn", name="get_market_data", tool_call_id="q1",
                      content='{"error":"unavailable"}', status="error")
        thread.append("assistant", "third-turn", content="", phase="commentary", tool_calls=[
            {**call, "function": {**call["function"], "arguments": '{"codes":["NVDA.US"],"start_date":"2026-11-12"}'}},
        ])
        thread.append("tool_result", "third-turn", name="get_market_data", tool_call_id="q1",
                      content=json.dumps(receipt), status="ok")
    else:
        messages = [{"role": "assistant", "tool_calls": [malformed_call]},
                    {"role": "tool", "tool_call_id": "bad-receipt", "content": malformed_receipt},
                    {"role": "assistant", "tool_calls": [call]},
                    {"role": "tool", "tool_call_id": "q1", "content": json.dumps(receipt)}]
        (source / "messages.json").write_text(json.dumps(messages))
    risk_dir = agent_artifact_dir(tmp_path, "risk", "risk")
    note = prepare_handoff(tmp_path, risk, risk_dir)
    assert "not fresh" in note
    index = json.loads((risk_dir / "upstream/index.json").read_text())
    assert index["unavailable"] == ["bull/bad-receipt observation unavailable: Invalid observation receipt"]
    from src.tools.read_file_tool import ReadFileTool
    page = json.loads(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path="upstream/index-parts/1.txt", run_dir=str(risk_dir)))
    assert page["status"] == "ok"
    assert "get_market_data" in page["content"]
    pm_dir = agent_artifact_dir(tmp_path, "pm", "pm")
    prepare_handoff(tmp_path, pm, pm_dir)
    entries = json.loads((pm_dir / "upstream/index.json").read_text())["observations"]
    assert len(entries) == (2 if canonical else 1)
    if canonical:
        assert [entry["turn_id"] for entry in entries] == ["first-turn", "third-turn"]
        assert entries[1]["request"] == {"codes": ["NVDA.US"], "start_date": "2026-11-12"}
        assert entries[1]["path"] == entries[0]["path"]
    assert entries[0]["source_task"] == "bull"
    assert entries[0]["tool"] == "get_market_data"
    assert entries[0]["call_id"] == "q1"
    assert entries[0]["request"] == {"codes": ["NVDA.US"], "end_date": "2026-11-12"}
    copied = pm_dir / entries[0]["path"]
    observation = json.loads(copied.read_text())
    assert (observation["source"], observation["as_of"]) == ("market fixture", "2026-11-12")
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == entries[0]["sha256"]
    assert resolve_data_refs(reference(copied, pointer="/NVDA.US", column="close", select="last"), str(pm_dir), [], roots=FileRoots.from_config(get_env_config().api)) == 166.19
    # Retry is stable; no duplicated evidence or new freshness claim.
    assert prepare_handoff(tmp_path, risk, risk_dir) == note


@pytest.mark.parametrize("locale_codec", ["gbk", "cp1252"])
@pytest.mark.parametrize("canonical", [False, True], ids=["legacy", "child-thread"])
def test_handoff_reads_utf8_evidence_under_a_non_utf8_locale(tmp_path, monkeypatch, locale_codec, canonical):
    # Windows without UTF-8 mode decodes a read that names no encoding with the
    # ANSI code page, while the worker writes every artifact as UTF-8.
    read_text = Path.read_text

    def read_with_locale(self, encoding=None, errors=None, **kwargs):
        return read_text(self, encoding or locale_codec, errors, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_with_locale)
    store = TaskStore(tmp_path)
    source_task = SwarmTask(id="bull", agent_id="bull", prompt_template="research")
    risk = SwarmTask(id="risk", agent_id="risk", prompt_template="risk", input_from={"bull": "bull"})
    pm = SwarmTask(id="pm", agent_id="pm", prompt_template="decision", input_from={"risk": "risk"})
    for task in (source_task, risk, pm):
        store.save_task(task)
    source = agent_artifact_dir(tmp_path, "bull", "bull")
    source.mkdir(parents=True)
    raw = json.dumps({"600519.SH": [{"trade_date": "2026-11-12", "name": "贵州茅台", "close": 1500.0}]},
                     ensure_ascii=False)
    result_root = source / "workspace" if canonical else source
    result_root.mkdir(exist_ok=True)
    receipt = persist_calculation_result(raw, result_root, roots=FileRoots.from_config(get_env_config().api))
    call = {"id": "q1", "function": {
        "name": "get_market_data", "arguments": '{"codes":["600519.SH"]}'}}
    if canonical:
        thread = ThreadLog(node_thread(tmp_path, "bull", "bull"))
        thread.append("assistant", "turn-1", content="先看行情", phase="commentary", tool_calls=[call])
        thread.append("tool_result", "turn-1", name="get_market_data", tool_call_id="q1",
                      content=receipt, status="ok")
    else:
        messages = [{"role": "assistant", "content": "先看行情", "tool_calls": [call]},
                    {"role": "tool", "tool_call_id": "q1", "content": receipt}]
        (source / "messages.json").write_text(json.dumps(messages, ensure_ascii=False), encoding="utf-8")
    # Both canonical and legacy direct reads, plus transitive upstream indexes.
    for task in (risk, pm):
        task_dir = agent_artifact_dir(tmp_path, task.agent_id, task.id)
        prepare_handoff(tmp_path, task, task_dir)
        index = json.loads((task_dir / "upstream/index.json").read_text(encoding="utf-8"))
        assert index["unavailable"] == []
        [entry] = index["observations"]
        assert entry["source_task"] == "bull"
        copied = json.loads((task_dir / entry["path"]).read_text(encoding="utf-8"))
        assert copied["600519.SH"][0]["name"] == "贵州茅台"


def test_large_payoff_keeps_basis_visible_and_paths_workspace_relative(tmp_path):
    from src.product.result_artifacts import deliver_tool_result
    from src.agent.tools import ToolRegistry
    from src.tools.read_file_tool import ReadFileTool
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)))
    raw = OptionsPayoffTool().execute(
        legs=[{"option_type": "call", "strike": 180, "qty": -1, "premium": 3.55}],
        underlying_qty=1, entry_spot=166.19, expiry_days=7, spot_points=501,
        price_as_of="2026-11-12")
    receipt = json.loads(deliver_tool_result(raw, tmp_path, registry))
    assert receipt["calculation_basis"] == json.loads(raw)["calculation_basis"]
    assert receipt["summary"] == json.loads(raw)["summary"]
    ref = receipt["_result_file"]
    assert (tmp_path / ref["relative_path"]).read_text() == raw
    page = json.loads(ReadFileTool(roots=FileRoots.from_config(get_env_config().api)).execute(path=ref["parts_relative_dir"] + "/1.txt", run_dir=str(tmp_path)))
    assert page["status"] == "ok"


@pytest.mark.parametrize("broken", ["{not json", "[]", "null", '{"observations": 5}', '{"observations": [null]}'])
def test_bad_inherited_index_keeps_the_producers_own_observations(tmp_path, broken):
    store = TaskStore(tmp_path)
    producer = SwarmTask(id="p", agent_id="data", prompt_template="Collect")
    consumer = SwarmTask(id="c", agent_id="editor", prompt_template="Edit", input_from={"d": "p"})
    for task in (producer, consumer):
        store.save_task(task)
    source = agent_artifact_dir(tmp_path, "data", "p")
    (source / "upstream").mkdir(parents=True)
    (source / "upstream/index.json").write_text(broken)
    thread = ThreadLog(node_thread(tmp_path, "data", "p"))
    thread.append("assistant", "t1", content="", tool_calls=[
        {"id": "own", "type": "function", "function": {"name": "get_market_data", "arguments": "{}"}}])
    thread.append("tool_result", "t1", tool_call_id="own", name="get_market_data",
                  content=json.dumps({"status": "ok", "AAPL.US": [{"close": 1.0}]}), status="ok")
    destination = agent_artifact_dir(tmp_path, "editor", "c")
    prepare_handoff(tmp_path, consumer, destination)
    index = json.loads((destination / "upstream/index.json").read_text())
    assert [entry["call_id"] for entry in index["observations"]] == ["own"]
    [reason] = index["unavailable"]
    assert reason.startswith("p inherited")


@pytest.mark.parametrize("broken", ["{not json", '{"observations": [null]}'])
def test_an_upstream_gap_reaches_every_later_consumer(tmp_path, broken):
    """What the first consumer could not get is still unavailable two roles later (rf3-e item 9)."""
    store = TaskStore(tmp_path)
    producer = SwarmTask(id="p", agent_id="data", prompt_template="Collect")
    consumer = SwarmTask(id="c", agent_id="editor", prompt_template="Edit", input_from={"d": "p"})
    final = SwarmTask(id="f", agent_id="publisher", prompt_template="Publish", input_from={"c": "c"})
    for task in (producer, consumer, final):
        store.save_task(task)
    source = agent_artifact_dir(tmp_path, "data", "p")
    (source / "upstream").mkdir(parents=True)
    (source / "upstream/index.json").write_text(broken)
    thread = ThreadLog(node_thread(tmp_path, "data", "p"))
    thread.append("assistant", "t1", content="", tool_calls=[
        {"id": "own", "type": "function", "function": {"name": "get_market_data", "arguments": "{}"}}])
    thread.append("tool_result", "t1", tool_call_id="own", name="get_market_data",
                  content=json.dumps({"status": "ok", "AAPL.US": [{"close": 1.0}]}), status="ok")
    middle = agent_artifact_dir(tmp_path, "editor", "c")
    prepare_handoff(tmp_path, consumer, middle)
    gaps = json.loads((middle / "upstream/index.json").read_text())["unavailable"]
    assert gaps
    last = agent_artifact_dir(tmp_path, "publisher", "f")
    prepare_handoff(tmp_path, final, last)
    inherited = json.loads((last / "upstream/index.json").read_text())
    assert inherited["unavailable"] == gaps
    assert [entry["call_id"] for entry in inherited["observations"]] == ["own"]


def test_handoff_preserves_calculation_parameters_and_redacts_secrets(tmp_path):
    """A consumer sees the kwargs a quantlib_call ran with, never a credential (rf3-e item 9)."""
    store = TaskStore(tmp_path)
    producer = SwarmTask(id="p", agent_id="quant", prompt_template="Calculate")
    consumer = SwarmTask(id="c", agent_id="editor", prompt_template="Explain", input_from={"x": "p"})
    for task in (producer, consumer):
        store.save_task(task)
    secret = "sk-live-0123456789abcdefghijklmnop"
    arguments = {"action": "call", "module": "risk", "function": "calculation",
                 "kwargs": {"annualization": 52, "baseline": 0.03, "ddof": 1, "api_key": secret},
                 "api_key": secret}
    thread = ThreadLog(node_thread(tmp_path, "quant", "p"))
    thread.append("assistant", "t1", content="", tool_calls=[
        {"id": "q", "type": "function", "function": {"name": "quantlib_call", "arguments": json.dumps(arguments)}}])
    thread.append("tool_result", "t1", tool_call_id="q", name="quantlib_call",
                  content=json.dumps({"status": "ok", "result": 1.7}), status="ok")
    destination = agent_artifact_dir(tmp_path, "editor", "c")
    prepare_handoff(tmp_path, consumer, destination)
    raw = (destination / "upstream/index.json").read_text()
    [entry] = json.loads(raw)["observations"]
    assert entry["request"]["kwargs"] == {"annualization": 52, "baseline": 0.03, "ddof": 1, "api_key": "[redacted]"}
    assert entry["request"]["function"] == "calculation"
    assert secret not in raw


def test_a_receipt_naming_a_path_outside_the_producer_workspace_is_not_read(tmp_path):
    store = TaskStore(tmp_path)
    producer = SwarmTask(id="p", agent_id="data", prompt_template="Collect")
    consumer = SwarmTask(id="c", agent_id="editor", prompt_template="Edit", input_from={"d": "p"})
    for task in (producer, consumer):
        store.save_task(task)
    source = agent_artifact_dir(tmp_path, "data", "p")
    source.mkdir(parents=True)
    raw = json.dumps({"SIBLING.US": [{"close": 9.0}]})
    digest = hashlib.sha256(raw.encode()).hexdigest()
    sibling = agent_artifact_dir(tmp_path, "other", "x") / "tool-results" / digest / "result.json"
    sibling.parent.mkdir(parents=True)
    sibling.write_text(raw)
    forged = f"{source}/../../other/x/tool-results/{digest}/result.json"
    thread = ThreadLog(node_thread(tmp_path, "data", "p"))
    thread.append("assistant", "t1", content="", tool_calls=[
        {"id": "q", "type": "function", "function": {"name": "get_market_data", "arguments": "{}"}}])
    thread.append("tool_result", "t1", tool_call_id="q", name="get_market_data", status="ok",
                  content=json.dumps({"_result_file": {"path": forged, "sha256": digest}}))
    destination = agent_artifact_dir(tmp_path, "editor", "c")
    prepare_handoff(tmp_path, consumer, destination)
    index = json.loads((destination / "upstream/index.json").read_text())
    assert index["observations"] == []
    assert [reason.split(":")[0] for reason in index["unavailable"]] == ["p/q observation unavailable"]
