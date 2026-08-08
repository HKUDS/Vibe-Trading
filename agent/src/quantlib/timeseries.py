"""Time-series and statistical tests for quantitative research.

Promoted verbatim-in-behaviour from the ``quant-statistics`` skill, where these
eleven routines existed only as markdown the LLM retyped on every run. One
implementation, pinned by tests, is now importable::

    from src.quantlib.timeseries import adf_test, cointegration_test

Optional dependencies
---------------------
Neither ``statsmodels`` nor ``arch`` is declared by ``vibe-trading-ai`` (checked
in ``pyproject.toml`` and ``agent/requirements.txt``; only ``numpy``, ``pandas``
and ``scipy`` are). They are therefore imported lazily *inside* each function
that needs them, so importing this module never fails and a user who only wants
the bootstrap helpers never pays for a compiler-heavy install. A function whose
backend is absent raises :class:`ImportError` naming the package and the exact
install command -- it never silently degrades to a wrong number.

  * ``statsmodels`` -- everything except :func:`bootstrap_statistic` and
    :func:`bootstrap_sharpe`, which are pure numpy.
  * ``arch`` -- :func:`fit_garch` only.

Related, deliberately not merged
--------------------------------
``backtest.validation.bootstrap_sharpe_ci`` also bootstraps a Sharpe ratio, but
it consumes an *equity curve* (it calls ``pct_change`` itself) and returns
backtest-report keys (``observed_sharpe``/``prob_positive``). :func:`bootstrap_sharpe`
here consumes a *return series* and returns the generic bootstrap envelope. They
are different call contracts; neither wraps the other.
"""

from __future__ import annotations

import contextlib
import importlib
import io
from typing import Any, Callable

import numpy as np
import pandas as pd

__all__ = [
    "adf_test",
    "cointegration_test",
    "find_hedge_ratio",
    "compute_half_life",
    "granger_test",
    "fit_garch",
    "fit_markov_regime",
    "heteroscedasticity_test",
    "autocorrelation_test",
    "vif_test",
    "bootstrap_statistic",
    "bootstrap_sharpe",
]

# Durbin-Watson conventional reading points. A DW of 2 means no first-order
# autocorrelation; these are the textbook bands either side of it.
_DW_POSITIVE_BELOW = 1.5
_DW_NEGATIVE_ABOVE = 2.5

#: Both packages ship in the one ``stats`` extra, so the hint is the same for
#: either miss: installing the extra resolves both at their pinned floors.
_INSTALL_HINT = 'pip install "vibe-trading-ai[stats]"'


def _require(module_path: str, package: str, feature: str) -> Any:
    """Import an optional backend module or raise an actionable ImportError.

    Args:
        module_path: Dotted module to import, e.g. ``"statsmodels.tsa.stattools"``.
        package: Distribution name the user must install, e.g. ``"statsmodels"``.
        feature: Human-readable name of the calling feature, used in the message.

    Returns:
        The imported module object.

    Raises:
        ImportError: If the module is unavailable. The message names the missing
            package and the ``stats`` extra that provides it.
    """
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch
        raise ImportError(
            f"{feature} requires the optional '{package}' package, which is "
            f"not part of the base install. "
            f"Install it with: {_INSTALL_HINT}"
        ) from exc


def _ols_params(endog: Any, exog_with_const: Any) -> np.ndarray:
    """Fit an OLS model and return its coefficients as a positional array.

    ``statsmodels`` returns ``params`` as a pandas Series when handed pandas
    input, where ``params[1]`` is a *label* lookup and misbehaves. Converting to
    an ndarray makes ``[0] = intercept, [1] = slope`` unambiguous.

    Args:
        endog: Dependent variable.
        exog_with_const: Design matrix that already includes a constant column.

    Returns:
        Coefficients as a 1-D numpy array, intercept first.
    """
    sm = _require("statsmodels.api", "statsmodels", "OLS regression")
    fitted = sm.OLS(np.asarray(endog, dtype=float), np.asarray(exog_with_const, dtype=float)).fit()
    return np.asarray(fitted.params, dtype=float)


