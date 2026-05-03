---
name: ashare-financial-enrichment
description: A-share financial statement enrichment flow — gate, plan, and request only the required Tushare financial tables and fields with strict ann_date-based point-in-time visibility.
category: flow
---
# A-share Financial Enrichment

## Purpose

This skill governs how an A-share strategy may use Tushare financial statement data.

It does **not** directly replace `strategy-generate`. Instead, it defines the mandatory gate before a strategy may rely on fields from:

- `income`
- `balancesheet`
- `cashflow`
- `express`
- `fina_indicator`

## When To Use

Use this skill only when **both** conditions are true:

1. The strategy is for **China A-shares**.
2. The strategy logic uses at least one field from the five Tushare financial tables above.

Do **not** use this skill when:

- the strategy is not A-share
- the strategy only uses OHLCV
- the strategy only uses the existing `daily_basic`-style fields already supported by the backtest loader (`pe`, `pb`, `pe_ttm`, `ps_ttm`, `dv_ttm`, `total_mv`, `circ_mv`, `roe`)

## Mandatory Gate

Before loading or planning any financial statement data, always execute this gate in order.

### Step 1: Confirm market

The strategy must clearly target A-shares.

Accepted indicators include:

- explicit China A-share wording
- stock codes matching `000001.SZ`, `600519.SH`, `300750.SZ`, and similar patterns
- `source="tushare"` or an explicit A-share universe

If the strategy is not clearly A-share, stop and ask the user.

### Step 2: Confirm actual need for statement fields

Only continue if the strategy truly needs fields from one or more of these tables:

- `income`
- `balancesheet`
- `cashflow`
- `express`
- `fina_indicator`

Examples that **do** trigger this flow:

- revenue growth
- balance-sheet leverage items
- cash-flow quality items
- express-based preliminary results
- profitability or margin fields that come from `fina_indicator`

Examples that **do not** trigger this flow:

- `pe`, `pb`, `pe_ttm`, `roe`, `total_mv` from `daily_basic`
- technical indicators computed from OHLCV only

### Step 3: Confirm `TUSHARE_TOKEN`

If this flow is triggered, `TUSHARE_TOKEN` is mandatory.

If `TUSHARE_TOKEN` is missing:

- state that A-share financial statement enrichment cannot proceed yet
- do **not** silently downgrade to AKShare
- do **not** silently rewrite the strategy into a different data regime
- wait for the user's decision

### Step 4: Check Tushare points for the planned runtime mode

When this flow is triggered, the point thresholds are:

- below 2000 points: stop, because the ordinary financial table interfaces are not available
- 2000-4999 points: financial-table backtests may still run, but full-market or universe requests must fall back to slower per-code fetching
- 5000 points and above: VIP period cross-sections are available and should be preferred for full-market or universe backtests

Implementation note:

- `0` points is a valid parsed account result, but it is below the minimum gate and must not be treated as an unknown capability state

### Step 5: Build a minimal field plan

When the gate passes, request only the necessary tables and fields.

The plan must answer:

- which tables are needed
- which exact fields are needed from each table
- whether the strategy also needs ordinary A-share `daily_basic` fields
- whether the request is expected to run in slower per-code mode or VIP cross-sectional mode based on the current 2000 / 5000 point tier

Never request all columns from all tables by default.

## Supported Tables

This flow covers these five Tushare tables only:

| Table | Tushare Doc | Typical Use |
|------|-------------|-------------|
| `income` | `doc_id=33` | revenue, profit, expense, R&D, EBIT/EBITDA |
| `balancesheet` | `doc_id=36` | assets, liabilities, equity, cash, debt, inventory |
| `cashflow` | `doc_id=44` | operating / investing / financing cash flow, FCF |
| `express` | `doc_id=46` | preliminary performance snapshots |
| `fina_indicator` | `doc_id=79` | profitability, margin, growth, turnover, leverage ratios |

## Authoritative Local References

The current project already includes the field definitions for these tables under the local Tushare reference tree.

When deciding which table a field belongs to, or which columns are available, use these local reference files as the primary source of truth:

