---
name: execution-model
description: Trade execution modeling (backtest only) — slippage formulas (linear / square-root impact), VWAP/TWAP execution logic, market-impact cost estimation, and execution-assumption configuration.
category: strategy
---

# Trade Execution Modeling

## Overview

Provide more realistic execution assumptions for backtests, including slippage models, market-impact estimation, and execution-algorithm principles. This skill is for backtest simulation only and does not involve live order execution.

## Slippage Models

### Why Slippage Models Are Needed

```
Idealized backtest: filled at the close, zero slippage
Real world:
1. The order book has a bid-ask spread
2. Large orders push prices (market impact)
3. Execution is delayed (there is latency from signal to fill)

No slippage model -> overly optimistic backtest -> losses in live trading
```

**Do not retype these models.** All four are implemented and tested in
`src/quantlib/impact.py`; import them. The tested versions validate their inputs —
a zero ADV raises instead of dividing by zero, and a negative `delay_bars` raises
instead of silently introducing look-ahead bias.

```python
from src.quantlib.impact import fixed_slippage, linear_impact, sqrt_impact, delayed_execution
```

### 1. Fixed Slippage Model

```python
fixed_slippage(price=100.0, direction=1, bps=5.0)   # 100.05  (buy pays up)
fixed_slippage(price=100.0, direction=-1, bps=5.0)  #  99.95  (sell receives less)
```

`direction` is 1 to buy or -1 to sell, and must be exactly one of those — it
multiplies the impact, so an unchecked 2 would silently double the modelled cost.
`bps` defaults to `DEFAULT_SLIPPAGE_BPS` (5.0).

**Reference fixed-slippage assumptions by market:**

| Market | Instrument | Suggested Slippage (bps) | Notes |
|------|------|-------------|------|
| China A-share large cap | CSI 300 constituents | 3-5 | Good liquidity |
| China A-share small cap | CSI 1000 constituents | 5-10 | Average liquidity |
| China micro-cap | market cap < 5 billion RMB | 10-30 | Poor liquidity |
| US large cap | AAPL / MSFT | 1-3 | Excellent liquidity |
| Hong Kong stocks | Hang Seng constituents | 5-10 | Less liquid than A / US |
| BTC spot | BTC-USDT | 2-5 | Good OKX liquidity |
| ETH spot | ETH-USDT | 3-8 | Slightly worse than BTC |
| Small altcoins | other `-USDT` pairs | 10-50 | Liquidity varies widely |

### 2. Linear Impact Model

`impact = impact_coeff × volume_traded / adv`

```python
# 100k shares against 1M ADV = 10% participation; at coeff 0.1 that is a 1% move.
linear_impact(price=100.0, direction=1, volume_traded=100_000, adv=1_000_000, impact_coeff=0.1)
# 101.0
```

Marginal impact is constant here, which overstates the cost of very large orders.
`impact_coeff` defaults to `DEFAULT_LINEAR_IMPACT_COEFF` (0.1).

**Reference impact coefficients:**

| Market | impact_coeff | Notes |
|------|-------------|------|
| China A-share large cap | 0.05-0.10 | 10% daily price-limit system |
| China A-share small cap | 0.10-0.20 | Liquidity premium |
| US equities | 0.03-0.08 | Market-maker buffering |
| Crypto | 0.05-0.15 | 24h trading is dispersed |

### 3. Square-Root Impact Model

`impact = η × σ × sqrt(volume_traded / adv)`

```python
# 250k against 1M ADV = 25% participation; 0.5 × 0.02 × sqrt(0.25) = 0.005 = 50bps.
sqrt_impact(price=100.0, direction=1, volume_traded=250_000, adv=1_000_000,
            volatility=0.02, eta=0.5)
# 100.5  (100.49999999999999 in binary floating point)
```

`volatility` is daily return volatility as a decimal fraction. `eta` defaults to
`DEFAULT_SQRT_IMPACT_ETA` (0.5); 0.3-0.8 is the usual calibrated range.

**Advantages of the square-root model**:
- Strongest empirical support (standard in financial literature)
- Marginal impact declines for larger orders (intuitive)
- Parameters can be estimated from historical data

