---
name: performance-attribution
description: Performance attribution analysis — Brinson sector/stock-selection attribution, factor alpha/beta decomposition, market-timing evaluation, and benchmark comparison framework.
category: analysis
---

# Performance Attribution Analysis

## Overview

Decompose portfolio excess returns into explainable sources: sector allocation, stock selection, factor exposure, timing contribution, and more. This helps explain **why** a strategy made or lost money, rather than only **how much** it made or lost.

## Brinson Attribution Model

**Do not retype these formulas into throwaway Python.** They are implemented and
tested in `src/quantlib/attribution.py`; import them.

### Single-Period Brinson-Fachler Model

```
Let w_p,i = portfolio weight of sector i
    w_b,i = benchmark weight of sector i
    r_p,i = portfolio return of sector i
    r_b,i = benchmark return of sector i
    R_b   = total benchmark return

Allocation_i  = (w_p,i - w_b,i) × (r_b,i - R_b)
Selection_i   =  w_b,i          × (r_p,i - r_b,i)
Interaction_i = (w_p,i - w_b,i) × (r_p,i - r_b,i)

Total active return = Σ(Allocation_i) + Σ(Selection_i) + Σ(Interaction_i)
```

**The decomposition itself has no residual term.** The three effects sum to
`R_p - R_b` identically, for any sector returns whatsoever, provided the
portfolio and benchmark weights carry the same total. `brinson_fachler` enforces
the weight-sum precondition and raises rather than returning a decomposition
that does not tie out.

A residual is therefore never a property of the algebra — but it is a real and
expected property of a *reported* attribution, because the inputs are a
snapshot. Intra-period trading, cash drag, corporate actions and FX translation
all move the actual portfolio return away from the one these weights and sector
returns imply. So:

- residual inside the decomposition, given the inputs → **impossible**; if you
  see one, the arithmetic or the weight convention is wrong;
- residual between the decomposition and the reported fund return → **normal**;
  quantify it and attribute it to its source rather than absorbing it silently
  into selection. This is what the `/attrib` reconciliation gate asks for.

```python
from src.quantlib.attribution import brinson_fachler

result = brinson_fachler(
    portfolio_weights={"Tech": 0.40, "Financials": 0.10, "Energy": 0.30, "Health": 0.20},
    benchmark_weights={"Tech": 0.25, "Financials": 0.30, "Energy": 0.25, "Health": 0.20},
    portfolio_returns={"Tech": 0.12, "Financials": 0.04, "Energy": -0.02, "Health": 0.07},
    benchmark_returns={"Tech": 0.10, "Financials": 0.05, "Energy": -0.01, "Health": 0.06},
)

result.portfolio_return   # 0.0600
result.benchmark_return   # 0.0495
result.active_return      # 0.0105
result.allocation         # 0.0045
result.selection          # 0.0015
result.interaction        # 0.0045
# 0.0045 + 0.0015 + 0.0045 == 0.0105 exactly (residual ~3e-18, machine epsilon)

for effect in result.sectors:
    print(effect.sector, effect.allocation, effect.selection, effect.interaction, effect.total)
```

A sector return may be omitted only where the matching weight is zero. A
benchmark sector you did not own therefore shows zero selection and zero
interaction, and the whole effect lands in allocation — you cannot demonstrate
stock-picking skill in something you never held.

### Example Brinson Attribution

Rendered from the call above, so every figure below is reproducible:

```markdown
### Brinson Sector Attribution

| Sector | Portfolio Weight | Benchmark Weight | Portfolio Return | Benchmark Return | Allocation | Selection | Interaction |
|------|---------|---------|---------|---------|---------|---------|---------|
| Tech | 40% | 25% | 12% | 10% | +0.7575% | +0.50% | +0.30% |
| Financials | 10% | 30% | 4% | 5% | -0.0100% | -0.30% | +0.20% |
| Energy | 30% | 25% | -2% | -1% | -0.2975% | -0.25% | -0.05% |
| Health | 20% | 20% | 7% | 6% | +0.0000% | +0.20% | +0.00% |
| **Total** | 100% | 100% | 6.00% | 4.95% | **+0.45%** | **+0.15%** | **+0.45%** |

Active return 1.05% = allocation 0.45% + selection 0.15% + interaction 0.45%. No residual.
```

### Multi-Period Attribution (Linked Brinson)

