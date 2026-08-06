"""Tested financial-mathematics primitives.

Formulas here were previously carried as markdown inside skills, where the LLM
retyped them into throwaway Python on every run. That delivery model is not
reproducible (different code each run), not reviewable (no tests, no version)
and not auditable (no artifact). Everything in this package is the opposite:
one implementation, pinned by tests, called by both the skills and the engines.

Import submodules directly -- this file deliberately imports nothing, so that a
missing optional dependency in one domain cannot break the others::

    from src.quantlib.options import implied_volatility
    from src.quantlib.fixedincome import dv01

Submodules:
  options      Black-Scholes price/greeks and implied-volatility inversion
  fixedincome  Bond pricing, YTM, duration/convexity/DV01, curve fitting
  credit       Altman Z, Merton/KMV, spread analytics
  timeseries   Stationarity, cointegration, GARCH, bootstrap
  risk         VaR/CVaR, drawdown, Monte Carlo, EVT tail fitting
  var_backtest Kupiec/Christoffersen coverage tests and the Basel traffic light
  multipletesting  Deflated Sharpe, CSCV/PBO and BH-FDR search corrections
  crossvalidation  Purged + embargoed splits for overlapping financial labels
  eventstudy   Abnormal returns around dated events (CAR/CAAR, Patell, BMP)
  factormodel  Cross-sectional style exposures, factor returns, style drift
  attribution  Brinson-Fachler allocation/selection/interaction
  impact       Market-impact and slippage models
  fundmath     Private-markets fund maths on the irregular cash-flow spine
  performance  Client money-weighted performance (XIRR, TWR) on that spine

Two modules expose a function named ``xirr`` and they are not interchangeable.
``fundmath.xirr`` takes a ``CashFlowSeries`` under a valuation policy, scans a
bounded rate window and (via ``xirr_all``) knows about multiple roots, raising
``XIRRError``. ``performance.xirr`` takes bare ``(date, amount)`` pairs, returns
the single root its bisection bracket isolates and raises
``UnsolvableRateError``. Import the one whose input you actually hold.
"""
