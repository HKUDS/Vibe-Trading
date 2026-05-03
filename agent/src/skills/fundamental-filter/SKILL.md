---
name: fundamental-filter
description: Fundamental factor screening — filter stocks by PE/PB/ROE and other financial metrics for value or growth selection. Supports A-shares (via tushare extra_fields) and HK/US stocks (via yfinance Ticker info).
category: flow
---
# Fundamental Factor Screening

## Purpose

Filter stocks using simple fundamental data (PE/PB/ROE, market cap, and similar metrics) to build value or growth screen signals for backtesting. Supports multiple markets with different data sources.

This skill is **not** the entry point for A-share financial statement strategies that depend on Tushare statement tables such as `income`, `balancesheet`, `cashflow`, `express`, or `fina_indicator`.

When an A-share strategy needs fields from those tables, switch to [ashare-financial-enrichment](../ashare-financial-enrichment/SKILL.md) instead of continuing with this simple screening flow.

## Market Support

| Market | Data Source | Method | Supported Metrics |
|--------|-----------|--------|------------------|
| A-shares | tushare `daily_basic` | `extra_fields` in config.json | pe, pb, pe_ttm, ps_ttm, dv_ttm, total_mv, circ_mv, roe |
| US stocks | yfinance `Ticker.info` | Direct API call | trailingPE, forwardPE, priceToBook, returnOnEquity, marketCap, dividendYield |
| HK stocks | yfinance `Ticker.info` | Direct API call | trailingPE, priceToBook, returnOnEquity, marketCap |

## Scope Boundary

This skill covers only these two data styles:

1. A-share `daily_basic`-style fields already supported by the backtest loader
2. US/HK `Ticker.info` point-in-time snapshots

This skill does **not** cover:

- A-share fields from `income`
- A-share fields from `balancesheet`
- A-share fields from `cashflow`
- A-share fields from `express`
- A-share fields from `fina_indicator` when they are being treated as financial statement enrichment rather than simple built-in daily fields

If the strategy is A-share and uses those financial statement fields:

- require `TUSHARE_TOKEN`
- require at least 2000 Tushare points to pull the financial tables at all
- treat 5000 points as the preferred threshold for full-market or universe backtests; with 2000-4999 points the runtime can still proceed, but it will fall back to slower per-code fetching
- do **not** silently degrade to `daily_basic`
- do **not** continue automatically
- follow [ashare-financial-enrichment](../ashare-financial-enrichment/SKILL.md)

## Signal Logic

### Value Filter (Default)

1. PE < pe_max AND PE > 0 (exclude loss-making stocks)
2. PB < pb_max
3. ROE > roe_min
4. All conditions met → long (1), otherwise → flat (0)

### Growth Filter (Optional)

1. PE_TTM within reasonable range (0 < PE_TTM < pe_ttm_max)
2. ROE > roe_min (profitability floor)
3. Market cap > mv_min (exclude micro-caps)

## A-Share Usage (tushare)

### config.json

```json
{
  "source": "tushare",
  "codes": ["000001.SZ", "600036.SH", "000858.SZ"],
  "start_date": "2023-01-01",
  "end_date": "2024-12-31",
  "extra_fields": ["pe", "pb", "pe_ttm", "roe", "total_mv"],
  "initial_cash": 1000000,
  "commission": 0.001
}
```

The `extra_fields` columns are automatically merged into the daily DataFrame by the DataLoader.

This is only for the currently supported simple A-share fields such as `pe`, `pb`, `pe_ttm`, `roe`, and `total_mv`.

If you need statement-style fields such as `revenue`, `total_assets`, `n_cashflow_act`, `free_cashflow`, `grossprofit_margin`, `netprofit_margin`, `ocfps`, or similar fields sourced from Tushare financial tables, this skill is no longer sufficient. Use [ashare-financial-enrichment](../ashare-financial-enrichment/SKILL.md).

## HK/US Stock Usage (yfinance)

For HK/US stocks, fundamental data is not available as daily time-series via the backtest loader. Instead, use `yfinance` Ticker info for point-in-time screening:

```python
import yfinance as yf

def screen_us_stocks(tickers, criteria):
    """Screen US/HK stocks by fundamental criteria."""
    passed = []
    for symbol in tickers:
        info = yf.Ticker(symbol).info
        pe = info.get("trailingPE")
        pb = info.get("priceToBook")
        roe = info.get("returnOnEquity")  # Decimal (e.g., 0.25 = 25%)
        mcap = info.get("marketCap")

        if pe is None or pb is None or roe is None:
            continue  # Skip stocks with missing data

        if (0 < pe < criteria["pe_max"]
            and pb < criteria["pb_max"]
            and roe > criteria["roe_min"]
            and (mcap or 0) > criteria.get("mcap_min", 0)):
            passed.append({
                "symbol": symbol,
                "pe": pe,
                "pb": pb,
                "roe": round(roe * 100, 1),  # Convert to percentage
                "mcap": mcap,
            })

    return passed

# Example: screen S&P 500 components
criteria = {"pe_max": 20, "pb_max": 3.0, "roe_min": 0.08, "mcap_min": 10_000_000_000}
results = screen_us_stocks(["AAPL", "MSFT", "JNJ", "JPM", "XOM"], criteria)
```

### HK Stock Screening

```python
# HK stocks use the same yfinance interface
hk_tickers = ["0700.HK", "9988.HK", "1810.HK", "2318.HK", "0005.HK"]
results = screen_us_stocks(hk_tickers, criteria)  # Same function works
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| pe_max | 20.0 | PE ceiling (exclude overvalued) |
| pb_max | 3.0 | PB ceiling |
| roe_min | 8.0 | ROE floor (%), exclude low-profitability |
| pe_min | 0.0 | PE floor (exclude loss-making stocks) |
| mcap_min | 0 | Market cap floor (for US/HK, in USD) |

## Common Pitfalls

- `extra_fields` columns may contain NaN (new listings, ST stocks) — must `fillna` or `dropna`
- Negative PE means loss-making — always filter with `pe > 0`
- ROE units differ: tushare uses percentage (e.g., 15 = 15%), yfinance uses decimal (e.g., 0.15 = 15%)
- For portfolio strategies: N stocks passing the screen each get weight 1/N
- yfinance `Ticker.info` is a point-in-time snapshot, not historical time-series — cannot directly use for daily rebalancing backtests on US/HK stocks
- For US/HK daily fundamental backtests, consider using the screening results as a stock universe, then applying technical signals within that universe
- Do not confuse simple A-share `daily_basic` fields with the full Tushare financial statement tables. They have different loading rules and different point-in-time semantics.

## Dependencies

```bash
pip install pandas numpy yfinance
```

## Signal Convention

- `1/N` = selected for long (N = number of stocks passing the screen), `0` = not selected
