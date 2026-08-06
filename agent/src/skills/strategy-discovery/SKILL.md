---
name: strategy-discovery
description: "Strategy Discovery: evidence-gated read-only facade over Alpha Zoo + the SDM strategy store — answers what strategies exist and what state they are in, with per-regime evidence instead of scenario tags."
category: research
---

# Strategy Discovery

## Purpose

Strategy Discovery is the single read-only entry point for two questions: **what strategies exist**, and **what state are they in**. It fronts the Alpha Zoo registry and the SDM strategy store with one facade and answers with computed evidence instead of labels.

It supersedes the earlier closed-registry attempt. That design attached boolean scenario tags (works in bear markets: yes/no) to a curated list. This skill replaces tags with **per-regime evidence rows**: every claim that a strategy works in a regime must come from a computed, reproducible backtest stored as evidence, never from curation or inference.

The surface is read-only. It never registers, mutates, or deletes strategies. To add or change strategies, use the `strategy-dev-manager` and `alpha-zoo` workflows — Strategy Discovery only reports what those workflows have produced.

## When to Use

Decision tree for routing user requests:

- User asks **what strategies exist** / "list available strategies" → `list_strategies(limit=..., offset=..., source=...)`
- User asks **which strategy fits a regime or threshold** ("what works in bear markets?", "anything with Sharpe above 1?") → `query_strategies(regime=..., min_sharpe=..., ...)`
- User asks for **the evidence behind one specific strategy** → `get_strategy_evidence(strategy_id=..., regime=...)`
- User asks to **create, backtest, or register** a strategy → this is NOT this skill; route to `strategy-generate` / `strategy-dev-manager` / `alpha-zoo`

This skill has **no CLI surface** — there is no `vibe-trading strategy-discovery` command and no CLI flags. The only access path is the three tools (`list_strategies`, `query_strategies`, `get_strategy_evidence`), available through the agent registry and the MCP server under the same names. Do not invent flags or subcommands.

## Tools

### list_strategies

Browse the catalogue.

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `limit` | integer | 20 | Maximum number of rows to return |
| `offset` | integer | 0 | Pagination offset |
| `source` | string | none | Optional filter: `alpha_zoo` or `sdm`; omit for both |

Returns identification metadata plus evidence status. This is a catalogue listing, not a ranking — use `query_strategies` for filtered, evidence-ranked results.

### query_strategies

Evidence-gated query.

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `regime` | string | none | `bear_market`, `bull_market`, or `structural`; omit for all regimes |
| `min_sharpe` | number | none | Minimum Sharpe on the evidence rows |
| `min_evidence_quality` | string | `adequate` | `adequate` \| `marginal` \| `insufficient` \| `any`. `any` only removes the quality floor — rows must still pass the other filters (`min_trades`, `cost_feasible`, `min_sharpe`) to be kept |
| `min_trades` | integer | 10 | Minimum executed-trade count for evidence to count |
| `cost_feasible` | boolean | true | Keep only rows that clear the cost screen. Fail-closed: rows whose breakeven is unverifiable (`null`, see Multi-position caveat) are excluded; set `false` to inspect them with their warnings |
| `limit` | integer | 10 | Maximum number of rows to return |

### get_strategy_evidence

Per-regime evidence detail for one strategy.

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `strategy_id` | string | — | Required. Identifier from `list_strategies` / `query_strategies` |
| `regime` | string | none | Optional regime filter (same values as `query_strategies`) |

Returns the per-regime evidence rows: trade count, coverage window, Sharpe, cost breakeven, and the resulting evidence-quality flag.

## Evidence Row Contract

Every row is self-describing — the metadata travels with the numbers:

| Field | Meaning |
|-------|---------|
| `evidence_stage` | Pipeline stage that produced the row: `hypothesis` \| `backtest` \| `holdout` \| `shadow` \| `live_canary` \| `retired`. The harness writes only `backtest` today (it computes over backtest artifacts); the other stages are reserved. A row answers "backtest evidence exists; no holdout/shadow/live evidence exists yet" — never more than the stage it carries |
| `provenance` | The reproducible backtest run directory the row was computed from (`artifacts/trades.csv` + `artifacts/equity.csv` inside it). The run directory holds the config and signal engine that produced the figures, so every row is traceable to a reproducible artifact |
| `regime_definition` | JSON naming the regime-labeling parameters used (rolling benchmark window, bear/bull thresholds, Sharpe annualization) — the definition travels with the data, not hidden in code constants |
| `breakeven_fee_bps` | Sizing-corrected cost breakeven, or `null` when the cost screen is unverifiable (see Multi-position caveat) |
| `warnings` | Stable machine-readable prefixes: `insufficient-trades:`, `short-coverage:`, `cost-sensitive:`, `borderline-evidence:`, `multi-position-breakeven:` |

