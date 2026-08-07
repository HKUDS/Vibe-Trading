---
name: strategy-discovery
description: "Strategy Discovery: evidence-gated facade over Alpha Zoo + the SDM strategy store — answers what strategies exist and what state they are in, with per-regime evidence instead of scenario tags; reports evidence freshness on every returned row and rebuilds the disposable evidence cache from local backtest runs."
category: research
---

# Strategy Discovery

## Purpose

Strategy Discovery is the single entry point for two questions: **what strategies exist**, and **what state are they in**. It fronts the Alpha Zoo registry and the SDM strategy store with one facade and answers with computed evidence instead of labels, and it reports the freshness of that evidence on every returned row.

It supersedes the earlier closed-registry attempt. That design attached boolean scenario tags (works in bear markets: yes/no) to a curated list. This skill replaces tags with **per-regime evidence rows**: every claim that a strategy works in a regime must come from a computed, reproducible backtest stored as evidence, never from curation or inference.

The three query tools are read-only: they never register, mutate, or delete strategies. To add or change strategies, use the `strategy-dev-manager` and `alpha-zoo` workflows — Strategy Discovery only reports what those workflows have produced. The fourth tool, `refresh_strategy_evidence`, is the single write in the surface: it rebuilds ONLY the disposable evidence cache from local backtest run artifacts (see Populating & Refreshing Evidence and Composition Guarantee).

## When to Use

Decision tree for routing user requests:

- User asks **what strategies exist** / "list available strategies" → `list_strategies(limit=..., offset=..., source=...)`
- User asks **which strategy fits a regime or threshold** ("what works in bear markets?", "anything with Sharpe above 1?") → `query_strategies(regime=..., min_sharpe=..., ...)`
- User asks for **the evidence behind one specific strategy** → `get_strategy_evidence(strategy_id=..., regime=...)`
- User asks to **populate or refresh the evidence cache** ("turn my backtest runs into evidence", "the evidence is stale, refresh it") → `refresh_strategy_evidence(manifest_path=...)` — this rebuilds the disposable cache from run artifacts; it is NOT strategy creation or registration
- User asks to **create, backtest, or register** a strategy → this is NOT this skill; route to `strategy-generate` / `strategy-dev-manager` / `alpha-zoo`

The access path is the three read tools (`list_strategies`, `query_strategies`, `get_strategy_evidence`) plus one cache-refresh tool (`refresh_strategy_evidence`), available through the agent registry and the MCP server under the same names. The only CLI surface is `vibe-trading strategy-evidence refresh --manifest <path>`, which runs the same refresh as the tool; queries stay with the agent tools. Do not invent flags or subcommands beyond that.

## Tools

### list_strategies

Browse the catalogue.

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `limit` | integer | 20 | Maximum number of rows to return |
| `offset` | integer | 0 | Pagination offset |
| `source` | string | none | Optional filter: `alpha_zoo \| sdm`; omit for both |

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
| `include_stale` | boolean | false | Keep rows whose evidence is stale (see Decay & Freshness Contract). They are surfaced with their `stale-evidence:` warnings, sorted after non-stale rows; the flag relaxes the staleness gate only, never any other gate |
| `limit` | integer | 10 | Maximum number of rows to return |

### get_strategy_evidence

Per-regime evidence detail for one strategy.

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `strategy_id` | string | — | Required. Identifier from `list_strategies` / `query_strategies` |
| `regime` | string | none | Optional regime filter (same values as `query_strategies`) |

Returns the per-regime evidence rows: trade count, coverage window, Sharpe, cost breakeven, the decay fields, and the resulting evidence-quality flag. This is an inspection surface — it returns ALL rows for the strategy and never filters.

### refresh_strategy_evidence

Rebuild the disposable evidence cache from local backtest run artifacts. This is the surface's only write; it touches only the facade-owned cache (see Composition Guarantee).

| Parameter | Type | Default | Meaning |
|-----------|------|---------|---------|
| `manifest_path` | string | none | Path to a JSON manifest: an object `{"runs": [...]}` or a bare JSON array of run specs |
| `runs` | array | none | Inline run specs, same shape as the manifest's `runs` array |

Exactly one of `manifest_path` or `runs` is required — supplying both or neither is an error. Each spec is `{strategy_id, run_dir, position_size?}`: a non-empty `strategy_id` (the catalogue identity the evidence belongs to), the `run_dir` of a reproducible backtest run, and an optional `position_size` passed through to the harness. Every entry is hard-gated and path-contained (see Populating & Refreshing Evidence); failing entries are skipped with a stable reason — `hard-gate:*` or `path-outside-allowed-roots:` — while the rest still process. The envelope reports `{status, runs, strategies, rows, skipped}`.

## Evidence Row Contract

