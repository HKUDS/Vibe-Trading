# Research workflows and examples

## ⚡ Quick Example

```bash
# After CLI installation and provider setup
# Natural-language research
vibe-trading run -p "Backtest a BTC-USDT 20/50 moving-average strategy for 2024, summarize return and drawdown, then export the report"

# Bench a pre-built alpha zoo (one line)
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

For a trade journal, [attach the broker export or pass its uploaded path](#upload--analyze-documents).

### Pixel Office management

Open **Pixel Office** from the feature menu to plan and assign research tasks.
The Web page, `vibe-trading office` CLI and `pixel_office` agent tool share one
SQLite task board under your runtime directory. Assignment does not start
execution; organizational ranks grant no trading permissions. Record the actual
result when completing a task. See [Pixel Office](../pixel-office/README.md) for CLI
and API examples.

## 🧪 Research Workflow

Most runs follow the same evidence path: route the request, load the right market context, execute tools, validate outputs, and keep the artifacts inspectable.

The agent stops with a visible recovery request after eight consecutive tool-call
iterations without a new successful observation. Repeating the same read result
or a failed call does not reset this budget. An identical call is refused from
its SECOND failure onward — one retry after a transient failure (a rate limit, a
network blip, a tool timeout) still runs — until a successful state-changing tool
executes or a new run starts; changed arguments can always execute. The recovery
asks for an artifact path or permission to rerun the missing research step, and
the run remains failed even if older metrics exist. This guard is separate from
the wall-clock activity watchdog.

| Layer | What happens |
|-------|--------------|
| **Plan** | Selects the relevant finance skills, tools, data sources, and swarm preset when useful. |
| **Ground** | Pulls A-shares, HK/US/Canada/UK equities, crypto, futures, forex, documents, or web context through the available loaders. |
| **Execute** | Generates testable strategy code, runs tools, and uses the matching backtest engine or analysis workflow. |
| **Validate** | Adds metrics, benchmark comparison, Monte Carlo, Bootstrap, Walk-Forward, run cards, and warnings where applicable. |
| **Deliver** | Returns reports, artifacts, tool traces, and exports for TradingView, TDX, MetaTrader 5, MCP clients, or later sessions. |

### Versioned research artifacts

**Since 0.1.19.** Earlier packages predate versioned research artifacts.

Completed analyses can be saved as immutable revisions with their subject, universe, data-as-of date, evidence references, verification status, and optional hypothesis, goal, session, or run links. Repeating identical content and provenance returns the existing revision; changed evidence or a new data-as-of date appends a linked revision instead of overwriting the old conclusion. Search returns the latest revision of each series, while the full history remains available in the Web research-artifact library, API, agent tools, and CLI. Historical content is never presented as newly revalidated.

```bash
vibe-trading research-artifact save --subject "NVDA fundamental review" --content "Conclusion with evidence." --data-as-of 2026-10-27 --evidence '[{"source_uri":"https://example.com/filing"}]'
vibe-trading research-artifact search --query "NVDA"
```

## 💡 Examples

### Strategy & Backtesting

**Daily paper trading** is available in the Web sidebar (`/paper-trading`),
`vibe-trading paper`, and the authenticated `/api/paper-accounts` API. Start today
or next session with configurable cash/positions; settle completed daily bars
and inspect fills, rejections and NAV history. Strategy history stops before the
execution date, and each day receives the ledger after preceding fills. The
agent/MCP `paper_trade_step` remains a stateless research primitive.

**Five-minute A-share simulation (since 0.1.19).** `paper_trade_step` accepts `interval="5m"`. Saved paper accounts still settle daily. Each step covers one
completed session and matches bar by bar against its 48 continuous five-minute
bars. The 09:30 label is the opening
call-auction print, single-priced on 4 of 5 probed days, and is excluded by
policy; labels in 09:15-09:25 or from 14:57 up to but not including 15:00 are
auction-window anomalies, and 15:00 is a continuous bar. The 5m leg uses Tushare
`stk_mins`, separate from the daily chain, which serves daily bars only. It
accepts one order symbol per step: the measured provider budget is 1
call/minute, 1 call/hour and 2 calls/day, and a refused call still consumes the
daily budget. It fills all-or-none at each bar's `path_model` reference
(`bar_median` or `bar_close`) and requires a non-empty `UNIVERSE` in strategy
mode. `session`,
`path_model` and `fill_model` default to the daily behaviour, so every existing
call is unchanged; `session` is a coherence selector only (`cn_a` requires
`market="cn_a"`) and does not change the day boundary.

Known limits: a mid-range zero-calendar (HK/US) weekday with no bar for any
symbol is inferred closed (`market_closed_inferred` with a warning) with no NAV
row, its orders reject `suspended` and positions carry the last available close
forward; an all-market zero bar on the target day is `PAPER_DATA_NOT_READY`
(retryable), and
a saved account advance reports `committed: false` instead of moving the
watermark. The provider's bar count is authoritative: a partial session still
fills with its `N/48` coverage warning. Payload faults fail closed: off-grid
labels (for example a 1m payload served as 5m) and all-NaN continuous bars are
`PAPER_DATA_NOT_READY`, while a zero-volume session is a halt. A 5m step with no
orders issues no `stk_mins` request and follows the 1d valuation contract: it
needs the target daily bar and values from that day's closes. The persistent v1.2
runner/account/store layer is a follow-up branch (`paper-trade-v12-persistence`)
and is not wired to any CLI, API or MCP surface in this PR.

Execution uses raw prices (Tencent raw for A-shares/HK, raw-capable US providers;
Tushare `stk_mins` for the A-share 5m leg). A-shares require a complete ClickHouse
calendar. Unavailable data/calendar and
unverified split-like events fail visibly without committing a saved ledger;
price/volume ratios never authorize multiplying a position. Cash dividends and
automatic corporate-action reconciliation are not implemented. See the
[paper-trading guide](../agent/src/tools/paper_trade/README.md) for CLI/API examples and model limits.

Daily-engine backtests report engine-specific unused settings in the run-card
warnings. For example, crypto reads `maker_rate` and `taker_rate`, so supplying
the A-share `commission_rate` setting warns instead of silently implying that
it configured crypto fees. Shared runner/loader settings and keys read by a
composite engine's selected sub-engines remain accepted. This conservative
source-reader check does not trace conditional branches inside an engine and
does not change options-engine configuration handling.

Average holding period includes completed same-bar trades (zero bars). The
existing `avg_holding_days` compatibility key reports the engine's holding-bar
measure; it is not a conversion to calendar days.

Standalone revalidation (`python -m backtest.validation <run_dir>`) runs all
three validation tools using saved `config.json` validation parameters; missing
parameters use the existing defaults. This includes simulation counts, seeds,
bootstrap confidence, and walk-forward window count.

New BaseEngine `artifacts/trades.csv` files include an `event` column:
`entry` marks an opening row and `exit` marks a completed trade, including
zero-PnL exits. Validation and strategy-discovery readers use this marker.
Files without it retain legacy loading; their zero-PnL exits remain ambiguous.
The separate options-engine trade format is unchanged. Validation also recovers entry dates from
matching adjacent `entry`/`exit` rows, so walk-forward trade counts and win rates
retain entry-window attribution after reload. Unmarked or unmatched rows keep
the legacy timestamp fallback.

```bash
# Moving average crossover on US equities
vibe-trading run -p "Backtest a 20/50-day moving average crossover on AAPL for the past year, show Sharpe ratio and max drawdown"