> **Naming.** This impact term is often labelled "Almgren-Chriss", and it does come
> from that literature, but it is **not** Almgren-Chriss optimal execution. There is
> no trading trajectory, no permanent/temporary impact split and no risk-aversion
> parameter here, and none is implemented anywhere in this repository. Call it a
> square-root impact function, and do not claim an optimal schedule was computed.

### Slippage Model Selection Decision Tree

```
Backtest capital vs instrument ADV:
├── Capital < 0.5% of ADV -> fixed slippage (5bps) is enough
├── Capital 0.5-5% -> linear impact model
└── Capital > 5% -> square-root impact model (required)
```

## Execution Algorithm Principles

### VWAP (Volume Weighted Average Price)

```
Goal: execute at the day's volume-weighted average price

VWAP = Σ(Price_i × Volume_i) / Σ(Volume_i)

Execution logic:
1. Forecast the intraday volume profile (typically U-shaped)
2. Split the order according to the predicted profile
3. Execute proportionally in each time slice

Typical China A-share VWAP volume profile (U-shaped):
09:30-10:00  15%  (active open)
10:00-11:30  25%  (normal morning session)
13:00-14:00  15%  (weak afternoon session)
14:00-14:30  15%  (afternoon recovery)
14:30-15:00  30%  (active close)

VWAP in backtests:
- Daily backtest: use the VWAP field directly as the fill price
- Minute backtest: simulate VWAP order slicing
```

### TWAP (Time Weighted Average Price)

```
Goal: execute evenly over a specified time window

TWAP = simple time-sliced execution

Execution logic:
1. Define an execution window (for example 09:30-11:30)
2. Divide it into N time buckets
3. Execute total_size / N in each bucket

Pros and cons:
+ Simple, no need to forecast volume
- Easier to cause impact during low-volume periods
- Less adaptive than VWAP
```

### Simulating Execution Delay in Backtests

```python
signals = delayed_execution(raw_signal, delay_bars=1)   # T+1: trade tomorrow on today's signal
signals = delayed_execution(raw_signal, delay_bars=0)   # same-bar execution
```

- China A-shares: `delay_bars=1` (T+1 rule)
- Crypto: `delay_bars=0` or `1`

A negative `delay_bars` raises. It would pull future signal values into the past,
which is look-ahead bias and silently inflates every backtest containing it — the
tested implementation refuses rather than letting that pass unnoticed.

## Integrated Transaction-Cost Model

### Total Cost Breakdown

```
Total trading cost = explicit cost + implicit cost

Explicit cost:
- Commission: China A-shares 2-3 bps, crypto 0.02-0.1%
- Stamp duty (China A-share sell side): 0.05% (sell orders only)
- Transfer fee: negligible

Implicit cost:
- Bid-ask spread: 0.5-5bps
- Market impact: depends on trade size and liquidity
- Opportunity cost: loss from not filling at the best price
```

### Reference Trading Costs by Market

| Cost Item | China A-shares | Hong Kong | US | Crypto (OKX) |
|--------|-----|------|------|-----------|
| Commission (one way) | 0.025% | 0.05% | 0 (zero commission) | 0.08% (maker) |
| Stamp duty | 0.05% (sell) | 0.1% (both sides) | 0 | 0 |
| Bid-ask spread | 0.03-0.1% | 0.05-0.2% | 0.01-0.05% | 0.01-0.05% |
| Total one-way | ~0.1% | ~0.2% | ~0.03% | ~0.1% |
| Total round-trip | ~0.2% | ~0.4% | ~0.06% | ~0.2% |

### Cost Settings in Backtests

```json
{
  "commission": 0.001,
  "comment": "0.1% one-way commission, already includes stamp duty and spread"
}
```

**Recommendations**:
- China A-shares: `commission = 0.001` (conservative, includes all costs)
- Crypto: `commission = 0.001` (including slippage)
- Hong Kong / US equities: `commission = 0.001-0.002`

## Backtest Execution Assumptions

### Relevant `config.json` Settings