Single-period effects add, but returns compound, so simply summing each period's
effects does **not** reproduce the compounded active return. Take the four-sector
period above and two more like it (the exact three are the `_three_periods`
fixture in `tests/quantlib/test_attribution.py`, so you can run them): summing the
three active returns gives 2.8500%, while the compounded active return is 3.0318%
— an 18.2bp error that grows with the horizon and the return level.

Use **Carino logarithmic linking**, implemented as `carino_link`. It is
residual-free, and its per-period scaling factor depends only on that period's
total portfolio and benchmark return — never on the effects being linked — so
linking is deterministic and cannot be steered by how sectors were bucketed.
(Menchero linking is also residual-free but distributes a correction term derived
from the effects themselves; Carino needs less machinery for the same guarantee.)

```
k   = (ln(1 + R_P) - ln(1 + R_B)) / (R_P - R_B)        # over the whole horizon
k_t = (ln(1 + R_p,t) - ln(1 + R_b,t)) / (R_p,t - R_b,t)  # for period t

linked effect = Σ_t (k_t / k) × effect_{i,t}
```

```python
from src.quantlib.attribution import brinson_fachler, carino_link

periods = [brinson_fachler(**month) for month in monthly_inputs]
linked = carino_link(periods)

linked.active_return   # compounded, not summed
linked.allocation, linked.selection, linked.interaction
linked.scaling_factors  # one k_t / k per period, exposed so a report can be audited

for sector in linked.sectors:
    print(sector.sector, sector.total)
# allocation + selection + interaction == linked.active_return exactly
```

Arithmetic linking is acceptable **only** when you explicitly report the residual.
Since `carino_link` costs one function call and leaves none, prefer it.

## Factor Attribution

### Alpha-Beta Decomposition

```
R_p = α + β × R_m + ε

α (alpha): excess return, manager skill
β (beta): market exposure, systematic risk
ε (epsilon): residual, idiosyncratic risk

Regression method: OLS regression, with at least 60 data points
```

#### Multi-Factor Attribution (Fama-French Extension)

```
R_p - R_f = α + β_mkt × (R_m - R_f) + β_smb × SMB + β_hml × HML + β_mom × MOM + ε

| Factor | Meaning | China A-share Proxy |
|------|------|--------|
| MKT | Market | CSI 300 return |
| SMB | Small-cap premium | CSI 500 - CSI 300 |
| HML | Value premium | high-PB group - low-PB group |
| MOM | Momentum | top past-12M winners - bottom group |
```

#### Factor Exposure Analysis Template

```markdown
### Factor Exposure Analysis

| Factor | Beta | t-stat | Significance | Interpretation |
|------|------|---------|--------|------|
| Market (MKT) | 0.85 | 12.3 | *** | Below 1, defensive profile |
| Small-cap (SMB) | 0.25 | 3.2 | ** | Small-cap tilt |
| Value (HML) | -0.15 | -1.8 | * | Growth tilt |
| Momentum (MOM) | 0.30 | 4.1 | *** | Significant momentum exposure |
| **Alpha** | **0.8% / month** | **2.5** | ** | **Significant alpha** |

R² = 0.72 → factors explain 72% of return variation
Alpha = 0.8% / month = 10% / year, significant
```

## Market-Timing Evaluation

### Treynor-Mazuy Model

```
R_p - R_f = α + β × (R_m - R_f) + γ × (R_m - R_f)² + ε

γ > 0 and significant → timing ability exists (adds risk in bull markets, cuts risk in bear markets)
γ ≤ 0 → no timing ability
```

### Henriksson-Merton Model

```
R_p - R_f = α + β × (R_m - R_f) + γ × max(R_m - R_f, 0) + ε

γ > 0 → portfolio beta is higher in bull markets (successful timing)
```

### Practical Timing Metrics

| Metric | Calculation | Meaning |
|------|------|------|
| Bull capture ratio | portfolio return in bull markets / benchmark return | >100% = outperforming |
| Bear capture ratio | portfolio return in bear markets / benchmark return | <100% = better downside defense |
| Timing hit rate | proportion of months where market direction was called correctly | >55% = shows skill |
| Correlation between position changes and market | `corr(position_change, future_return)` | >0 = timing is correct |

## Benchmark Comparison Framework

### Benchmark Selection