Every row is self-describing — the metadata travels with the numbers:

| Field | Meaning |
|-------|---------|
| `evidence_stage` | Pipeline stage that produced the row: `hypothesis` \| `backtest` \| `holdout` \| `shadow` \| `live_canary` \| `retired`. The harness writes only `backtest` today (it computes over backtest artifacts); the other stages are reserved. A row answers "backtest evidence exists; no holdout/shadow/live evidence exists yet" — never more than the stage it carries |
| `provenance` | The reproducible backtest run directory the row was computed from (`artifacts/trades.csv` + `artifacts/equity.csv` inside it). The run directory holds the config and signal engine that produced the figures, so every row is traceable to a reproducible artifact |
| `regime_definition` | JSON naming the regime-labeling parameters used (rolling benchmark window, bear/bull thresholds, Sharpe annualization) — the definition travels with the data, not hidden in code constants |
| `breakeven_fee_bps` | Sizing-corrected cost breakeven, or `null` when the cost screen is unverifiable (see Multi-position caveat) |
| `decay_status` | Freshness verdict computed at read time: `fresh` \| `aging` \| `stale` (see Decay & Freshness Contract). Never stored — derived from the evidence window on every query |
| `evidence_age_days` | Days since the end of the row's latest evidence window; the number that drives `decay_status` |
| `staleness_days` | Days since the row's `last_verified` timestamp. Reported only — never gates anything (see Decay & Freshness Contract) |
| `warnings` | Stable machine-readable prefixes: `insufficient-trades:`, `short-coverage:`, `cost-sensitive:`, `borderline-evidence:`, `multi-position-breakeven:`, `stale-evidence:`, `aged-evidence:`, `sdm-lifecycle:` |

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

## Decay & Freshness Contract

Every returned row carries a freshness verdict computed from the evidence itself at read time — never from model memory, never persisted. The verdict is **freshness-derived**, not performance-derived: it measures how old the evidence window is, not how the strategy is performing. Performance decay (degraded results measured on holdout/shadow/live evidence) arrives with holdout/shadow-stage rows — that ladder is reserved, and no such rows exist yet. Until then, the honest signal is window recency.

