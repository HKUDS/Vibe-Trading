---
name: risk-analysis
description: Risk measurement and stress testing — VaR/CVaR/max drawdown calculation, Monte Carlo simulation, extreme-value tail-risk analysis, and historical scenario stress testing.
category: analysis
---

# Risk Measurement and Stress Testing

## Overview

Systematic risk-measurement methodology covering VaR/CVaR calculation, Monte Carlo simulation, stress-test design, and tail-risk analysis. It provides risk evaluation for backtest results and risk-control constraints for asset allocation.

The measures below are implemented once, with tests, in `src/quantlib/risk.py`. Call them; do not retype the formulas, because a hand-retyped VaR is where the sign convention silently flips.

```python
from src.quantlib.risk import (
    historical_var, parametric_var, historical_cvar,
    max_drawdown_analysis, monte_carlo_gbm, analyze_mc_results, fit_gpd_tail,
)
```

### Sign convention

**A loss is a positive number**, uniformly, across every function in the module:

| Value | Reads as |
|------|------|
| `historical_var(...) == 0.028` | a 2.8% loss |
| `historical_cvar(...) == 0.042` | a 4.2% average loss in the tail |
| `max_drawdown_analysis(...)["max_drawdown"] == 0.325` | a 32.5% peak-to-trough decline |
| `analyze_mc_results(...)["var"] == 0.224` | a 22.4% loss |

Quantities that are *returns* rather than *losses* keep their natural sign and are named `*_return` (`mean_return`, `worst_5pct_return`, `best_5pct_return`), so a bad outcome there is negative. Report VaR to the user with the sign the user expects, but never re-derive it — flip it at the presentation layer only.

`cvar >= var` holds by construction whenever both come from the same sample at the same confidence level. If you ever compute a CVaR below its VaR, the tail mask is wrong.

This is *not* `cvar >= var >= 0`. The magnitudes are never clipped, so a sample whose tail contains no actual loss reports a **negative** loss — a gain. That is deliberate and informative; do not assert non-negativity on a VaR and do not clip it, or you destroy the distinction between "small loss" and "no loss at all".

## Risk Measurement Methods

### 1. VaR (Value at Risk)

**Definition**: the maximum expected loss over a given horizon at a specified confidence level.

#### Three Calculation Methods

| Method | Formula / Steps | Advantages | Disadvantages |
|------|----------|------|------|
| Historical simulation | Sort historical returns and take the quantile | No distribution assumption | Depends on historical samples |
| Parametric (normal) | `VaR = μ - z_α × σ` | Easy to compute | Assumes a normal distribution |
| Monte Carlo | Simulate N paths and take the quantile | Flexible | Computationally intensive |

#### Historical Simulation

Reads the loss straight off the sorted sample, so it inherits whatever fat tails the history actually had. `horizon` scales by the square-root-of-time rule, which is only valid under i.i.d. returns.

```python
historical_var(returns, confidence=0.95)              # 1-day 95% VaR
historical_var(returns, confidence=0.99, horizon=10)  # 10-day 99% VaR
```

The quantile is a *non-interpolating lower order statistic*: element `floor((1 - confidence) * n)` of the ascending-sorted returns, negated. The result is therefore always a return that was actually observed, never a blend of two neighbours.

#### Parametric (normal)

```python
parametric_var(returns, confidence=0.95)
```

Fits `mu` and the sample `sigma` (ddof=1) and returns `-(mu + z*sigma)` with `z = norm.ppf(1 - confidence)`. Needs at least 2 observations.

**Do not assume the parametric figure is the lower one.** The direction of the gap depends on the confidence level. A fat tail inflates the fitted `sigma`, which pushes the normal quantile *outward* at moderate confidence, where the empirical quantile is still sitting in the well-behaved body. Measured over 300 t(4) samples of 750 daily returns:

| Confidence | Parametric reads **above** historical |
|---|---|
| 90% | 100% of samples |
| 95% | 92.7% |
| 97.5% | 40.3% |
| 99% | 5.3% |

