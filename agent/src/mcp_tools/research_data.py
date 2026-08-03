"""MCP read-only fundamentals, flow, news & discovery tools.

Each wrapper delegates to the auto-discovered local registry, exactly like
factor_analysis / pattern_recognition in ``analysis.py``. The registry returns
a clean JSON error envelope when a key-gated tool (get_macro_series needs
FRED_API_KEY, iwencai_search needs VIBE_TRADING_IWENCAI_KEY) is absent — see
``_execute_key_gated`` below, which honours that contract even though the tool
is excluded from the registry by ``check_available()``. Every tool here is
strictly read-only data — no order/trading tool is ever surfaced via MCP.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from src.mcp_tools._shared import clean_list, get_registry


# Map of key-gated MCP tools to their concrete tool class. When the required
# API key is unset the class' ``check_available()`` returns False, so the tool
# is excluded from the auto-discovered registry and ``registry.execute`` would
# answer with a generic "Tool not found". That contradicts the documented
# contract above (a clean, env-var-named error). For these tools we therefore
# fall through to the tool's own ``execute()`` — whose missing-key envelope
# names the exact env var (``FRED_API_KEY`` / ``VIBE_TRADING_IWENCAI_KEY``).
def _key_gated_tool_classes() -> dict[str, Any]:
    """Return the {tool_name: tool_class} map for key-gated MCP tools.

    Imported lazily so a missing optional dependency in either module degrades
    to the registry path rather than breaking module import.
    """
    from src.tools.fred_macro_tool import FredMacroTool
    from src.tools.iwencai_tool import IWenCaiSearchTool

    return {
        "get_macro_series": FredMacroTool,
        "iwencai_search": IWenCaiSearchTool,
    }


def _execute_key_gated(name: str, params: dict[str, Any]) -> str:
    """Run a key-gated read-only tool, preserving its env-var-named error.

    Prefers the auto-discovered registry (present when the API key is set). When
    the key is absent the tool is excluded from the registry, so we invoke its
    concrete ``execute()`` directly to surface the documented missing-key error
    that names the exact env var — never a generic "Tool not found".
    """
    registry = get_registry()
    if registry.get(name) is not None:
        return registry.execute(name, params)
    tool_cls = _key_gated_tool_classes().get(name)
    if tool_cls is None:
        return registry.execute(name, params)
    return tool_cls().execute(**params)


def get_fund_flow(codes: list[str], period: str = "daily", days: int = 30) -> str:
    """Fetch order-bucket net capital inflow (main/super-large/large/medium/small).

    Markets: A-share (.SH/.SZ/.BJ), Hong Kong (.HK) and US (.US). Use this to
    gauge whether large/main-force money is flowing in or out, as daily history
    or the current session's per-minute line. One unresolvable symbol is
    reported per-symbol and does not abort the batch.

    Args:
        codes: Symbols with market suffix, e.g. ["600519.SH", "00700.HK"].
        period: "daily" (daily net-inflow history) or "min" (per-minute line).
        days: For period="daily", number of most-recent daily bars to keep.
    """
    registry = get_registry()
    return registry.execute("get_fund_flow", {"codes": codes, "period": period, "days": days})


def get_dragon_tiger(date: str, code: str | None = None) -> str:
    """Fetch the A-share dragon-tiger board (龙虎榜) for a trade date (Eastmoney).

    Markets: China A-share (SH/SZ). Omit ``code`` for the full-market list of
    every security on the board that day; supply ``code`` to also get that
    security's ranked top buy/sell brokerage seats. Read-only, no auth.

    Args:
        date: Trade date in YYYY-MM-DD format (e.g. 2024-01-02).
        code: Optional A-share symbol or bare code (e.g. "600519.SH" or "600519").
    """
    params: dict[str, Any] = {"date": date}
    if code:
        params["code"] = code
    registry = get_registry()
    return registry.execute("get_dragon_tiger", params)


def get_northbound_flow(lookback_days: int = 30) -> str:
    """Fetch Northbound (Stock-Connect) net capital flow for China A-shares.

    Returns the latest realtime net inflow plus recent daily history, split into
    Shanghai-Connect (沪股通) and Shenzhen-Connect (深股通) channels (units: 10k
    CNY) from Eastmoney. Read-only; China A-share market only.

    Args:
        lookback_days: Trailing trading days of daily net-inflow history to return.
    """
    registry = get_registry()
    return registry.execute("get_northbound_flow", {"lookback_days": lookback_days})


def get_margin_trading(code: str, days: int = 30) -> str:
    """Fetch an A-share stock's daily margin-trading (融资融券) balances (Eastmoney).

    Returns outstanding financing balance, financing buy amount,
    securities-lending balance, and combined RZRQ balance, one row per trading
    day (most recent first). Read-only, no credentials, A-shares only (SH/SZ).

    Args:
        code: A-share code: bare ("600519"), suffixed ("600519.SH"), or
            exchange-prefixed ("sh600519").
        days: Number of most-recent trading days to return.
    """
    registry = get_registry()
    return registry.execute("get_margin_trading", {"code": code, "days": days})


def get_block_trades(code: str, days: int = 30) -> str:
    """Fetch recent A-share block trades (大宗交易) for one symbol (Eastmoney).

    Returns per-deal price, volume, amount, the premium/discount versus that
    day's close, and the buyer/seller broker seats (营业部). Markets: China
    A-share only (.SH/.SZ/.BJ). Read-only.

    Args:
        code: A-share symbol with exchange suffix, e.g. "600519.SH", "830799.BJ".
        days: Lookback window in calendar days ending today.
    """
    registry = get_registry()
    return registry.execute("get_block_trades", {"code": code, "days": days})


def get_shareholder_count(code: str, max_periods: int = 24) -> str:
    """Fetch mainland A-share quarterly shareholder count (股东户数) (Eastmoney).

    Returns holder count per report period, quarter-over-quarter change
    (absolute and percent), and average holding (shares and market value) per
    account. Markets: China A-shares only (.SH/.SZ/.BJ).

    Args:
        code: A-share symbol in <code>.<exchange> form (SH/SZ/BJ).
        max_periods: Maximum number of most-recent report periods to return.
    """
    registry = get_registry()
    return registry.execute("get_shareholder_count", {"code": code, "max_periods": max_periods})


def get_lockup_expiry(code: str | None = None, horizon_days: int = 90) -> str:
    """Fetch Chinese A-share lockup-expiry (restricted-share unlock, 限售解禁) data.

    Pass an A-share ``code`` to get that stock's full historical unlock
    schedule, or omit it for a market-wide calendar of upcoming unlocks within
    the next ``horizon_days`` (Eastmoney). A large near-term unlock adds
    tradable supply and often pressures the stock. Read-only.

    Args:
        code: A-share symbol (e.g. "600519", "600519.SH"). Omit for a
            market-wide upcoming-unlock calendar.
        horizon_days: Upcoming-unlock window in days for the market-wide
            calendar; ignored when ``code`` is given (full history is returned).
    """
    params: dict[str, Any] = {"horizon_days": horizon_days}
    if code:
        params["code"] = code
    registry = get_registry()
    return registry.execute("get_lockup_expiry", params)


def get_sector_info(code: str | None = None, mode: str = "membership", limit: int = 30) -> str:
    """Look up Chinese A-share sector / concept board info (Eastmoney, no auth).

    Two modes: (1) membership — given a stock ``code``, list the industry and
    concept boards it belongs to; (2) ranking — set ``mode="ranking"`` to rank
    industry boards by today's percent change (with up/down constituent counts
    and the leading stock). Market: A-share stocks.

    Args:
        code: A-share stock symbol with market suffix. Required when
            mode="membership"; ignored when mode="ranking".
        mode: "membership" (default) or "ranking".
        limit: For mode="ranking", number of top boards to return.
    """
    params: dict[str, Any] = {"mode": mode, "limit": limit}
    if code:
        params["code"] = code
    registry = get_registry()
    return registry.execute("get_sector_info", params)


def get_research_reports(code: str, limit: int = 20) -> str:
    """Fetch mainland A-share sell-side research coverage and consensus forecasts.

    Returns recent broker research reports (title, brokerage, analyst, publish
    date, rating) with each broker's per-year EPS and PE forecasts from
    Eastmoney, plus the market consensus (mean) EPS forecast per forward fiscal
    year from THS (同花顺). Markets: China A-shares only (.SH/.SZ/.BJ).

    Args:
        code: A-share symbol in <code>.<exchange> form (SH/SZ/BJ).
        limit: Maximum number of most-recent research reports to return.
    """
    registry = get_registry()
    return registry.execute("get_research_reports", {"code": code, "limit": limit})


def get_stock_news(code: str | None = None, scope: str = "stock", limit: int = 20) -> str:
    """Fetch recent financial news headlines, read-only and no auth.

    Markets: China A-share (SH/SZ/BJ) headlines from Eastmoney; US (.US) and
    Hong Kong (.HK) related-instrument matches from Yahoo Finance. Use scope
    "stock" with a ``code`` for one security's headlines, or scope "global"
    (no code) for broad China-market finance news.

    Args:
        code: Symbol whose news to fetch (e.g. "600519.SH", "AAPL.US").
            Required when scope="stock"; ignored when scope="global".
        scope: "stock" (default) or "global".
        limit: Maximum number of headlines to return.
    """
    params: dict[str, Any] = {"scope": scope, "limit": limit}
    if code:
        params["code"] = code
    registry = get_registry()
    return registry.execute("get_stock_news", params)


def get_sec_filings(
    ticker: str,
    form: str | None = None,
    metric: str | None = None,
    limit: int = 20,
) -> str:
    """Fetch U.S. SEC EDGAR filings or reported XBRL financials for a company.

    Returns a list of recent filings (10-K / 10-Q / 8-K, etc.) with accession
    number, filing and report dates, and the primary-document URL; or, when
    ``metric`` is given, the reported XBRL us-gaap financial series for that
    concept (e.g. Revenues, NetIncomeLoss, Assets). Markets: United States only.

    Args:
        ticker: U.S. equity ticker, case-insensitive (e.g. "AAPL").
        form: Optional SEC form type filter (e.g. "10-K", "10-Q", "8-K").
        metric: Optional XBRL us-gaap concept name (e.g. "Revenues").
        limit: Maximum number of most-recent filings and metric points to return.
    """
    params: dict[str, Any] = {"ticker": ticker, "limit": limit}
    if form:
        params["form"] = form
    if metric:
        params["metric"] = metric
    registry = get_registry()
    return registry.execute("get_sec_filings", params)


def get_financial_statements(code: str, statement: str = "indicators", period: str = "annual") -> str:
    """Fetch a stock's financial statements or key per-period indicators.

    Markets: A-share (.SH/.SZ/.BJ, via Sina), US (.US) and Hong Kong (.HK, via
    Eastmoney). Reports come back newest-first as flat per-period rows. Use this
    to read fundamentals before building a valuation or screen.

    Args:
        code: Single symbol with a market suffix (e.g. "600519.SH", "AAPL.US").
        statement: "balance", "income", "cashflow", or "indicators".
        period: "annual" or "quarter".
    """
    registry = get_registry()
    return registry.execute(
        "get_financial_statements",
        {"code": code, "statement": statement, "period": period},
    )


def get_options_chain(ticker: str, expiration: int | None = None) -> str:
    """Fetch the US-listed options chain (calls and puts) for one expiration.

    Returns per-contract strike, bid/ask, last price, volume, open interest,
    implied volatility, and in-the-money flag, plus the list of available
    expirations (epoch seconds) via Yahoo Finance. Read-only US options data.

    Args:
        ticker: US underlying symbol (e.g. "AAPL" or "AAPL.US").
        expiration: Optional expiration as Unix epoch seconds (one of the
            returned expirations). Omit for the nearest expiration.
    """
    params: dict[str, Any] = {"ticker": ticker}
    if expiration is not None:
        params["expiration"] = expiration
    registry = get_registry()
    return registry.execute("get_options_chain", params)


def get_stock_profile(ticker: str, sections: list[str] | None = None) -> str:
    """Fetch a read-only company profile for a US or HK listing (Yahoo Finance).

    Returns valuation key statistics, analyst price targets and
    earnings/revenue estimates, institutional and insider ownership, and the
    analyst recommendation trend. Use this for fundamentals and consensus
    context, not for OHLCV price bars (use get_market_data).

    Args:
        ticker: US (bare or .US suffix) or HK (zero-padded .HK code) symbol.
        sections: Profile sections to return, any of: key_stats, financials,
            earnings_trend, institution_ownership, insider_holders,
            recommendation_trend. Defaults to all sections.
    """
    params: dict[str, Any] = {"ticker": ticker}
    clean_sections = clean_list(sections)
    if clean_sections:
        params["sections"] = clean_sections
    registry = get_registry()
    return registry.execute("get_stock_profile", params)


def screen_market(market: str, sort_by: str = "change_pct", top_n: int = 30) -> str:
    """Screen a market's listed instruments and rank the top names by a metric.

    Use this to find today's biggest movers or most-actively-traded names
    without fetching every symbol. Markets: A-share ("a"), US ("us"), Hong
    Kong ("hk").

    Args:
        market: Market universe: "a", "us", or "hk".
        sort_by: Ranking metric (descending): "change_pct", "volume",
            "amount", or "turnover".
        top_n: Number of top-ranked instruments to return.
    """
    registry = get_registry()
    return registry.execute("screen_market", {"market": market, "sort_by": sort_by, "top_n": top_n})


def search_symbol(query: str, limit: int = 10) -> str:
    """Resolve a company name or ticker fragment to candidate trading symbols.

    Returns candidates with their market in the project's symbol convention
    (A-shares 600519.SH, Hong Kong 00700.HK, U.S. AAPL.US, plus crypto/index/FX
    from Yahoo). Searches Eastmoney and Yahoo and, for U.S. equities, attaches
    the SEC CIK. Use this to turn an ambiguous name into a concrete symbol
    before calling get_market_data or get_sec_filings.

    Args:
        query: Free-text company name or ticker fragment (Chinese or English).
        limit: Maximum number of merged candidates to return.
    """
    registry = get_registry()
    return registry.execute("search_symbol", {"query": query, "limit": limit})


def get_macro_series(
    series_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 2000,
) -> str:
    """Fetch a FRED macroeconomic time series from the St. Louis Fed.

    Returns dated observations of indicators such as CPI (CPIAUCSL),
    unemployment (UNRATE), real GDP (GDPC1), the federal funds rate (FEDFUNDS),
    or the 10-year Treasury yield (DGS10). Markets: US / global macro data.
    Requires a free FRED API key (FRED_API_KEY); without it the tool returns a
    not-available error.

    Args:
        series_id: FRED series identifier (e.g. "CPIAUCSL", "UNRATE").
        start_date: Inclusive window start, YYYY-MM-DD. Omit for full history.
        end_date: Inclusive window end, YYYY-MM-DD. Omit for the latest date.
        limit: Maximum number of most-recent observations to return.
    """
    params: dict[str, Any] = {"series_id": series_id, "limit": limit}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _execute_key_gated("get_macro_series", params)


def iwencai_search(query: str, limit: int = 20) -> str:
    """Run a natural-language A-share research query against iWenCai (问财).

    iWenCai is a Chinese-market semantic stock screener. Phrase the question in
    plain language (Chinese works best) and get back the matching China A-share
    (SH/SZ) securities with the metric columns iWenCai parsed from the question.
    Read-only; requires the VIBE_TRADING_IWENCAI_KEY access key (without it the
    tool returns a not-available error).

    Args:
        query: Natural-language research question (Chinese phrasing yields the
            best parse, e.g. "市盈率低于15的银行股").
        limit: Maximum securities to return.
    """
    return _execute_key_gated("iwencai_search", {"query": query, "limit": limit})


def analyze_trade_journal(
    file_path: str,
    analysis_type: str = "full",
    filter_expr: str = "",
) -> str:
    """Analyze a user's trade journal (CSV/Excel broker export) and return
    a trading profile plus behavior diagnostics.

    Parses 同花顺 / 东方财富 / 富途 / generic formats (encoding auto-detected).
    Output (JSON):
      - profile: holding days, frequency, win rate, PnL ratio, top symbols,
                 market distribution, hourly distribution
      - behaviors: disposition effect, overtrading, chasing momentum,
                   anchoring (each with severity + numeric evidence)

    Args:
        file_path: Absolute path to the uploaded CSV/Excel file.
        analysis_type: "full" | "profile" | "behavior" | "strategy".
        filter_expr: Optional filter (e.g. "2026-01 to 2026-03",
                     "symbol=600519.SH", "market=china_a").
    """
    registry = get_registry()
    return registry.execute(
        "analyze_trade_journal",
        {
            "file_path": file_path,
            "analysis_type": analysis_type,
            "filter_expr": filter_expr,
        },
    )


def extract_shadow_strategy(
    journal_path: str,
    min_support: int = 3,
    max_rules: int = 5,
) -> str:
    """Extract a Shadow Account profile (3-5 human-readable if-then rules)
    from the user's profitable roundtrips in a trade journal.

    Run `analyze_trade_journal` first if the journal hasn't been parsed.
    Returns shadow_id + rules preview. Profile persists to
    ~/.vibe-trading/shadow_accounts/.

    Args:
        journal_path: Path to the CSV/Excel broker export.
        min_support: Minimum profitable roundtrips required to back one rule.
        max_rules: Maximum rules to return (typically 3-5).
    """
    registry = get_registry()
    return registry.execute(
        "extract_shadow_strategy",
        {
            "journal_path": journal_path,
            "min_support": min_support,
            "max_rules": max_rules,
        },
    )


def run_shadow_backtest(
    shadow_id: str,
    window_start: str = "",
    window_end: str = "",
    markets: list[str] | None = None,
    journal_path: str = "",
) -> str:
    """Run a multi-market backtest (A股/港股/美股/crypto) on a Shadow Account
    profile and compute delta-PnL attribution vs the user's realized trades.

    Requires `extract_shadow_strategy` to have run first.

    Args:
        shadow_id: ID returned by extract_shadow_strategy.
        window_start: ISO date, default today-1y.
        window_end: ISO date, default today.
        markets: Subset of ["china_a", "hk", "us", "crypto"], default all four.
        journal_path: Original journal path (enables attribution), optional.
    """
    registry = get_registry()
    params: dict[str, Any] = {"shadow_id": shadow_id}
    if window_start:
        params["window_start"] = window_start
    if window_end:
        params["window_end"] = window_end
    if markets:
        params["markets"] = markets
    if journal_path:
        params["journal_path"] = journal_path
    return registry.execute("run_shadow_backtest", params)


def render_shadow_report(
    shadow_id: str,
    include_today_signals: bool = True,
    window_start: str = "",
    window_end: str = "",
    journal_path: str = "",
) -> str:
    """Render the Shadow Account HTML/PDF report (8 sections + charts) for
    a shadow_id. If no cached backtest, one is run automatically.

    Args:
        shadow_id: Shadow Account ID.
        include_today_signals: Include today's market scan section.
        window_start: Optional backtest window override.
        window_end: Optional backtest window override.
        journal_path: Original journal path (for attribution), optional.
    """
    registry = get_registry()
    params: dict[str, Any] = {
        "shadow_id": shadow_id,
        "include_today_signals": include_today_signals,
    }
    if window_start:
        params["window_start"] = window_start
    if window_end:
        params["window_end"] = window_end
    if journal_path:
        params["journal_path"] = journal_path
    return registry.execute("render_shadow_report", params)


def scan_shadow_signals(
    shadow_id: str,
    date: str = "",
    per_market: int = 3,
) -> str:
    """List today's symbols that match the Shadow Account's entry cadence
    (research use only — not a trade recommendation).

    Args:
        shadow_id: Shadow Account ID.
        date: ISO YYYY-MM-DD target date, default today.
        per_market: Max signals per market.
    """
    registry = get_registry()
    params: dict[str, Any] = {"shadow_id": shadow_id, "per_market": per_market}
    if date:
        params["date"] = date
    return registry.execute("scan_shadow_signals", params)


def register(mcp: FastMCP) -> None:
    """Register the read-only research-data tools with the FastMCP instance."""
    mcp.tool()(get_fund_flow)
    mcp.tool()(get_dragon_tiger)
    mcp.tool()(get_northbound_flow)
    mcp.tool()(get_margin_trading)
    mcp.tool()(get_block_trades)
    mcp.tool()(get_shareholder_count)
    mcp.tool()(get_lockup_expiry)
    mcp.tool()(get_sector_info)
    mcp.tool()(get_research_reports)
    mcp.tool()(get_stock_news)
    mcp.tool()(get_sec_filings)
    mcp.tool()(get_financial_statements)
    mcp.tool()(get_options_chain)
    mcp.tool()(get_stock_profile)
    mcp.tool()(screen_market)
    mcp.tool()(search_symbol)
    mcp.tool()(get_macro_series)
    mcp.tool()(iwencai_search)
    mcp.tool()(analyze_trade_journal)
    mcp.tool()(extract_shadow_strategy)
    mcp.tool()(run_shadow_backtest)
    mcp.tool()(render_shadow_report)
    mcp.tool()(scan_shadow_signals)
