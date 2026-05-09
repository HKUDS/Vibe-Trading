---
name: vn-foreign-room
category: risk-analysis
description: Track foreign ownership remaining room for Vietnam-listed stocks. Alert when room is ≥95% utilized — strategies relying on foreign demand may fail.
---

## What is Foreign Room?

Vietnam imposes statutory caps on the percentage of a listed company's shares that may be held by non-domestic investors. The "foreign room" (room ngoại) is the remaining gap between the cap and the current foreign holding.

- **Default cap**: 49% of charter capital for most sectors
- **Banks**: 30% (Luật các Tổ chức Tín dụng — Law on Credit Institutions)
- **Conditional industries** (telecom, aviation, some logistics): variable, often 30–49%
- **Unconditional sectors**: SBV/SSC may grant 100% on case-by-case basis (rare; e.g. PNJ, REE earlier waves)

When a stock is "full room" (kín room), foreign buyers can only acquire shares by waiting for another foreign holder to sell. This frequently produces a persistent OTC premium ("giá thỏa thuận room ngoại") of 5–20% over the on-screen price.

## Why It Matters for Strategy

Strategies that assume marginal foreign demand will lift price (e.g. ETF rebalance trades, MSCI inclusion themes, foreign-flow factor models) **fail silently** when the target stock is at or near full room. ALWAYS check room before recommending entries that depend on foreign capital flows.

## Data Fields

The typical schema returned by VN data providers:

| Field | Type | Description (EN / VI) |
|-------|------|------------------------|
| `total_shares` | int | Total outstanding shares (Tổng số cổ phiếu lưu hành) |
| `foreign_held` | int | Shares currently held by foreigners (Khối lượng nước ngoài đang sở hữu) |
| `foreign_limit_pct` | float | Statutory cap, percent (Tỷ lệ sở hữu nước ngoài tối đa) |
| `foreign_held_pct` | float | Current foreign holding, percent (Tỷ lệ sở hữu nước ngoài hiện tại) |
| `room_remaining` | int | Shares still available to foreign buyers (Room còn lại) |
| `room_remaining_pct` | float | `room_remaining / total_shares * 100` |

## How to Fetch

```python
from vnstock import Company

info = Company(symbol='VNM').overview()
# Relevant columns: foreign_percent, outstanding_share, ...
foreign_pct = info['foreign_percent'].iloc[0]
foreign_limit = info.get('foreign_limit', 49.0)  # default 49% if not provided
room_remaining_pct = max(0.0, foreign_limit - foreign_pct)
utilization = foreign_pct / foreign_limit if foreign_limit else 0.0
```

For deeper detail (daily tracking, foreign net buy/sell volume), use the TCBS public endpoint exposed by `vnstock.Listing()` or `vnstock.Quote(symbol).intraday(...)`.

## Alert Thresholds

| Utilization | State | Action |
|-------------|-------|--------|
| ≥ 95% | Full room (kín room) | Block / warn: foreign-flow strategies will not work; expect OTC premium |
| ≥ 85% | Tight room | Caution: confirm strategy still works in size; reduce position sizing |
| < 85% | Normal | No special handling needed |

Surface a structured warning to the user when emitting strategy recommendations:

```
⚠ Foreign room alert: VNM.HOSE is at 47.8% / 49.0% (97.5% utilized).
  Strategies dependent on foreign inflows are unlikely to execute at quoted prices.
```

## Strategy Integration

When generating any strategy for VN equities, run the foreign-room check **before** finalizing the entry list. Drop or downweight names with utilization ≥ 95% if the thesis depends on:

- ETF inclusion / rebalance flows
- MSCI / FTSE upgrade themes
- Foreign-fund factor signals (e.g. "follow-the-block")
- Index-arbitrage trades that need primary-market depth

For domestic-flow strategies (retail momentum, technical breakouts driven by local money) the alert is informational only.

## Sectors with Strict Limits

| Sector | Cap | Notes |
|--------|-----|-------|
| Banking | 30% | Hard cap; only the SBV may grant exemptions (typically for restructuring, e.g. CTG, BID windows) |
| Telecom | 49%, often lower in practice | Strategic state holdings reduce floating room (e.g. VGI, FPT telecom subsidiaries) |
| Aviation | 30% | Vietnam Aviation Law caps foreign ownership in carriers |
| Insurance | 49% | Some life-insurance JVs are higher via project-by-project waiver |
| Real estate (with land use rights near defense zones) | Restricted | Rarely material for listed names |

## Common Pitfalls

- **Stale snapshots**: `Company().overview()` may cache for several minutes; for live trading checks, prefer the daily `foreign_trade` endpoint on TCBS.
- **Nominee structures**: some "foreign" holdings are routed through domestic SPVs and may not appear in the official tally. Treat reported numbers as a lower bound.
- **Recently changed caps**: when a company amends its charter to lift/lower the cap, the data feed can lag by 1–3 trading days.
