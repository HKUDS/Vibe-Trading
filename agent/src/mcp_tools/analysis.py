"""MCP analysis tools: backtest, factor analysis, options, pattern recognition."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from src.mcp_tools._shared import get_registry


def backtest(run_dir: str) -> str:
    """Run a vectorized backtest using config.json and code/signal_engine.py.

    The run_dir must contain:
    - config.json: backtest configuration (source, codes, dates, etc.)
    - code/signal_engine.py: strategy signal generation code

    Supported data sources (set in config.json "source" field):
    - "yfinance": HK/US equities (free, no API key needed)
    - "okx": cryptocurrency (free, no API key needed)
    - "tushare": China A-shares (requires TUSHARE_TOKEN env var)
    - "akshare": A-shares, US, HK, futures, forex (free, no API key)
    - "ccxt": crypto from 100+ exchanges (free, no API key)
    - "auto": auto-detect based on symbol format (with fallback)

    Returns metrics (Sharpe, return, drawdown, etc.) and artifact paths.

    Args:
        run_dir: Path to the run directory containing config.json and code/.
    """
    from src.tools.backtest_tool import run_backtest

    return run_backtest(run_dir)


def factor_analysis(
    factor_csv: str,
    return_csv: str,
    output_dir: str,
    n_groups: int = 5,
) -> str:
    """Compute factor IC/IR analysis and layered backtest from prepared CSVs.

    Analyzes factor predictive power using Spearman rank IC, IR (IC/std),
    and quantile group return spreads.

    Args:
        factor_csv: Path to factor values CSV (index=date, columns=codes).
        return_csv: Path to returns CSV (same structure as factor_csv).
        output_dir: Directory for output files (ic_series.csv, ic_summary.json, group_equity.csv).
        n_groups: Number of quantile groups (default 5).
    """
    registry = get_registry()
    return registry.execute(
        "factor_analysis",
        {
            "factor_csv": factor_csv,
            "return_csv": return_csv,
            "output_dir": output_dir,
            "n_groups": n_groups,
        },
    )


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
    registry = get_registry()
    return registry.execute(
        "options_pricing",
        {
            "spot": spot,
            "strike": strike,
            "expiry_days": expiry_days,
            "risk_free_rate": risk_free_rate,
            "volatility": volatility,
            "option_type": option_type,
        },
    )


def analyze_options_payoff(
    legs: list[dict[str, Any]],
    entry_spot: float,
    expiry_days: float,
    risk_free_rate: float = 0.05,
    volatility: float = 0.3,
    multiplier: float = 1.0,
    commission_rate: float = 0.001,
    spot_min: float | None = None,
    spot_max: float | None = None,
    spot_points: int = 121,
    scenario_iv_values: list[float] | None = None,
) -> str:
    """Analyze a multi-leg option strategy's payoff and spot/IV scenarios.

    The expiry summary is analytic rather than chart-grid dependent. Returns
    entry debit/credit and commission, breakevens, bounded or unbounded maximum
    profit/loss, an expiry curve, and a Black-Scholes spot/IV P&L matrix.
    Research only; this tool cannot place orders.

    Args:
        legs: Option leg objects with ``option_type`` (call/put), positive
            ``strike``, signed integer ``qty``, and optional per-share
            ``premium``. Positive quantity is long; negative is short.
        entry_spot: Positive underlying spot at entry.
        expiry_days: Non-negative calendar days to expiry.
        risk_free_rate: Annual continuously compounded risk-free rate.
        volatility: Annualized entry volatility, e.g. 0.3 for 30%.
        multiplier: Currency multiplier per option price unit.
        commission_rate: Entry commission fraction, aligned with the options
            backtest engine.
        spot_min: Optional non-negative chart/scenario lower bound.
        spot_max: Optional chart/scenario upper bound above ``spot_min``.
        spot_points: Display-grid size from 21 through 501.
        scenario_iv_values: Optional positive annualized IV scenarios. Omit for
            50%, 75%, 100%, 125%, and 150% of entry volatility.
    """
    params: dict[str, Any] = {
        "legs": legs,
        "entry_spot": entry_spot,
        "expiry_days": expiry_days,
        "risk_free_rate": risk_free_rate,
        "volatility": volatility,
        "multiplier": multiplier,
        "commission_rate": commission_rate,
        "spot_points": spot_points,
    }
    if spot_min is not None:
        params["spot_min"] = spot_min
    if spot_max is not None:
        params["spot_max"] = spot_max
    if scenario_iv_values is not None:
        params["scenario_iv_values"] = scenario_iv_values
    registry = get_registry()
    return registry.execute("options_payoff", params)


def pattern_recognition(run_dir: str) -> str:
    """Detect technical chart patterns (head-and-shoulders, double top/bottom,
    triangles, wedges, channels) in OHLCV data.

    Reads price data from run_dir/artifacts/ohlcv_*.csv files.
    Can be called before coding (to inform strategy) or after backtest (to analyse).

    Args:
        run_dir: Path to run directory containing artifacts/ohlcv_*.csv.
    """
    registry = get_registry()
    return registry.execute("pattern", {"run_dir": run_dir})


def register(mcp: FastMCP) -> None:
    """Register the analysis tools with the FastMCP instance."""
    mcp.tool()(backtest)
    mcp.tool()(factor_analysis)
    mcp.tool()(analyze_options)
    mcp.tool()(analyze_options_payoff)
    mcp.tool()(pattern_recognition)