- `income`
  - repo path: `agent/src/skills/tushare/references/股票数据/财务数据/利润表.md`
  - MCP `read_file` path: `skills/tushare/references/股票数据/财务数据/利润表.md`
- `balancesheet`
  - repo path: `agent/src/skills/tushare/references/股票数据/财务数据/资产负债表.md`
  - MCP `read_file` path: `skills/tushare/references/股票数据/财务数据/资产负债表.md`
- `cashflow`
  - repo path: `agent/src/skills/tushare/references/股票数据/财务数据/现金流量表.md`
  - MCP `read_file` path: `skills/tushare/references/股票数据/财务数据/现金流量表.md`
- `express`
  - repo path: `agent/src/skills/tushare/references/股票数据/财务数据/业绩快报.md`
  - MCP `read_file` path: `skills/tushare/references/股票数据/财务数据/业绩快报.md`
- `fina_indicator`
  - repo path: `agent/src/skills/tushare/references/股票数据/财务数据/财务指标数据.md`
  - MCP `read_file` path: `skills/tushare/references/股票数据/财务数据/财务指标数据.md`

Practical rule:

- Use the local reference files first to confirm field names, parameter names, key columns, and table ownership.
- When using an MCP client such as opencode, do not assume Markdown link targets will be resolved automatically; use the explicit `MCP read_file` paths above.
- Use the public Tushare web docs only as a secondary cross-check when the local reference appears outdated or ambiguous.
- Do not invent field names when a field cannot be found in the local reference.

## ann_date Rule

This is the most important rule in the entire flow.

For every table in this skill, assume:

- financial data becomes visible only **after** its `ann_date`
- `period` / `end_date` is the report period, not the market availability date
- two stocks with the same `period` may still become visible on different dates because their `ann_date` values differ

Conservative point-in-time rule:

- treat the data as unavailable before `ann_date`
- for daily backtests, treat the data as usable only from the **next trading day after `ann_date`**

Never expose a financial field earlier just because a quarter ended on `0331`, `0630`, `0930`, or `1231`.

## Decision Matrix

| Scenario | Action |
|---------|--------|
| A-share + no statement fields | Stay in normal strategy flow |
| A-share + statement fields + token available | Continue with this skill |
| A-share + statement fields + token missing | Stop, explain, wait for user |
| Non-A-share + statement fields | Explain current limitation, wait for user |

## Output Requirements For The Planner

When this skill is triggered, the planner should produce a compact plan with:

1. A-share confirmation
2. required financial tables
3. required fields per table
4. confirmation that `TUSHARE_TOKEN` is available
5. explicit note that point-in-time visibility must follow `ann_date`
6. explicit note about the current Tushare point tier and whether the run needs slower per-code fallback or can use VIP cross-sections

Example:

```json
{
  "market": "a_share",
  "financial_statement_flow": true,
  "required_tables": {
    "income": ["revenue", "operate_profit"],
    "cashflow": ["n_cashflow_act", "free_cashflow"],
    "fina_indicator": ["grossprofit_margin", "roe", "ocfps"]
  },
  "requires_tushare_token": true,
  "availability_rule": "ann_date_next_trade_day",
  "point_tier_note": "2000-4999 points uses slower per-code fetch; 5000+ points can use VIP cross-sections"
}
```

## Failure Handling

When blocked, the response must be explicit and must not continue automatically.

### Token missing

Say:

- the strategy requires A-share financial statement data
- this flow requires `TUSHARE_TOKEN`
- the current run cannot proceed under the required data regime
- wait for the user's decision

### Non-A-share request

Say:

- this financial statement enrichment flow currently applies only to A-shares
- the requested market is not yet supported under this flow
- wait for the user's decision

## Notes

- This skill is about gating and data planning, not about rewriting the `SignalEngine` contract.
- The strategy may still use a normal `SignalEngine.generate(data_map)` implementation after the financial fields are prepared by the runtime.
- Do not collapse this flow back into generic `extra_fields`; the data source semantics are different.