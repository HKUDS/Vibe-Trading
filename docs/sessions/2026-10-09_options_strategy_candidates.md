# Options strategies worth automating: candidate backtests

Goal: backtest a small set of options strategies with the existing engine
(`agent/backtest/engines/options_portfolio.py`, unchanged) and decide which, if
any, to carry forward to paper trading.

Code: `agent/src/skills/options-strategy/example_signal_engine.py` (engines),
`agent/scripts/options_candidates_backtest.py` (this study; reruns end to end
with `PYTHONPATH=agent python agent/scripts/options_candidates_backtest.py`),
`agent/tests/test_options_strategy_engines.py`.

## Bottom line

- **No premium-selling strategy qualifies.** Cash-secured puts, iron condors
  and short strangles made between -4% and +4% a year out of sample, against
  15–19% for buy-and-hold. The model has no volatility risk premium: options
  are priced at trailing realized vol, and that premium is where these
  strategies' edge comes from in practice. **This backtest cannot validate them
  either way.** They need real option-chain history first.
- **Carry forward one: a 0.20-delta, ~35-DTE covered call on SPY (QQQ as a
  second underlying).** It was the only strategy that matched or beat
  buy-and-hold on risk-adjusted terms in both periods for the index ETFs:
  - SPY out of sample: Sharpe 1.10 vs 0.94, max drawdown -19% vs -25%, CAGR
    about the same.
  - QQQ: Sharpe about equal, drawdown -29% vs -35%, about 2 points a year less
    CAGR.

  Its result doesn't depend on the missing premium: real calls are richer than
  modeled here, which would help it. It lagged buy-and-hold on AAPL and MSFT
  (CAGR 4–5 points a year lower), so it is for index ETFs only.
- **Don't carry the protective put forward, even though it looks good.** Puts
  are priced at trailing realized vol plus a mild skew, which makes them
  several vol points cheaper than real index puts. Its strong in-sample
  result (Sharpe 1.2 against 0.86 for SPY) mostly comes from the cheap
  pre-COVID puts in February 2020, priced at about 12% vol. In reality those
  puts cost far more.
- The vol gate helped the strangle in every run: an "elevated" regime (30-day
  realized vol above its 1-year median) beat no gate in sample. Out of sample
  it kept drawdowns to 8–19% but still earned ~0–1% a year. The gate's benefit
  here comes from realized vol reverting to its mean. Real implied vol already
  prices that in, so don't expect the benefit to carry over.

## Setup

| Item | Value |
|---|---|
| Underlyings | SPY, QQQ (index ETFs); AAPL, MSFT (single names). yfinance closes, dividend- and split-adjusted |
| In-sample | 2016-01-04 → 2020-12-31 (includes 2020 crash), history from 2015 used for vol warm-up |
| Out-of-sample | 2021-01-04 → 2026-10-08 (includes 2022 bear market), parameters frozen |
| Tuning | one parameter per strategy, best mean Sharpe over SPY+QQQ in sample (grid in the script) |
| Pricing | Black-Scholes on 30-day historical vol, `iv_skew=-0.3` smile, r = 2%, European, next-bar-close fills |
| Costs | commission = 1% of premium per side for ETFs, 2% for single names (≈ half-spread + fees) |
| Margin | engine's CBOE-style naked margin for cash-secured puts and strangles; off for covered call, protective put and condor (see caveats) |
| Capital | $100k, size compounds on each strategy's own realized P&L |

Strategies (chosen parameters in bold):

| Strategy | Rules |
|---|---|
| Covered call | shares + short call **0.20Δ** (vs 0.30), ~35 DTE, hold to expiry, shares re-sized to equity each cycle |
| Cash-secured put | short put **0.30Δ** (vs 0.20), ~35 DTE, hold to expiry, notional = capital (fully secured) |
| Iron condor | short **0.16Δ** (vs 0.10/0.25) put+call, 0.05Δ wings, 45 DTE, close at 50% of credit or 21 DTE; max loss 10% of capital per trade |
| Vol-gated strangle | short 0.16Δ put+call, 45 DTE, 50% / 21 DTE; gate **elevated** (vs none / contracting); notional = capital |
| Protective put | shares + long put **0.15Δ** (vs 0.30), ~60 DTE, rolled at 21 DTE |

## Out-of-sample results (2021-01 → 2026-10)

CAGR+bill is CAGR after crediting the 13-week T-bill rate on cash (the engine
pays 0% on cash). It matters for cash-heavy short-premium books.