def adf_test(series: pd.Series, significance: float = 0.05) -> dict:
    """Augmented Dickey-Fuller unit-root (stationarity) test.

    H0 = a unit root exists (non-stationary); H1 = stationary. Regressing
    non-stationary series on each other produces spurious regression, so this is
    the gate before any level-on-level model.

    Args:
        series: Time series to test. NaNs are dropped.
        significance: Significance level for the ``is_stationary`` verdict.

    Returns:
        Dict with keys ``adf_statistic`` (float), ``p_value`` (float),
        ``lags_used`` (int), ``is_stationary`` (bool) and ``critical_values``
        (dict mapping ``'1%'``/``'5%'``/``'10%'`` to floats).

    Raises:
        ImportError: If ``statsmodels`` is not installed.
        ValueError: If fewer than 2 non-NaN observations remain.
    """
    stattools = _require("statsmodels.tsa.stattools", "statsmodels", "adf_test")
    clean = pd.Series(series).dropna()
    if len(clean) < 2:
        raise ValueError(f"adf_test needs at least 2 non-NaN observations, got {len(clean)}")

    result = stattools.adfuller(clean, autolag="AIC")
    return {
        "adf_statistic": float(result[0]),
        "p_value": float(result[1]),
        "lags_used": int(result[2]),
        "is_stationary": bool(result[1] < significance),
        "critical_values": {k: float(v) for k, v in result[4].items()},
    }


def cointegration_test(y: pd.Series, x: pd.Series, significance: float = 0.05) -> dict:
    """Engle-Granger two-step cointegration test.

    H0 = no cointegrating relationship. Two individually non-stationary series
    are cointegrated when some linear combination of them is stationary, which
    is the statistical premise of pair trading.

    Args:
        y: First price series.
        x: Second price series, same length as ``y``.
        significance: Significance level for the ``is_cointegrated`` verdict.

    Returns:
        Dict with keys ``test_statistic`` (float), ``p_value`` (float),
        ``is_cointegrated`` (bool) and ``critical_values`` (dict mapping
        ``'1%'``/``'5%'``/``'10%'`` to floats).

    Raises:
        ImportError: If ``statsmodels`` is not installed.
        ValueError: If the two series differ in length, or carry different
            indices. Two same-length series with different indices would
            otherwise be joined *positionally* and could report a spurious
            cointegration, so the mismatch is refused rather than guessed --
            the same contract :func:`find_hedge_ratio` enforces, since the pair
            workflow runs both on the same two legs.
    """
    stattools = _require("statsmodels.tsa.stattools", "statsmodels", "cointegration_test")
    y_ser = pd.Series(y, dtype=float)
    x_ser = pd.Series(x, dtype=float)
    if len(y_ser) != len(x_ser):
        raise ValueError(f"cointegration_test needs equal-length series, got {len(y_ser)} and {len(x_ser)}")
    if not y_ser.index.equals(x_ser.index):
        raise ValueError("cointegration_test needs y and x sharing one index")

    score, p_value, critical = stattools.coint(y_ser.to_numpy(), x_ser.to_numpy())
    return {
        "test_statistic": float(score),
        "p_value": float(p_value),
        "is_cointegrated": bool(p_value < significance),
        "critical_values": {
            "1%": float(critical[0]),
            "5%": float(critical[1]),
            "10%": float(critical[2]),
        },
    }


