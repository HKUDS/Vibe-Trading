# Strategy Development Manager: Example Workflows

## Example 1: Paper to Factor

**Scenario**: Extracting a momentum factor from Jegadeesh and Titman (1993), "Returns to Buying Winners and Selling Losers."

### Phase 1: INGEST

```
read_document(paper_path="papers/jegadeesh_titman_1993.pdf")
```

Output: full text extracted. Classification: **factor-research**.

Key information extracted:
- Methodology: sort stocks by past 3-12 month returns, buy winners, sell losers
- Formula: `R_mom = cumulative_return(t-12, t-1)` with 1-month skip
- Variables: past returns, skip period, formation period
- Universe: US equities (NYSE/AMEX/NASDAQ)
- Reported performance: ~1% monthly excess return

### Phase 2: EXTRACT

Structured extraction:

```python
factor_def = {
    "name": "momentum_12_1",
    "formula_latex": "R_{mom} = \\prod_{i=t-12}^{t-1}(1 + r_i) - 1",
    "variables": {"formation_period": 12, "skip_period": 1, "return_type": "cumulative"},
    "columns_required": ["close"],
    "universe": "equity_us",
    "decay_horizon": 21,
}
```

Deduplication check:

```
alpha_bench(zoo="academic", universe="equity_us", period="2015-2025")
```

Result: the existing `academic_carhart_momentum` alpha has IC 0.92 with our formula. This is a variant (not a duplicate, since IC < 0.99), so we proceed with a note.

Register:

```
sdm_register(
    artifact_type="factor",
    name="momentum_12_1",
    universe="equity_us",
    formula_latex="R_{mom} = \\prod_{i=t-12}^{t-1}(1 + r_i) - 1",
    columns_required=["close"],
    decay_horizon=21,
    source_paper="Jegadeesh & Titman (1993)",
    notes="Variant of Carhart momentum with explicit 1-month skip"
)
```

### Phase 3: IMPLEMENT

```
create_hypothesis(
    title="Jegadeesh-Titman 12-1 Momentum Factor",
    thesis="Stocks with high cumulative returns over the past 12 months (skipping the most recent month) will continue to outperform in the next month.",
    universe="equity_us",
    signal_definition="Cross-sectional rank of 12-month cumulative return, skipping month t-1"
)
```

```
generate_backtest_config(
    hypothesis_id="hyp_001",
    start_date="2015-01-01",
    end_date="2025-01-01"
)
```

```
scaffold_signal_engine(hypothesis_id="hyp_001", run_dir="runs/hyp_001")
```

Then implement `signal_engine.py` using the factor template, filling in the momentum computation:

```python
# Inside generate():
for symbol, df in data_map.items():
    # 12-month cumulative return, skip most recent month
    ret_12m = df["close"].pct_change(12).shift(1)
    ret_1m = df["close"].pct_change(1)
    mom_signal = ret_12m - ret_1m  # skip the most recent month
    signals[symbol] = mom_signal
```

```
backtest(run_dir="runs/hyp_001")
```

```
link_autopilot_backtest(hypothesis_id="hyp_001", run_dir="runs/hyp_001")
```

```
sdm_status(action="update", artifact_id="momentum_12_1", status="benching")
```

### Phase 4: EVALUATE

```
factor_analysis(
    factor_csv="runs/hyp_001/artifacts/factor.csv",
    return_csv="runs/hyp_001/artifacts/return.csv",
    output_dir="runs/hyp_001/artifacts/analysis"
)
```

Results:
- IC mean: 0.042 (> 0.03 threshold)
- IR: 0.68 (> 0.5 threshold)
- IC positive ratio: 58% (> 55% threshold)

Verdict: **alive**. Register as active:

```
sdm_status(action="update", artifact_id="momentum_12_1", status="active",
           metrics={"ic_mean": 0.042, "ir": 0.68, "ic_positive_ratio": 0.58})
```

---

## Example 2: Paper to Strategy

**Scenario**: Implementing a mean-reversion strategy from Avramov and Chordia (2006), "Predicting Stock Returns Using Transaction Activity."

### Phase 1: INGEST

```
read_document(paper_path="papers/avramov_chordia_2006.pdf")
```

Output: full text extracted. Classification: **strategy**.

