# Design Addendum: VN30 Futures Engine (Sprint 2.1)

> Companion to `design.md`. Implementation-level design for `VNFuturesEngine`.
> All code paths verified against actual codebase (Sprint 1 baseline).

## Why a separate engine

VN30F differs from VNEquityEngine on every axis: cash margin (not full payment), multiplier (100k VND/point), daily mark-to-market, cash settlement at expiry, position-based not share-based, no T+2 (futures are T+0). It differs from ChinaFuturesEngine on: single product family (4 contracts vs 50+), cash-settled only, simpler margin schedule.

Decision: extend `FuturesBaseEngine` (which already handles multiplier-aware PnL/margin/sizing). One file, ~150 LOC, mirrors `china_futures.py` style minus the giant lookup tables.

## VN30F contract spec (verified, HNX 2024-2026)

| Property | Value |
|----------|-------|
| Underlying | VN30 Index |
| Listing | HNX |
| Active contracts | `VN30F1M`, `VN30F2M`, `VN30F1Q`, `VN30F2Q` |
| Multiplier | 100,000 VND × index points |
| Initial margin (broker) | 17% (exchange minimum 13%, configurable) |
| Maintenance margin | 80% of initial (configurable) |
| Daily price band | ±7% from prior settlement |
| Tick size | 0.1 points |
| Trading hours | 08:45–14:30 (continuous) + 14:30–14:45 (ATC) |
| Settlement | Cash, mark-to-market each session, final = avg VN30 last 30 min of expiry day |
| Expiry day | 3rd Thursday of contract month |
| Tax | 0.1% per side on contract value (MoF Circular 100/2017/TT-BTC) |
| Position limit | 5,000 contracts per retail individual |
| Short selling | Allowed (futures are inherently long/short symmetric) |

## Symbol routing

VN30F symbols MUST be detected BEFORE the generic `.HNX` equity rule in `composite._MARKET_PATTERNS`:

```python
# Insert at top of _MARKET_PATTERNS (highest priority)
(re.compile(r"^VN30F[12][MQ](\.HNX)?$"), "vn_futures"),
# ... existing patterns ...
(re.compile(r"\.(HOSE|HNX|UPCOM)$", re.I), "vn_equity"),
```

Canonical form: `VN30F1M` (no suffix). Loader accepts both `VN30F1M` and `VN30F1M.HNX`.

## Engine API

```python
class VNFuturesEngine(FuturesBaseEngine):
    """VN30 index futures engine (HNX).

    Market rules:
      - 4 active contracts: F1M / F2M / F1Q / F2Q
      - Initial margin: 17% (configurable per broker)
      - Daily mark-to-market with margin call simulation
      - Cash settlement at expiry against VN30 close
      - Long/short symmetric (no T+2, no short-sell restriction)
      - Price band: ±7% from prior settlement
      - Tax: 0.1% per side
    """

    CONTRACT_MULTIPLIER: float = 100_000.0
    KNOWN_CONTRACTS: tuple[str, ...] = ("VN30F1M", "VN30F2M", "VN30F1Q", "VN30F2Q")

    def __init__(self, config: dict):
        config = {**config, "leverage": 1 / config.get("margin_rate", 0.17)}
        super().__init__(config)
        self.margin_rate = config.get("margin_rate", 0.17)
        self.maintenance_ratio = config.get("maintenance_ratio", 0.80)
        self.commission_per_contract = config.get("commission_per_contract", 2700.0)  # VND
        self.tax_rate = config.get("tax_rate", 0.001)
        self.price_band = config.get("price_band", 0.07)
        self.position_limit = config.get("position_limit", 5000)

    def get_contract_multiplier(self, symbol: str) -> float:
        return self.CONTRACT_MULTIPLIER

    def can_execute(self, symbol, direction, bar) -> bool:
        # 1. Symbol must be a known VN30F contract
        # 2. Price band: block if pct_change at limit (±7%)
        # 3. Position limit: block opens that would exceed 5000 contracts
        # NO T+2 (futures), NO short-block

    def round_size(self, raw_size, price) -> float:
        return max(int(abs(raw_size)), 0)  # 1-contract granularity

    def calc_commission(self, size, price, direction, is_open) -> float:
        # Per-contract commission + per-side tax on notional
        notional = abs(size) * price * self.CONTRACT_MULTIPLIER
        return abs(size) * self.commission_per_contract + notional * self.tax_rate

    def daily_settle(self, bar_close: float, prior_settle: float):
        # End-of-day mark-to-market: realize unrealized PnL
        # Triggers margin call check
        ...

    def is_expiry(self, symbol: str, bar_date) -> bool:
        # 3rd Thursday of contract month
        ...

    def expiry_settlement(self, symbol: str, vn30_avg: float):
        # Cash-settle position at avg VN30 of last 30 min
        ...
```