def compute_half_life(spread: pd.Series) -> float:
    """Estimate mean-reversion half-life of a spread by delta regression.

    Regresses ``ΔS_t`` on ``S_{t-1}`` (Ornstein-Uhlenbeck discretisation) and
    reports ``-ln(2) / b``, the time for a deviation to decay by half.

    Args:
        spread: Spread series, in observation order.

    Returns:
        Half-life in observation periods. Returns ``inf`` when the estimated
        reversion coefficient is non-negative, i.e. the series does not revert.

    Raises:
        ImportError: If ``statsmodels`` is not installed.
        ValueError: If fewer than 3 usable lag/delta pairs remain, or the spread
            never moves. A flat regressor is refused rather than fitted:
            ``sm.add_constant`` leaves an already-constant column alone, so the
            design would silently collapse to one column and the slope lookup
            would be a bare ``IndexError``.
    """
    sm = _require("statsmodels.api", "statsmodels", "compute_half_life")
    series = pd.Series(spread, dtype=float)
    lagged = series.shift(1)
    delta = series - lagged
    # Align on the index where BOTH the level and its delta exist; dropping each
    # side independently would silently mis-pair rows around interior NaNs.
    frame = pd.concat({"delta": delta, "lag": lagged}, axis=1).dropna()
    if len(frame) < 3:
        raise ValueError(f"compute_half_life needs at least 3 lag/delta pairs, got {len(frame)}")
    if frame["lag"].std(ddof=0) == 0:
        raise ValueError("compute_half_life needs a spread that varies; this one is constant")

    params = _ols_params(frame["delta"], sm.add_constant(frame[["lag"]]))
    reversion = params[1]
    if reversion >= 0:
        return float("inf")
    return float(-np.log(2) / reversion)


def find_hedge_ratio(y: pd.Series, x: pd.Series) -> dict:
    """Fit the pair-trading hedge ratio ``y = α + β·x + ε``.

    The tradeable spread is ``y - β·x``; its mean and standard deviation define
    the z-score used to enter and exit, and its half-life says how long a round
    trip should take.

    Args:
        y: Dependent price series.
        x: Independent (hedging) price series, same length as ``y``.

    Returns:
        Dict with keys ``hedge_ratio`` (β, float), ``intercept`` (α, float),
        ``spread_mean`` (float), ``spread_std`` (float, sample ddof=1) and
        ``half_life`` (float, in observation periods).

    Raises:
        ImportError: If ``statsmodels`` is not installed.
        ValueError: If the series differ in length, carry different indices,
            fewer than 3 aligned non-NaN observations remain, or ``x`` is
            constant. A flat hedging leg is refused rather than fitted:
            ``sm.add_constant`` leaves an already-constant column alone, so the
            design would silently collapse to one column and the β lookup would
            be a bare ``IndexError``.
    """
    sm = _require("statsmodels.api", "statsmodels", "find_hedge_ratio")
    frame = pd.concat({"y": pd.Series(y, dtype=float), "x": pd.Series(x, dtype=float)}, axis=1)
    if len(frame) != len(pd.Series(y)) or len(frame) != len(pd.Series(x)):
        raise ValueError("find_hedge_ratio needs y and x sharing one index")
    frame = frame.dropna()
    if len(frame) < 3:
        raise ValueError(f"find_hedge_ratio needs at least 3 aligned observations, got {len(frame)}")
    if frame["x"].std(ddof=0) == 0:
        raise ValueError("find_hedge_ratio needs an x that varies; this one is constant")

    params = _ols_params(frame["y"], sm.add_constant(frame[["x"]]))
    intercept, beta = float(params[0]), float(params[1])
    spread = frame["y"] - beta * frame["x"]

    return {
        "hedge_ratio": beta,
        "intercept": intercept,
        "spread_mean": float(spread.mean()),
        "spread_std": float(spread.std()),
        "half_life": compute_half_life(spread),
    }


