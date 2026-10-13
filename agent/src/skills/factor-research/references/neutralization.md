# Cross-sectional factor neutralization and PCA

The optional `neutralization` quantlib module provides two pure-compute functions:

| Function | Purpose |
| --- | --- |
| `neutralize_factor` | OLS/WLS residualization of one signal against numeric and categorical exposures |
| `pca_factors` | PCA compression of two or more factor panels, with loadings and explained variance |

Both are available through `quantlib_call`, including transports without shell
tools. The factor research committee grants this tool to its miner, validator
and combiner. Existing alpha formulas and backtests are unchanged; applying a
transform remains a research choice.

## Observation frequency and data contract

Each DataFrame has observation times as rows and assets as columns. One row is
one independent cross-section, whether observations are minute, hourly, daily,
weekly, monthly, timezone-aware or irregular. No annualization, time pooling,
sorting, resampling or forward filling occurs. A single asset is insufficient
for this model; time-series/rolling regression requires a separate model.

The first signal/factor panel defines output axes. Controls, weights and other
factors align by exact time/asset labels; missing observations stay missing.
Supply a full boolean mask when restricting the universe. Duplicate labels and
invalid settings are rejected. Nonfinite numeric observations are treated as
missing, not made into zero exposures or prices.

All exposures, classifications and universe memberships must be known at the
signal timestamp. Equal labels do not prove point-in-time availability. For
example, a monthly fundamental exposure used by an hourly signal must already
be expanded to hourly observations using verified publication times. The module
does not perform this expansion or infer release dates. Never supply forward
returns, labels, future classifications or test-period-selected factors.

## OLS and WLS

At each observation, fit an intercept plus the supplied exposures to the raw
signal. Return the residual at the same time/asset cell. Numeric design columns
are centered/scaled on that complete cross-section to improve conditioning;
categorical groups use dummy columns with one reference level omitted. This
scaling preserves the regression span; it does not winsorize inputs.

```python
from src.quantlib.neutralization import neutralize_factor, pca_factors

# signal, log_market_cap, beta and industry are time-by-asset DataFrames.
result = neutralize_factor(
    signal,
    controls={"log_market_cap": log_market_cap, "beta": beta},
    categorical_controls={"industry": industry},
    control_selection="explicit",
    min_observations=10,
)
residual_signal = result.residuals
diagnostics = result.diagnostics

# Weights must be economically justified and available at each signal time.
weighted = neutralize_factor(
    signal,
    controls={"log_market_cap": log_market_cap, "beta": beta},
    method="wls",
    weights=regression_weights,
)
```

OLS does not accept a weight panel that it would silently ignore. WLS requires
one and excludes missing, zero, negative or infinite weights; it never imputes
unit weights. Constant/collinear explicit designs, insufficient complete assets
or insufficient residual degrees of freedom yield NaN residual rows and a
specific skip reason. Default minimum complete assets is 10, with at least two
residual degrees of freedom; both thresholds are configurable, not frequency
dependent.

Residuals default to unit standard deviation under the regression weights.
Exact zero residuals remain zero and are flagged: an entirely explained signal
does not supply independent alpha. Set `standardize=False` for raw residuals.
No post-fit winsorization/ranking is applied, since nonlinear transformations
can reintroduce exposure. OLS residuals are linearly orthogonal in the fitted
sample; WLS residuals are orthogonal under its weights. Neither guarantees
statistical independence, zero Spearman correlation or out-of-sample alpha.

## Automatic control quality selection

`control_selection="auto"` selects from caller-supplied candidates. It processes
numeric controls in insertion order, then categorical groups in insertion order.
This order expresses caller priority and is reported. Categorical groups are
accepted/rejected together, not selectively stripped of some industries.

For each time independently, reject candidates with coverage below
`min_coverage` (default 0.8) among finite, unmasked signals with valid weights,
constant/collinear designs, too few joint complete assets, or too few remaining
degrees of freedom. Selection checks the joint sample, since two individually
well-covered controls can have a poor overlap. It does not inspect the signal's
correlation with a candidate, IC, returns, Sharpe or future rows.