| Strategy | Code | CAGR | CAGR+bill | Sharpe | MaxDD | Worst month | Worst day | CVaR 5% (daily) | Skew | Win rate | Trades |
|---|---|---|---|---|---|---|---|---|---|---|---|
| buy & hold | SPY | 15.3% | | 0.94 | -24.5% | -9.2% | -5.9% | -2.4% | 0.28 | | |
| covered call | SPY | 15.5% | 15.5% | **1.10** | -19.4% | -8.3% | -5.6% | -2.1% | -0.00 | 81% | 59 |
| cash-secured put | SPY | 2.9% | 5.8% | 0.42 | -13.9% | -7.3% | -4.8% | -1.3% | -0.16 | 85% | 59 |
| iron condor | SPY | -1.4% | 1.6% | -0.18 | -14.8% | -4.2% | -2.8% | -1.2% | -0.51 | 64% | 90 |
| vol-gated strangle | SPY | 0.0% | 3.0% | 0.02 | -8.4% | -3.2% | -3.1% | -0.7% | -1.61 | 72% | 53 |
| protective put | SPY | 15.1% | 15.1% | 1.07 | -20.5% | -8.2% | -3.8% | -1.9% | 0.75 | 14% | 49 |
| buy & hold | QQQ | 17.2% | | 0.82 | -35.1% | -13.6% | -6.2% | -3.2% | 0.15 | | |
| covered call | QQQ | 15.4% | 15.4% | 0.86 | -29.2% | -12.5% | -5.9% | -2.8% | -0.06 | 73% | 59 |
| cash-secured put | QQQ | 3.7% | 6.4% | 0.42 | -21.4% | -7.2% | -4.9% | -1.7% | -0.58 | 88% | 59 |
| iron condor | QQQ | -3.1% | 0.1% | -0.46 | -22.9% | -5.1% | -2.7% | -1.1% | -1.42 | 62% | 90 |
| vol-gated strangle | QQQ | 1.3% | 4.3% | 0.29 | -10.5% | -6.1% | -2.8% | -0.9% | -2.37 | 77% | 52 |
| protective put | QQQ | 16.7% | 16.7% | 0.92 | -31.0% | -12.6% | -4.1% | -2.5% | 0.48 | 18% | 49 |
| buy & hold | AAPL | 18.9% | | 0.77 | -33.4% | -12.2% | -9.2% | -3.9% | 0.34 | | |
| covered call | AAPL | 13.7% | 13.8% | 0.67 | -32.0% | -11.4% | -8.7% | -3.5% | 0.27 | 71% | 59 |
| cash-secured put | AAPL | 3.4% | 6.3% | 0.32 | -23.9% | -6.0% | -6.1% | -2.3% | 0.62 | 78% | 59 |
| iron condor | AAPL | -4.3% | -0.8% | -0.59 | -28.7% | -8.7% | -4.3% | -1.3% | -1.45 | 66% | 90 |
| vol-gated strangle | AAPL | -0.4% | 2.8% | -0.01 | -15.1% | -9.1% | -4.2% | -1.4% | -1.25 | 75% | 52 |
| protective put | AAPL | 17.2% | 17.2% | 0.79 | -29.0% | -12.9% | -6.2% | -3.1% | 0.67 | 16% | 49 |
| buy & hold | MSFT | 17.4% | | 0.73 | -37.1% | -17.2% | -10.0% | -3.7% | 0.54 | | |
| covered call | MSFT | 12.7% | 12.9% | 0.67 | -28.7% | -13.5% | -9.2% | -3.2% | -0.20 | 78% | 59 |
| cash-secured put | MSFT | 4.1% | 7.1% | 0.42 | -18.8% | -7.9% | -6.1% | -2.0% | -0.88 | 86% | 59 |
| iron condor | MSFT | -1.5% | 1.7% | -0.19 | -13.6% | -4.1% | -3.9% | -1.2% | -1.71 | 67% | 91 |
| vol-gated strangle | MSFT | 0.7% | 4.0% | 0.13 | -18.5% | -7.0% | -6.6% | -1.2% | -3.53 | 72% | 47 |
| protective put | MSFT | 13.7% | 13.7% | 0.65 | -33.1% | -14.8% | -10.0% | -3.1% | 1.03 | 22% | 49 |

Win rate is per structure (all legs of one entry), excluding the share leg.
No opens were rejected for margin in any run.

## In-sample (2016 → 2020), chosen parameters