def granger_test(data: pd.DataFrame, x_col: str, y_col: str, max_lag: int = 5) -> dict:
    """Test whether ``x`` Granger-causes ``y``.

    Granger causality is predictive, not structural: it asks only whether past
    ``x`` improves the forecast of ``y`` beyond ``y``'s own past. It is not
    evidence of a causal mechanism.

    Args:
        data: Frame containing both columns.
        x_col: Name of the candidate predictor column.
        y_col: Name of the predicted column.
        max_lag: Maximum lag order to test; every lag from 1 to this is reported.

    Returns:
        Dict mapping lag (int, 1..``max_lag``) to the SSR F-test p-value (float).
        A small p-value rejects "x does not Granger-cause y".

    Raises:
        ImportError: If ``statsmodels`` is not installed.
        KeyError: If either column is missing from ``data``.
        ValueError: If ``max_lag`` is below 1, or if ``x_col`` and ``y_col`` are
            the same column. Testing a series against itself hands statsmodels a
            duplicated column, where the F-test trivially fails to reject and
            every p-value comes back 1.0 -- an answer that looks like a finding.
    """
    if x_col == y_col:
        raise ValueError(
            f"x_col and y_col must differ; both are {x_col!r}. A series cannot "
            "Granger-cause itself and the test returns p=1.0 regardless."
        )
    stattools = _require("statsmodels.tsa.stattools", "statsmodels", "granger_test")
    if max_lag < 1:
        raise ValueError(f"granger_test needs max_lag >= 1, got {max_lag}")
    missing = [c for c in (y_col, x_col) if c not in data.columns]
    if missing:
        raise KeyError(f"granger_test: column(s) not in data: {missing}")

    # statsmodels >= 0.14 dropped the `verbose` kwarg and prints the full test
    # table to stdout unconditionally; swallow it so a library call stays quiet.
    with contextlib.redirect_stdout(io.StringIO()):
        results = stattools.grangercausalitytests(data[[y_col, x_col]].dropna(), maxlag=max_lag)
    return {lag: float(results[lag][0]["ssr_ftest"][1]) for lag in range(1, max_lag + 1)}


def fit_garch(returns: pd.Series, horizon: int = 5) -> dict:
    """Fit a GARCH(1,1) model and forecast forward volatility.

    Model: ``r_t = μ + ε_t`` with ``σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}``.
    ``α + β`` is volatility persistence (typically 0.95-0.99 in equities).

    Args:
        returns: Daily return series as *fractions* (0.01 = 1%). Scaled to
            percent internally, which is what ``arch`` optimises well on.
        horizon: Number of days ahead to forecast.

    Returns:
        Dict with keys ``omega``, ``alpha``, ``beta``, ``persistence``,
        ``long_run_vol``, ``current_vol`` (all float, volatilities as daily
        fractions), ``forecast_vol`` (numpy array of length ``horizon``, daily
        fractions), ``horizon`` (int), ``aic`` and ``bic`` (float).
        ``long_run_vol`` is ``nan`` when persistence >= 1 (no finite
        unconditional variance).

    Raises:
        ImportError: If ``arch`` is not installed.
        ValueError: If ``horizon`` is below 1.
    """
    arch_mod = _require("arch", "arch", "fit_garch")
    if horizon < 1:
        raise ValueError(f"fit_garch needs horizon >= 1, got {horizon}")

    model = arch_mod.arch_model(
        pd.Series(returns, dtype=float).dropna() * 100,
        vol="Garch",
        p=1,
        q=1,
        mean="Constant",
        dist="normal",
    )
    result = model.fit(disp="off")

    omega = float(result.params["omega"])
    alpha = float(result.params["alpha[1]"])
    beta = float(result.params["beta[1]"])
    persistence = alpha + beta

    # `conditional_volatility` is already a standard deviation (in percent);
    # the skill's markdown took sqrt of it again, which is dimensionally wrong.
    current_vol = float(np.asarray(result.conditional_volatility, dtype=float)[-1]) / 100
    forecast = result.forecast(horizon=horizon, reindex=False)
    forecast_vol = np.sqrt(np.asarray(forecast.variance.values, dtype=float)[-1, :]) / 100

    return {
        "omega": omega,
        "alpha": alpha,
        "beta": beta,
        "persistence": persistence,
        "long_run_vol": float(np.sqrt(omega / (1 - persistence)) / 100) if persistence < 1 else float("nan"),
        "current_vol": current_vol,
        "forecast_vol": forecast_vol,
        "horizon": horizon,
        "aic": float(result.aic),
        "bic": float(result.bic),
    }