# RSI mean-reversion on crypto
vibe-trading run -p "Test RSI(14) mean-reversion on BTC-USDT: buy below 30, sell above 70, last 6 months"

# Multi-factor strategy on A-shares
vibe-trading run -p "Backtest a momentum + value + quality multi-factor strategy on CSI 300 constituents over 2 years"

# After backtesting, export to TradingView / TDX / MetaTrader 5
vibe-trading --pine <run_id>
```

For calendar-triggered partial rebalancing, keep the strategy signal dense and
select execution bars in `config.json`:

```json
{
  "position_adjustment": "rebalance",
  "rebalance_mask": "MS"
}
```

Backtest run cards record the provider and model that wrote `config.json` and
`code/signal_engine.py`. Set `model_training_cutoff` in `config.json` to an
ISO date to record the model's cutoff; a window ending earlier is marked as
potentially exposed, and an unset cutoff is treated as unknown and exposed.
For strict factor benchmarks, pass `--training-cutoff YYYY-MM-DD` to
`vibe-trading alpha bench --strict` to place the out-of-sample segment strictly
after the cutoff.

`MS` executes the aligned target on the first observed trading bar of each
month. Weekly/quarterly pandas offset aliases (for example `W-FRI` and `QS`) and
explicit ISO date lists are also accepted. An alias must not be finer than the
aligned bar interval. Period aliases select the first observed bar in each
period; `W-FRI` starts a Friday-anchored week and therefore normally executes
on the following Monday, not on Friday itself. Omit `rebalance_mask` to
preserve the existing every-bar rebalance behavior. A mask is deliberately
incompatible with `position_adjustment="hold"`.

**Bench a pre-built alpha zoo** (one line):
```bash
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 --top 20
```

Bench results also carry `meta.data_availability`, a field-level contract for
the loaded inputs. It records the market adapter, venue, currency, calendar,
observed window, serving source, validation coverage, and an explicit status:
`verified`, `assumed`, `unknown`, or `failed`. Date-only fundamental filings
remain `unknown` when the source does not expose a publication timestamp, even
when the bench applies its protective one-bar lag; consumers must not treat
them as PIT-safe. New markets can register an adapter without changing this
wire shape.

Bench results also carry `meta.research`, the versioned factor-research run
contract (`factor-research.run/v1`). It records the declared research stage,
factor IDs, input lineage, transformations and evaluation settings so a result
can be traced from Alpha Zoo inputs through later research steps. The CLI can
label a run with `--research-stage`, for example:

```bash
vibe-trading alpha bench --zoo gtja191 --universe csi300 --period 2018-2025 \
  --research-stage factor_screening
