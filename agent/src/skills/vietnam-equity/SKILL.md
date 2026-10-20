---
name: vietnam-equity
description: Vietnam stock market playbook (HOSE, HNX, UPCoM) — symbol suffixes and data sources, what the VietnamEquityEngine enforces (T+2 hold, ±7/10/15% bands, VND tick grid, 100-share lots, 10% of session volume per order, long-only, brokerage plus 0.1% sell tax), VN-Index benchmarking, and how to design strategies that survive those rules.
category: tool
---
# Vietnam Equities (HOSE, HNX, UPCoM)

## Overview

Use this skill for any research or backtest on Vietnamese listed shares, ETFs or fund certificates. Vietnam's cash market has rules that break strategies written for the US or China: a buy settles T+2, so nothing can be sold for two sessions; daily price bands lock stocks at the ceiling or the floor; orders trade in 100-share lots on a coarse VND tick grid; short selling is not available; and every sale pays a 0.1% tax. The `VietnamEquityEngine` enforces all of these, so read what it does before interpreting a result.

## Symbols and Data Sources

| Exchange | Symbol | Example | Data | Daily band | Tick |
|----------|--------|---------|------|------------|------|
| HOSE (Ho Chi Minh City) | `<TICKER>.VN` | `VCB.VN`, `FPT.VN` | `yahoo` / `yfinance`, free, no key | ±7% | 10 VND below 10,000; 50 VND below 50,000; 100 VND from 50,000 |
| HNX (Hanoi) | `<TICKER>.HNX` | `PVS.HNX` | `local` files only | ±10% | 100 VND |
| UPCoM | `<TICKER>.UPCOM` | `ACV.UPCOM` | `local` files only | ±15% | 100 VND |

- `.VN` is Yahoo's suffix, and Yahoo lists HOSE only. `.HNX` and `.UPCOM` are this project's suffixes: the Yahoo loaders skip them, and the `vietnam_equity` chain (yahoo, yfinance, local) serves them from your Data Bridge files.
- With `"source": "auto"`, one run can mix exchanges: `.VN` codes come from Yahoo and the rest from local files. Prefix a code with `local:` (for example `local:VCB.VN`) to use your own file for a HOSE symbol too.
- Register local files in `~/.vibe-trading/data-bridge/config.yaml`:

```yaml
sources:
  - symbol: "PVS.HNX"
    type: csv
    path: "~/data/vn/PVS.csv"        # columns: date, open, high, low, close, volume
  - symbol: "ACV.UPCOM"
    type: parquet
    path: "~/data/vn/ACV.parquet"
```

- **Prices are whole VND.** The band and tick arithmetic expects prices such as `24200`. Several Vietnamese data APIs return prices in thousands of VND (`24.2`); multiply those by 1,000 before writing a local file, or the tick and band arithmetic runs on numbers a thousand times too small. Check one known quote before the first run.
- **Adjustment.** Yahoo's `.VN` bars are split- and dividend-adjusted, so older bars sit off the tick grid while the relative band checks still hold. Fills still snap to the grid, and on a flat grid a tick weighs more on an adjusted price than it did on the traded one: HNX and UPCoM's 100 VND tick is 1.8% of an adjusted 5,550 VND but 0.4% of a traded 24,000 VND. Vietnamese issuers pay stock dividends and run rights issues often; adjust local files the same way, because an unadjusted ex-rights gap looks like a limit-down day. Put the volume on the same basis as the prices: multiply each bar's traded volume by its traded close over its adjusted close. The engine counts shares as money divided by the adjusted price, so against raw volume the volume cap binds harder on older bars than the market did.
- yfinance is an unofficial Yahoo client, so treat availability as best-effort.

## What the Engine Enforces

Every `.VN`, `.HNX` and `.UPCOM` code runs on `VietnamEquityEngine`, alone or as one leg of a cross-market composite run.