```python
automatic = neutralize_factor(
    signal,
    controls={"log_market_cap": log_market_cap, "beta": beta, "legacy": old_factor},
    categorical_controls={"industry": industry},
    control_selection="auto",
    min_coverage=0.9,
)
```

No accepted candidates means a skipped row, not silent intercept-only
demeaning. Quality selection is not economic model discovery: decide whether
size, value, momentum etc. should be stripped for the research question. Control
sets can change over time and must be reviewed using the diagnostic history.

## PCA

```python
pca = pca_factors(
    {"value": value_factor, "momentum": momentum_factor, "quality": quality_factor},
    n_components=0.95,  # Or an integer component count.
    standardize=True,
)
first_component = pca.components["PC1"]
```

PCA fits across assets at each timestamp, using the existing scikit-learn PCA
implementation with a full SVD. It centers factors and optionally standardizes
their scales. Complete assets only are used; constant factors and inadequate
sample/rank yield explicit skips. A variance fraction in `(0, 1)` chooses enough
components to meet that threshold; an integer requires exactly that many
nonzero components. Threshold selection can therefore produce varying component
counts, with unused component rows kept NaN.

Per-time diagnostics include loadings, factor means/scales, explained-variance
ratios and retained variance. The largest absolute loading anchors each
component's sign. It does not prevent rotation, permutation or instability
between times when eigenvalues are close; do not assume `PC1` is a stable
tradable economic factor without assessing this. PCA decorrelates components,
not designated industry/style exposures. Avoid choosing PCA settings on the
final test period.

## Tool invocation

Use `action="list"` or `action="describe"` with `module="neutralization"` to
inspect the two functions. Pass indexed panels using the existing JSON envelope:

```json
{
  "action": "call",
  "module": "neutralization",
  "function": "neutralize_factor",
  "kwargs": {
    "factor": {"__dataframe__": {
      "index": ["2024-01-02T09:35:00Z"],
      "columns": ["A", "B", "C", "D", "E", "F"],
      "data": [[1.5, 2.2, 2.7, 4.5, 3.9, 6.2]]
    }},
    "controls": {"size": {"__dataframe__": {
      "index": ["2024-01-02T09:35:00Z"],
      "columns": ["A", "B", "C", "D", "E", "F"],
      "data": [[1, 2, 3, 4, 5, 6]]
    }}},
    "min_observations": 4
  }
}
```

Results serialize panels plus diagnostic records through the existing tool
contract. Its 5,000-value output budget still applies; a truncated result is
explicitly marked and is not a complete panel. Use smaller chunks or direct
Python imports with normal artifact writing for large research panels. Chunking
time rows preserves these independent fits; do not chunk the asset dimension,
which would change each cross-section.

## Diagnostics and evaluation

Every observation reports status, complete/fitted counts and output coverage.
Skipped observations have zero output coverage. Residualization also reports
selected/dropped controls, exclusion reasons, rank, residual degrees of freedom,
zero-residual flags and Pearson exposures before/after on identical fit assets.
WLS exposures use its regression weights. Undefined correlations are `None`.

Compare raw and transformed IC/quantile backtests separately with the existing
`factor_analysis` tool, using matching masks and explicitly chosen holding
horizons. Sharpe, costs, drawdowns and portfolio turnover require a separate
backtest; this module does not infer them from factor values or issue a pass/fail
investment verdict. Coverage and smaller exposure alone are not evidence of
profitable alpha.

## Local validation

```bash
pytest agent/tests/quantlib/test_neutralization.py agent/tests/test_quantlib_tool.py -q
```

Fixtures are synthetic and offline. Tests cover OLS/WLS reference fits, weighted
orthogonality, classification/missingness, control selection, PCA reconstruction,
multiple frequencies, irregular observations, future-row independence, input
validation and the JSON tool contract. No data credentials or broker actions
are needed.
