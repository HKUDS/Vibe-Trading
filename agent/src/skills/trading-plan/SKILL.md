---
name: trading-plan
description: Refresh a weekly trading plan, to-do list, or sell-orders file with current observed evidence and explicit derived-level labels.
category: strategy
---

# Trading plan and sell-orders files

Use this workflow when the user asks to create, refresh, or extend a weekly plan, to-do list, or sell-orders Markdown file from a prior file.

1. Read the source file or files first.
2. Before writing the file or giving the final summary, fetch observed prices for every symbol whose price, P&L, or level you will state. Use `get_market_data` with the exact canonical suffixed tickers in this session and dates covering the reference close. A price from another plan file is not current-session evidence.
3. Use the gateway tool's returned artifact paths for calculations. Do not fetch the same OHLC rows again through bash or yfinance. If an uncovered field needs a bounded Python adapter, preserve its observed rows and provenance under `run_dir/data/raw/`.
4. Write and summarize only after every cited symbol has observed evidence. Bind each figure to symbol, currency, and as-of date. Label ladder triggers, targets, stops, and other prospective levels as derived or prospective rather than observed prices.
