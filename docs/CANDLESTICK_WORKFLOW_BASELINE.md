# Level 2 Candlestick Workflow — SEALED

Status: **SEALED** as of PR #6.
Baseline = Patch 5.

This document is a contract. Any change that breaks one of the thirteen
invariants below must explicitly bump the baseline (new SEALED PR), not
silently regress.

The anti-regression canary lives at:

```
pytest agent/tests/test_baseline_candlestick_workflow.py -v
```

Run it locally before any PR that touches `agent/src/agent/loop.py`,
`agent/src/agent/candlestick_intent.py`,
`agent/src/agent/candlestick_workflow.py`, or
`agent/src/tools/pattern_tool.py`.

---

## 1. Objective: deterministic pre-LLM workflow for simple candlestick analysis

The agent must answer canonical candlestick-pattern analysis prompts with a
deterministic verdict (bullish / bearish / neutral / no_clear_signal) without
depending on the LLM to orchestrate `load_skill → get_market_data → write_file →
bash → pattern → interpret`. Three local LLMs (7B / 8B / 14B) were empirically
unable to compose that orchestration; Patch 5 replaces it with code.

## 2. Simple candlestick prompts are intercepted before the LLM/ReAct loop

`AgentLoop.run()` invokes `CandlestickWorkflowDispatcher().try_route(...)`
immediately after the `MarketDataDispatcher` short-circuit and before the ReAct
`while` loop. If the dispatcher returns a result dict, the loop short-circuits
and the LLM is never called. If it returns None, the ReAct loop runs unchanged.

## 3. `candlestick_workflow` is the deterministic entrypoint

Defined in `agent/src/agent/candlestick_workflow.py` as
`CandlestickWorkflowDispatcher.ROUTED_BY = "candlestick_workflow"`. The
dispatcher emits trace events tagged with this name so any auditing tool can
filter on it.

## 4. `get_market_data` must run before `pattern`

The dispatcher calls `registry.execute("get_market_data", ...)` first and only
then `registry.execute("pattern", ...)`. The trace records this ordering. Any
inversion or skip is a baseline regression.

## 5. OHLCV must be persisted in an allowed run_dir

The dispatcher writes the candles returned by `get_market_data` into
`<run_dir>/artifacts/ohlcv_<safe_code>.csv` using the stdlib `csv` module.
`safe_code` is the canonical symbol with `/`, `-`, `.` mapped to `_`
(`BTC/USDT` → `BTC_USDT`). The `run_dir` is the one already injected by
`AgentLoop.run` — never fabricated.

## 6. `pattern` must receive a valid existing run_dir

`pattern` is called with `run_dir = <real loop run_dir>` (string), and
`pattern` itself validates it via `safe_run_dir` (defence in depth). The
dispatcher must not invent a `run_dir` such as `/backtests/btc_usdt_daily`
or `./btcbusd_daily/btcbusd.csv` — both observed empirically as LLM
hallucinations before Patch 5.

## 7. The verdict is one of four exact strings

Allowed values:
`bullish`, `bearish`, `neutral`, `no_clear_signal`. Any other value is a
baseline regression. The verdict is exposed on the dispatcher result dict
(`result["verdict"]`) and echoed in the final `end` trace event.

## 8. The LLM does not decide the first action for simple candlestick

Confirmed by the integration test
`test_loop_does_not_call_llm_for_candlestick_prompt`, which asserts
`llm.stream_chat.call_count == 0`. The short-circuit result carries
`iterations == 0` and `routed_by == "candlestick_workflow"`.

## 9. `web_search`, `read_url` and `browser` are forbidden as first action

For any prompt the dispatcher accepts, the only tools invoked are
`get_market_data` and `pattern`. Neither on success nor on failure does the
dispatcher call `web_search`, `read_url`, or any browser primitive.

## 10. Inventing a CSV path is a regression

The dispatcher writes exactly one file per run, at
`<run_dir>/artifacts/ohlcv_<safe_code>.csv`. It never reads a fabricated path
like `./btcbusd_daily/btcbusd.csv`, never queries a non-existent file as a
hint for the LLM, never expects the user to provide a CSV. The 14B model
fabricated such a path before Patch 5 — that mode is now closed.

## 11. Inventing a run_dir is a regression

The dispatcher never builds a `run_dir` from the symbol alone (e.g.
`/BTC-USDT-daily-60days` or `/backtests/btc_usdt_daily`). It passes through
the `run_dir` parameter received from `AgentLoop.run`. Both fabrication
patterns were observed empirically with 7B/8B/14B before Patch 5.

## 12. Backtest, strategy and swarm are not intercepted

`detect_candlestick_intent` carries an explicit blacklist:

```
backtest, strategy, estratégia, estrategia, swarm, signal_engine,
optimize, otimizar, moving average, média móvel, media movel,
RSI, MACD, entry signal, entry signals
```

Any prompt containing one of these tokens returns `None` from
`detect_candlestick_intent` and falls through to the ReAct loop.

## 13. Baseline = Patch 5

| PR | Layer | Concern |
|----|-------|---------|
| #5 | Pre-LLM workflow | `CandlestickWorkflowDispatcher` orchestrates `get_market_data → persist OHLCV → pattern → verdict` without the LLM. |
| #6 | **SEALED** | This document + the anti-regression canary. |

Patch 5 must remain present and integrated in `AgentLoop.run`. Removing the
dispatcher invocation or any of its five workflow steps is a baseline
regression.

---

## Anti-regression test

The canary `agent/tests/test_baseline_candlestick_workflow.py` has five
classes:

- **Class A — Document**: this file exists, contains the thirteen invariant
  substrings, does not leak credentials, and is bounded by identical SEALED
  markers.
- **Class B — Surface**: `candlestick_intent`, `candlestick_workflow`,
  `MarketDataTool` and `PatternTool` are present in code, and `AgentLoop`
  integrates the dispatcher (source-level grep guard).
- **Class C — Workflow**: canonical prompt drives the dispatcher; mocked
  registry records `get_market_data` invoked before `pattern`; `run_dir`
  passed through unchanged; OHLCV CSV written at the canonical path;
  verdict is one of the four allowed strings.
- **Class D — Out-of-scope**: backtest, strategy, and swarm prompts return
  `None` from `try_route` — the ReAct loop runs as before.
- **Class E — Fail-closed**: poisoned `get_market_data` error is sanitised
  against a credential-pattern blocklist, `pattern` is not called, and no
  web tool is invoked. Poisoned `pattern` error is sanitised the same way.

Run:

```
pytest agent/tests/test_baseline_candlestick_workflow.py -v
```

A green run means Level 2 Candlestick Workflow is intact. A red run means a
baseline regression — investigate before merging.

---

Level 2 Candlestick Workflow — SEALED