def fit_markov_regime(
    returns: pd.Series,
    n_regimes: int = 2,
    switching_variance: bool = True,
) -> dict:
    """Fit a Markov regime-switching model and label the current regime.

    A GARCH model says how volatile tomorrow is. This says *which state the
    market is in* and how likely it is to stay there, which is the question a
    regime section of a risk report is actually asking. The states are latent:
    they are inferred from the return series, never labelled by hand.

    Two implementation choices matter and neither is cosmetic.

    **Regimes are relabelled by volatility, ascending.** The EM fit returns
    states in an arbitrary order, so the same data can come back as "regime 0 is
    calm" on one run and "regime 0 is turbulent" on the next. That is the
    classic label-switching problem, and left alone it makes every downstream
    number non-reproducible. Here regime 0 is always the calmest and the last is
    always the most turbulent, with the transition matrix and the smoothed
    probabilities permuted to match.

    **The transition matrix is returned row-stochastic**: ``transition[i][j]`` is
    ``P(regime j tomorrow | regime i today)`` and every row sums to 1.
    ``statsmodels`` returns the transpose of this, and reading it the wrong way
    round silently swaps the two regimes' persistence.

    Args:
        returns: Return series as *fractions* (0.01 = 1%). Scaled to percent
            internally for optimiser stability and converted back on the way
            out, so every reported mean and volatility is a fraction again.
        n_regimes: Number of latent states, at least 2. Three is occasionally
            defensible (calm / normal / crisis); beyond that the states stop
            being interpretable and the fit stops being stable.
        switching_variance: Let volatility differ across regimes. Leaving this
            False fits regimes that differ only in mean return, which for asset
            returns is nearly always the wrong model -- regimes in markets are a
            volatility phenomenon first.

    Returns:
        Dict with keys ``n_regimes`` (int), ``regime_means`` and ``regime_vols``
        (numpy arrays, ascending volatility, daily fractions),
        ``transition_matrix`` (2-D numpy array, row-stochastic),
        ``expected_durations`` (numpy array, ``1 / (1 - p_ii)`` in periods),
        ``smoothed_probabilities`` (DataFrame on the input index, one column per
        regime), ``current_regime`` (int) and ``current_regime_probability``
        (float) for the last observation, ``converged`` (bool), and ``llf``,
        ``aic``, ``bic`` (float).

    Raises:
        ImportError: If ``statsmodels`` is not installed.
        ValueError: If ``n_regimes`` is below 2, or fewer than 50 finite
            observations survive -- an EM fit on a shorter series produces
            regimes that are numerically fine and substantively meaningless.
    """
    markov = _require(
        "statsmodels.tsa.regime_switching.markov_regression",
        "statsmodels",
        "fit_markov_regime",
    )
    if n_regimes < 2:
        raise ValueError(f"n_regimes must be at least 2, got {n_regimes}")

    series = pd.Series(returns, dtype=float).dropna()
    if series.size < 50:
        raise ValueError(
            f"fit_markov_regime needs at least 50 finite observations, got {series.size}"
        )

    # Passed as a Series, not an array: statsmodels only names the fitted
    # parameters (``const[k]``, ``sigma2[k]``) when the input is pandas, and
    # positional unpacking of that vector would silently break if the package
    # ever reorders it.
    model = markov.MarkovRegression(
        series * 100,
        k_regimes=n_regimes,
        trend="c",
        switching_variance=switching_variance,
    )
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = model.fit()

    means = np.array(
        [float(result.params[f"const[{k}]"]) / 100 for k in range(n_regimes)]
    )
    if switching_variance:
        variances = np.array([float(result.params[f"sigma2[{k}]"]) for k in range(n_regimes)])
    else:
        variances = np.full(n_regimes, float(result.params["sigma2"]))
    vols = np.sqrt(np.maximum(variances, 0.0)) / 100

    # Canonical order: calmest regime first. Everything below is permuted to it.
    order = np.argsort(vols, kind="stable")

    # statsmodels gives P(to i | from j); transpose to the conventional
    # P(from i | to j) reading, then permute rows and columns together.
    raw_transition = np.asarray(result.regime_transition, dtype=float)
    if raw_transition.ndim == 3:
        raw_transition = raw_transition[:, :, 0]
    transition = raw_transition.T[np.ix_(order, order)]

    diagonal = np.clip(np.diag(transition), None, 1.0 - 1e-12)
    expected_durations = 1.0 / (1.0 - diagonal)

    smoothed = np.asarray(result.smoothed_marginal_probabilities, dtype=float)
    if smoothed.ndim == 1:
        smoothed = smoothed.reshape(-1, 1)
    smoothed = smoothed[:, order]
    smoothed_frame = pd.DataFrame(
        smoothed, index=series.index, columns=[f"regime_{k}" for k in range(n_regimes)]
    )

    last_row = smoothed[-1]
    current_regime = int(np.argmax(last_row))

    return {
        "n_regimes": n_regimes,
        "regime_means": means[order],
        "regime_vols": vols[order],
        "transition_matrix": transition,
        "expected_durations": expected_durations,
        "smoothed_probabilities": smoothed_frame,
        "current_regime": current_regime,
        "current_regime_probability": float(last_row[current_regime]),
        "converged": bool(result.mle_retvals.get("converged", False)),
        "llf": float(result.llf),
        "aic": float(result.aic),
        "bic": float(result.bic),
    }


