---
name: quant-statistics
description: "Quantitative statistical methods: ADF unit-root / cointegration tests, GARCH volatility modeling, regression diagnostics (heteroskedasticity / autocorrelation), Bootstrap, and hypothesis testing."
category: analysis
---

# Quantitative Statistical Methods

## Overview

Common statistical methodology used in quantitative investing, covering time-series testing, volatility modeling, regression diagnostics, and statistical inference. Provides the statistical foundation for strategy development and factor research.

## Implementation

Every test below is already implemented and unit-tested in `src.quantlib.timeseries`. **Import and call it — do not retype these formulas into throwaway code**, which is how sign errors and double-sqrt bugs get into results.

```python
from src.quantlib.timeseries import (
    adf_test, cointegration_test, find_hedge_ratio, compute_half_life,
    granger_test, fit_garch, heteroscedasticity_test, autocorrelation_test,
    vif_test, bootstrap_statistic, bootstrap_sharpe,
)
```

**Optional backends**: `statsmodels` powers everything except the two bootstrap helpers (which are pure numpy); `arch` powers `fit_garch` only. Neither is declared as a dependency of `vibe-trading-ai`, so both are imported lazily inside the functions. Importing the module always works; calling a function whose backend is missing raises an `ImportError` naming the package and the install command (`pip install "statsmodels>=0.14"` / `pip install "arch>=6.0"`). If you hit that error, report it to the user rather than silently substituting a different method.

## Time-Series Tests

### 1. ADF Unit-Root Test (Stationarity Test)

**Why it matters**: regressing non-stationary series directly can produce spurious regression, making conclusions unreliable.

```python
from src.quantlib.timeseries import adf_test

result = adf_test(prices['close'], significance=0.05)
# {'adf_statistic': -1.23, 'p_value': 0.65, 'lags_used': 4,
#  'is_stationary': False,
#  'critical_values': {'1%': -3.44, '5%': -2.87, '10%': -2.57}}

if not result['is_stationary']:
    returns = np.log(prices['close']).diff().dropna()
    adf_test(returns)  # log returns are normally stationary
```

**Decision rules**:

| p-value | Conclusion | Action |
|-----|------|------|
| < 0.01 | Strongly stationary | Can be used directly for regression / modeling |
| 0.01-0.05 | Stationary | Usable |
| 0.05-0.10 | Weak evidence | Difference the series and retest |
| > 0.10 | Non-stationary | Must difference or handle with cointegration |

**Stationarity of common financial series**:

| Series | Typical Result | Treatment |
|------|---------|---------|
| Price series | Non-stationary (unit root) | Use log returns |
| Log returns | Stationary | Can be used directly |
| PE / PB series | Usually non-stationary | Use changes or logs |
| Volatility series | Usually stationary | Can be used directly |
| Volume | May be non-stationary | Use logs or standardization |

### 2. Cointegration Test

**Purpose**: determine whether two non-stationary series share a long-run equilibrium relationship (the foundation of pair trading / statistical arbitrage).

```python
from src.quantlib.timeseries import cointegration_test

result = cointegration_test(prices_a, prices_b, significance=0.05)
# {'test_statistic': -4.52, 'p_value': 0.002, 'is_cointegrated': True,
#  'critical_values': {'1%': -3.90, '5%': -3.34, '10%': -3.05}}
```

Both legs must be individually non-stationary (check with `adf_test` first) — cointegration on two already-stationary series is meaningless.

Both legs must also share one index. Two same-length series on *different* indices raise `ValueError` rather than being zipped positionally, because a positional join of, say, an A-share calendar against a US one reports cointegration between days that never coexisted. Reindex or inner-join the two legs yourself before calling.

**Application in pair trading**:

```python
from src.quantlib.timeseries import find_hedge_ratio, compute_half_life

result = find_hedge_ratio(prices_a, prices_b)
# {'hedge_ratio': 2.49, 'intercept': 0.40,
#  'spread_mean': 0.40, 'spread_std': 1.73, 'half_life': 16.7}

spread = prices_a - result['hedge_ratio'] * prices_b
z_score = (spread - result['spread_mean']) / result['spread_std']

# half_life is in observation periods (days for daily bars) and is `inf`
# when the spread does not mean-revert. Sanity-check it before trading:
# a half-life longer than your holding horizon means the spread will not
# close in time, however good the cointegration p-value looks.
compute_half_life(spread)
```

