# Trade Attribution Design: Why We Chose Lightweight Over Full Brinson

## Why This Problem Exists

Every quant researcher who has run a 10-year backtest has faced the same uncomfortable question: where did the profits actually come from?

Consider a typical scenario. You backtest a momentum strategy on the S&P 500 from 2014 to 2024. The equity curve looks great: 200% cumulative return, a Sharpe ratio of 1.8, and a max drawdown of only 15%. You feel confident. Then you dig into the trade log and discover that 80% of the total P&L came from three trades. One was a lucky bottom-fish during the March 2020 COVID crash. Another was a short position that happened to be open during the February 2022 Russia-Ukraine invasion. The third was a leveraged bet that coincided with the November 2022 FTX collapse.

Remove those three trades and your Sharpe drops from 1.8 to 0.6. The strategy is not generating alpha. It is generating exposure to tail events.

This is the core challenge of trade attribution for individual researchers: distinguishing genuine signal-driven profits from what we call "10-year event" profits. The latter are real gains, but they will not repeat. A strategy that depends on being long during a once-in-a-decade crash is not a strategy you can trade forward with confidence.

### Why traditional attribution models fall short

The institutional world solved this problem decades ago, at least on paper. The Brinson-Hood-Beebower model (1986) decomposes portfolio returns into allocation, selection, and interaction effects. Factor attribution (Fama-French, Barra) breaks returns into exposures to systematic risk factors. These frameworks work well for their intended audience: pension funds, endowments, and registered investment advisors who need to explain performance to boards and regulators.

But they break down for individual quant researchers for several reasons.

First, Brinson attribution requires a benchmark. Most individual researchers run absolute-return strategies on single instruments or small portfolios. There is no natural benchmark to compare against, and picking one introduces arbitrary choices that contaminate the results.

Second, the interaction effect in Brinson models is economically meaningless. As Rocco (2010) pointed out, "interaction is not a decision." It is a mathematical artifact that cannot guide any actionable change to your strategy.

Third, factor attribution requires factor model infrastructure. You need access to Fama-French factor data, Barra risk models, or equivalent. For crypto strategies, no standard factor model exists at all. The engineering cost of building this infrastructure far exceeds the value it provides to a solo researcher iterating on strategy ideas.

Fourth, and most importantly, attribution is strictly ex-post. Hsu et al. (2010) acknowledged that traditional attribution "does not reflect any real investment process" but rather "attempts to characterize the effects of investment decisions after the fact." For a researcher who wants to know whether a strategy will work tomorrow, knowing why it worked yesterday is only half the answer.

### The gap

Institutional tools assume institutional context: benchmarks, compliance requirements, multi-asset portfolios, and teams of analysts to interpret the results. Individual researchers need something different. They need to know, quickly and with minimal setup, whether their strategy's profits are concentrated in a handful of anomalous trades, whether specific exit reasons dominate the P&L, and whether the strategy survives when you remove its best days.

That is the gap we set out to fill.


## How We Solved It

We took a deliberately lightweight approach. Instead of building a full attribution system, we implemented three complementary analyses that together answer the questions individual researchers actually ask: FIFO trade pairing, Top-N anomaly detection, and grouping statistics.

### Step 1: Pair entry and exit rows with FIFO

The backtest engine writes a `trades.csv` event log where each round trip produces two rows: an entry row (with `pnl=0`) and an exit row (with the realized P&L). The `pair_trades()` function reads this log and reconstructs round trips using a FIFO queue per symbol.

```python
def pair_trades(trade_rows: list[dict]) -> list[RoundTrip]:
    """Pair entry/exit rows from trades.csv into RoundTrip records."""
    by_symbol: Dict[str, list] = {}
    for row in trade_rows:
        by_symbol.setdefault(row["code"], []).append(row)

    result: list[RoundTrip] = []
    for symbol, rows in by_symbol.items():
        rows.sort(key=lambda r: r["timestamp"])
        entry_queue: list[dict] = []
        for row in rows:
            pnl = float(row.get("pnl", 0))
            if pnl == 0.0:
                entry_queue.append(row)
            else:
                if not entry_queue:
                    continue
                entry = entry_queue.pop(0)
                # ... compute holding_days, pnl_pct, direction
                result.append(RoundTrip(
                    symbol=symbol,
                    entry_time=pd.Timestamp(entry["timestamp"]),
                    exit_time=pd.Timestamp(row["timestamp"]),
                    pnl=pnl,
                    holding_days=holding_days,
                    exit_reason=str(row.get("reason", "")),
                ))
    return result
```