So the familiar "parametric understates risk" result only appears at 99% and deeper. At the 95% default it is normally the *higher* of the two, and that is not a sign your code is wrong. Quote both at 99% when the point is to expose the tail.

### 2. CVaR / ES (Conditional VaR / Expected Shortfall)

**Definition**: the average loss beyond the VaR threshold, more conservative than VaR.

```python
historical_cvar(returns, confidence=0.95)
historical_cvar(returns, confidence=0.99, horizon=10)
```

Averages the VaR order statistic together with everything worse than it (inclusive), which is the standard expected shortfall and is what makes `cvar >= var` structural rather than incidental.

**VaR vs CVaR comparison**:

| Metric | VaR(95%) | CVaR(95%) | Meaning |
|------|----------|-----------|------|
| Typical value | 2.1% | 3.4% | CVaR is usually 1.3-1.8x VaR |
| Subadditivity | Not satisfied | Satisfied | CVaR can be used for portfolio risk decomposition |
| Regulation | Basel II | Basel III | Regulatory trend is shifting toward CVaR |

### 3. Maximum Drawdown Analysis

```python
dd = max_drawdown_analysis(equity)   # equity = a strictly positive net-value Series
dd["max_drawdown"]        # 0.325 -> fell 32.5% below its running peak (POSITIVE)
dd["peak_date"], dd["trough_date"], dd["recovery_date"]
dd["recovered"]           # False when the series ends still underwater
```

Full return keys: `max_drawdown`, `peak_date`, `trough_date`, `recovery_date`, `recovered`, `peak_to_trough_periods`, `trough_to_recovery_periods`, `underwater_days`, `recovery_days`.

- Recovery means reaching the **peak** value again, not merely bouncing off the trough; `recovery_date` is None and `recovered` is False if it never happens.
- `underwater_days` / `recovery_days` are calendar days and require a `DatetimeIndex`; on any other index they come back None and you should use the `*_periods` counts, which are always populated.
- Non-positive equity raises — a drawdown *ratio* is undefined at or below zero. Rebase a signed PnL series to a positive net value first.

### 4. Monte Carlo Simulation

#### Geometric Brownian Motion (GBM)

```python
paths = monte_carlo_gbm(
    s0=100.0, mu=0.10, sigma=0.20,   # mu/sigma are ANNUALISED
    n_steps=252, n_paths=10_000,
    seed=42,                          # keyword-only; required for a reproducible run
)
paths.shape        # (10000, 253) -- n_steps + 1 columns
paths[:, 0]        # exactly s0 on every path
```

**Always pass `seed`.** It is keyword-only so it cannot be supplied by accident, and leaving it None draws fresh OS entropy — the run is then unreproducible and the numbers in your report cannot be regenerated. Use `steps_per_year` if the step is not a 252-day trading day.

Column 0 is the starting price, so `paths[:, -1] / paths[:, 0] - 1` is the total return over the whole simulation. Terminal expectation is `s0 * exp(mu * n_steps / steps_per_year)`; the *median* sits lower, at `s0 * exp((mu - 0.5*sigma**2) * T)`, and that gap is the volatility drag, not a bug.

#### Simulation Result Analysis

```python
summary = analyze_mc_results(paths, confidence=0.95)
summary["var"], summary["cvar"]                 # positive loss magnitudes
summary["mean_return"], summary["prob_loss"]
summary["worst_5pct_return"], summary["best_5pct_return"]   # signed returns
```

`var` / `cvar` are computed with exactly the same order-statistic convention as `historical_var` / `historical_cvar`, so a simulated VaR and a historical VaR are directly comparable.

## Stress-Testing Framework

### Historical Scenario Stress Tests