A perfectly flat leg (a name halted for the whole window) makes the regression
degenerate, so `find_hedge_ratio` and `compute_half_life` raise `ValueError`
rather than return a meaningless β. Treat that as "this pair has no usable data
in this window", not as something to work around.

**Pair-trading signal**:

```
z_score = (spread - mean) / std

| z_score | Signal |
|---------|------|
| > 2.0 | Short spread (sell y, buy x) |
| > 1.5 | Small short spread |
| < -1.5 | Small long spread |
| < -2.0 | Long spread (buy y, sell x) |
| Back near 0 | Close position |
```

### 3. Granger Causality Test

```python
from src.quantlib.timeseries import granger_test

p_by_lag = granger_test(df, x_col='volume', y_col='return', max_lag=5)
# {1: 0.003, 2: 0.011, 3: 0.08, 4: 0.21, 5: 0.33}
# small p at lag k -> past x at that lag helps predict y
```

Granger causality is **predictive, not structural**: it says past `x` improves the forecast of `y`, never that `x` causes `y`. A common confounder is that both respond to a third variable. Note also that testing 5 lags is 5 hypothesis tests — one small p-value among them is weak evidence.

## GARCH Volatility Modeling

### GARCH(1,1) Model

```
Returns: r_t = μ + ε_t
Volatility: σ²_t = ω + α×ε²_{t-1} + β×σ²_{t-1}

Parameter meanings:
- ω (omega): long-run variance baseline
- α (alpha): impact of yesterday's shock on today's volatility
- β (beta): persistence of yesterday's volatility into today
- α + β: volatility persistence (usually 0.95-0.99)
- Long-run volatility = sqrt(ω / (1 - α - β))
```

```python
from src.quantlib.timeseries import fit_garch

# `returns` are FRACTIONS (0.01 = 1%); the function rescales to percent itself.
result = fit_garch(returns, horizon=5)
# {'omega': 0.0453, 'alpha': 0.1213, 'beta': 0.8348, 'persistence': 0.9561,
#  'long_run_vol': 0.0102, 'current_vol': 0.0149,
#  'forecast_vol': array([0.0138, 0.0137, 0.0136, 0.0134, 0.0133]),
#  'horizon': 5, 'aic': 10882.39, 'bic': 10907.57}
```

The forecast decays from `current_vol` toward `long_run_vol` — that mean reversion is the whole point of the model, and a forecast that does *not* decay signals `persistence` too close to 1.

All volatilities come back as **daily fractions** — multiply by `sqrt(252)` to annualise. `long_run_vol` is `nan` when `persistence >= 1`, which means the model has no finite unconditional variance and its long-horizon forecast is not usable.

Requires the optional `arch` package (`pip install "arch>=6.0"`); the call raises a named `ImportError` if it is absent.

### GARCH Variants

| Model | Characteristics | Applicable Scenario |
|------|------|---------|
| GARCH(1,1) | Baseline, symmetric shock response | Default choice |
| EGARCH | Asymmetric (leverage effect) | Down-move volatility > up-move volatility |
| GJR-GARCH | Another asymmetric form | Same use case as EGARCH, easier to interpret |
| FIGARCH | Long memory | Volatility clustering persists for very long periods |

**GARCH characteristics in China A-shares / crypto**:

```
China A-shares:
- α usually 0.05-0.15
- β usually 0.80-0.90
- Clear leverage effect (EGARCH fits better)
- Strong volatility clustering persistence

BTC:
- α usually 0.05-0.20 (shocks matter more)
- β usually 0.75-0.90
- More symmetric shocks (little difference between up/down volatility)
- Long-run volatility around 60-80% annualized
```

## Regression Diagnostics

### 1. Heteroskedasticity Test