The FIFO approach handles pyramiding (multiple entries before an exit) correctly. It is simple, deterministic, and requires no external data beyond what the backtest engine already produces.

### Step 2: Top-N anomaly detection and grouping

The `compute_trade_attribution()` function takes the paired round trips and runs three analyses in one pass:

**Top-N winners and losers.** Sort all trades by P&L, surface the top 5 winners and top 5 losers. This immediately shows whether profits are concentrated. If your top 3 winners account for 60% of total P&L, you have a concentration problem.

**Robustness check.** Remove the top N winners and ask: is the strategy still profitable? This is the single most useful number in the entire attribution output. If `is_profitable_after_removal` is `False`, the strategy depends on a handful of lucky trades and should not be trusted for live trading.

**Grouping by exit reason and holding period.** Group trades by `exit_reason` (take-profit, stop-loss, timeout, signal reversal) and by holding period bucket (short: under 3 days, medium: 3 to 20 days, long: over 20 days). Each group reports count, total P&L, average P&L, and win rate.

```python
def compute_trade_attribution(round_trips, top_n=5):
    sorted_by_pnl = sorted(round_trips, key=lambda rt: rt.pnl, reverse=True)
    top_winners = [rt for rt in sorted_by_pnl[:top_n] if rt.pnl > 0]

    removed_pnl = sum(rt.pnl for rt in top_winners)
    remaining_pnl = total_pnl - removed_pnl

    # Group by exit_reason
    for rt in round_trips:
        reason_groups.setdefault(rt.exit_reason, []).append(rt)

    # Bucket by holding_days: short (<3), medium (3-20), long (>20)
    for rt in round_trips:
        if rt.holding_days < 3:
            buckets["short"].append(rt)
        elif rt.holding_days <= 20:
            buckets["medium"].append(rt)
        else:
            buckets["long"].append(rt)
```

### Step 3: JSON-safe formatting for API responses

The `build_trade_attribution()` wrapper reads the CSV, runs the pipeline, and sanitizes the output for JSON serialization. All `pd.Timestamp` values become ISO 8601 strings, and non-finite floats (NaN, Inf) become `null`. This makes the attribution data safe to return through REST APIs, MCP tool responses, and SSE streams without custom encoders.

### Visualization

The attribution output feeds directly into the Run Detail page. The K-line chart highlights Top-N trades with colored markers, and an attribution panel below the chart shows the exit-reason breakdown, holding-period distribution, and the robustness check result. No separate visualization library is needed. The data structure is designed to render cleanly in a table or a set of small charts.

### Why this works for individual researchers

The entire pipeline runs in under 10 milliseconds for a typical 500-trade backtest. It requires no external data, no benchmark selection, no factor model, and no configuration. The output answers three questions directly:

1. Are my profits concentrated in a few trades? (Top-N analysis)
2. Does my strategy survive without its best trades? (Robustness check)
3. Which exit reasons and holding periods drive my P&L? (Grouping statistics)

If the answer to any of these is concerning, the researcher knows to dig deeper. If all three look healthy, the strategy has passed a basic sanity check that most backtests never get.


## Alternative Solutions We Considered

Before settling on the lightweight approach, we evaluated the full spectrum of attribution methodologies. Each has merit in the right context, but none fit the individual researcher use case as well as what we built.

### Full Brinson attribution

The Brinson-Hood-Beebower model decomposes excess returns into allocation, selection, and interaction effects. It is the industry standard for institutional portfolio attribution and is required by GIPS compliance standards.

Why we rejected it: Brinson requires a benchmark, assumes a hierarchical decision process (asset allocation then security selection), and produces an interaction term that has no economic interpretation. Nuttall's survey identified four major fallacies in the original Brinson paper. Hentschel (2024) showed that traditional attribution results are essentially arbitrary solutions to an underdetermined system. For a solo researcher running a single-instrument momentum strategy, none of this machinery is useful.

### Factor attribution (Fama-French / Barra)

Factor models decompose returns into exposures to systematic risk factors like market, size, value, momentum, and profitability. The Fama-French five-factor model (2015) and MSCI Barra risk models are the standard implementations.

Why we rejected it: Factor attribution requires factor data infrastructure. For A-shares, you need Barra CNE5 or equivalent. For US equities, Fama-French data is freely available but still requires a data pipeline. For crypto, no standard factor model exists. The engineering cost is high, and the results are only as good as the factor model you choose. We plan to add simple beta regression (strategy returns vs. market returns) as a lightweight alternative that captures the most useful part of factor analysis without the full infrastructure cost.

