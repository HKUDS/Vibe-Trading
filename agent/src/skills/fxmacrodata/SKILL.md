---
name: fxmacrodata
category: data-source
description: Reference FXMacroData when a task selects its FX spot, macro indicator, release-calendar, prediction, COT, commodity, rate-differential, curve, market-session, risk-sentiment, or central-bank-news datasets.
---
# FXMacroData

FXMacroData is an optional data source for FX and macro research when the task
selects official-source currency, macroeconomic, central-bank, or cross-asset
datasets. Use `FXMD_API_KEY` for protected data. Do not put the key in prompts,
files, logs, URLs, or generated code output.

## Source Selection

Use `get_market_data` with `source: "auto"` or `source: "fxmacrodata"` for
numeric series that can be represented as OHLCV-like bars:

- FX spot: `EUR/USD`, `EURUSD`, `EURUSD.FX`, `fx:EUR/USD`, `fxmd:forex:EUR/USD`
- Macro series: `fxmd:indicator:USD:inflation`, `fxmd:indicator:EUR:policy_rate`
- COT: `fxmd:cot:JPY`
- Commodities: `fxmd:commodity:gold`
- Risk sentiment: `fxmd:risk_sentiment`
- Differentials: `fxmd:rate_diff:EUR/USD:policy_rate`,
  `fxmd:forward_diff:EUR/USD`

The loader maps a single numeric value to `open = high = low = close = value`
with `volume = 0`, so only use it for historical numeric series. For richer
metadata, calendars, forecasts, news, curves, or coverage checks, call the
dedicated FXMacroData tools below.

## Dedicated Tools

- `get_fxmacrodata_catalogue`: discover current indicator coverage and metadata.
- `get_fxmacrodata_indicator`: fetch a macro indicator series.
- `get_fxmacrodata_release_calendar`: fetch economic announcement rows.
- `get_fxmacrodata_predictions`: fetch forecasts, nowcasts, surveys, or consensus.
- `get_fxmacrodata_cot`: fetch CFTC positioning.
- `get_fxmacrodata_commodities`: fetch commodity latest values or history.
- `get_fxmacrodata_rate_differentials`: fetch spot-rate or forward-rate differentials.
- `get_fxmacrodata_curves`: fetch curves, curve proxies, or forward curves.
- `get_fxmacrodata_news`: fetch central-bank news or press releases.
- `get_fxmacrodata_market_sessions`: fetch current or timestamped FX sessions.
- `get_fxmacrodata_risk_sentiment`: fetch risk-on/risk-off readings.

## Coverage Rule

Runtime coverage must come from the FXMacroData API. Do not hard-code supported
currencies in code or strategies. For unfamiliar macro indicators, call
`get_fxmacrodata_catalogue` first and then request the exact indicator slug the
API returns.
