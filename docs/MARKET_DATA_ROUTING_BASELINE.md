# Level 1 Market Data Routing — SEALED

Status: **SEALED** as of PR #4.
Baseline = Patch 1 + Patch 2 + Patch 3.

This document is a contract. Any change that breaks one of the eleven
invariants below must explicitly bump the baseline (new SEALED PR), not
silently regress.

The anti-regression canary lives at:

```
pytest agent/tests/test_baseline_market_data_routing.py -v
```

Run it locally before any PR that touches `agent/src/agent/loop.py`,
`agent/src/agent/context.py`, `agent/src/agent/market_data_intent.py`,
`agent/src/agent/market_data_dispatcher.py`, or
`agent/src/tools/market_data_tool.py`.

---

## 1. Objective: deterministic pre-LLM routing of simple market-data prompts

The agent must answer simple market-data prompts (price, OHLCV, candles,
ticker close) without depending on the LLM to pick the correct tool. The
LLM is non-deterministic; for this class of prompts the dispatch is
encoded in code, not in instructions.

## 2. Simple market-data prompts are intercepted before the LLM/ReAct loop

`AgentLoop.run()` invokes `MarketDataDispatcher().try_route(...)`
immediately after emitting the `start` trace event and before entering
the ReAct `while` loop. If the dispatcher returns a result dict, the
loop short-circuits and the LLM is never called. If it returns None,
the ReAct loop runs unchanged.

## 3. `market_data_router` is the deterministic entrypoint

Defined in `agent/src/agent/market_data_dispatcher.py` as
`MarketDataDispatcher.ROUTED_BY = "market_data_router"`. The dispatcher
emits trace events tagged with this name so any tooling that audits
runs can filter on it.

## 4. `get_market_data` is the first-class tool

Defined in `agent/src/tools/market_data_tool.py`. Registered via
auto-discovery in `agent/src/tools/__init__.py`. The dispatcher calls
this tool through `registry.execute("get_market_data", ...)` — no
indirection, no skill loading, no `bash` + `write_file` choreography.

## 5. The LLM does not decide the first action for simple market data

Confirmed by the integration test
`test_loop_does_not_call_llm_for_vague_market_prompt`, which asserts
`llm.stream_chat.call_count == 0` for the canonical vague prompt. The
short-circuit result carries `iterations == 0` and
`routed_by == "market_data_router"`.

## 6. `web_search`, `read_url` and `browser` are forbidden as first action

For any prompt the dispatcher accepts, the only tool invoked is
`get_market_data`. The dispatcher does not call `web_search`, does
not call `read_url`, does not invoke any browser primitive — neither
on success nor on failure. This is enforced by
`test_dispatcher_never_calls_web_tools` and
`test_dispatcher_failure_does_not_invoke_web_tools`.

## 7. Inventing a skill name such as `crypto-price` is a regression

`LoadSkillTool` rejects unknown skill names with a sanitized error that
explicitly redirects the model to `get_market_data` (see
`agent/src/tools/load_skill_tool.py`). Any future change that allows
the agent to call `load_skill("crypto-price")` without that redirect
is a baseline regression.

## 8. Dynamic skill creation for simple market data is a regression

`SaveSkillTool` refuses names matching the market-data pattern (regex
covers `crypto-price`, `market-price`, `price-fetcher`, `btc-price`,
`ohlcv-fetch`, `ticker-fetcher`, …) with no directory created on disk.
Pinned by `test_save_skill_blocks_market_data_pattern_names`.

## 9. Backtest, candlestick, strategy and swarm are not intercepted

The detector in `agent/src/agent/market_data_intent.py` carries an
explicit blacklist:

```
backtest, strategy, estratégia, estrategia,
candlestick pattern, candlestick patterns,
analyze, analise, análise técnica, swarm,
signal_engine, optimize, otimizar,
moving average, média móvel, media movel,
RSI, MACD
```

Any prompt containing one of these tokens returns `None` from
`detect_market_data_intent` and falls through to the ReAct loop.
Pinned by `test_router_does_not_intercept_backtest`,
`test_router_does_not_intercept_candlestick_pattern`,
`test_router_does_not_intercept_swarm`.

## 10. Baseline = Patch 1 + Patch 2 + Patch 3

| PR | Layer | Concern |
|----|-------|---------|
| #1 | System prompt | Forbids `web_search`/`read_url` for price/OHLCV; routes the LLM to market-data skills. |
| #2 | Tool + guards | Adds `get_market_data` first-class tool; hardens `load_skill` and `save_skill` against hallucinated names. |
| #3 | Pre-LLM dispatcher | `MarketDataDispatcher` short-circuits `AgentLoop.run` for simple market-data prompts; LLM is never called. |
| #4 | **SEALED** | This document + the anti-regression canary. |

All three runtime layers must remain present. Removing any one of them
is a baseline regression.

## 11. Anti-regression test

The canary `agent/tests/test_baseline_market_data_routing.py` has five
classes:

- **Class A — Document**: this file exists, contains the eleven
  invariant substrings, does not leak credentials, and is bounded by
  identical SEALED markers.
- **Class B — Surface**: `market_data_intent`, `market_data_dispatcher`,
  `MarketDataTool`, and `AgentLoop` integration are present in code.
- **Class C — System prompt**: five pinned substrings (Patch 1 × 3 +
  Patch 2 × 1 + Patch 3 × 1) live in `_SYSTEM_PROMPT`.
- **Class D — Behavioural**: three canonical prompts intercepted, three
  out-of-scope prompts passed through.
- **Class E — Fail-closed**: dispatcher sanitises a poisoned tool error
  against an explicit blocklist of credential-pattern substrings, and
  never invokes web tools on failure.

Run:

```
pytest agent/tests/test_baseline_market_data_routing.py -v
```

A green run means Level 1 Market Data Routing is intact. A red run
means a baseline regression — investigate before merging.

---

Level 1 Market Data Routing — SEALED
