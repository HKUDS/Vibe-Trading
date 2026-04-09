#!/usr/bin/env python3
"""Vibe-Trading MCP Server — expose 17 finance research tools to any MCP client.

Works with OpenClaw, Claude Desktop, Cursor, and any MCP-compatible client.
Zero API key required for HK/US/crypto markets (yfinance + OKX are free).

Usage:
    python mcp_server.py                    # stdio transport (default)
    python mcp_server.py --transport sse    # SSE transport for web clients

OpenClaw config (~/.openclaw/config.yaml):
    skills:
      - name: vibe-trading
        command: python /path/to/agent/mcp_server.py

Claude Desktop config:
    {
      "mcpServers": {
        "vibe-trading": {
          "command": "python",
          "args": ["/path/to/agent/mcp_server.py"]
        }
      }
    }
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure agent/ is on sys.path
AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

from fastmcp import FastMCP

mcp = FastMCP("Vibe-Trading")


# ---------------------------------------------------------------------------
# Lazy-loaded singletons
# ---------------------------------------------------------------------------

_skills_loader = None
_registry = None


def _get_skills_loader():
    global _skills_loader
    if _skills_loader is None:
        from src.agent.skills import SkillsLoader
        _skills_loader = SkillsLoader()
    return _skills_loader


def _get_registry():
    global _registry
    if _registry is None:
        from src.tools import build_registry
        _registry = build_registry()
    return _registry


# ---------------------------------------------------------------------------
# Skill tools
# ---------------------------------------------------------------------------

@mcp.tool
def list_skills() -> str:
    """List all available finance skills with names and descriptions.

    Returns a JSON array of {name, description} for all 56 skills.
    Use load_skill(name) to get the full documentation for any skill.
    """
    loader = _get_skills_loader()
    skills = [{"name": s.name, "description": s.description} for s in loader.skills]
    return json.dumps(skills, ensure_ascii=False, indent=2)


@mcp.tool
def load_skill(name: str) -> str:
    """Load full documentation for a named finance skill.

    Each skill is a comprehensive knowledge document covering methodology,
    code templates, parameters, and examples. Use list_skills() first to
    discover available skills.

    Args:
        name: Skill name (e.g. 'strategy-generate', 'risk-analysis', 'technical-basic').
    """
    loader = _get_skills_loader()
    content = loader.get_content(name)
    if content.startswith("Error:"):
        return json.dumps({"status": "error", "error": content}, ensure_ascii=False)
    return json.dumps({"status": "ok", "skill": name, "content": content}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Backtest tool
# ---------------------------------------------------------------------------

@mcp.tool
def backtest(run_dir: str) -> str:
    """Run a vectorized backtest using config.json and code/signal_engine.py.

    The run_dir must contain:
    - config.json: backtest configuration (source, codes, dates, etc.)
    - code/signal_engine.py: strategy signal generation code

    Supported data sources (set in config.json "source" field):
    - "yfinance": HK/US equities (free, no API key needed)
    - "okx": cryptocurrency (free, no API key needed)
    - "tushare": China A-shares (requires TUSHARE_TOKEN env var)
    - "auto": auto-detect based on symbol format

    Returns metrics (Sharpe, return, drawdown, etc.) and artifact paths.

    Args:
        run_dir: Path to the run directory containing config.json and code/.
    """
    from src.tools.backtest_tool import run_backtest
    return run_backtest(run_dir)


# ---------------------------------------------------------------------------
# Factor analysis tool
# ---------------------------------------------------------------------------

@mcp.tool
def factor_analysis(
    codes: list[str],
    factor_name: str,
    start_date: str,
    end_date: str,
    source: str = "auto",
    top_n: int = 10,
    bottom_n: int = 10,
) -> str:
    """Compute factor IC/IR analysis and layered backtest for a cross-section of stocks.

    Analyzes factor predictive power using Spearman rank IC, IR (IC/std),
    and top/bottom quintile return spreads.

    Args:
        codes: List of stock codes (e.g. ["000001.SZ", "600519.SH"]).
        factor_name: Factor column name in daily_basic data (e.g. "pe_ttm", "pb", "turnover_rate").
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        source: Data source ("tushare", "yfinance", "auto").
        top_n: Number of top-ranked stocks per period.
        bottom_n: Number of bottom-ranked stocks per period.
    """
    registry = _get_registry()
    return registry.execute("factor_analysis", {
        "codes": codes, "factor_name": factor_name,
        "start_date": start_date, "end_date": end_date,
        "source": source, "top_n": top_n, "bottom_n": bottom_n,
    })


# ---------------------------------------------------------------------------
# Options pricing tool
# ---------------------------------------------------------------------------

@mcp.tool
def analyze_options(
    spot: float,
    strike: float,
    expiry_days: int,
    risk_free_rate: float = 0.03,
    volatility: float = 0.25,
    option_type: str = "call",
) -> str:
    """Calculate Black-Scholes option price and Greeks (Delta, Gamma, Theta, Vega).

    Args:
        spot: Current underlying price.
        strike: Strike price.
        expiry_days: Days until expiration.
        risk_free_rate: Annual risk-free rate (default 0.03 = 3%).
        volatility: Annual volatility (default 0.25 = 25%).
        option_type: "call" or "put".
    """
    registry = _get_registry()
    return registry.execute("options_pricing", {
        "spot": spot, "strike": strike, "expiry_days": expiry_days,
        "risk_free_rate": risk_free_rate, "volatility": volatility,
        "option_type": option_type,
    })


# ---------------------------------------------------------------------------
# Pattern recognition tool
# ---------------------------------------------------------------------------

@mcp.tool
def pattern_recognition(run_dir: str) -> str:
    """Detect technical chart patterns (head-and-shoulders, double top/bottom,
    triangles, wedges, channels) in OHLCV data.

    Reads price data from run_dir/artifacts/ohlcv_*.csv files.
    Can be called before coding (to inform strategy) or after backtest (to analyse).

    Args:
        run_dir: Path to run directory containing artifacts/ohlcv_*.csv.
    """
    registry = _get_registry()
    return registry.execute("pattern_recognition", {"run_dir": run_dir})


# ---------------------------------------------------------------------------
# Web & document reading tools
# ---------------------------------------------------------------------------

@mcp.tool
def read_url(url: str) -> str:
    """Fetch a web page and convert it to clean Markdown text.

    Strips ads, navigation, and styling. Useful for reading API docs,
    financial articles, research reports, and GitHub READMEs.

    Args:
        url: Target URL to read.
    """
    from src.tools.web_reader_tool import read_url as _read_url
    return _read_url(url)


@mcp.tool
def read_document(file_path: str) -> str:
    """Extract text from a PDF document with OCR fallback for scanned pages.

    Supports text-based and image-based PDFs. Automatically uses OCR
    for pages with insufficient extractable text.

    Args:
        file_path: Absolute path to the PDF file.
    """
    registry = _get_registry()
    return registry.execute("read_document", {"file_path": file_path})


# ---------------------------------------------------------------------------
# File I/O tools (sandboxed to workspace)
# ---------------------------------------------------------------------------

@mcp.tool
def write_file(path: str, content: str) -> str:
    """Write content to a file. Used to create config.json and signal_engine.py
    for backtesting workflows.

    Args:
        path: File path (relative to workspace or absolute).
        content: File content to write.
    """
    registry = _get_registry()
    return registry.execute("write_file", {"path": path, "content": content})


@mcp.tool
def read_file(path: str) -> str:
    """Read the contents of a file.

    Args:
        path: File path to read.
    """
    registry = _get_registry()
    return registry.execute("read_file", {"path": path})


# ---------------------------------------------------------------------------
# Swarm team tool
# ---------------------------------------------------------------------------

@mcp.tool
def list_swarm_presets() -> str:
    """List available swarm multi-agent team presets.

    Each preset defines a team of specialized agents (e.g. investment committee,
    quant desk, risk committee) that collaborate on complex research tasks.
    Returns preset names, descriptions, agent counts, and required variables.
    """
    from src.swarm.presets import list_presets
    presets = list_presets()
    return json.dumps(presets, ensure_ascii=False, indent=2)


@mcp.tool
def run_swarm(preset_name: str, variables: dict[str, str]) -> str:
    """Run a swarm multi-agent team and return the final report.

    Assembles a team of specialized agents that collaborate through a DAG workflow.
    For example, the 'investment_committee' preset runs bull analyst, bear analyst,
    risk officer, and portfolio manager in sequence.

    Use list_swarm_presets() to see available presets and their required variables.

    Args:
        preset_name: Swarm preset name (e.g. 'investment_committee', 'quant_strategy_desk').
        variables: Required variables for the preset (e.g. {"target": "AAPL.US", "market": "US"}).
    """
    import time
    from src.swarm.runtime import SwarmRuntime
    from src.swarm.store import SwarmStore
    from src.swarm.models import RunStatus

    swarm_dir = AGENT_DIR / ".swarm" / "runs"
    store = SwarmStore(base_dir=swarm_dir)
    runtime = SwarmRuntime(store=store)

    try:
        run = runtime.start_run(preset_name, variables)
    except FileNotFoundError as exc:
        return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"status": "error", "error": f"DAG validation failed: {exc}"}, ensure_ascii=False)

    # Poll until complete (max 30 minutes)
    for _ in range(360):
        time.sleep(5)
        current = store.load_run(run.id)
        if current is None:
            return json.dumps({"status": "error", "error": "Run record lost"}, ensure_ascii=False)
        if current.status in (RunStatus.completed, RunStatus.failed, RunStatus.cancelled):
            tasks = [
                {"id": t.id, "agent_id": t.agent_id, "status": t.status.value, "summary": t.summary}
                for t in current.tasks
            ]
            return json.dumps({
                "status": current.status.value,
                "preset": preset_name,
                "run_id": current.id,
                "final_report": current.final_report,
                "tasks": tasks,
                "total_input_tokens": current.total_input_tokens,
                "total_output_tokens": current.total_output_tokens,
            }, ensure_ascii=False, indent=2)

    return json.dumps({"status": "error", "error": "Swarm timed out after 30 minutes"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Market data tool
# ---------------------------------------------------------------------------

_SOURCE_PATTERNS = [
    (re.compile(r"^\d{6}\.(SZ|SH|BJ)$", re.I), "tushare"),
    (re.compile(r"^[A-Z]+\.US$", re.I), "yfinance"),
    (re.compile(r"^\d{3,5}\.HK$", re.I), "yfinance"),
    (re.compile(r"^[A-Z]+-USDT$", re.I), "okx"),
]


def _detect_source(code: str) -> str:
    for pattern, source in _SOURCE_PATTERNS:
        if pattern.match(code):
            return source
    return "tushare"


def _get_loader(source: str):
    if source == "okx":
        from backtest.loaders.okx import DataLoader
    elif source == "yfinance":
        from backtest.loaders.yfinance_loader import DataLoader
    else:
        from backtest.loaders.tushare import DataLoader
    return DataLoader


@mcp.tool
def get_market_data(
    codes: list[str],
    start_date: str,
    end_date: str,
    source: str = "auto",
    interval: str = "1D",
) -> str:
    """Fetch OHLCV market data for stocks, crypto, or mixed symbols.

    Supported sources:
    - "yfinance": HK/US equities (free, e.g. AAPL.US, 700.HK)
    - "okx": cryptocurrency (free, e.g. BTC-USDT, ETH-USDT)
    - "tushare": China A-shares (requires TUSHARE_TOKEN, e.g. 000001.SZ)
    - "auto": auto-detect based on symbol format (supports mixed markets)

    Args:
        codes: List of symbols (e.g. ["AAPL.US", "BTC-USDT", "000001.SZ"]).
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        source: Data source ("auto", "yfinance", "okx", "tushare").
        interval: Bar size (1m/5m/15m/30m/1H/4H/1D, default "1D").
    """
    results = {}

    if source == "auto":
        groups: dict[str, list[str]] = {}
        for code in codes:
            src = _detect_source(code)
            groups.setdefault(src, []).append(code)
    else:
        groups = {source: list(codes)}

    for src, src_codes in groups.items():
        loader_cls = _get_loader(src)
        loader = loader_cls()
        data_map = loader.fetch(src_codes, start_date, end_date, interval=interval)
        for symbol, df in data_map.items():
            records = df.reset_index().to_dict(orient="records")
            for r in records:
                for k, v in r.items():
                    if hasattr(v, "isoformat"):
                        r[k] = v.isoformat()
                    elif hasattr(v, "item"):
                        r[k] = v.item()
            results[symbol] = records

    return json.dumps(results, ensure_ascii=False, indent=2)


@mcp.tool
def market_sentiment(
    mode: str = "snapshot",
    tickers: list[str] | None = None,
    source: str = "all",
    days: int = 7,
    limit: int = 10,
) -> str:
    """Fetch optional structured market sentiment for US equities and ETFs.

    The Adanos sentiment integration is optional and only becomes active when
    ADANOS_API_KEY is configured. Without it, the tool returns
    {"status":"not_configured"} so agents can fall back to web research.

    Args:
        mode: "snapshot" for ticker comparison or "trending" for hot names.
        tickers: List of tickers for snapshot mode (e.g. ["AAPL", "NVDA", "TSLA"]).
        source: all, reddit, x, news, or polymarket.
        days: Lookback window in days.
        limit: Max trending rows per source.
    """
    from src.tools.market_sentiment_tool import run_market_sentiment

    return run_market_sentiment(
        mode=mode,
        tickers=tickers,
        source=source,
        days=days,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Swarm status & history tools
# ---------------------------------------------------------------------------

def _get_swarm_store():
    swarm_dir = AGENT_DIR / ".swarm" / "runs"
    swarm_dir.mkdir(parents=True, exist_ok=True)
    from src.swarm.store import SwarmStore
    return SwarmStore(base_dir=swarm_dir)


def _run_to_dict(run) -> dict:
    return {
        "run_id": run.id,
        "status": run.status.value,
        "preset": run.preset_name,
        "created_at": run.created_at,
        "tasks": [
            {
                "id": t.id,
                "agent_id": t.agent_id,
                "status": t.status.value,
                "summary": t.summary,
            }
            for t in run.tasks
        ],
        "final_report": run.final_report,
        "total_input_tokens": run.total_input_tokens,
        "total_output_tokens": run.total_output_tokens,
    }


@mcp.tool
def get_swarm_status(run_id: str) -> str:
    """Get the current status of a swarm run.

    Returns status, task progress, and token usage for the specified run.
    Use this to poll a long-running swarm without blocking.

    Args:
        run_id: The run ID returned by run_swarm.
    """
    store = _get_swarm_store()
    run = store.load_run(run_id)
    if run is None:
        return json.dumps({"status": "error", "error": f"Run {run_id} not found"}, ensure_ascii=False)
    return json.dumps(_run_to_dict(run), ensure_ascii=False, indent=2)


@mcp.tool
def get_run_result(run_id: str) -> str:
    """Get the final report and task summaries of a completed swarm run.

    Returns the final_report text and per-task summaries. If the run is
    still in progress, returns current status instead.

    Args:
        run_id: The run ID returned by run_swarm.
    """
    store = _get_swarm_store()
    run = store.load_run(run_id)
    if run is None:
        return json.dumps({"status": "error", "error": f"Run {run_id} not found"}, ensure_ascii=False)
    return json.dumps(_run_to_dict(run), ensure_ascii=False, indent=2)


@mcp.tool
def list_runs(limit: int = 20) -> str:
    """List recent swarm runs sorted by creation time (newest first).

    Returns run IDs, presets, statuses, and creation timestamps.
    Use get_run_result(run_id) to fetch full details for a specific run.

    Args:
        limit: Maximum number of runs to return (default 20).
    """
    store = _get_swarm_store()
    runs = store.list_runs(limit=limit)
    items = []
    for run in runs:
        items.append({
            "run_id": run.id,
            "preset": run.preset_name,
            "status": run.status.value,
            "created_at": run.created_at,
            "total_input_tokens": run.total_input_tokens,
            "total_output_tokens": run.total_output_tokens,
        })
    return json.dumps(items, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Entry point for `vibe-trading-mcp` CLI command."""
    import argparse

    parser = argparse.ArgumentParser(description="Vibe-Trading MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio",
                        help="MCP transport (default: stdio)")
    parser.add_argument("--port", type=int, default=8900,
                        help="SSE port (only used with --transport sse)")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