```python
import statsmodels.api as sm
from src.quantlib.timeseries import heteroscedasticity_test

fitted = sm.OLS(y, sm.add_constant(X)).fit()
result = heteroscedasticity_test(fitted)   # pass the FITTED result, not the data
# {'white_p': 0.0001, 'bp_p': 0.0003, 'has_heteroscedasticity': True,
#  'fix': 'Use HAC standard errors (Newey-West) or WLS'}
```

`fix` tracks `has_heteroscedasticity`, and the verdict is `white_p < α` **or** `bp_p < α` — either test rejecting is enough to act on. The two disagree fairly often near the threshold (White has less power against a simple linear variance trend), so do not read "White says no" as the answer.

**Heteroskedasticity fixes**:
- Use `model.fit(cov_type='HAC', cov_kwds={'maxlags': 5})`
- Or use weighted least squares (WLS)
- Financial data is almost always heteroskedastic -> use HAC standard errors by default

### 2. Autocorrelation Test

```python
from src.quantlib.timeseries import autocorrelation_test

result = autocorrelation_test(fitted.resid, lags=10)
# {'durbin_watson': 1.21, 'dw_interpretation': 'positive autocorrelation',
#  'ljung_box_p': array([0.001, 0.002, ...]),   # one p-value per lag
#  'has_autocorrelation': True,
#  'fix': 'Use Newey-West standard errors or include lag terms'}
```

⚠️ **`has_autocorrelation` is `any(p < significance)` across all `lags` — that is a family of tests, not one.** On pure white noise it fires about **13%** of the time at `lags=10` versus about **2%** at `lags=1` (measured over 120 seeds, n=1500). Treat a lone flag at high `lags` as a prompt to inspect `ljung_box_p` lag by lag, not as a 5%-level rejection.

### 3. Multicollinearity Test

```python
from src.quantlib.timeseries import vif_test

vif_test(factors, severe_threshold=10.0, watch_threshold=5.0)
#     feature     VIF  concern
# 0     value   28.41   severe
# 1  momentum    1.12   normal
# 2      size    6.30    watch
```

Include the constant column if your model has one — VIF is otherwise distorted by the un-centred means.

### Regression Diagnostics Checklist

```
□ 1. Linearity: residuals vs fitted values show no obvious pattern
□ 2. Normality: residual QQ plot is close to a straight line, Jarque-Bera p>0.05
□ 3. Heteroskedasticity: White / BP test p>0.05, or use HAC standard errors
□ 4. Autocorrelation: DW≈2, Ljung-Box p>0.05
□ 5. Multicollinearity: VIF<5
□ 6. Outliers: Cook's D < 4/n
```

## Bootstrap Methods

### Nonparametric Bootstrap

```python
from src.quantlib.timeseries import bootstrap_statistic

result = bootstrap_statistic(returns.values, np.median,
                             n_bootstrap=10000, confidence=0.95, seed=42)
# {'point_estimate': 0.0004, 'bootstrap_mean': 0.0004, 'bootstrap_std': 0.0002,
#  'ci_lower': 0.0001, 'ci_upper': 0.0008, 'confidence': 0.95}
```

Pass `seed` whenever the number goes into a report — an unseeded bootstrap gives a slightly different interval on every run, which makes results irreproducible. Needs no optional dependency (pure numpy).

### Bootstrap Applications in Quant

| Scenario | Method | Purpose |
|------|------|------|
| Sharpe-ratio confidence interval | Bootstrap return series | Determine whether Sharpe is significantly >0 |
| Factor return test | Bootstrap factor values | Whether factor premium is robust |
| Maximum drawdown distribution | Bootstrap equity paths | Probability distribution of max drawdown |
| Strategy comparison | Paired Bootstrap | Whether strategy A is significantly better than B |

```python
from src.quantlib.timeseries import bootstrap_sharpe

# Takes a RETURN series (fractions), not an equity curve.
result = bootstrap_sharpe(returns, n_bootstrap=10000,
                          periods_per_year=252, seed=42)
# {'point_estimate': 1.25, 'ci_lower': 0.62, 'ci_upper': 1.88,
#  'bootstrap_mean': 1.26, 'bootstrap_std': 0.32,
#  'confidence': 0.95, 'is_significant': True}
```

