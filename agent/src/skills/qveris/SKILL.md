---
name: qveris
category: data-source
description: Paid capability marketplace for global multi-asset data; use it when free Vibe-Trading sources lack coverage, depth, or provider quality, and keep free sources as the default for routine OHLCV.
---
# QVeris

QVeris is a paid capability marketplace for global market, fundamental, macro,
derivatives, crypto, China/HK, news, filings, and alternative-data calls. Use it
when the built-in free sources cannot cover the requested dataset, when the user
explicitly asks for QVeris, or when a premium provider is needed for depth such
as options Greeks, analyst/calendar feeds, broad provider comparison, or paid
China/HK/global coverage. For ordinary OHLCV, keep `source: "auto"` on the free
loader chain unless the user explicitly selects `source: "qveris"`.

Signup link: [QVeris via Vibe-Trading](https://qveris.ai/?ref=Vyjjo5G_1cAHJA).
Invite code fallback: `Vyjjo5G_1cAHJA`.

## Workflow

### 1. Discover with `qveris_search`

Call `qveris_search` first. Search is free and returns candidate capabilities
with `tool_id`, provider, parameters, examples, `expected_cost`, billing rule,
categories, and `stats` such as `success_rate` and average execution time.

Good queries are concrete:

- `US listed options chain implied volatility Greeks AAPL`
- `Hong Kong market daily OHLCV financial statements`
- `FRED CPI Treasury yield curve macro series`
- `China A share northbound fund flow daily`

### 2. Inspect with `qveris_inspect`

Call `qveris_inspect` on one or more `tool_id` values before any paid call.
Inspect is free and returns the fuller parameter schema and sample parameters.
Use it to verify required parameters, enum values, date formats, and output
shape before execution.

### 3. Call with `qveris_execute`

Call `qveris_execute` only after the user has enabled QVeris and the tool has
been inspected. Pass the inspected `tool_id`, the exact `parameters`, and a
reasonable `max_response_size`. Use `session_id` and `search_id` when available
so usage can be reconciled later.

## Choosing a Capability

Prefer the candidate with the best combination of:

1. High `stats.success_rate`.
2. Low `expected_cost` for equivalent data.
3. Provider fit for the task: official or specialist sources before generic
   mirrors when the figure matters.
4. Parameter clarity: required fields and examples should match the user's
   requested asset, date range, and granularity.

Do not assume tools with similar names are interchangeable. The measured catalog
has very large quality variance inside the same category; design notes recorded
FMP tools ranging from near-zero to 100% success and some tradefeeds tools at
0%. Surface `success_rate` and `expected_cost` in the answer whenever the user is
choosing among paid options.

## Billing and Modes

- The default free route is Vibe-Trading's built-in public data stack; QVeris
  tools are unavailable in `mode="free"`.
- Discover (`qveris_search`) and inspect (`qveris_inspect`) are free only after
  the user explicitly enables the paid QVeris route.
- Execute (`qveris_execute`) is paid only when the provider call is billable.
- Failed calls, empty results, and parameter errors are not charged by the
  QVeris contract; observed missing-parameter calls returned `success=false`,
  `cost=0.0`, `status=not_charged`, and unchanged balance.
- `mode="free"` means the original free public-data path stays active and
  QVeris is hidden from agent/tool/backtest routing.
- `mode="paid"` permits QVeris discovery, inspect, and execute calls, bounded by
  `budget_credits_per_session`.
- Never hide cost: every successful execute result should preserve `cost` and
  `remaining_credits` for the user.

Configuration can come from `QVERIS_API_KEY` / `QVERIS_BASE_URL`, or from
Settings -> QVeris / `vibe-trading data mode paid`. If QVeris is disabled, in
free mode, or no API key is configured, the tools should be treated as
unavailable.

## Truncation

`qveris_execute` accepts `max_response_size` (`20480` default, `-1` means do not
ask QVeris to truncate). When a response is too large, QVeris returns a result
object containing a message, `truncated_content`, and `full_content_file_url`.
If the full JSON is required, fetch that signed URL and use the full payload.
If a summary is enough, cite that the response was truncated and work only from
`truncated_content`.

## Balance and Usage

Check balance and recent usage through:

- Web: Settings -> QVeris.
- CLI: `vibe-trading data status` or `vibe-trading data usage`.
- Agent/API tools: status is derived from free search/ledger/usage endpoints.

For reconciliation, prefer `execution_id`, `tool_id`, `charge_outcome`, `cost`,
and `remaining_credits` over text summaries.

## References

- [REST API reference](references/rest-api.md)
- [Coverage map](references/coverage.md)