| Scenario | Period | China A-share Drawdown | US Equity Drawdown | BTC Drawdown | 10Y Government Bonds |
|------|--------|---------|---------|---------|---------|
| 2008 financial crisis | 2008.01-2008.10 | -65% | -50% | N/A | yield ↓ 100bp |
| 2015 China equity crash | 2015.06-2015.08 | -45% | -10% | -20% | yield ↓ 50bp |
| 2018 trade war | 2018.01-2018.12 | -25% | -20% | -80% | yield ↓ 30bp |
| 2020 COVID shock | 2020.01-2020.03 | -15% | -35% | -50% | yield ↓ 80bp |
| 2022 hiking cycle | 2022.01-2022.10 | -20% | -25% | -65% | yield ↑ 200bp |

### Hypothetical Scenario Design

```python
STRESS_SCENARIOS = {
    'rate_shock_up_100bp': {
        'equity': -0.10,    # equities down 10%
        'bond_10y': -0.08,  # 10-year bonds down 8%
        'bond_2y': -0.02,   # short bonds down 2%
        'gold': +0.05,      # gold up 5%
        'btc': -0.15,       # BTC down 15%
    },
    'credit_crisis': {
        'equity': -0.25,
        'bond_10y': +0.05,  # government bonds act as a safe haven
        'credit_bond': -0.15,
        'gold': +0.10,
        'btc': -0.30,
    },
    'liquidity_dry_up': {
        'equity': -0.20,
        'bond_10y': -0.05,  # when liquidity is poor, everything falls
        'gold': -0.05,
        'btc': -0.40,
        'cash': 0.0,
    },
    'geopolitical_conflict': {
        'equity': -0.15,
        'bond_10y': +0.03,
        'gold': +0.15,
        'oil': +0.30,
        'btc': -0.20,
    },
}
```

### Stress-Test Implementation Steps

1. **Select a scenario**: either historical or hypothetical
2. **Apply shocks**: multiply scenario shocks by the current positions
3. **Compute portfolio loss**: `portfolio_loss = Σ(weight_i × shock_i × position_i)`
4. **Assess adequacy**: compare loss vs risk budget and whether stop-loss thresholds are triggered

## Tail-Risk Analysis (Extreme Value Theory, EVT)

### POT Method (Peaks Over Threshold)

```python
fit = fit_gpd_tail(returns, threshold_pct=5.0)   # keep the worst 5%
fit["shape_xi"]      # ξ>0 fat tail, ξ=0 exponential tail, ξ<0 bounded tail
fit["shape_stderr"]  # standard error of ξ -- quote ξ with it, never alone
fit["scale_sigma"]   # in units of loss magnitude
fit["tail_type"]     # "fat" | "exponential" | "bounded"
fit["threshold"], fit["n_exceedances"], fit["exceedance_rate"]
```

Exceedances are non-negative by construction (`threshold - return`, kept only where the return fell below the threshold), so the GPD location is pinned at zero. Letting `loc` float instead lets the optimiser absorb tail mass into a shifted origin and biases `shape_xi`.

**`tail_type` is decided against `shape_stderr`, not against exact zero.** A fitted `shape_xi` is a float and is never exactly `0.0`, so a bare `ξ > 0` test would call a genuinely exponential tail "fat" purely on the sign of estimation noise. `"fat"` therefore means `ξ > 2 × shape_stderr`, `"bounded"` means `ξ < -2 × shape_stderr`, and anything in between is `"exponential"` — indistinguishable from zero at this sample size. Measured over 200 refits, that 2σ band labels a truly exponential tail `"exponential"` 96.5% of the time while still catching `ξ = +0.40` and `ξ = -0.35` 100% of the time. A `shape_xi` of 0.03 with a `shape_stderr` of 0.02 is not evidence of a fat tail; get more exceedances before you call it one.

Threshold choice is the real judgement call: too high and there is nothing left to fit (fewer than 2 exceedances raises), too low and the EVT limit theorem no longer applies, so the fitted shape stops meaning anything. Check that `shape_xi` is stable across a few nearby `threshold_pct` values before quoting it.

### Tail-Risk Metrics