| Rule | Behaviour | Config key (default) |
|------|-----------|----------------------|
| Long-only | a short order is refused; `allow_short` raises at construction | leave `allow_short` unset |
| Settlement | a buy may be sold from the second following session (T+2: shares arrive for the afternoon session of T+2). Adding to a position restarts the hold for the whole position | `vn_settlement_bars` (2) |
| Price band | a buy is blocked when its fill would be at or above the ceiling, a sell at or below the floor; bounds come from the previous close and are rounded onto the tick grid | `price_limit` (unset: each exchange's band; a value applies to every symbol; `0` disables) |
| Listing history | a name that moved exchange takes, on each bar, the band and tick grid of the exchange it traded on that day; its first session after a move takes the new exchange's first-day band (±20% HOSE, ±30% HNX, ±40% UPCoM) | `vn_exchange_history` (unset: the suffix decides on every bar) |
| Lots | orders floor to multiples of 100 shares; odd lots are not modelled | none |
| Liquidity | one order fills at most this share of the session's traded volume, floored to the lot; the rest keeps working on the following sessions | `vn_volume_cap` (0.10; `0` disables) |
| Working orders | an order the volume cap cut short, or one the band or the T+2 hold blocked, keeps working on the following sessions, as an order resting on the exchange would, until it fills or the strategy's target for the name changes | none |
| Brokerage | charged on both sides | `vn_brokerage` (0.0015) |
| Sell tax | 0.1% of gross proceeds on every sale, at a gain or a loss (individual investors) | `vn_tax_sell` (0.001) |
| Slippage | fills slip against you and snap to the next valid tick | `slippage` (0.001) |
| Leverage | forced to 1.0 (cash account) | none |

A name that moved exchange keeps one code over its whole history, the one for the exchange it lists on now. `"vn_exchange_history": {"ACB.VN": {"2018-01-02": "HNX", "2020-12-09": "HOSE"}}` runs ACB under HNX's band and tick grid until its first HOSE session on 9 December 2020. Each date is the first session on that exchange, and the earliest only has to precede your data; exchanges are `HOSE` (or `HSX`), `HNX` and `UPCOM`.

Known approximations:

- **Reference price.** The engine uses the previous close. UPCoM's real reference is the previous session's volume-weighted average price, and the `local` loader keeps OHLCV columns only, so a `pre_close` column in your file is not used.
- **Wider first-day bands.** First trading days and resumptions after long suspensions trade within ±20% (HOSE), ±30% (HNX) or ±40% (UPCoM). The engine does not detect them; set `price_limit` for a run that studies new listings. The first session after a move in `vn_exchange_history` is the exception: it takes the new exchange's first-day band, measured from the previous close, although the exchange sets that day's reference price afresh, as for a new listing.
- **ETF tick.** HOSE quotes ETFs and covered warrants on a 10 VND tick at every price, but the engine applies the share grid to every `.VN` code, so ETF fill rounding is coarser than reality.
- **Daily bars.** The hold is counted in bars. Run on `"interval": "1D"`; on intraday bars a two-bar hold releases after two bars, not two sessions.
- **Volume.** The cap reads each bar's `volume`. A session with zero volume fills nothing, a bar without a volume value is not limited, and a symbol whose data shows no traded volume on any bar is exempt (the run logs a warning). The sale of the whole book when the run ends is not capped.

## Costs Decide What Is Tradable

At the defaults a round trip costs at least 0.6%: 0.15% brokerage on each side, the 0.1% sell tax, and about one tick of slippage each way. The tick dominates on cheap shares: one 100 VND tick is 2% of a 5,000 VND HNX share, and one 50 VND tick is 0.5% of a HOSE share priced just above 10,000.

- Prefer holding periods of weeks over days, and weekly or monthly rebalancing.
- Require an expected edge per trade well above the round-trip cost.
- Re-run with `slippage` doubled; an edge that disappears was a cost artifact.

## Designing Strategies for This Market

1. **Hold for at least two sessions.** A signal that wants out the next day cannot be filled; the engine delays the sale until the hold clears. Overnight reversal and other one-day strategies are not implementable on the cash market.
2. **Expect locked days.** A stock at the ceiling cannot be bought and one at the floor cannot be sold, sometimes for several sessions in a row. Stop-losses do not fill during a limit-down run, so size positions to survive a few sessions at the floor. Momentum strategies that chase ceiling stocks show many blocked buys.
3. **Screen liquidity.** One order fills at most 10% of a session's volume (`vn_volume_cap`), so a position that is large next to a name's trading takes several sessions to build or unwind, at those sessions' prices. Filter the universe by average daily traded value (for example, above 10 billion VND over 20 sessions) and keep each position a small fraction of it. Many HNX and UPCoM names trade too little to enter or exit at size.
4. **Use a point-in-time universe.** Yahoo serves only symbols listed today, so delisted names and names that moved exchange vanish, and survivorship bias inflates results. Build index universes from historical constituents; VN30 membership is reviewed twice a year, in January and July. When a local file for a `.VN` name also holds its years on HNX or UPCoM, give the earlier exchange in `vn_exchange_history`; otherwise those sessions run under HOSE's ±7% band.
5. **Respect foreign ownership limits.** Foreign investors face caps, commonly 30% of a bank and 49% of most other companies. A stock at its cap ("full room") can only be bought from another foreign holder, often at a premium. The engine does not model this; exclude capped names when simulating a foreign investor.
6. **Express bearish views by not holding.** With no shorting, a Sell or Underweight view means cutting or exiting the position, so keep target weights between 0 and 1. VN30 index futures can hedge, but this engine does not cover them.
7. **Mind the calendar.** The market closes for about a week at Tet (Lunar New Year), and liquidity thins before it. Sessions run roughly 9:00 to 11:30 and 13:00 to 14:45 local time (UTC+7). Index reviews and ETF rebalances (VN30, VNDiamond and foreign ETFs that track Vietnam) concentrate flows around known dates.
8. **Choose how target changes execute.** The default `"position_adjustment": "hold"` opens and closes positions but never resizes one already held, so a quarterly re-weighting of names the book keeps is dropped. A strategy that re-weights on a schedule needs `"position_adjustment": "rebalance"` and one of two controls:
   - `rebalance_mask` is an execution calendar, such as `"QS"` (the first session of each quarter) or a list of decision dates. Orders start only on those dates; one that the band, the T+2 hold or the volume cap stops keeps working on the following sessions until it fills or a later date changes its target.
   - `rebalance_tolerance` is a drift band, such as `0.05`: a position is resized only when its size is more than that fraction away from the size its target implies, and a blocked order retries the next session. The band also skips a target change smaller than the band, so keep it below the smallest re-weighting you mean to trade. A working order is the exception: it keeps filling until it reaches its target.

   With neither, positions are traded back to their targets on many sessions as prices drift, and each of those trades pays brokerage, slippage and, on a sale, the sell tax. The run card warns in either case.

## Benchmarks

- Without a `benchmark` key, or with `"auto"`, results are compared with an equal-weight buy-and-hold of the run's own symbols.
- `"benchmark": "^VNINDEX.VN"` compares with the VN-Index through Yahoo. With `"source": "local"` the benchmark must be in your local files too, because an offline run never fetches it from the network.
- For a book of HNX or UPCoM names, an index series of that exchange from your own files is the fairer comparison.

## Example

```json
{
  "codes": ["VCB.VN", "FPT.VN", "HPG.VN", "MWG.VN", "PVS.HNX"],
  "start_date": "2021-01-01",
  "end_date": "2025-12-31",
  "source": "auto",
  "interval": "1D",
  "initial_cash": 1000000000,
  "benchmark": "^VNINDEX.VN",
  "slippage": 0.001,
  "vn_brokerage": 0.0015,
  "vn_tax_sell": 0.001
}
```

`PVS.HNX` needs a Data Bridge entry; drop it to run on Yahoo data alone. One billion VND of starting cash keeps 100-share lots of high-priced names from rounding to zero.

## Before Trusting a Result

- Read the run card's warnings. They report re-weightings that `"hold"` dropped, a `"rebalance"` run with neither control whose resize fills mostly re-traded unchanged targets (`rebalance_unchanged_target_fills` out of `rebalance_executed_fills` in the metrics), and orders the volume cap cut.
- Read `unfilled_plan_rejections_by_symbol` in the metrics: `execution_blocked` counts buys refused at the ceiling (and any short the strategy asked for), `zero_size` counts orders smaller than one lot, and `volume_cap` counts openings whose session volume allowed less than one lot.
- Read `volume_capped_orders` and `unfinished_orders_at_end` in the metrics: orders the volume cap cut, and orders still working when the run ended. Many of either mean the book is large for its names; positions reached their targets late, at other prices than the strategy saw.
- Compare `target_positions.csv` with `positions.csv` to see exits the settlement hold or the floor delayed.
- Measure the cost drag: re-run with `vn_brokerage`, `vn_tax_sell` and `slippage` at 0 and compare. At about 0.6% per round trip, rotating the whole book every week costs roughly 30% a year; `avg_turnover` in the metrics shows how often the book turns over.
- Confirm the units (whole VND) and the adjustment of every local file.
