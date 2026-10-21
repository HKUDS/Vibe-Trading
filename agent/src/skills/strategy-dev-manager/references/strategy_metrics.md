# Strategy Evaluation Metrics

This document defines strategy-specific evaluation metrics that supplement the factor-focused IC/IR metrics in `decay_thresholds.md`. Factor-type artifacts use IC ratio, IR, and IC positive ratio as primary metrics. Strategy-type artifacts use risk-adjusted return metrics as defined below.

## 1. Strategy Evaluation Metrics

### 1.1 Primary Metrics

| Metric | Formula | Healthy | Warning | Decayed | Critical |
|--------|---------|---------|---------|---------|----------|
| Sharpe Ratio | (R - Rf) / sigma | > 1.0 | 0.5 - 1.0 | 0.0 - 0.5 | < 0.0 |
| Sortino Ratio | (R - Rf) / sigma_downside | > 1.5 | 1.0 - 1.5 | 0.5 - 1.0 | < 0.5 |
| Calmar Ratio | Annual Return / Max Drawdown | > 2.0 | 1.0 - 2.0 | 0.0 - 1.0 | < 0.0 |
| Max Drawdown | peak-to-trough decline | < 15% | 15% - 25% | 25% - 40% | > 40% |

### 1.2 Secondary Metrics

| Metric | Formula | Healthy | Warning | Decayed | Critical |
|--------|---------|---------|---------|---------|----------|
| Win Rate | winning trades / total trades | > 55% | 45% - 55% | 35% - 45% | < 35% |
| Profit Factor | gross profit / gross loss | > 1.5 | 1.2 - 1.5 | 1.0 - 1.2 | < 1.0 |
| Avg Trade Duration | mean holding period in bars | per strategy type | -- | -- | -- |

### 1.3 Metric Definitions

**Sharpe Ratio**: The excess return per unit of total risk. Uses annualized return minus the risk-free rate, divided by annualized standard deviation of returns. The primary metric for strategy health assessment.

```
Sharpe = (R_annual - Rf_annual) / sigma_annual
```

Where R_annual is the annualized portfolio return, Rf_annual is the annualized risk-free rate, and sigma_annual is the annualized standard deviation of daily returns multiplied by sqrt(252).

**Sortino Ratio**: Similar to Sharpe but penalizes only downside volatility. More appropriate for strategies with asymmetric return distributions.

```
Sortino = (R_annual - Rf_annual) / sigma_downside_annual
```

Where sigma_downside is the standard deviation of negative daily returns only.

**Calmar Ratio**: Annualized return divided by the maximum drawdown over the evaluation period. Captures the return-to-drawdown tradeoff.

```
Calmar = R_annual / |MaxDD|
```

Where MaxDD is the largest peak-to-trough decline expressed as a negative decimal.

**Max Drawdown**: The largest peak-to-trough decline in portfolio value during the evaluation period.

```
MaxDD = min over t of (V_t - max(V_0..V_t)) / max(V_0..V_t)
```

**Win Rate**: The fraction of closed trades that produced a positive return.

```
Win Rate = count(trades with PnL > 0) / count(all closed trades)
```

**Profit Factor**: The ratio of total gross profit to total gross loss across all closed trades.

```
Profit Factor = sum(positive PnL) / |sum(negative PnL)|
```

**Avg Trade Duration**: The mean number of bars (trading days) between entry and exit across all closed trades. This metric has no universal threshold; it is evaluated relative to the strategy's stated holding horizon.

### 1.4 Evaluation Priority

When evaluating a strategy backtest, check metrics in this order:

1. **Sharpe Ratio** -- primary gate; must exceed 0.5 for the artifact to be considered alive
2. **Max Drawdown** -- risk tolerance gate; must be below 30% for the artifact to be considered alive
3. **Sortino Ratio** -- secondary confirmation of risk-adjusted performance
4. **Win Rate and Profit Factor** -- additional context for strategy characterization

A strategy fails the minimum threshold if Sharpe < 0.5 OR Max Drawdown > 30%.

## 2. Strategy Decay Monitoring

### 2.1 How Strategy Decay Differs from Factor Decay

Factor decay and strategy decay use different primary signals:

| Aspect | Factor Decay | Strategy Decay |
|--------|-------------|----------------|
| Primary metric | IC ratio (rolling / baseline) | Sharpe ratio (rolling window) |
| What decays | Predictive power of the factor | Risk-adjusted return of the strategy |
| Detection speed | Fast (IC is computed per period) | Slower (Sharpe requires return accumulation) |
| Additional signals | IC positive ratio drop | Drawdown depth increase, win rate drop, trade frequency change |

### 2.2 Strategy-Specific Decay Signals

Beyond the Sharpe ratio, monitor these additional signals for strategy decay:

| Signal | Description | Threshold |
|--------|-------------|-----------|
| Increasing drawdown depth | Rolling max drawdown is deepening over successive windows | Each window deeper than the last for 3+ windows |
| Decreasing win rate | Rolling win rate is declining | Drop of > 10 percentage points from baseline |
| Increasing trade frequency | Number of trades per period is rising without return improvement | > 50% increase in trade count with flat or lower Sharpe |
| Decreasing profit factor | Rolling profit factor is declining | Drop below 1.0 (net losing) |