Vocabulary and thresholds, applied to `evidence_age_days` (days since the end of the row's latest evidence window):

| `decay_status` | Condition | Meaning |
|----------------|-----------|---------|
| `fresh` | age < 90 days | Evidence window is current; the row participates in recommendations |
| `aging` | 90 ≤ age < 180 days | Window is older than one re-backtest cycle; the row is still returned and recommendable, with an `aged-evidence:` warning |
| `stale` | age ≥ 180 days, or window unparseable | The row is excluded from default recommendations; inspectable via `include_stale=true` or `get_strategy_evidence` |

The 90/180-day thresholds encode the documented **quarterly re-backtest cadence**: a window end more than 90 days old means at least one scheduled re-backtest cycle was missed; more than 180 days means at least two. Exact-threshold ages take the stricter side (`age >= 180` ⇒ stale, else `age >= 90` ⇒ aging, else fresh).

`evidence_age_days` is the only field that drives the verdict. `last_verified` and its derived `staleness_days` are **reported on every row but never gate** — a refresh over unchanged artifacts bumps `last_verified` without moving the evidence window, and gating on it would let a no-op refresh keep old evidence "fresh" forever.

Fail-closed: a row whose evidence window cannot be parsed is `stale`. An unparseable window is never relaxed into a guess.

Stable machine-readable prefixes:

| Prefix | Where it appears | Meaning |
|--------|------------------|---------|
| `stale-evidence:` | row warnings | Window end is missing/unparseable or at least 180 days old; the row is excluded from default recommendations |
| `aged-evidence:` | row warnings | Window end is at least 90 days old; the row is returned but flagged for re-backtest |
| `sdm-lifecycle:` | row warnings / `lifecycle_note` | The `sdm:*` strategy's artifact is decayed or disabled in the SDM store; excluded from recommendations regardless of freshness |
| `hard-gate:*` | refresh envelope `skipped` list | The run failed one of the ingestion hard gates and produced no evidence rows (see Populating & Refreshing Evidence) |

`include_stale` (on `query_strategies`, default `false`) controls the staleness gate only: `true` surfaces staleness-excluded rows with their `stale-evidence:` warnings, sorted after non-stale rows. It does not relax any other gate, and it never affects lifecycle exclusions. Aging rows are never excluded — they carry `aged-evidence:` warnings.

SDM lifecycle mirroring: for rows whose `strategy_id` starts with `sdm:`, the facade looks up the SDM artifact status. `decayed` or `disabled` artifacts are excluded from default recommendations regardless of evidence freshness, with the `sdm-lifecycle:` prefix, and counted separately in the envelope; they remain inspectable via `get_strategy_evidence`. A decayed or disabled SDM artifact is never recommended.

## Populating & Refreshing Evidence

The evidence cache is populated and refreshed through `refresh_strategy_evidence` (agent tool / MCP tool) or the equivalent CLI, `vibe-trading strategy-evidence refresh --manifest <path>`. There is no auto-discovery of runs — population is manifest-first, because runs carry no stable strategy identity of their own (directory names are timestamp+uuid, and an auto-derived id would orphan its rows on every rerun).

Manifest format — a JSON object with a `runs` array, or a bare JSON array of the same specs:

```json
{
  "runs": [
    {"strategy_id": "sdm:my_strategy", "run_dir": "~/.vibe-trading/runs/20260701-123456-abcdef", "position_size": 0.25},
    {"strategy_id": "alpha_zoo:gtja191_171", "run_dir": "~/.vibe-trading/runs/20260702-234567-bcdef0"}
  ]
}
```

Each `run_dir` must resolve inside the runtime runs root or `VIBE_TRADING_ALLOWED_RUN_ROOTS`; entries outside are skipped with `path-outside-allowed-roots:` while the rest still process. Expect manifests in the tens of runs, not thousands — a full rebuild must complete within the tool timeout.

Every run passes five hard gates before it can produce evidence rows — one-to-one with the `backtest-diagnose` skill's Hard-Gate Checklist, in this order:

1. Run status is `success` (`state.json`) → else `hard-gate:exit-nonzero` (a missing `state.json` fails onto the same token)
2. `artifacts/metrics.csv` exists non-empty → else `hard-gate:metrics-missing`
3. `trade_count > 0` → else `hard-gate:zero-trades`
4. `artifacts/equity.csv` exists non-empty → else `hard-gate:equity-empty`
5. The equity series contains no NaN/non-finite value → else `hard-gate:equity-nan`

A run failing any gate produces **no evidence rows** — never partial rows — and is reported in the envelope's `skipped` list with its stable token. The rebuild is atomic: either all computed rows replace the cache in one transaction, or the prior cache survives intact.

**Periodic recipe** (this is what keeps evidence fresh):

1. Re-backtest the strategy over a **recent window** — the window end is what `evidence_age_days` measures
2. `refresh_strategy_evidence` with a manifest naming the new run
3. `query_strategies` — the rows now carry the moved window

Refreshing over unchanged artifacts is legal but limited: it re-verifies and bumps `last_verified`, and can never move the evidence window forward. That is why the recipe starts with a re-backtest, and why `last_verified` never gates.

**Scheduling**: the re-backtest + refresh cadence can run through the existing `/scheduled-runs` mechanism — no new scheduler exists, and its semantics apply. The executor is off by default (`VIBE_TRADING_ENABLE_SCHEDULER=1` enables it); a job status of COMPLETED means the run was enqueued, and FAILED jobs are terminal after repeated failures — check job status rather than assuming a cadence is alive.

**After an upgrade**: the evidence cache is disposable by contract — any cache schema drift drops it, so an upgraded install can start with an empty store. `refresh_strategy_evidence` is how it is repopulated; an empty result is the expected state until the first refresh (see Honest-Empty Semantics).

## Honest-Empty Semantics

The facade refuses regime assessments without computed evidence. If a strategy has no backtest evidence for a regime, `get_strategy_evidence` returns an honest empty for that regime instead of a guess; `query_strategies` likewise never fabricates rows to satisfy a filter.

An empty result is an answer, not an error: it means "no computed evidence exists for this request." The population path is `refresh_strategy_evidence` (agent tool / MCP tool) or `vibe-trading strategy-evidence refresh --manifest <path>` — point a manifest of healthy backtest runs at the cache and the rows appear (see Populating & Refreshing Evidence). Until a refresh has run, an empty store is the expected state after a fresh install or an upgrade. Never relax a threshold or narrate from a scenario tag instead.

## Composition Guarantee

- **Query tools read-only**: `list_strategies`, `query_strategies`, and `get_strategy_evidence` read the Alpha Zoo Registry, the SDM strategy store, and the facade-owned evidence cache DB — and modify nothing in any of them.
- **Refresh tool writes only the disposable cache**: `refresh_strategy_evidence` rebuilds the facade-owned evidence cache DB from local run artifacts, and nothing else. It never writes to the Alpha Zoo registry, the SDM store, or the run artifacts it reads; no network, no credentials, no broker paths.
- **Cache is disposable**: the evidence cache DB is owned by the facade, deletable, and rebuildable from run artifacts plus the two authoritative sources. Its location can be overridden with the `VIBE_TRADING_STRATEGY_DISCOVERY_DB_PATH` environment variable; unset means the default location.
- **No other state**: no network calls, no writes outside the cache, no side effects on the registries it reads.