| Metric | Calculation | Meaning |
|------|------|------|
| Kurtosis | `returns.kurtosis()` | >3 indicates fat tails; China A-shares are often in the 4-8 range |
| Skewness | `returns.skew()` | <0 means left-skewed (large drops are more common than large rallies) |
| Tail ratio | worst 5% / best 5% | >1 means larger downside risk |
| Hill estimator | Tail index | `α<2` implies extremely fat tails |

## Analysis Framework

### Input Requirements

```
Required:
- Return series (daily or higher frequency) or net-value series
- Portfolio weights (if it is a portfolio)

Optional:
- Benchmark returns (for relative risk analysis)
- Risk budget / constraint settings
```

### Analysis Steps

1. **Data preprocessing**: compute returns, check missing values, and handle outliers
2. **Descriptive statistics**: mean / volatility / skewness / kurtosis / maximum drawdown
3. **VaR/CVaR calculation**: compare three methods at both 95% and 99% confidence levels
4. **Monte Carlo simulation**: 10,000 paths, output distribution statistics and VaR
5. **Stress testing**: at least 3 historical scenarios + 2 hypothetical scenarios
6. **Tail analysis**: fit GPD and determine tail type
7. **Risk-control recommendations**: provide concrete recommendations based on the results

## Output Format

Note the sign flip: the module returns losses as positive numbers, while the report below prints them the way a reader expects to see them (`max_drawdown 0.325` → `-32.5%`). Flip once, here at the presentation layer, and never inside a calculation.

```markdown
## Risk Analysis Report

### Core Risk Metrics
| Metric | Value |
|------|-----|
| Daily volatility | 1.85% |
| Annualized volatility | 29.3% |
| Maximum drawdown | -32.5% (2024.09.15 → 2024.11.20) |
| VaR(95%, 1D) | -2.8% |
| CVaR(95%, 1D) | -4.2% |
| Skewness | -0.45 |
| Kurtosis | 5.2 (fat tail) |

### Stress-Test Results
| Scenario | Portfolio Loss | Stop Triggered |
|------|---------|----------|
| 2020 COVID replay | -18.5% | No |
| Rates +100bp | -12.3% | No |
| Liquidity dry-up | -28.7% | Yes |

### Monte Carlo Simulation (252 days, 10000 paths)
| Statistic | Value |
|------|-----|
| Expected return | +8.2% |
| Loss probability | 35% |
| Worst 5% scenario | -22.4% |

### Risk-Control Recommendations
1. Recommend setting a portfolio stop-loss at -15%
2. Tail risk is elevated; consider allocating 5% to gold as a hedge
3. Correlations rise in stressed markets, so diversification benefits will be discounted
```

## Notes

1. **VaR is not the maximum loss**: VaR only says "with 95% probability, losses will not exceed X"; the remaining 5% can be far worse
2. **Normality assumption is dangerous**: financial returns are almost always fat-tailed, so parametric VaR underestimates risk **deep in the tail (99% and beyond)**. At 90–95% it usually reads *higher* than the historical figure, because the fat tail inflates the fitted sigma — see the table under "Parametric (normal)". Never cite a 95% parametric VaR as evidence that the normal fit is conservative
3. **History does not equal the future**: historical simulation fails when structural breaks occur (for example, the first negative oil price)
4. **Correlation is unstable**: correlation matrices observed in normal markets can collapse in crises (correlations trend toward 1)
5. **Monte Carlo seed**: always pass `seed=` to `monte_carlo_gbm` and quote it in the report, so the numbers can be regenerated; use at least 10,000 paths for stability
6. **Holding-period scaling**: the square-root-of-time rule only applies under i.i.d. returns; it becomes inaccurate under autocorrelation
7. **Risk in backtests**: `metrics.csv` already includes `max_drawdown` and `sharpe`; this skill provides deeper analysis
8. **Sign discipline**: every measure here returns a loss as a positive number. Do not re-derive a measure inline to "get the sign you want" — call the function and flip once when printing