### 2.3 Strategy State Transition Rules

Strategy artifacts use the same state machine as factor artifacts but with strategy-specific transition conditions:

```
active -> monitoring:  rolling Sharpe < 0.5 for 3 consecutive monitoring periods
monitoring -> decayed: rolling Sharpe < 0.0 for 2 additional consecutive periods
decayed -> disabled:   negative Sharpe for 3 monitoring periods
monitoring -> active:  rolling Sharpe > 1.0 for 2 consecutive periods (recovery)
```

| Transition | Condition | Consecutive Requirement |
|------------|-----------|------------------------|
| active -> monitoring | Rolling Sharpe < 0.5 OR Max DD > 25% | 3 consecutive monitoring periods |
| monitoring -> decayed | Rolling Sharpe < 0.0 OR Max DD > 40% | 2 additional consecutive periods |
| monitoring -> active | Rolling Sharpe > 1.0 AND Max DD < 15% | 2 consecutive periods (recovery) |
| decayed -> disabled | Rolling Sharpe < 0.0 | 3 monitoring periods |
| created -> benching | Manual bench via `sdm_status(action="bench")` after the initial backtest is recorded | -- |
| benching -> active | Manual activate via `sdm_status(action="activate")` after Phase 4 passes | -- |
| disabled -> active | Manual enable via `sdm_status(action="enable")` | -- |

### 2.4 Combined Metric Evaluation

When multiple metrics are available, the worst signal determines the overall state:

- If Sharpe is "Healthy" but Max Drawdown is "Warning", the overall signal is "Warning"
- If Sharpe is "Decayed" but all other metrics are "Healthy", the overall signal is "Decayed"
- This conservative approach prevents a single deteriorating metric from being masked by others

## 3. Benchmark Comparison

Strategy metrics should be evaluated in context by comparing against relevant benchmarks.

### 3.1 Required Benchmarks

| Benchmark | Purpose | When to Use |
|-----------|---------|-------------|
| Buy-and-hold | Baseline return of the target universe | Always |
| Risk-free rate | Reference for Sharpe/Sortino computation | Always |
| Equal-weight portfolio | Naive diversification baseline | Multi-instrument strategies |

### 3.2 Optional Benchmarks

| Benchmark | Purpose | When to Use |
|-----------|---------|-------------|
| Existing strategies in same category | Relative performance comparison | When similar strategies exist in the store |
| Market index (SPY, CSI 300, etc.) | Broad market comparison | Universe-specific |
| Inverse strategy | Check if the strategy is just shorting the market | When Sharpe is negative |

### 3.3 Comparison Metrics

When comparing a strategy against a benchmark, compute:

- **Excess return**: Strategy annual return minus benchmark annual return
- **Information ratio**: Excess return divided by tracking error (standard deviation of excess returns)
- **Beta**: Strategy return sensitivity to benchmark return
- **Alpha**: Strategy return minus (Rf + Beta * (Benchmark return - Rf))

A strategy with positive excess return and Information Ratio > 0.5 provides value beyond the benchmark.

## 4. Rolling Window Configuration

The rolling window for strategy decay monitoring should match the strategy's rebalance frequency.

### 4.1 Recommended Windows

| Strategy Horizon | Rebalance Frequency | Rolling Window | Rationale |
|-----------------|--------------------|----------------|-----------|
| Short-horizon | Daily | 60 trading days (~3 months) | Enough trades for statistical significance |
| Medium-horizon | Weekly or monthly | 120 trading days (~6 months) | Captures multiple rebalance cycles |
| Long-horizon | Quarterly | 252 trading days (~1 year) | Full market cycle coverage |

### 4.2 Window Selection Rules

- If the strategy's average trade duration is < 5 days, use the 60-day window
- If the strategy's average trade duration is 5-20 days, use the 120-day window
- If the strategy's average trade duration is > 20 days, use the 252-day window
- When in doubt, use the 120-day window as the default

### 4.3 Minimum Sample Size

A rolling window must contain a minimum number of trades for the metrics to be meaningful:

| Metric | Minimum Trades | Rationale |
|--------|---------------|-----------|
| Sharpe Ratio | 30 trades | Central limit theorem threshold |
| Win Rate | 50 trades | Binomial proportion stability |
| Profit Factor | 30 trades | Ratio stability |
| Max Drawdown | No minimum | Always computable from equity curve |

If the rolling window contains fewer trades than the minimum, the metric is reported but flagged as "insufficient sample" and excluded from state transition evaluation.

## 5. Configuration

All thresholds in this document are configurable via the `DecayThresholds` dataclass in `src/strategy_store/decay.py`. Strategy-specific overrides can be set per artifact during registration:

```
sdm_register(
    artifact_type="strategy",
    name="mean_reversion_rsi",
    universe="equity_us",
    sharpe_healthy=1.0,
    sharpe_warning=0.5,
    sharpe_decayed=0.0,
    max_dd_healthy=0.15,
    max_dd_warning=0.25,
    max_dd_decayed=0.40,
    rolling_window_days=120,
    ...
)
```