`is_significant` means the interval sits entirely above zero. Remember what it does **not** mean: the interval is centred on the *realised* Sharpe, so it quantifies sampling error around this sample, not whether the edge persists out of sample. With only 1000 daily bars the realised Sharpe of a zero-edge strategy already has a standard deviation of `sqrt(252/1000) ≈ 0.50`.

For a backtest **equity curve** use `backtest.validation.bootstrap_sharpe_ci` instead — it differences the curve itself and returns report-shaped keys. The two also use different denominators: `bootstrap_sharpe` divides by the sample standard deviation (`ddof=1`), `bootstrap_sharpe_ci` by the population one (`ddof=0`). On identical data they differ by `sqrt(n / (n-1))` — about 0.2% over a year of daily bars. Report one or the other, never both as if they agreed.

## Hypothesis-Testing Framework

### Quick Reference for Common Tests

| Testing Goal | Test Method | Null Hypothesis |
|---------|---------|--------|
| Mean = 0 | t-test | `μ = 0` |
| Two means are equal | Independent t-test | `μ1 = μ2` |
| Normality | Jarque-Bera | Normal distribution |
| Stationarity | ADF | Has unit root (non-stationary) |
| Autocorrelation | Ljung-Box | No autocorrelation |
| Heteroskedasticity | White / BP | Homoskedasticity |
| Cointegration | Engle-Granger | Not cointegrated |

### Multiple-Testing Problem

```
Problem: test 100 factors and filter with p<0.05 -> expect 5 false positives

Correction methods:
1. Bonferroni: p_adj = p × n_tests (most conservative)
2. Holm-Bonferroni: stepwise correction (fairly conservative)
3. Benjamini-Hochberg (FDR): control false discovery rate (recommended)

from statsmodels.stats.multitest import multipletests
reject, p_adj, _, _ = multipletests(p_values, method='fdr_bh')
```

### Statistical Significance in Financial Backtests

```
Sharpe significance test:
H0: Sharpe = 0 (strategy is ineffective)
H1: Sharpe > 0

Test statistic: t = Sharpe × sqrt(n) / sqrt(1 + 0.5×Sharpe²)
where n = number of observation periods (years)

Rules of thumb:
- Sharpe > 0.5 and backtest >5 years -> may be significant
- Sharpe > 1.0 and backtest >3 years -> likely significant
- Sharpe > 2.0 -> overfitting warning (hard to sustain in reality)
```

## Output Format

```markdown
## Statistical Testing Report

### Stationarity Test
| Series | ADF Statistic | p-value | Conclusion |
|------|----------|-----|------|
| Price | -1.23 | 0.65 | Non-stationary |
| Return | -15.8 | 0.000 | Stationary *** |

### Cointegration Test
| Pair | Statistic | p-value | Cointegrated |
|------|--------|-----|------|
| 600519/000858 | -4.52 | 0.002 | Yes ** |

### GARCH Model
| Parameter | Value | Meaning |
|------|-----|------|
| α | 0.08 | Shock effect |
| β | 0.88 | Volatility persistence |
| Long-run volatility | 22.5% | Annualized |

### Bootstrap Result
| Metric | Point Estimate | 95% CI | Significant |
|------|--------|--------|------|
| Sharpe | 1.25 | [0.62, 1.88] | Yes |
| Alpha (monthly) | 0.8% | [0.1%, 1.5%] | Yes |
```

## Notes

1. **Financial data is non-normal**: almost all financial return series are fat-tailed, so be careful with tests assuming normality
2. **Multiple testing**: when backtesting many strategies / factors, multiple-testing correction (FDR control) is mandatory
3. **Out-of-sample validation**: statistical significance does not guarantee profitability; out-of-sample testing is still required
4. **Cointegration can break down**: historical cointegration does not guarantee persistence, so pair trading needs ongoing monitoring
5. **GARCH forecast horizon is limited**: volatility-forecast accuracy declines rapidly beyond 5-10 days
6. **Be careful with small samples**: financial datasets may look large, but the number of independent observations can still be small (for example, annual data)
7. **p-hacking risk**: do not keep adjusting until p<0.05; predefine the testing plan