def heteroscedasticity_test(model_result: Any, significance: float = 0.05) -> dict:
    """Test regression residuals for heteroskedasticity (White and Breusch-Pagan).

    H0 = homoskedasticity. Financial residuals are almost always
    heteroskedastic, so the practical answer is usually HAC standard errors
    rather than dropping the model.

    Both p-values are Lagrange-multiplier p-values: ``white_p`` is
    ``het_white``'s and ``bp_p`` is ``het_breuschpagan``'s studentised
    (Koenker) ``n·R²`` variant, which is what statsmodels returns by default.

    Args:
        model_result: A fitted ``statsmodels`` regression result, i.e. the object
            returned by ``sm.OLS(...).fit()``. Its ``.resid`` and
            ``.model.exog`` are read.
        significance: Significance level for the verdict and the advice string.

    Returns:
        Dict with keys ``white_p`` (float), ``bp_p`` (float),
        ``has_heteroscedasticity`` (bool) and ``fix`` (str advice). ``fix``
        tracks ``has_heteroscedasticity``, so the verdict and the advice can
        never contradict each other.

    Raises:
        ImportError: If ``statsmodels`` is not installed.
    """
    diagnostic = _require("statsmodels.stats.diagnostic", "statsmodels", "heteroscedasticity_test")
    white_p = float(diagnostic.het_white(model_result.resid, model_result.model.exog)[1])
    bp_p = float(diagnostic.het_breuschpagan(model_result.resid, model_result.model.exog)[1])

    # Either test rejecting is enough to act on. Keying the advice off `white_p`
    # alone -- as the skill's markdown did -- returns "No adjustment needed"
    # alongside `has_heteroscedasticity: True` whenever only BP rejects.
    has_het = bool(white_p < significance or bp_p < significance)
    return {
        "white_p": white_p,
        "bp_p": bp_p,
        "has_heteroscedasticity": has_het,
        "fix": (
            "Use HAC standard errors (Newey-West) or WLS"
            if has_het
            else "No adjustment needed"
        ),
    }


