"""SEALED baseline canary for Level 2 Candlestick Workflow.

Risk level: 4 (SEALED). Protects the public contract of the deterministic
candlestick workflow established by Patch 5. Five classes:

  A. Document  — docs/CANDLESTICK_WORKFLOW_BASELINE.md is intact.
  B. Surface   — code modules / classes / registry / loop integration.
  C. Workflow  — ordering, run_dir, OHLCV persistence, verdict.
  D. Out-of-scope — backtest / strategy / swarm fall through.
  E. Fail-closed — sanitised errors, no web, no LLM fallback.

Failure here means a Level 2 baseline regression.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_BASELINE_DOC = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "CANDLESTICK_WORKFLOW_BASELINE.md"
)

_INVARIANT_SUBSTRINGS = (
    "Objective: deterministic pre-LLM workflow for simple candlestick analysis",
    "Simple candlestick prompts are intercepted before the LLM/ReAct loop",
    "`candlestick_workflow` is the deterministic entrypoint",
    "`get_market_data` must run before `pattern`",
    "OHLCV must be persisted in an allowed run_dir",
    "`pattern` must receive a valid existing run_dir",
    "The verdict is one of four exact strings",
    "The LLM does not decide the first action for simple candlestick",
    "`web_search`, `read_url` and `browser` are forbidden as first action",
    "Inventing a CSV path is a regression",
    "Inventing a run_dir is a regression",
    "Backtest, strategy and swarm are not intercepted",
    "Baseline = Patch 5",
    "Level 2 Candlestick Workflow — SEALED",
)

_SECRET_SHAPED_BLOCKLIST = (
    "Authorization:", "Bearer ", "token=", "api_key=",
    "secret-", "Traceback", "internal://", "/Users/", "/home/",
    "proxy.local:",
)

_ALLOWED_VERDICTS = {"bullish", "bearish", "neutral", "no_clear_signal"}


# --- Class A: Document ------------------------------------------------------

@pytest.mark.unit
def test_baseline_doc_exists() -> None:
    assert _BASELINE_DOC.is_file(), (
        f"Baseline document missing at {_BASELINE_DOC}. "
        "Level 2 Candlestick Workflow cannot be SEALED without it."
    )


@pytest.mark.unit
def test_baseline_doc_contains_all_invariant_substrings() -> None:
    text = _BASELINE_DOC.read_text(encoding="utf-8")
    missing = [s for s in _INVARIANT_SUBSTRINGS if s not in text]
    assert not missing, f"Baseline doc is missing invariant substrings: {missing}"


@pytest.mark.unit
def test_baseline_doc_does_not_leak_secrets() -> None:
    text = _BASELINE_DOC.read_text(encoding="utf-8")
    found = [s for s in _SECRET_SHAPED_BLOCKLIST if s in text]
    assert not found, (
        f"Baseline doc contains secret-shaped substrings: {found}."
    )


@pytest.mark.unit
def test_baseline_doc_starts_and_ends_with_sealed_marker() -> None:
    text = _BASELINE_DOC.read_text(encoding="utf-8").strip()
    marker = "Level 2 Candlestick Workflow — SEALED"
    first = text.splitlines()[0]
    assert marker in first, f"First line must be the SEALED marker: '{first}'"
    assert text.endswith(marker), (
        f"Last line must be the SEALED marker: '{text.splitlines()[-1]}'"
    )


# --- Class B: Surface -------------------------------------------------------

@pytest.mark.unit
def test_module_candlestick_intent_exports_detector() -> None:
    from src.agent.candlestick_intent import (
        CandlestickIntent,
        detect_candlestick_intent,
    )

    assert callable(detect_candlestick_intent)
    fields = CandlestickIntent.__dataclass_fields__
    for f in ("symbol", "timeframe", "limit", "window"):
        assert f in fields, f"Missing field {f!r} on CandlestickIntent"


@pytest.mark.unit
def test_module_candlestick_workflow_exports_class() -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    assert CandlestickWorkflowDispatcher.ROUTED_BY == "candlestick_workflow"
    assert callable(CandlestickWorkflowDispatcher().try_route)


@pytest.mark.unit
def test_get_market_data_and_pattern_tools_in_registry() -> None:
    from src.tools import build_registry

    registry = build_registry()
    assert registry.get("get_market_data") is not None
    assert registry.get("pattern") is not None


@pytest.mark.unit
def test_loop_integrates_candlestick_workflow() -> None:
    """AgentLoop must reference CandlestickWorkflowDispatcher. If someone
    deletes the integration, this canary fails before the runtime regresses."""
    from src.agent import loop as loop_module

    source = Path(loop_module.__file__).read_text(encoding="utf-8")
    assert "CandlestickWorkflowDispatcher" in source, (
        "AgentLoop no longer references CandlestickWorkflowDispatcher — "
        "Patch 5 integration has been removed."
    )
    # Patch 3 dispatcher must remain too (Level 1 SEALED defence in depth).
    assert "MarketDataDispatcher" in source, (
        "AgentLoop no longer references MarketDataDispatcher — Level 1 "
        "SEALED contract regressed."
    )


# --- Class C: Workflow ------------------------------------------------------

def _ohlcv_ok(n: int = 60) -> str:
    from datetime import datetime, timedelta, timezone
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    candles = [
        {
            "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": 80000 + i, "high": 80500 + i, "low": 79500 + i,
            "close": 80200 + i, "volume": 1000.0 + i,
        }
        for i in range(n)
    ]
    return json.dumps({
        "status": "ok", "symbol": "BTC/USDT", "provider": "ccxt",
        "timeframe": "1d", "current_price": candles[-1]["close"],
        "candles": candles,
    })


def _pattern_ok(bull: int, bear: int, neutral: int) -> str:
    counts: dict = {}
    if bull: counts[1] = bull
    if bear: counts[-1] = bear
    if neutral: counts[0] = neutral
    return json.dumps({
        "status": "ok",
        "results": {"BTC_USDT": {"candlestick": counts}},
        "patterns": ["candlestick"], "window": 20,
    })


def _registry(get_md_response: str, pattern_response: str) -> MagicMock:
    reg = MagicMock()

    def _execute(name: str, args: dict) -> str:
        if name == "get_market_data":
            return get_md_response
        if name == "pattern":
            return pattern_response
        return json.dumps({"status": "error", "error": f"unknown tool {name}"})

    reg.execute = MagicMock(side_effect=_execute)
    return reg


def _trace_sink() -> tuple[MagicMock, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    trace = MagicMock()
    trace.write = MagicMock(side_effect=lambda evt: events.append(evt))
    return trace, events


@pytest.mark.unit
def test_workflow_calls_get_market_data_before_pattern(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_ok(5, 1, 50))
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        "Analyze the candlestick patterns on BTC-USDT daily for the last 60 days. "
        "Tell me if there are any bullish or bearish signals right now.",
        reg, trace, str(tmp_path),
    )
    assert result is not None and result["status"] == "success"
    names = [c.args[0] for c in reg.execute.call_args_list]
    assert names.index("get_market_data") < names.index("pattern")


@pytest.mark.unit
def test_workflow_passes_real_run_dir_to_pattern(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_ok(1, 0, 0))
    trace, _ = _trace_sink()
    CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    pattern_call = next(c for c in reg.execute.call_args_list if c.args[0] == "pattern")
    assert pattern_call.args[1]["run_dir"] == str(tmp_path)


@pytest.mark.unit
def test_workflow_writes_ohlcv_csv_at_canonical_path(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_ok(1, 0, 0))
    trace, _ = _trace_sink()
    CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    csv_path = tmp_path / "artifacts" / "ohlcv_BTC_USDT.csv"
    assert csv_path.is_file()
    # And nothing else has been created at the run_dir top level beyond artifacts/
    top = {p.name for p in tmp_path.iterdir()}
    assert "artifacts" in top
    for invented in ("btcbusd.csv", "btcbusd_daily", "btc_usdt_daily"):
        assert invented not in top, (
            f"Workflow created a non-canonical artefact: {invented!r}"
        )


@pytest.mark.unit
@pytest.mark.parametrize("bull,bear,neutral,expected", [
    (10, 1, 30, "bullish"),
    (1, 10, 30, "bearish"),
    (0, 0, 30, "no_clear_signal"),
    (2, 2, 30, "neutral"),
])
def test_workflow_verdict_is_one_of_allowed_values(
    tmp_path: Path, bull: int, bear: int, neutral: int, expected: str
) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_ok(bull, bear, neutral))
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    assert result is not None
    assert result["verdict"] in _ALLOWED_VERDICTS
    assert result["verdict"] == expected


# --- Class D: Out-of-scope --------------------------------------------------

@pytest.mark.unit
@pytest.mark.parametrize("prompt", [
    "Backtest a BTC-USDT 20/50 moving-average strategy for 2024",
    "Build a strategy on BTC-USDT using candlestick patterns as entry signal",
    "Run the crypto_research_lab swarm to analyze candlestick on ETH",
])
def test_workflow_does_not_intercept_out_of_scope(tmp_path: Path, prompt: str) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    reg = _registry(_ohlcv_ok(), _pattern_ok(1, 0, 0))
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        prompt, reg, trace, str(tmp_path),
    )
    assert result is None, (
        f"Out-of-scope prompt was incorrectly intercepted: {prompt!r}"
    )
    reg.execute.assert_not_called()


# --- Class E: Fail-closed ---------------------------------------------------

@pytest.mark.unit
def test_get_market_data_failure_sanitises_and_skips_pattern(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    poisoned = json.dumps({
        "status": "error",
        "error": (
            "Authorization: Bearer secret-xyz Traceback "
            "internal://proxy.local:9090/leak /Users/ian /home/x "
            "token=abc api_key=APIKEY1"
        ),
    })
    reg = _registry(poisoned, _pattern_ok(0, 0, 0))
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    assert result is not None and result["status"] == "failed"

    pattern_calls = [c for c in reg.execute.call_args_list if c.args[0] == "pattern"]
    assert not pattern_calls, "pattern must not run after get_market_data fails."

    content = result["content"]
    leaks = [s for s in _SECRET_SHAPED_BLOCKLIST if s in content]
    assert not leaks, (
        f"Sanitisation failed; leaked: {leaks!r} into content={content!r}"
    )


@pytest.mark.unit
def test_pattern_failure_sanitises(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    bad_pattern = json.dumps({
        "status": "error",
        "error": "Bearer xyz token=abc /Users/ian secret-leak Traceback internal://x",
    })
    reg = _registry(_ohlcv_ok(), bad_pattern)
    trace, _ = _trace_sink()
    result = CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg, trace, str(tmp_path),
    )
    assert result is not None and result["status"] == "failed"
    content = result["content"]
    leaks = [s for s in _SECRET_SHAPED_BLOCKLIST if s in content]
    assert not leaks


@pytest.mark.unit
def test_workflow_never_invokes_web_tools_on_any_path(tmp_path: Path) -> None:
    from src.agent.candlestick_workflow import CandlestickWorkflowDispatcher

    # Success path
    reg_ok = _registry(_ohlcv_ok(), _pattern_ok(1, 0, 50))
    trace_ok, _ = _trace_sink()
    CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg_ok, trace_ok, str(tmp_path),
    )

    # Failure path
    reg_fail = _registry(
        json.dumps({"status": "error", "error": "boom"}), _pattern_ok(0, 0, 0)
    )
    trace_fail, _ = _trace_sink()
    CandlestickWorkflowDispatcher().try_route(
        "candlestick on BTC-USDT", reg_fail, trace_fail, str(tmp_path),
    )

    for reg in (reg_ok, reg_fail):
        names = [c.args[0] for c in reg.execute.call_args_list]
        assert "web_search" not in names
        assert "read_url" not in names