```

The v1 contract is additive provenance metadata. Its `explore`, `strict` and
`locked` values describe research intent; they do not by themselves reject
unknown data or enforce a locked test set. Those checks remain separate from
the existing availability contract until a future policy layer enables them.

**Browse the catalogue** and inspect a single alpha:
```bash
vibe-trading alpha list --zoo gtja191 --theme reversal --limit 10
vibe-trading alpha show gtja191_171
```

**Compose a multi-factor signal** from the zoo (Python):
```python
from src.skills.multi_factor.zoo_signal_engine import ZooSignalEngine
engine = ZooSignalEngine.from_zoo(["gtja191_171", "gtja191_111", "gtja191_163"])
panel = ...  # your wide OHLCV panel
signal = engine.compute_signal(panel)
```

Correlation market inference recognizes explicit crypto pairs; bare equity tickers such as `ABNB` and `SOL` use the US equity data chain.

### Trade journal fees

Journal PnL includes recorded fees. When one fill closes a position and opens
an opposite position, its fee is split by quantity between the two legs.
Profile win rate and the average-win/average-loss ratio use the resulting net
PnL of FIFO matched portions; those portions are not necessarily whole orders.

Generic journals accept a complete `datetime` column or separate `date` and
`time` columns (case-insensitive). Split columns are combined before sorting
and FIFO matching; Excel date serials and time fractions are supported.
A complete `datetime` column takes precedence when all three are present.
Journal analysis rejects missing or invalid dates in any parsed record,
including dividends, before applying filters. Correct those dates and retry.
Buy/sell records also require finite, positive quantities before any filter is
applied; correct missing or invalid quantities and retry. Cash dividends may
have zero quantity.
Rows with equal timestamps retain their source-file order for FIFO matching.
This preserves the supplied sequence; it does not reconstruct missing fill order.

### Market Research

```bash
# Equity deep-dive
vibe-trading run -p "Research NVDA: earnings trend, analyst consensus, option flow, and key risks for next quarter"

# Macro analysis
vibe-trading run -p "Analyze the current Fed rate path, USD strength, and impact on EM equities and gold"

# Crypto on-chain
vibe-trading run -p "Deep dive BTC on-chain: whale flows, exchange balances, miner activity, and funding rates"
```

### Swarm Workflows

```bash
# Bull/bear debate on a stock
vibe-trading --swarm-run investment_committee '{"target":"TSLA","market":"US"}'

# Quant strategy from screening to backtest
vibe-trading --swarm-run quant_strategy_desk '{"universe": "S&P 500", "horizon": "3 months"}'

# Crypto desk: funding + liquidation + flow → risk manager
vibe-trading --swarm-run crypto_trading_desk '{"asset": "ETH-USDT", "timeframe": "1w"}'

# Global macro portfolio allocation
vibe-trading --swarm-run macro_rates_fx_desk '{"focus": "Fed pivot impact on EM bonds"}'

# Resume a failed or cancelled run while keeping its completed tasks
vibe-trading --swarm-retry <run_id> --swarm-resume
```

Each Swarm task keeps its reports, summary and message log under
`artifacts/<agent_id>/<task_id>/`, so tasks assigned to the same agent retain
their own output during sequential or parallel execution. Retrying a task clears
only that task's output; completed task artifacts remain available to downstream
workers. Resume also preserves artifacts recorded by older runs.

### Cross-Session Memory

```bash
# Save your preferences once
vibe-trading run -p "Remember: I prefer RSI-based strategies, max 10% drawdown, hold period 5–20 days"

# The agent recalls them in future sessions automatically
vibe-trading run -p "Build a crypto strategy that fits my risk profile"
```

### Upload & Analyze Documents

In Web chat, attach a broker export or earnings report and send your question in the same message. The picker, drag-and-drop and clipboard paste support up to five files per message.

From the CLI, upload the file first. The command prints its saved path with a generated filename.

```bash
vibe-trading --upload trades_export.csv
```

For example, if the printed path ends in `uploads/012345abcdef.csv`, use the following prompt. Replace the example filename with the one your upload returned.

```bash
vibe-trading run -p "Read uploads/012345abcdef.csv, profile my trading behavior and compare it with my shadow strategy."
```

For an earnings report, upload the PDF and use its returned path in the same way. Quoted figures are checked against the source document.