### Regime switching (Hidden Markov Models)

Hamilton's (1989) Markov regime-switching model identifies distinct market states (bull, bear, crisis) and allows conditional performance analysis within each state. This approach can automatically detect periods like the 2020 COVID crash without requiring manually defined event windows.

Why we deferred it: HMM-based regime detection is a strong candidate for a future iteration. It sits at medium complexity and directly answers the question "does my strategy work in different market environments?" The Python ecosystem supports it well through `hmmlearn`. We consider this the most promising next step after the current lightweight approach.

### SHAP values

Lundberg and Lee (2017) introduced SHAP (SHapley Additive exPlanations), which decomposes model predictions into per-feature contributions based on cooperative game theory. Applied to trade attribution, you would train a model to predict trade P&L from features like signal strength, market conditions, and factor exposures, then use SHAP to attribute each trade's outcome to its contributing factors.

Why we rejected it: SHAP requires training a predictive model, which needs sufficient sample size and careful feature engineering. The attribution explains the model, not reality. If the model fits poorly, the SHAP values are misleading. For most individual researchers running 50 to 500 trades per backtest, the sample size is too small for reliable ML-based attribution.

### Causal inference

Methods like difference-in-differences, synthetic control, and causal forests (Athey and Wager, 2018) offer the strongest theoretical foundation for attribution. They can answer counterfactual questions like "what would this trade's P&L have been if the COVID crash had not happened?"

Why we rejected it: Causal inference requires clearly defined treatment and control groups, which are hard to construct in financial markets. The identifying assumptions (parallel trends, no unmeasured confounders) are difficult to verify and often violated in practice. Pearl's (2009) structural causal models provide elegant theory but the implementation gap for individual researchers is enormous.

### Summary comparison

| Method | Complexity | Data Requirements | Best For | Our Decision |
|--------|-----------|-------------------|----------|-------------|
| Brinson | Low | Benchmark | Institutional compliance | Rejected |
| Factor attribution | High | Factor model + data | Alpha/Beta separation | Deferred (simple beta regression planned) |
| Regime switching | Medium | Price data only | Market-state conditioning | Planned for next iteration |
| SHAP values | High | Training data + features | ML strategy deep-dive | Rejected |
| Causal inference | Very high | Treatment/control groups | Counterfactual analysis | Rejected |
| **Lightweight (ours)** | **Low** | **trades.csv only** | **Individual researchers** | **Shipped** |

We chose the lightweight approach because it delivers immediate value with zero configuration, zero external dependencies, and results that any researcher can interpret without statistical training. The two research reports that informed this decision are available in the repository at `.omo/research/attribution-methodology.md` and `.omo/research/attribution-necessity.md`.


## Research References

Two internal research reports guided the design decisions for this feature.

The **methodology report** (`.omo/research/attribution-methodology.md`) surveyed the full landscape of attribution methods, from classical Brinson and factor models through machine learning approaches like SHAP and causal inference. Its key finding was that no single method perfectly solves the extreme-event attribution problem, but a combination of approaches can build a practical hybrid framework. The report recommended a three-stage architecture: event exclusion plus simple factor regression as the base layer, regime-conditional analysis as the second layer, and SHAP plus counterfactual analysis as an optional advanced layer.

The **necessity report** (`.omo/research/attribution-necessity.md`) asked a more fundamental question: is attribution even necessary for individual researchers? Its conclusion was conditional: full attribution is not required in the Vibe-Trading context, because the primary driver of attribution adoption (institutional compliance through GIPS and SEC requirements) does not apply. However, simplified profit-source analysis, specifically exit-reason grouping, Top-N anomaly detection, and holding-period segmentation, has clear and demonstrable value.

### Academic references

1. Brinson, G. P., Hood, L. R., and Beebower, G. L. (1986). "Determinants of Portfolio Performance." *Financial Analysts Journal*, 42(4), 39-44. https://doi.org/10.2469/faj.v42.n4.39

2. Fama, E. F. and French, K. R. (1993). "Common Risk Factors in the Returns on Stocks and Bonds." *Journal of Financial Economics*, 33(1), 3-56. https://doi.org/10.1016/0304-405X(93)90023-5

3. Hamilton, J. D. (1989). "A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle." *Econometrica*, 57(2), 357-384. https://doi.org/10.2307/1912559