| Strategy | SPY CAGR / Sharpe / MaxDD | QQQ CAGR / Sharpe / MaxDD |
|---|---|---|
| buy & hold | 15.5% / 0.86 / -33.7% | 24.5% / 1.11 / -28.6% |
| covered call 0.20Δ | 13.7% / 0.85 / -32.7% | 20.2% / 1.07 / -27.6% |
| cash-secured put 0.30Δ | -1.2% / -0.02 / -33.1% | 1.1% / 0.15 / -26.8% |
| iron condor 0.16Δ | -2.8% / -0.32 / -26.9% | -3.1% / -0.38 / -26.5% |
| strangle, elevated gate | 1.0% / 0.18 / -18.2% | 3.1% / 0.48 / -12.3% |
| protective put 0.15Δ | 15.8% / 1.20 / -14.4% | 23.0% / 1.31 / -18.9% |

The full in-sample grid (every parameter, worst month/day, CVaR, skew) is
printed by the script.

## Tail behavior

- Short premium has the expected left tail. Every short-premium book has
  negative daily skew, worst at -5.3 for the ungated SPY strangle in sample.
  In 2020 the SPY cash-secured put lost 16–17% in its worst month, and the
  ungated SPY strangle lost 14%. Win rates of 80–90% sit alongside negative CAGR,
  so a high win rate is no evidence of an edge here.
- The covered call keeps almost all of the underlying's crash exposure: its
  in-sample max drawdown is -33% against -34% for SPY. It mainly gives up
  upside, which is why it lags on strongly trending single names.
- The protective put is the only strategy with positive skew, and it cut
  the worst day on SPY, QQQ and AAPL. That benefit is overstated for the reason given in the bottom
  line.

## Sensitivity to the smile (SPY, out of sample)

`iv_skew` is the only setting the engine has for how rich OTM options are.
Changing it barely moves the ranking:

| iv_skew | covered call Sharpe | CSP CAGR+bill | condor CAGR+bill | strangle CAGR+bill | protective put Sharpe |
|---|---|---|---|---|---|
| 0.0 | 1.15 | 5.1% | 0.9% | 3.9% | 1.18 |
| -0.3 (base) | 1.10 | 5.8% | 1.6% | 3.0% | 1.07 |
| -0.6 | 1.04 | 6.4% | 1.5% | 2.7% | 0.95 |

## Caveats

1. **Prices come from a model, not from real option chains.** Every price is
   Black-Scholes on trailing 30-day realized vol plus a fixed quadratic smile:
   - The volatility risk premium is effectively **zero**. Real index implied
     vol has averaged a few points above later realized vol. That gap is the
     return premium sellers collect and buyers pay. Here, premium selling
     looks worse than it is and option buying looks better.
   - Real implied vol jumps the day a crash starts. Here it lags by up to 30
     days: options are cheap going into a crash and expensive after it.
   - The bid/ask spread is modeled as a flat 1–2% of premium. Real spreads
     widen sharply in a crisis, the exact days that matter for short-premium
     strategies.
2. **There is no early assignment and no share delivery.** Options are
   European and settle in cash. The covered call and protective put hold a
   "share replica" (a call struck at $0.01) and re-size it to equity each
   cycle, which approximates assignment and re-buying. The cash-secured put
   settles in cash, so it is not a full wheel (no calls written on assigned
   shares). Dividends reach the results only through adjusted closes.
3. **Some margin was switched off.** The engine margins every short leg as
   naked. That is right for cash-secured puts and strangles. It overcharges
   covered calls and defined-risk condors, and it rejected single condor legs
   in a trial run, which left the rest of the condor naked. So those three
   were run with `margin_enabled: false`:
   - the condor is sized so its maximum loss is 10% of capital, which matches
     the Reg-T spread requirement;
   - the share-based strategies hold about zero cash.
4. **Cash earns 0% in the engine.** The CAGR+bill column adds T-bill interest
   after the fact, as simple interest on the engine's cash balance.
5. **This is a small study.** It covers four underlyings, about 11 years, and
   ~50–90 trades per strategy per period. The parameter grid is deliberately
   small (2–3 values), so the in-sample choice gives only a little room for
   overfitting. A Sharpe ratio measured over ~5 years has a standard error of about
   0.45, so none of the Sharpe gaps above are statistically significant.

## Next steps

- Paper-trade the SPY 0.20Δ / 35-DTE covered call (QQQ optional). Record real
  fills against the model's mid price to measure the actual spread cost.
- Before paper-trading any short-premium strategy, replace the synthetic
  pricing with historical chain IV, for example by loading an IV series in
  place of `historical_volatility`. That is the input that decides whether
  the cash-secured put or the vol-gated strangle has an edge. This study
  can't answer that.