Key information extracted:
- Methodology: use order flow imbalance to predict short-term mean reversion
- Entry rule: buy when normalized order flow is below -2 standard deviations (heavy selling), sell when above +2 standard deviations
- Exit rule: hold for 5 trading days or exit when order flow normalizes
- Position sizing: equal-weight across selected stocks, max 10 positions
- Risk management: 5% stop-loss per position
- Universe: US equities, large-cap

### Phase 2: EXTRACT

Structured extraction:

```python
strategy_def = {
    "name": "order_flow_mean_reversion",
    "entry_rules": [
        "normalized_order_flow < -2.0 (heavy selling, buy signal)",
        "normalized_order_flow > 2.0 (heavy buying, sell signal)",
    ],
    "exit_rules": [
        "hold_days >= 5 (time-based exit)",
        "abs(normalized_order_flow) < 0.5 (flow normalized, exit)",
        "position_pnl < -0.05 (stop-loss)",
    ],
    "position_sizing": "equal_weight, max_positions=10",
    "risk_management": {"stop_loss_pct": 0.05, "max_positions": 10},
    "universe": "equity_us",
    "columns_required": ["close", "volume"],
    "source_paper": "Avramov & Chordia (2006)",
}
```

Deduplication check:

```
sdm_status(action="list", artifact_type="strategy", universe="equity_us")
```

No existing strategy matches. Register:

```
sdm_register(
    artifact_type="strategy",
    name="order_flow_mean_reversion",
    universe="equity_us",
    entry_rules=strategy_def["entry_rules"],
    exit_rules=strategy_def["exit_rules"],
    position_sizing="equal_weight",
    columns_required=["close", "volume"],
    source_paper="Avramov & Chordia (2006)"
)
```

### Phase 3: IMPLEMENT

```
create_hypothesis(
    title="Order Flow Mean Reversion Strategy",
    thesis="Stocks experiencing extreme order flow imbalances (measured by volume-weighted price pressure) will revert in the short term.",
    universe="equity_us",
    signal_definition="Buy when normalized volume-pressure is below -2 std, sell when above +2 std, hold 5 days"
)
```

```
generate_backtest_config(
    hypothesis_id="hyp_002",
    start_date="2018-01-01",
    end_date="2025-01-01"
)
```

```
scaffold_signal_engine(hypothesis_id="hyp_002", run_dir="runs/hyp_002")
```

Then implement `signal_engine.py` using the strategy template, filling in the order flow logic:

```python
# Inside generate():
for symbol, df in data_map.items():
    # Volume-weighted price pressure as order flow proxy
    vwap_proxy = (df["volume"] * df["close"]).rolling(20).sum() / df["volume"].rolling(20).sum()
    price_pressure = (df["close"] - vwap_proxy) / df["close"].rolling(20).std()

    # Entry: extreme selling pressure -> buy signal
    buy_signal = (price_pressure < -2.0).astype(float)
    sell_signal = (price_pressure > 2.0).astype(float)

    # Hold for 5 days using a simple decay
    raw_signal = buy_signal - sell_signal
    signals[symbol] = raw_signal.rolling(5).max() * raw_signal
```

```
backtest(run_dir="runs/hyp_002")
```

```
link_autopilot_backtest(hypothesis_id="hyp_002", run_dir="runs/hyp_002")
```

```
sdm_status(action="update", artifact_id="order_flow_mean_reversion", status="benching")
```

### Phase 4: EVALUATE

Read `runs/hyp_002/artifacts/metrics.csv` and `run_card.json`:

Results:
- Sharpe ratio: 0.82 (> 0.5 threshold)
- Max drawdown: 18.3% (< 30% threshold)
- Win rate: 54%
- Profit factor: 1.35

Verdict: **alive**. Update status:

```
sdm_status(action="update", artifact_id="order_flow_mean_reversion", status="active",
           metrics={"sharpe": 0.82, "max_drawdown": 0.183, "win_rate": 0.54})
```

### Phase 5: MONITOR (later)

After several weeks of live benching:

```
sdm_decay_scan(universe="equity_us")
```

Output shows `order_flow_mean_reversion` with status "healthy" (all metrics above thresholds). The momentum factor from Example 1 shows "warning" on IC ratio (dropped to 0.62). No action needed yet, but the next scan will determine if it transitions to "monitoring."