4. Lundberg, S. M. and Lee, S.-I. (2017). "A Unified Approach to Interpreting Model Predictions." *NeurIPS 30*, 4765-4774. https://arxiv.org/abs/1705.07874

5. Athey, S. and Wager, S. (2018). "Estimating Treatment Effects with Causal Forests: An Application." *Observational Studies*, 4(2), 37-51. https://arxiv.org/abs/1709.03489

6. Hentschel, L. (2024). "Performance Attribution as an Estimation Problem." Working Paper. https://www.ludgerhentschel.com/PDFs/Hentschel%20'24b.pdf

7. Hsu, J., Hsu, J. C., and Kalesnik, V. (2010). "Performance Attribution: Measuring Dynamic Allocation Skill." *Research Affiliates*. https://www.researchaffiliates.com/content/dam/ra/publications/pdf/p-2010-nov-performance-attribution-measuring-dynamic-allocation-skill.pdf

---

## Threshold Rationale

This section documents the rationale and sources for all hard-coded thresholds
used in the post-backtest attribution layers defined in `agent/src/agent/context.py`.

### Strategy Routing

| Threshold | Classification | Source |
|-----------|---------------|--------|
| Sharpe ≤ 0.5 | At-risk | Preqin Academy "Poor" tier; Investopedia SR < 0.5 = sub-par |
| Sharpe ≤ 1.0 | Sub-optimal | Industry consensus — SR > 1.0 means "earned more than one unit of return per unit of risk" (Preqin) |
| MaxDD ≥ 20% | Sub-optimal | De facto hedge fund warning level; ECB Financial Stability Review (2007) redemption triggers |
| MaxDD ≥ 40% | At-risk | Extreme drawdown — most institutional mandates trigger forced liquidation or investor redemption |

### Layer 1 — Trade Attribution

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Top-N winners/losers | 5 | Balance between granularity and noise; standard in trade journal analysis |
| Holding-period buckets | <3d / 3-20d / >20d | Aligned with CMC Markets & IG Academy definitions: day-trading / swing / position |
| Robustness check | Remove top-5 winners | Industry practice for detecting profit concentration in small trade sets |

### Layer 2 — Beta Regression

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Minimum sample | 60 trading days | OLS stability requirement (df ≈ 58); standard rolling-window size for CAPM beta estimation (MDPI Finance, Ofgem, MetricGate) |
| Significance | \|t\| ≥ 2 | Two-tailed 95% confidence; at df = 60, critical t = 2.000 |
| Benchmark mapping | A-share → CSI 300; US → SPY; Crypto → BTC-USDT | Consistent with `performance-attribution` SKILL.md benchmark selection guide |

### Layer 3 — Regime Analysis

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Rolling window | N trading days (US = 252, A-share = 244, Crypto = 365) | See agent/src/skills/correlation-analysis/SKILL.md (authoritative source). Market-adaptive: US=252, A-share=244, Crypto=365 |
| High-vol multiplier | 1.5× long-term average | See agent/src/skills/correlation-analysis/SKILL.md (authoritative source). Default 1.5×; skill defines fallback for short data |
| Minimum data span | > 1 year | Required to compute meaningful rolling statistics over a full market cycle |
| Profit concentration warning | > 60% from single regime | Heuristic — no single academic source. Design intent: flag strategies that rely on one market environment for majority of PnL. **Future consideration**: upgrade to Herfindahl-Hirschman Index (HHI > 0.4 = concentrated) for a more principled measure |

### Layer 4 — Monte Carlo Permutation Test

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Significance level | p ≤ 0.05 | Standard 5% level in statistical hypothesis testing |
| Default simulations | 1000 | Sufficient to estimate p = 0.05 with SE ≈ 0.007; **future consideration**: increase to 5000 for tighter confidence |

### Future Work

The following improvements are planned but not yet implemented:

1. **Profit concentration metric upgrade**: Replace the 60% threshold with Herfindahl-Hirschman Index (HHI > 0.4 = concentrated, 0.25–0.4 = moderate)
2. **Asset-class-specific MaxDD**: Equity 20%/40%, Crypto 30%/50%, Bond 8%/15%
3. **Market-adaptive volatility multiplier**: A-share 2.0×, US equity 1.5×, Crypto 2.5×, Bond 1.2×
4. **Multiple testing correction**: Add Bonferroni or FDR note when testing multiple alphas simultaneously
5. **Monte Carlo precision**: Increase n_simulations to 5000 to reduce p-value sampling error
