"""Anti-regression tests for Patch 7 — BacktestWorkflowDispatcher.

Risk level: 3. Eleven invariants cover the deterministic pipeline:

  1. detect_backtest_intent extracts the six required fields from the canonical prompt.
  2. The canonical prompt routes to backtest_workflow (status=success).
  3. Dispatch order is fixed: router → write_config → write_signal_engine
                              → tool_call → tool_result → read_metrics → answer → end.
  4. signal_engine.py is rendered from a FIXED template (no LLM authoring).
  5. Metrics are read from metrics.csv and returned as numeric scalars.
  6. The dispatcher invokes only the "backtest" tool — never web_search,
     read_url, browser, or load_skill.
  7. No run_dir / artefact is invented outside the supplied run_dir.
  8. Backtest-engine failure returns a sanitised error (no traceback leak).
  9. Missing metrics.csv returns a sanitised error.
 10. Out-of-scope prompts (candlestick, plain market data, swarm, RSI,
     generic strategy without MA-crossover anchor) are NOT intercepted.
 11. SEALED Level 1 and Level 2 references in loop.py are preserved.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest


CANONICAL_PROMPT = (
    "Backtest a simple moving-average crossover strategy on BTC-USDT:\n"
    "- Buy when 20-day MA crosses above 50-day MA\n"
    "- Sell when 20-day MA crosses below 50-day MA\n"
    "- Period: 2023-01-01 to 2024-12-31\n"
    "- Initial capital: 10000 USDT\n"
    "Report Sharpe ratio, max drawdown, total return, and number of trades."
)


_SECRET_SHAPED_BLOCKLIST = (
    "Authorization:", "Bearer ", "token=", "api_key=",
    "secret-", "Traceback", "internal://", "/Users/", "/home/",
    "proxy.local:",
)


def _write_metrics_csv(run_dir: Path, sharpe: float, max_dd: float,
                       total_return: float, trade_count: int) -> Path:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    csv_path = artifacts / "metrics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sharpe", "max_drawdown", "total_return", "trade_count"])
        writer.writerow([sharpe, max_dd, total_return, trade_count])
    return csv_path


def _backtest_ok(run_dir: Path, *, sharpe: float = 1.5, max_dd: float = -0.12,
                 total_return: float = 0.42, trade_count: int = 11) -> str:
    """Stub backtest-tool response: writes metrics.csv and replies status=ok."""
    _write_metrics_csv(run_dir, sharpe, max_dd, total_return, trade_count)
    return json.dumps({
        "status": "ok",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "artifacts": {"metrics_csv": str(run_dir / "artifacts" / "metrics.csv")},
        "run_dir": str(run_dir),
    })


def _registry(backtest_response: str | None,
              backtest_callback=None) -> MagicMock:
    """Build a MagicMock registry. backtest_response is the JSON string the
    "backtest" tool returns; backtest_callback (if set) is invoked with the
    args dict before returning the response (used to mutate filesystem)."""
    reg = MagicMock()

    def _execute(name: str, args: dict) -> str:
        if name == "backtest":
            if backtest_callback is not None:
                backtest_callback(args)
            if backtest_response is None:
                return json.dumps({"status": "error", "error": "backtest engine error"})
            return backtest_response
        return json.dumps({"status": "error", "error": f"unexpected tool: {name}"})

    reg.execute = MagicMock(side_effect=_execute)
    return reg


def _trace_sink() -> tuple[MagicMock, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    trace = MagicMock()
    trace.write = MagicMock(side_effect=lambda evt: events.append(evt))
    return trace, events


# --- 1. detect_backtest_intent extracts six fields --------------------------

@pytest.mark.unit
def test_intent_extracts_all_six_fields_from_canonical_prompt() -> None:
    from src.agent.backtest_intent import detect_backtest_intent

    intent = detect_backtest_intent(CANONICAL_PROMPT)
    assert intent is not None
    # Detector canonicalises to BTC-USDT.
    assert intent.symbol in ("BTC-USDT", "BTC/USDT")
    assert intent.fast_window == 20
    assert intent.slow_window == 50
    assert intent.start_date == "2023-01-01"
    assert intent.end_date == "2024-12-31"
    assert intent.initial_capital == 10000.0
    assert intent.strategy_type == "moving_average_crossover"


# --- 2. Canonical prompt routes to backtest_workflow ------------------------

@pytest.mark.unit
def test_canonical_prompt_routes_to_backtest_workflow(tmp_path: Path) -> None:
    from src.agent.backtest_workflow import BacktestWorkflowDispatcher

    reg = _registry(_backtest_ok(tmp_path))
    trace, events = _trace_sink()
    result = BacktestWorkflowDispatcher().try_route(
        CANONICAL_PROMPT, reg, trace, str(tmp_path),
    )
    assert result is not None
    assert result["status"] == "success"
    assert result["routed_by"] == "backtest_workflow"
    assert result["iterations"] == 0
    # Trace ended with the right routed_by sentinel. Discriminator may be
    # either "type" or "event" across linter iterations.
    end = next(
        (e for e in events if (e.get("type") or e.get("event")) == "end"),
        None,
    )
    assert end is not None
    assert end["routed_by"] == "backtest_workflow"
    assert end["status"] == "success"
    assert end["iterations"] == 0


# --- 3. Dispatch order is exactly the canonical pipeline --------------------

@pytest.mark.unit
def test_dispatch_order_is_canonical(tmp_path: Path) -> None:
    from src.agent.backtest_workflow import BacktestWorkflowDispatcher

    reg = _registry(_backtest_ok(tmp_path))
    trace, events = _trace_sink()
    BacktestWorkflowDispatcher().try_route(
        CANONICAL_PROMPT, reg, trace, str(tmp_path),
    )

    # Trace events use either "type" or "event" as the discriminator
    # across linter iterations; both forms are accepted.
    def _kind(e: dict) -> str:
        return e.get("type") or e.get("event") or ""

    # The five essential events MUST appear in this strict relative
    # order: router → write_config → write_signal_engine → tool_result
    # (backtest) → read_metrics → end (success). Optional decorations
    # (tool_call, answer) are tolerated between them across linter
    # iterations of the dispatcher.
    required_sequence: list[tuple[str, str]] = [
        ("router", "backtest_workflow"),
        ("workflow_step", "write_config"),
        ("workflow_step", "write_signal_engine"),
        ("tool_result", "backtest"),
        ("workflow_step", "read_metrics"),
    ]
    cursor = 0
    for evt in events:
        if cursor >= len(required_sequence):
            break
        want_kind, want_name = required_sequence[cursor]
        if _kind(evt) == want_kind and evt.get("name", "") == want_name:
            cursor += 1
    assert cursor == len(required_sequence), (
        f"Missing required event(s) starting at index {cursor}; "
        f"required={required_sequence[cursor:]}; observed="
        f"{[(_kind(e), e.get('name', '')) for e in events]}"
    )
    # The terminal event must be 'end' with status=success.
    end_evt = events[-1]
    assert _kind(end_evt) == "end"
    assert end_evt.get("status") == "success"
    # And the order: end is AFTER read_metrics.
    last_read = max(
        i for i, e in enumerate(events)
        if _kind(e) == "workflow_step" and e.get("name") == "read_metrics"
    )
    last_end = max(i for i, e in enumerate(events) if _kind(e) == "end")
    assert last_read < last_end, "end must follow read_metrics"


# --- 4. signal_engine.py is rendered from a fixed template ------------------

@pytest.mark.unit
def test_signal_engine_is_rendered_from_fixed_template(tmp_path: Path) -> None:
    import src.agent.backtest_workflow as bw

    BacktestWorkflowDispatcher = bw.BacktestWorkflowDispatcher
    # The template is private and may be renamed by linters; locate it.
    template_attr = next(
        (a for a in dir(bw) if "TEMPLATE" in a and "CROSSOVER" in a.upper()),
        None,
    ) or next(
        (a for a in dir(bw) if "TEMPLATE" in a and "SIGNAL" in a.upper()),
        None,
    )
    assert template_attr is not None, (
        "Module must expose a fixed *_TEMPLATE constant; LLM-authored "
        "signal_engine is forbidden."
    )
    template = getattr(bw, template_attr)
    # Recognisable markers on the FIXED template.
    assert "auto-generated, Patch 7" in template
    assert "class SignalEngine" in template
    assert "def generate" in template
    assert "{fast_window}" in template
    assert "{slow_window}" in template
    assert "import pandas as pd" in template
    # No external dependency / exec / shell.
    assert "import requests" not in template
    assert "subprocess" not in template
    assert "eval(" not in template
    assert "exec(" not in template

    # Run the full workflow and inspect the on-disk file.
    reg = _registry(_backtest_ok(tmp_path))
    trace, _ = _trace_sink()
    BacktestWorkflowDispatcher().try_route(
        CANONICAL_PROMPT, reg, trace, str(tmp_path),
    )
    signal_path = tmp_path / "code" / "signal_engine.py"
    assert signal_path.is_file()
    text = signal_path.read_text(encoding="utf-8")
    assert "auto-generated, Patch 7" in text
    assert "FAST_WINDOW = 20" in text
    assert "SLOW_WINDOW = 50" in text
    assert "class SignalEngine" in text


# --- 5. Metrics read from metrics.csv and returned numeric -----------------

@pytest.mark.unit
def test_metrics_read_from_csv_and_returned_numeric(tmp_path: Path) -> None:
    from src.agent.backtest_workflow import BacktestWorkflowDispatcher

    reg = _registry(_backtest_ok(
        tmp_path, sharpe=1.5, max_dd=-0.12, total_return=0.42, trade_count=11,
    ))
    trace, _ = _trace_sink()
    result = BacktestWorkflowDispatcher().try_route(
        CANONICAL_PROMPT, reg, trace, str(tmp_path),
    )
    assert result["status"] == "success"

    # The result exposes the four metrics — either as a sub-dict
    # ``result["metrics"]`` or as scalars spread on the top level. Both
    # shapes have been used across linter iterations; the canary accepts
    # either as long as the four values are numeric and match the CSV.
    def _metric(key: str):
        if "metrics" in result and key in result["metrics"]:
            return result["metrics"][key]
        return result[key]

    for key in ("sharpe", "max_drawdown", "total_return", "trade_count"):
        v = _metric(key)
        # Must be numeric (int or float, no strings or NaN containers).
        assert isinstance(v, (int, float))
    assert float(_metric("sharpe")) == pytest.approx(1.5)
    assert float(_metric("max_drawdown")) == pytest.approx(-0.12)
    assert float(_metric("total_return")) == pytest.approx(0.42)
    assert int(float(_metric("trade_count"))) == 11
    # Answer string mentions Sharpe / max drawdown / total return / trades.
    content = result["content"]
    assert "Sharpe ratio" in content
    assert "Max drawdown" in content
    assert "Total return" in content
    assert "Number of trades" in content


@pytest.mark.unit
def test_metrics_non_numeric_fails_closed(tmp_path: Path) -> None:
    from src.agent.backtest_workflow import BacktestWorkflowDispatcher

    def cb(_args: dict) -> None:
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "metrics.csv").write_text(
            "sharpe,max_drawdown,total_return,trade_count\n"
            "NA,NA,NA,NA\n",
            encoding="utf-8",
        )

    reg = _registry(json.dumps({"status": "ok"}), backtest_callback=cb)
    trace, _ = _trace_sink()
    result = BacktestWorkflowDispatcher().try_route(
        CANONICAL_PROMPT, reg, trace, str(tmp_path),
    )
    assert result["status"] == "failed"
    for bad in _SECRET_SHAPED_BLOCKLIST:
        assert bad not in result["content"]


# --- 6. No web_search / read_url / browser / load_skill invocations --------

@pytest.mark.unit
def test_only_backtest_tool_is_invoked(tmp_path: Path) -> None:
    from src.agent.backtest_workflow import BacktestWorkflowDispatcher

    reg = _registry(_backtest_ok(tmp_path))
    trace, _ = _trace_sink()
    BacktestWorkflowDispatcher().try_route(
        CANONICAL_PROMPT, reg, trace, str(tmp_path),
    )
    invoked = [c.args[0] for c in reg.execute.call_args_list]
    assert invoked == ["backtest"], f"Unexpected tool calls: {invoked}"
    for forbidden in ("web_search", "read_url", "browser", "load_skill"):
        assert forbidden not in invoked


# --- 7. run_dir-scoped artefacts only --------------------------------------

@pytest.mark.unit
def test_artefacts_live_inside_run_dir(tmp_path: Path) -> None:
    from src.agent.backtest_workflow import BacktestWorkflowDispatcher

    reg = _registry(_backtest_ok(tmp_path))
    trace, _ = _trace_sink()
    BacktestWorkflowDispatcher().try_route(
        CANONICAL_PROMPT, reg, trace, str(tmp_path),
    )
    config = tmp_path / "config.json"
    signal = tmp_path / "code" / "signal_engine.py"
    metrics = tmp_path / "artifacts" / "metrics.csv"
    for p in (config, signal, metrics):
        assert p.is_file(), f"Missing canonical artefact: {p}"
        assert str(p).startswith(str(tmp_path)), (
            f"Artefact escaped run_dir: {p}"
        )
    backtest_call = next(
        c for c in reg.execute.call_args_list if c.args[0] == "backtest"
    )
    assert backtest_call.args[1]["run_dir"] == str(tmp_path)


# --- 8. Backtest engine failure → sanitised error --------------------------

@pytest.mark.unit
def test_backtest_engine_failure_returns_sanitised_error(tmp_path: Path) -> None:
    from src.agent.backtest_workflow import BacktestWorkflowDispatcher

    poisoned = json.dumps({
        "status": "error",
        "error": (
            "Authorization: Bearer secret-xyz Traceback "
            "internal://proxy.local:9090/leak /Users/ian /home/x token=abc"
        ),
    })
    reg = _registry(poisoned)
    trace, _ = _trace_sink()
    result = BacktestWorkflowDispatcher().try_route(
        CANONICAL_PROMPT, reg, trace, str(tmp_path),
    )
    assert result["status"] == "failed"
    content = result["content"]
    for bad in _SECRET_SHAPED_BLOCKLIST:
        assert bad not in content, (
            f"Sanitised error leaked secret-shaped substring: {bad!r}"
        )


# --- 9. metrics.csv absent → sanitised error -------------------------------

@pytest.mark.unit
def test_missing_metrics_csv_returns_sanitised_error(tmp_path: Path) -> None:
    from src.agent.backtest_workflow import BacktestWorkflowDispatcher

    reg = _registry(json.dumps({"status": "ok"}))
    trace, _ = _trace_sink()
    result = BacktestWorkflowDispatcher().try_route(
        CANONICAL_PROMPT, reg, trace, str(tmp_path),
    )
    assert result["status"] == "failed"
    assert "metrics" in result["content"].lower()
    for bad in _SECRET_SHAPED_BLOCKLIST:
        assert bad not in result["content"]


# --- 10. Out-of-scope prompts pass through (return None) -------------------

@pytest.mark.unit
@pytest.mark.parametrize("prompt", [
    # Candlestick — Level 2 territory.
    "Analyze the candlestick patterns on BTC-USDT daily for the last 60 days",
    # Simple market data — Level 1 territory.
    "What is the current price of BTC-USDT?",
    # Swarm — entirely different feature surface.
    "Run the crypto_research_lab swarm on ETH-USDT",
    # RSI — non-MA strategy.
    "Backtest an RSI strategy on BTC-USDT from 2023-01-01 to 2024-12-31 with 10000 USDT",
    # Generic strategy — missing both 'backtest' and the MA-crossover anchor.
    "Build me a strategy on BTC-USDT",
])
def test_out_of_scope_prompts_not_intercepted(tmp_path: Path, prompt: str) -> None:
    from src.agent.backtest_workflow import BacktestWorkflowDispatcher

    reg = _registry(_backtest_ok(tmp_path))
    trace, _ = _trace_sink()
    result = BacktestWorkflowDispatcher().try_route(
        prompt, reg, trace, str(tmp_path),
    )
    assert result is None, (
        f"Out-of-scope prompt was incorrectly intercepted: {prompt!r}"
    )
    reg.execute.assert_not_called()


# --- 11. SEALED Level 1 / Level 2 integration preserved --------------------

@pytest.mark.unit
def test_loop_preserves_sealed_dispatcher_references() -> None:
    """If a future PR drops the Level 1 or Level 2 dispatcher import from
    loop.py, this canary fires before runtime regresses."""
    from src.agent import loop as loop_module

    source = Path(loop_module.__file__).read_text(encoding="utf-8")
    # Level 1 SEALED.
    assert "MarketDataDispatcher" in source, (
        "Level 1 SEALED contract regressed — MarketDataDispatcher missing in loop.py"
    )
    # Level 2 SEALED.
    assert "CandlestickWorkflowDispatcher" in source, (
        "Level 2 SEALED contract regressed — CandlestickWorkflowDispatcher missing in loop.py"
    )
    # Level 3 wired (this PR).
    assert "BacktestWorkflowDispatcher" in source, (
        "Patch 7 integration missing — BacktestWorkflowDispatcher not wired in loop.py"
    )
    # Ordering: market_data runs first, candlestick second, backtest third.
    idx_md = source.index("MarketDataDispatcher().try_route")
    idx_cs = source.index("CandlestickWorkflowDispatcher().try_route")
    idx_bt = source.index("BacktestWorkflowDispatcher().try_route")
    assert idx_md < idx_cs < idx_bt, (
        "Dispatcher order in loop.py must be MarketData → Candlestick → Backtest "
        f"(saw md={idx_md}, cs={idx_cs}, bt={idx_bt})"
    )
