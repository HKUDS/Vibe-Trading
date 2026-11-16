"""Shared model guidance for data acquisition; no runtime network interception."""

DATA_ACCESS_POLICY = """## Market Data Tool Policy

Use the unified data gateway for market/research data acquisition. Choose an
available gateway-backed tool first: get_market_data for bars, get_options_chain
for options, or the matching profile, fundamentals, news or screening tool.
Load deferred tool schemas when available; never invent a tool the current
registry/worker does not expose. Reuse returned data and artifact paths.

Plan acquisition before calling: resolve ambiguous or bare stock tickers once
with search_symbol before dependent reads (including option chains). Keep explicit
canonical symbols from the user. Group symbols sharing dates and interval in one
get_market_data call; independent intervals/products can run together. Use the
exact inclusive dates requested, without padding unless the calculation needs
warmup. Fetch enough rows once: for a bounded one-day minute series needed for
computation, request all rows with max_rows=0 instead of fetching a preview and
then the same bars again. For large history use history_data. Inspect truncation
and coverage metadata; never infer completeness from a preview. Reuse artifacts
already covering the task. Combine artifact inspection, calculations and CSV
writing in one Python execution when possible. Once requested outputs exist,
answer concisely; do not add exploratory reads or extra analysis rounds.

Python is for computation on those artifacts by default. Do not substitute raw
requests/httpx, curl, yfinance, Tushare, AKShare or a broker SDK for a supported
gateway read. When a genuinely missing field needs Python, consult data-routing
and use src.market_data.fetch_market_data or src.data_gateway.skill_sources;
custom SDK collectors must use managed_reader (managed_async_reader for async),
materializing results and closing clients inside the callback. Do not spawn
per-symbol processes or independent polling/retry/cache loops: each child would
have its own gateway limits, not share the host process budget. Prefer history_data
for resumable large downloads when available. Keep currency, adjustment, timestamp,
coverage and missing-data diagnostics with the returned observations.

For external MCP public-data reads, prefer the equivalent gateway-backed tool.
A timeout, busy response, cooldown or rate limit is not permission to switch to
raw Python or another MCP route for the same request. Follow the returned recovery
instructions; do not increase deadlines, resource limits or retry counts. A truly
uncovered capability or explicitly requested provider may still use its existing
authorized MCP tool; identify that source and gateway-coverage gap rather than
claiming it was gateway-managed. Preserve broker/account authorization and order
gates; never reinterpret account reads or mutations as public cached data.
"""

SHELL_DATA_GUIDANCE = (
    " For financial data, use gateway-backed tools first, then calculate from "
    "their returned artifact paths. For missing fields consult data-routing and "
    "src.data_gateway.skill_sources/managed_reader; do not bypass gateway "
    "cooldowns with raw SDK/HTTP reads or launch per-symbol fetch processes."
)

MCP_DATA_GUIDANCE = (
    " Public-data reads: prefer equivalent gateway tools; do not bypass cooldowns/"
    "timeouts. For uncovered/requested providers, disclose source and coverage gap. "
    "Existing authorization and remote execution are unchanged."
)