## Evidence Thresholds

Evidence quality is derived from the computed rows, not asserted:

| Condition | Flag | Meaning |
|-----------|------|---------|
| Trade count < 10 | `insufficient` | Too few trades to say anything; the row carries no claim |
| Coverage < 2 years | `marginal` | Real but short sample; report with the caveat, not as proof |
| Breakeven < 5 bps | `cost_sensitive` | Gross edge is thinner than realistic per-trade costs |
| Right at a boundary (e.g. exactly 10 trades) | borderline caveat | Report the raw numbers alongside the flag; the flag alone is not the story |

Rows flagged `insufficient` or `marginal` are returned so the caller can see the gap — they are **flagged, never recommended**. Filtering them out is what `min_evidence_quality` and `min_trades` are for.

## Cost Screen

The feasibility screen uses the sizing-corrected breakeven, in basis points:

```
breakeven_bps = ln(1 + g) / (2 · n · s) · 10⁴
```

where `g` is the gross edge over the evidence window, `n` is the number of trades, and `s` is the average position sizing. A strategy is cost-feasible only when its breakeven is thick enough (`cost_feasible=true` keeps the passing rows; a sub-5 bps breakeven reads as `cost_sensitive` above).

The facade deliberately **does not report an `estimated_net_sharpe`**. A net Sharpe requires picking concrete cost assumptions, and any choice there would present an unverified estimate as evidence. The honest number is the breakeven itself — it tells the caller how much per-trade cost the gross edge tolerates, and leaves the cost assumption to them.

## Multi-position caveat

`breakeven_fee_bps` is exact only for strategies holding **one position at a time**. Per the #969 discussion (sergio12S), the aggregate form has **no closed form for multi-sleeve / multi-name strategies** — the portfolio break-even equation needs per-sleeve returns and trade counts, which aggregate figures do not contain; measured error is 1.1–6.5x versus per-position accounting, and the error is not a constant factor.

The harness therefore **refuses to store an aggregate breakeven**: any run that held more than one concurrent position — or whose artifacts make concurrency undetectable — gets `breakeven_fee_bps = null` on every row, plus a stable `multi-position-breakeven:` warning. A null is a better answer than a number that is wrong by a factor between 1.1 and 6.5.

Consequences for queries:

- `cost_feasible=true` (default) is **fail-closed**: a null breakeven means the cost screen is unverifiable, which is not a pass — such rows are excluded from default results.
- The rows are not lost: query with `cost_feasible=false` or call `get_strategy_evidence` to see them with their warnings.
- Single-position runs keep the exact sizing-corrected breakeven and are unaffected.

## Honest-Empty Semantics

The facade refuses regime assessments without computed evidence. If a strategy has no backtest evidence for a regime, `get_strategy_evidence` returns an honest empty for that regime instead of a guess; `query_strategies` likewise never fabricates rows to satisfy a filter.

An empty result is an answer, not an error: it means "no computed evidence exists for this request." There is **no user-runnable command or workflow** that changes that. The evidence store is populated only by the evidence harness **library API** (`src.strategy_discovery.evidence_harness.rebuild_evidence` over reproducible run artifacts); automated workflow wiring is still pending, so until then evidence rows come from harness runs executed by developers/integrators. Never relax a threshold or narrate from a scenario tag instead.

## Composition Guarantee

- **Reads only**: the Alpha Zoo Registry, the SDM strategy store, and the facade-owned evidence cache DB. Modifies nothing in any of them.
- **Cache is disposable**: the evidence cache DB is owned by the facade, deletable, and rebuildable from the two authoritative sources. Its location can be overridden with the `VIBE_TRADING_STRATEGY_DISCOVERY_DB_PATH` environment variable; unset means the default location.
- **No other state**: no network calls, no writes outside the cache, no side effects on the registries it reads.