def autocorrelation_test(residuals: pd.Series, lags: int = 10, significance: float = 0.05) -> dict:
    """Test residuals for serial correlation (Durbin-Watson and Ljung-Box).

    H0 = no autocorrelation. Durbin-Watson sees only lag 1; Ljung-Box tests the
    joint hypothesis across all lags up to ``lags``.

    Caveat, measured not assumed: ``has_autocorrelation`` is ``any(p < significance)``
    over ``lags`` p-values, so it is a family of tests, not one. On pure white
    noise it fires about 13% of the time at ``lags=10`` versus about 2% at
    ``lags=1`` (120 seeds, n=1500 -- see ``test_ljung_box_any_lag_rule_inflates_
    the_false_positive_rate``). Read a lone flag at high ``lags`` as a prompt to
    look at ``ljung_box_p`` per lag, not as a 5%-level rejection.

    Args:
        residuals: Residual series to test.
        lags: Highest lag included in the Ljung-Box test.
        significance: Significance level for the ``has_autocorrelation`` verdict.

    Returns:
        Dict with keys ``durbin_watson`` (float), ``dw_interpretation`` (str,
        one of ``'positive autocorrelation'`` / ``'no autocorrelation'`` /
        ``'negative autocorrelation'``), ``ljung_box_p`` (numpy array of
        p-values, one per lag), ``has_autocorrelation`` (bool) and ``fix`` (str).

    Raises:
        ImportError: If ``statsmodels`` is not installed.
        ValueError: If ``lags`` is below 1.
    """
    diagnostic = _require("statsmodels.stats.diagnostic", "statsmodels", "autocorrelation_test")
    stattools = _require("statsmodels.stats.stattools", "statsmodels", "autocorrelation_test")
    if lags < 1:
        raise ValueError(f"autocorrelation_test needs lags >= 1, got {lags}")

    clean = pd.Series(residuals, dtype=float).dropna()
    if lags >= clean.size:
        # acorr_ljungbox silently caps lags and then dies on a shape mismatch
        # with a numpy message that names neither argument.
        raise ValueError(
            f"lags must be < the number of observations; got lags={lags} "
            f"for {clean.size} observations"
        )
    dw = float(stattools.durbin_watson(clean))
    lb_p = np.asarray(diagnostic.acorr_ljungbox(clean, lags=lags)["lb_pvalue"].values, dtype=float)

    if dw < _DW_POSITIVE_BELOW:
        interpretation = "positive autocorrelation"
    elif dw < _DW_NEGATIVE_ABOVE:
        interpretation = "no autocorrelation"
    else:
        interpretation = "negative autocorrelation"

    return {
        "durbin_watson": dw,
        "dw_interpretation": interpretation,
        "ljung_box_p": lb_p,
        "has_autocorrelation": bool(np.any(lb_p < significance)),
        "fix": "Use Newey-West standard errors or include lag terms",
    }


def vif_test(
    X: pd.DataFrame,
    severe_threshold: float = 10.0,
    watch_threshold: float = 5.0,
) -> pd.DataFrame:
    """Score each regressor's variance inflation factor for multicollinearity.

    VIF measures how much a coefficient's variance is inflated by correlation
    with the other regressors. Include a constant column if the model has one --
    VIF is otherwise distorted by the un-centred means.

    Args:
        X: Design matrix, one column per feature. Must contain no NaN or inf --
            ``statsmodels`` raises ``MissingDataError`` on either.
        severe_threshold: VIF strictly above which collinearity is flagged
            severe. A VIF exactly on the threshold is not flagged.
        watch_threshold: VIF strictly above which collinearity is flagged as
            worth watching. A VIF exactly on the threshold is not flagged.

    Returns:
        DataFrame with one row per column of ``X`` and columns ``feature``
        (str), ``VIF`` (float) and ``concern`` (str, one of ``'severe'`` /
        ``'watch'`` / ``'normal'``).

    Raises:
        ImportError: If ``statsmodels`` is not installed.
        ValueError: If ``X`` has no columns.
    """
    influence = _require(
        "statsmodels.stats.outliers_influence", "statsmodels", "vif_test"
    )
    if X.shape[1] == 0:
        raise ValueError("vif_test needs at least one column")

    values = np.asarray(X, dtype=float)
    vifs = [float(influence.variance_inflation_factor(values, i)) for i in range(X.shape[1])]

    return pd.DataFrame(
        {
            "feature": list(X.columns),
            "VIF": vifs,
            "concern": [
                "severe" if v > severe_threshold else "watch" if v > watch_threshold else "normal"
                for v in vifs
            ],
        }
    )