## Daily mark-to-market hook

`BaseEngine.run_backtest()` already handles bar-by-bar PnL via `_calc_pnl`. The new piece is the **end-of-bar settlement** event:

- After each bar close: realize unrealized P&L from prior settle to current close
- Update margin balance
- If margin balance < maintenance threshold → forced liquidation (closes position at next-bar open)
- Record settlement record per (symbol, date) in `self.settlements`

Implementation: add a `_after_bar_close(bar)` hook in `BaseEngine` (default no-op), override in `VNFuturesEngine`. Avoids touching A-share/equity/crypto code paths.

## Expiry handling

The `vnstock_loader.py` (Sprint 1) returns continuous bars per contract. To avoid look-ahead at expiry:

1. On expiry day, after the standard daily settle, mark the position as `expired`
2. Compute final settlement price = mean of last 30-min VN30 minute bars (if minute data unavailable, fall back to close)
3. Close position at the settlement price
4. Subsequent bars for that contract are ignored (engine treats as no position)
5. User strategy is responsible for rolling — we do NOT auto-roll

Edge case: if expiry day data missing from vnstock, settle at last available close with a warning logged.

## Margin call simulator

```
margin_balance = initial_deposit + cumulative_settled_pnl
maintenance_threshold = current_position_notional × margin_rate × maintenance_ratio

if margin_balance < maintenance_threshold:
    # Margin call — engine forces close at next bar open
    forced_close_pending = True
    record_event("margin_call", symbol, bar_date, balance, threshold)
```

If balance goes negative, position is force-closed even mid-bar at the available price (trade record marked `forced_liquidation`).

## Loader contract for VN30F

`VNStockLoader` already declares `vn_futures` market in Sprint 1. Sprint 2 adds:
- `_strip_exchange()` already strips `.HNX` → `VN30F1M.HNX` becomes `VN30F1M` ✓
- New: detect VN30F prefix in `fetch()` and use vnstock's derivatives data API

vnstock library: `from vnstock import Quote; Quote(symbol='VN30F1M', source='VCI').history(...)`. Verified: VCI source carries derivatives. TCBS may also work. MSN unknown — test during Sprint 2.1.

If derivatives are NOT supported by vnstock, fallback path: query TCBS public API directly (TCBS exposes derivatives). Document this fallback in loader, gate by symbol-prefix check.

## Verification

| Component | Verification |
|-----------|--------------|
| Symbol routing | Unit: `_detect_market("VN30F1M")` → `vn_futures`; `_detect_market("VN30F1M.HNX")` → `vn_futures`; `_detect_market("ABC.HNX")` → `vn_equity` |
| Margin call | Property: starting balance B, after sequence of losses summing to B*(1−maintenance_ratio×margin_rate)+ε, position is force-closed |
| Expiry settlement | Snapshot: open VN30F1M long, hold to 3rd Thursday, assert final P&L computed against fixture VN30 avg |
| Multiplier | Unit: P&L of 1 long contract from 1200 → 1210 = 1 × 100k × 10 = 1,000,000 VND |
| Tax + commission | Unit: 1-contract round trip at 1200 with 2700 VND commission and 0.1% tax = 2×2700 + 2×(1200×100k×0.001) = 5400 + 240,000 = 245,400 VND |
| Position limit | Unit: open 5000 contracts → next open blocked |
| Composite cross-asset | Smoke: VN equity portfolio + VN30F short hedge in CompositeEngine, assert shared cash pool |

## What we're NOT doing in Sprint 2.1

- **No options on VN30F** (don't exist in VN market yet)
- **No individual stock futures** (don't exist on VN listed market)
- **No auto-roll** at expiry (strategy's responsibility)
- **No basis arbitrage helper** (that's the `vn-vn30-arbitrage` skill in Sprint 3)
- **No minute-bar settlement** for the final 30-min avg if minute data not available — fall back to close with warning
- **No exchange margin tier table** — use single configurable margin rate (per-broker variation handled via config)
- **No night session** (VN derivatives have no night session — simpler than China futures)
