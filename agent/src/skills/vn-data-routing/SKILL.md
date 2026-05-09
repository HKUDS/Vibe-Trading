---
name: vn-data-routing
category: data-source
description: Decision tree for routing Vietnam stock symbols (HOSE/HNX/UPCoM) to the vnstock loader. Load BEFORE any VN backtest or research task.
---

## Overview

Vietnam's listed equity universe spans three exchanges, each with distinct listing standards and tick conventions. This skill routes any Vietnam-flavored ticker to the correct loader and tells the runner which `market` namespace to use.

Load this BEFORE writing a config.json, fetching financials, or starting a research script that touches a Vietnamese symbol.

## Symbol Formats

Vietnam tickers are 3-letter alphabetic codes (e.g. `VNM`, `FPT`, `SHB`). To disambiguate exchange we adopt a `.HOSE / .HNX / .UPCOM` suffix convention internally:

| Suffix | Exchange | Market namespace |
|--------|----------|------------------|
| `.HOSE` | Ho Chi Minh Stock Exchange (Sở Giao dịch Chứng khoán TP.HCM) | `vn_equity` |
| `.HNX` | Hanoi Stock Exchange (Sở Giao dịch Chứng khoán Hà Nội) | `vn_equity` |
| `.UPCOM` | Unlisted Public Company Market (Thị trường UPCoM) | `vn_equity` |

Bare 3-letter tickers (no suffix) default to **HOSE** — this matches the most common case (~400 of the ~700 actively traded names).

## Source Priority

1. **vnstock** (primary) — Python library that wraps multiple Vietnamese broker APIs. Internally cycles through:
   - VCI (Viet Capital Securities) — fastest, default
   - TCBS (Techcom Securities) — fallback for OHLCV and corporate actions
   - MSN (MSN/Microsoft finance proxy) — last-resort intraday quotes
2. **akshare** (off-site fallback) — only useful for HK-listed Vietnamese ADRs (rare; e.g. some shell-company ADR proxies). Do NOT use akshare for primary VN equity history.

If `vnstock` raises a network or rate-limit error, retry once with the next internal source before failing the task.

## Code Pattern Detection

Use this regex to identify VN exchange suffixes:

```python
import re
VN_EXCHANGE_RE = re.compile(r"\.(HOSE|HNX|UPCOM)$")

def is_vn_symbol(sym: str) -> bool:
    if VN_EXCHANGE_RE.search(sym):
        return True
    # Fallback: bare 3-letter alpha → assume VN HOSE
    return bool(re.fullmatch(r"[A-Z]{3}", sym))
```

## Examples

| Input | Routes to | Notes |
|-------|-----------|-------|
| `VNM.HOSE` | HOSE / vn_equity | Vinamilk — large-cap consumer staple |
| `FPT` | HOSE / vn_equity (default) | FPT Corporation — bare ticker → HOSE |
| `SHB.HNX` | HNX / vn_equity | Saigon Hanoi Bank |
| `VEA.UPCOM` | UPCoM / vn_equity | Vietnam Engine and Agricultural Machinery |
| `VN30F2406.HOSE` | HOSE / vn_futures | VN30 index future, June 2024 |
| `VNINDEX.HOSE` | HOSE / vn_index | HOSE composite index |

## Loader Markets

The vnstock loader exposes three market namespaces:

| Market | Coverage |
|--------|----------|
| `vn_equity` | Common stocks across HOSE / HNX / UPCoM, including fundamentals, OHLCV, corporate actions |
| `vn_index` | VNINDEX, VN30, HNX-Index, HNX30, UPCoM-Index — daily and intraday |
| `vn_futures` | VN30 index futures (monthly contracts: F1, F2, F3, F4) — only product currently listed |

## When to Use

Trigger this skill any time the request involves:

- The user explicitly mentions Vietnam, VN market, HOSE, HNX, or UPCoM
- A ticker carries a `.HOSE / .HNX / .UPCOM` suffix
- A ticker is a 3-letter bare alpha code with no other market context
- The user names a known Vietnamese company (Vinamilk, FPT, Vietcombank, Hoa Phat, etc.)
- The config.json declares `market: "vn_equity" | "vn_index" | "vn_futures"`

## Backtest Configuration

Use `source: "auto"` in config.json — the runner detects VN markets by suffix and routes to the vnstock loader. You do NOT need to hard-code `source: "vnstock"` unless the user explicitly requests it.

```json
{
  "symbol": "VNM.HOSE",
  "market": "vn_equity",
  "source": "auto"
}
```

## Availability Check

- `vnstock`: free, no API key. May be rate-limited (~60 req/min per source). The library auto-rotates internal sources.
- Network: requires access to Vietnamese broker domains (vps.com.vn, tcbs.com.vn). Behind a strict firewall, expect timeouts.
- If all internal sources fail, surface the error to the user — do NOT silently fall back to akshare for VN equities (data quality differs).