def bootstrap_statistic(
    data: np.ndarray,
    statistic_func: Callable[[np.ndarray], float],
    n_bootstrap: int = 10000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> dict:
    """Percentile-bootstrap confidence interval for an arbitrary statistic.

    Resamples ``data`` with replacement ``n_bootstrap`` times, recomputes the
    statistic on each resample, and reads the confidence interval off the
    resulting distribution. Makes no distributional assumption, which matters
    because financial returns are fat-tailed.

    Args:
        data: One-dimensional sample of observations.
        statistic_func: Callable mapping a resample to a scalar, e.g. ``np.mean``.
        n_bootstrap: Number of bootstrap resamples.
        confidence: Confidence level in (0, 1), e.g. 0.95 for a 95% interval.
        seed: Seed for the random generator; pass an int for reproducible output.

    Returns:
        Dict with keys ``point_estimate``, ``bootstrap_mean``, ``bootstrap_std``,
        ``ci_lower``, ``ci_upper`` (all float) and ``confidence`` (float, echoed).

    Raises:
        ValueError: If ``data`` is empty, ``n_bootstrap`` is below 1, or
            ``confidence`` is not strictly inside (0, 1).
    """
    sample = np.asarray(data, dtype=float).ravel()
    if sample.size == 0:
        raise ValueError("bootstrap_statistic needs a non-empty sample")
    if n_bootstrap < 1:
        raise ValueError(f"bootstrap_statistic needs n_bootstrap >= 1, got {n_bootstrap}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"bootstrap_statistic needs confidence in (0, 1), got {confidence}")

    rng = np.random.default_rng(seed)
    n = sample.size
    # Resample one draw at a time. Materialising the whole (n_bootstrap, n)
    # index matrix would be ~160MB at the default 10000 draws over 2000 bars.
    bootstrap_stats = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        bootstrap_stats[i] = float(statistic_func(sample[rng.integers(0, n, size=n)]))

    alpha = 1 - confidence
    return {
        "point_estimate": float(statistic_func(sample)),
        "bootstrap_mean": float(np.mean(bootstrap_stats)),
        "bootstrap_std": float(np.std(bootstrap_stats)),
        "ci_lower": float(np.percentile(bootstrap_stats, alpha / 2 * 100)),
        "ci_upper": float(np.percentile(bootstrap_stats, (1 - alpha / 2) * 100)),
        "confidence": confidence,
    }


def bootstrap_sharpe(
    returns: pd.Series,
    n_bootstrap: int = 10000,
    confidence: float = 0.95,
    periods_per_year: int = 252,
    seed: int | None = None,
    ddof: int = 1,
) -> dict:
    """Bootstrap a confidence interval for an annualised Sharpe ratio.

    A point Sharpe with no interval is not evidence: an interval that straddles
    zero means the strategy is statistically indistinguishable from noise.

    Convention, stated because it differs from this repo's other Sharpe: the
    denominator defaults to the *sample* standard deviation (``ddof=1``).
    ``backtest.validation._sharpe`` uses the population one (``ddof=0``), so the
    two report Sharpes a factor ``sqrt(n / (n - 1))`` apart on identical data --
    about 0.2% over one year of daily bars. Neither is wrong, but comparing
    their numbers digit for digit is. Pass ``ddof=0`` to reconcile with the
    backtest engine's figure rather than eyeballing the gap.

    Args:
        returns: Periodic return series as fractions (not an equity curve).
        n_bootstrap: Number of bootstrap resamples.
        confidence: Confidence level in (0, 1).
        periods_per_year: Annualisation factor, e.g. 252 for daily bars.
        seed: Seed for the random generator; pass an int for reproducible output.
        ddof: Delta degrees of freedom for the standard deviation. 1 (default)
            is the sample estimator; 0 matches ``backtest.validation._sharpe``.

    Returns:
        The :func:`bootstrap_statistic` dict, plus ``is_significant`` (bool) --
        ``True`` when the whole interval sits above zero.

    Raises:
        ValueError: If the return series is empty or the bootstrap arguments are
            out of range (propagated from :func:`bootstrap_statistic`).
    """
    def sharpe(sample: np.ndarray) -> float:
        std = float(np.std(sample, ddof=ddof)) if sample.size > ddof else 0.0
        if std == 0.0:
            return 0.0
        return float(np.mean(sample) / std * np.sqrt(periods_per_year))

    result = bootstrap_statistic(
        np.asarray(pd.Series(returns, dtype=float).dropna(), dtype=float),
        sharpe,
        n_bootstrap=n_bootstrap,
        confidence=confidence,
        seed=seed,
    )
    result["is_significant"] = bool(result["ci_lower"] > 0)
    return result