| Strategy Type | Recommended Benchmark | China A-share Code |
|---------|---------|---------|
| China A-share large cap | CSI 300 | 000300.SH |
| China A-share small cap | CSI 500 / CSI 1000 | 000905.SH |
| China A-share broad market | CSI All Share | 000985.SH |
| Hong Kong equities | Hang Seng Index | HSI |
| US equities | S&P 500 | SPX |
| Crypto | BTC | BTC-USDT |
| Multi-asset | 60/40 portfolio | self-constructed |

### Risk-Adjusted Performance Metrics

| Metric | Formula | Excellent | Good | Average |
|------|------|------|------|------|
| Sharpe | `(R_p - R_f) / σ_p` | >1.5 | 1.0-1.5 | 0.5-1.0 |
| Sortino | `(R_p - R_f) / σ_down` | >2.0 | 1.5-2.0 | 1.0-1.5 |
| Calmar | `R_p / MaxDD` | >1.0 | 0.5-1.0 | 0.2-0.5 |
| Information Ratio | `(R_p - R_b) / TE` | >1.0 | 0.5-1.0 | 0.2-0.5 |
| Treynor | `(R_p - R_f) / β` | used comparatively | | |

### Rolling Analysis

```
Use rolling windows (such as 12 months) to analyze:
- Rolling Sharpe: strategy stability
- Rolling alpha: whether alpha persists
- Rolling beta: whether market exposure is stable
- Rolling information ratio: persistence of benchmark outperformance

Suggested windows: 252 days for daily data, 12-36 months for monthly data
```

## Analysis Framework

### Step 1: Aggregate Analysis

```
1. Cumulative return vs benchmark
2. Excess-return decomposition (annual / monthly)
3. Summary risk metrics (volatility / max drawdown / Sharpe)
```

### Step 2: Attribution Decomposition

```
1. Brinson attribution (if sector information is available)
2. Factor attribution (alpha / beta / factor exposure)
3. Timing attribution (TM / HM models)
```

### Step 3: Style Analysis

```
1. Large cap vs small cap exposure
2. Growth vs value exposure
3. Style drift detection (rolling style analysis)
```

### Step 4: Conclusions and Recommendations

```
1. Main sources of excess return
2. Whether risk exposure is reasonable
3. Suggested improvement directions
```

## Output Format

```markdown
## Performance Attribution Report

### Performance Overview
| Metric | Strategy | Benchmark | Excess |
|------|------|------|------|
| Cumulative return | +85.2% | +32.1% | +53.1% |
| Annualized return | 12.5% | 5.8% | +6.7% |
| Annualized volatility | 18.2% | 20.5% | - |
| Sharpe | 0.69 | 0.28 | - |
| Information Ratio | 0.82 | - | - |

### Attribution Breakdown
| Source | Contribution (annualized) | Share |
|------|-----------|------|
| Sector allocation | +2.1% | 31% |
| Stock selection | +3.8% | 57% |
| Timing | +0.8% | 12% |

### Factor Exposure
[factor exposure table]

### Conclusion
Excess return mainly comes from stock selection (57% contribution), followed by sector allocation.
Alpha is significant (`t=2.5`), indicating real stock-picking ability.
Watch the risk of excessive small-cap exposure (`SMB beta=0.25`).
```

## Notes

1. **Attribution ≠ prediction**: attribution explains the past; it does not guarantee persistence in the future
2. **Benchmark selection affects attribution**: switch the benchmark and alpha may disappear, so benchmark choice must be appropriate
3. **Data frequency**: daily attribution is noisy, monthly attribution is more stable but has fewer samples; recommended workflow is daily computation with monthly reporting
4. **Survivorship bias**: delisted stocks may be excluded in backtests, creating false alpha
5. **Multiple-testing problem**: if you test 100 strategies, about 5 may appear significant by chance (`p=0.05`); use multiple-comparison correction
6. **Factor data requirement**: factor attribution requires factor return data, which can be obtained from `tushare` or self-constructed
7. **Attribution in backtest reports**: `metrics.csv` already provides basic metrics after a backtest; this skill adds deeper attribution analysis
8. **Brinson is implemented, not improvised**: `src/quantlib/attribution.py` holds the tested single-period and Carino-linked decomposition. Import it. Hand-written attribution code that reports a single-period residual is a bug in that code, not a property of the model