```json
{
  "commission": 0.001,
  "engine": "daily",
  "interval": "1D"
}
```

### Advanced Execution Assumptions (implemented in `signal_engine.py`)

```python
from src.quantlib.impact import delayed_execution


class SignalEngine:
    def __init__(self):
        # Execution assumption parameters
        self.execution_delay = 1       # T+1 delay
        self.slippage_bps = 5          # Fixed 5bps slippage
        self.max_participation = 0.05  # Maximum participation rate 5%

    def generate(self, data_map):
        for code, df in data_map.items():
            # 1. Generate raw signal
            raw_signal = self._compute_signal(df)

            # 2. Apply execution delay
            delayed_signal = delayed_execution(raw_signal, self.execution_delay)

            # 3. Apply volume filter (do not trade when liquidity is too low)
            volume_ok = df['volume'] > df['volume'].rolling(20).mean() * 0.3
            delayed_signal[~volume_ok] = 0

            signals[code] = delayed_signal
```

## Analysis Framework

### Evaluate the Impact of Transaction Costs

```
Step 1: Estimate annual turnover
  Annual turnover = annual trade count × 2 (buy + sell) / number of positions

Step 2: Compute annual cost drag
  Annual cost = annual turnover × total one-way cost

Step 3: Evaluate the impact on returns
  Net return = gross return - annual cost

Example:
  Annual turnover = 12 (monthly rebalance)
  One-way cost = 0.1%
  Annual cost = 12 × 0.1% = 1.2%
  If annualized return is only 5% -> costs eat 24% of returns!
```

### Sensitivity Analysis for Execution Assumptions

```markdown
### Backtest Results Under Different Slippage Assumptions

| Slippage (bps) | Annual Return | Sharpe | Max Drawdown |
|-----------|---------|--------|---------|
| 0 (ideal) | 15.2% | 1.35 | -18.5% |
| 3 | 13.8% | 1.22 | -19.0% |
| 5 | 12.9% | 1.15 | -19.2% |
| 10 | 11.1% | 0.98 | -19.8% |
| 20 | 7.5% | 0.65 | -20.5% |

Conclusion: the strategy still has meaningful profitability under 10bps slippage
```

## Output Format

```markdown
## Execution Cost Analysis

### Strategy Trading Characteristics
| Metric | Value |
|------|-----|
| Average annual trade count | 48 |
| Annual turnover | 4.8x |
| Average holding days | 25 |
| Average order size | ¥50,000 |

### Cost Estimate
| Cost Item | Per Trade | Annualized |
|--------|------|------|
| Commission | 0.025% | 0.24% |
| Stamp duty | 0.025% | 0.12% |
| Estimated slippage | 0.03% | 0.29% |
| **Total** | **0.08%** | **0.65%** |

### Cost Impact
- Gross return: 12.5%
- Net return: 11.85%
- Cost drag: -0.65% (5.2% of gross return)
- Conclusion: cost impact is manageable

### Optimization Suggestions
1. Lower turnover (lengthen holding period)
2. Avoid trading during low-liquidity windows
3. Use limit orders instead of market orders
```

## Notes

1. **Backtest only**: this system does not execute live trades; the execution model is used only to improve backtest realism
2. **Conservative assumptions**: in backtests, it is better to overestimate transaction costs than to underestimate them
3. **China A-share T+1 rule**: trades cannot be executed on the same day the signal is generated, so execution must be delayed by 1 day
4. **Price-limit constraints**: when China A-shares are locked at limit-up / limit-down, no fill is possible; those dates should be skipped in backtests
5. **Volume constraints**: order size should not exceed 5-10% of the day’s traded volume, otherwise the impact model becomes invalid
6. **Backtest overfitting**: even with slippage included, the strategy may still overfit; out-of-sample validation matters more
7. **`commission` in config**: the default `0.001` (0.1%) is a reasonable all-in cost estimate
8. **The models are implemented, not improvised**: `src/quantlib/impact.py` holds all four, tested. Import them rather than retyping; the tested versions reject a zero ADV, a negative order size and a negative execution delay, all of which the retyped versions used to accept silently
