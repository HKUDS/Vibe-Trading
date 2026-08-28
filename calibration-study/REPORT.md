# Calibration Study — Vibe-Trading backtest & factor tooling

Date: 2026-08-28 · Repo: HKU-personal-hedge-fund (fork of HKUDS/Vibe-Trading), branch `calibration-study`, based on `80ffdda4` (v0.1.14, editable install).

**Scope guardrails observed:** everything ran through the offline backtest engine (`python -m backtest.runner`) and the key-free `alpha bench` CLI. No broker credentials, connector profiles, live/paper trading mandates, or LLM API keys were configured or touched at any point — neither path requires them. The repo's "Shadow Account" turned out to be a *broker-journal replay* feature (it starts from a broker CSV export), not a backtest paper mode; it is unrelated to the backtest engine and was correctly not used (see Limitations).

---

## 1. Environment

- Python **3.13.13** in a fresh isolated venv at `calibration-study/.venv` (`include-system-site-packages = false`).
- Install: `pip install -e .` from the repo root → `vibe-trading-ai 0.1.14` (editable). Exact versions of all 320 packages: [pip-freeze.txt](pip-freeze.txt). Key ones: pandas 2.3.3, numpy 2.5.2, scipy 1.18.1, yfinance 1.7.0.
- Install issues: only one benign pip-resolver warning about an unrelated system package (`launch-ros requires setuptools`); no extras were needed — everything used here (`pandas`, `yfinance`, `matplotlib`, `bottleneck`, `scikit-learn`) is in the base dependency set. The `stats`/`smc`/broker extras were not installed.
- Environment variables used for all runs (no `.env` file was created):
  - `VIBE_TRADING_DATA_CACHE=1` — reproducibility + avoids refetching
  - `VIBE_TRADING_BENCH_WORKERS=1` — deterministic bench
  - `VIBE_TRADING_ALLOWED_RUN_ROOTS=<repo>/calibration-study/runs` — run dirs must live under an allow-listed root
- Network note: direct `curl` to Yahoo's chart API returned HTTP 429, but both the repo's `yahoo` loader and the `yfinance` SDK worked normally. Stooq was reachable as fallback but never needed.

### How the repo's tooling works (as used here)

- **Backtest**: `cd agent && python -m backtest.runner <run_dir>` — no LLM, no CLI subcommand. A run dir contains `config.json` (JSON, schema in `agent/backtest/runner.py:62-164`) and `code/signal_engine.py` (a `SignalEngine.generate(data_map) -> {code: weight Series in [-1,1]}` contract). The engine shifts signals 1 bar (next-bar-open execution) and fills at open with slippage. Artifacts land in `<run_dir>/artifacts/` (`equity.csv`, `metrics.csv`, `trades.csv`, `fills.jsonl`, …) and `<run_dir>/run_card.json` records which data source actually served the run.
- **`alpha bench`**: `vibe-trading alpha bench --zoo <zoo> --universe sp500 --period YYYY-YYYY`. Computes, per factor, the daily cross-sectional Spearman IC against next-bar close-to-close returns. **Frictionless** — no costs, turnover, or portfolio construction — and writes one HTML report to `~/.vibe-trading/reports/`. `--strict` replaces the naive "IC>0.02" liveness gate with a same-universe row-shuffled random control (t-stat of real-IC minus random-IC) plus an optional `--oos-split` train/test confirmation gate.
- **Quantile curves / long-short**: not produced by `alpha bench`; the repo's `src.tools.factor_analysis_tool.run_factor_analysis` (agent/MCP tool, Python-only) produces `ic_series.csv` and `group_equity.csv`.
- **Costs for factor portfolios**: `agent/backtest/factor_costs.rebalance_cost` (weight-space; spread bps + impact + borrow). It has no production caller in the repo — `alpha bench` never applies it — so Task 2's cost pass calls it from a script.
- **Purged CV**: `agent/src/quantlib/crossvalidation.py` (pure Python API, no CLI): `group_purged_kfold_splits(dates, n_folds, embargo_fraction)`.

## 2. Smoke test

Buy-and-hold AAPL, daily bars, calendar 2024, via the engine ([runs/smoke_aapl/](runs/smoke_aapl/)):

```bash
cd agent
VIBE_TRADING_ALLOWED_RUN_ROOTS=$PWD/../calibration-study/runs VIBE_TRADING_DATA_CACHE=1 \
  ../calibration-study/.venv/bin/python -m backtest.runner ../calibration-study/runs/smoke_aapl
```

Result: 1 trade, held 250 days, total return +35.8% vs SPY +24.0%, Sharpe 1.48, `run_card.json → data_sources: ["yahoo"]`. Sanity: matches AAPL's raw (unadjusted) 2024 price return. ✅

---

## 3. Task 1 — Reproduce a known effect

**Factors:** `academic_carhart_mom` (Carhart 1997, 12-1 momentum: 252d return − 21d return, cross-sectionally z-scored) as the primary anomaly, with `academic_bab` (Frazzini-Pedersen 2014 betting-against-beta, price-only proxy) alongside since the same bench run covers the whole academic zoo.

**Universe / period:** `--universe sp500`, `--period 2010-2025`. ⚠️ **The SP500 bench universe is the *current* Wikipedia constituent list (snapshot 2026-05-17), not point-in-time membership — this is survivorship-biased**, the loader itself logs the warning and stamps `survivorship_bias: true` into the output metadata. Point-in-time membership exists only for the CSI300 universe (needs a Tushare token). 501/503 names were served by the `yahoo` loader; FDXF and HONA (recent additions) have no Yahoo history and were skipped.

**Command** (frictionless IC bench; ~7 min cold, seconds cached):

```bash
cd agent
VIBE_TRADING_DATA_CACHE=1 VIBE_TRADING_BENCH_WORKERS=1 \
  ../calibration-study/.venv/bin/vibe-trading alpha bench --zoo academic --universe sp500 --period 2010-2025 --top 20
```

Outputs: [artifacts/bench_academic_sp500_2010-2025.json](artifacts/bench_academic_sp500_2010-2025.json), HTML report [artifacts/alpha_bench_20260828T071116Z.html](artifacts/alpha_bench_20260828T071116Z.html).

The deeper pass (IC series, quantile equity, long-short Sharpe) uses the repo's `run_factor_analysis` + registry via [scripts/task1_task2_factor_study.py](scripts/task1_task2_factor_study.py):

```bash
cd agent && VIBE_TRADING_DATA_CACHE=1 ../calibration-study/.venv/bin/python ../calibration-study/scripts/task1_task2_factor_study.py
```

### Results (3,771 daily cross-sections, 2010-01→2025-12)

| factor | IC mean | IC std | IR | IC>0 ratio | t-stat | frictionless daily-quantile L/S Sharpe (Q5−Q1) |
|---|---|---|---|---|---|---|
| `academic_carhart_mom` | **+0.0158** | 0.222 | 0.071 | 54.8% | **4.29** (vs random control) | +0.24 |
| `academic_bab` | −0.0027 | 0.304 | −0.0089 | 49.4% | −0.56 (noise) | −0.56 |

Quantile detail (Group_1 = lowest score, Group_5 = highest; equal-weight, daily-rebalanced, frictionless; per-group figures in [artifacts/task12_summary.json](artifacts/task12_summary.json), charts in [artifacts/task1/](artifacts/task1/)):

- **Momentum**: winners (Q5) final NAV **14.9×** vs losers (Q1) 7.5× — winners clearly outperform, and Q5 has the best Sharpe (1.00 vs 0.71). The middle groups are non-monotonic (Q1 beats Q2-Q4 on NAV), which is the well-known instability of the momentum *short* leg (high-vol junk rallies), not a data error.
- **BAB**: NAV falls monotonically with the score — low-beta (Q5) made only 4.4× vs high-beta (Q1) 19.6×, as expected for raw returns. Volatility also falls monotonically (28.1% → 13.0%), but the **Sharpe ratios end up flat across beta quintiles (Q1 0.85 vs Q5 0.83)** — low-beta did *not* outperform on a risk-adjusted basis here.

### Verdict vs literature

- **Momentum: directionally consistent.** Positive IC, positive hit ratio, winners-minus-losers spread positive, statistically strong against a shuffled control (t≈4.3). Consistent with Carhart/Jegadeesh-Titman. Note the repo's naive gate labels it `dead` because its threshold is `ic_mean > 0.02` — at 0.0158 it misses the bar; the strict random-control gate (the better test) confirms it (§4).
- **BAB: not reproduced, and I attribute that to configuration/period, not the engine.** Diagnosis:
  1. **Metric**: next-day raw-return IC is the wrong lens for BAB — the anomaly is *risk-adjusted*; a near-zero raw IC is expected. The right test is the quantile Sharpe comparison, which came out flat rather than favoring low-beta.
  2. **Proxy simplifications** (declared in the factor's own docstring): equal-weighted market, single 252d window (paper: 5y correlation / 1y vol, shrunk betas), and no leverage — the paper's BAB longs *levered* low-beta vs shorts de-levered high-beta; unlevered quintile Sharpes are a strictly weaker rendition.
  3. **Sample**: 2010–2025 is dominated by a QE/mega-cap-growth bull where high-beta ran; published BAB results lean on 1926+ history and multiple asset classes. Survivorship bias additionally flatters the high-beta group (delisted high-beta losers are excluded from a current-membership universe).
  
  The vol monotonicity (13%→28% across quintiles) shows the beta *sort* itself works — the construction is sound; the premium simply isn't there in this sample/at this construction. I found no evidence of an engine defect (checks: monotone group vols, IC count matches calendar, warmup respected, shuffled-control IC ≈ 0).

---

## 4. Task 2 — Break it on purpose (momentum)

All portfolio numbers: monthly (21 trading-day) rebalance, quintile portfolios from `academic_carhart_mom`, 1-day execution lag, weight-space cost model `backtest/factor_costs.rebalance_cost` with **15 bps per side** (stated retail assumption, midpoint of 10–20 bps; "fixed" impact model, `adv_value=None` i.e. **infinite liquidity assumed**, US borrow 0.30%/yr on the short leg). Script: [scripts/task1_task2_factor_study.py](scripts/task1_task2_factor_study.py); numbers: [artifacts/task12_summary.json](artifacts/task12_summary.json); equity charts: [artifacts/task2/](artifacts/task2/).

| perturbation | gross Sharpe | net Sharpe | net ann. ret | ann. turnover | cost drag /yr |
|---|---|---|---|---|---|
| **Baseline L/S (Q5 − Q1)** | 0.16 | **0.05** | **−0.5%** | 11.2× | 1.87% |
| Long-only top quintile | 0.91 | 0.88 | +16.6% | 5.3× | 0.75% |
| **(1) costs** — see baseline rows | — | — | — | — | — |
| **(2) rebalance shifted +1 day** (L/S) | 0.16 | 0.04 | −0.6% | 11.2× | 1.85% |
| **(3a) 2010–2017 half** (L/S net) | 0.17 | 0.00 | −0.5% | 11.3× | 1.75% |
| **(3b) 2018–2025 half** (L/S net) | 0.16 | 0.06 | −0.9% | 11.3× | 2.01% |

IC by half-sample: 2010–2017 IC 0.0118 (t=2.6) vs 2018–2025 IC 0.0192 (t=3.5) — the *signal* is present in both halves and, unusually vs the "momentum is fading" narrative, stronger in the second half of this survivorship-biased sample.

**(4a) Strict out-of-sample gate:**

```bash
cd agent && VIBE_TRADING_DATA_CACHE=1 VIBE_TRADING_BENCH_WORKERS=1 \
  ../calibration-study/.venv/bin/vibe-trading alpha bench --zoo academic --universe sp500 --period 2010-2025 --top 20 --strict --oos-split 2018-01-01
```

Of the 12 academic factors: **1 `confirmed_alive` (momentum: α-t 4.29 full / 2.63 train / 3.39 test)**, 3 `train_only` (illiquidity, SMB-proxy, short-term reversal — all die out-of-sample), 2 `reversed_strict` (HML-proxy, market factor), 6 `noise` (BAB among them). Output: [artifacts/bench_academic_sp500_strict.json](artifacts/bench_academic_sp500_strict.json) / [HTML](artifacts/alpha_bench_20260828T071246Z.html).

**(4b) Purged 5-fold CV** (`group_purged_kfold_splits`, 1% embargo, on the daily IC series): fold-mean IC is **positive in all five folds** — 0.014, 0.008, 0.017, 0.016, 0.024 chronologically — with t>2 in three of five.

### What survives

The momentum **information** is robust: it survives a shuffled-control t-test, a 2018 OOS split, both half-samples, purged CV in every fold, and doesn't care about a 1-day rebalance shift (a genuine multi-week signal, not a timing artifact). The momentum **long-short strategy** does not survive retail costs: ~11× annual turnover × 15 bps ≈ 1.9%/yr drag versus ~1.3%/yr gross return — the classic "momentum works until costs" result, here reproduced with the repo's own cost model. The long-only top-quintile keeps a 0.88 net Sharpe, but that is mostly market beta plus survivorship bias, not harvestable alpha. Implication: at daily-quintile granularity on a large-cap universe with retail costs, this edge is real but not tradable in long-short form; cost reduction (lower turnover, smarter netting) matters more than signal improvement.

---

## 5. Task 3 — Semiconductor baseline test

**Question:** does anything simple beat buy-and-hold on a semiconductor basket after costs?

**Setup:** equal-weight basket of NVDA, TSM, ASML, AMD, AVGO, MU, AMAT, LRCX (basket used instead of the SMH ETF as permitted — proxy choice noted). Daily bars. **Data: dividend/split-adjusted OHLCV from yfinance (`auto_adjust=True`), fetched 2017-06-01→2026-08-27 and served to the engine via the repo's `local` Data Bridge loader** (`~/.vibe-trading/data-bridge/config.yaml` → [data/local/](data/local/)) — chosen over the default `yahoo` chain because that chain serves *unadjusted* prices (a repo-documented caveat) and total-return comparisons need dividends. `run_card.json` confirms `data_sources: ["local"]` for all four runs.

All four strategies ran through the repo engine with identical costs (10 bps slippage per side, $0 commission — the engine's US model). Warmup 2017-06→2018-12 with zero weight; **all strategies activate 2019-01-02**; metrics below are computed on the common window 2019-01-02 → 2026-08-27 (7.65 years) from each run's `equity.csv` by [scripts/task3_compare.py](scripts/task3_compare.py).

```bash
cd agent
for run in semis_bh semis_ma200 semis_mom semis_invvol; do
  VIBE_TRADING_ALLOWED_RUN_ROOTS=$PWD/../calibration-study/runs VIBE_TRADING_DATA_CACHE=1 \
    ../calibration-study/.venv/bin/python -m backtest.runner ../calibration-study/runs/$run
done
../calibration-study/.venv/bin/python ../calibration-study/scripts/task3_compare.py
```

### Results, net of costs (2019-01-02 → 2026-08-27; Sharpe at 0% risk-free)

| strategy | CAGR | ann. vol | Sharpe | max DD | max DD in 2022 | total turnover | fills |
|---|---|---|---|---|---|---|---|
| **Buy-and-hold (baseline)** | **53.6%** | 41.0% | 1.25 | **−55.4%** | −55.4% | 1.0× | 8 |
| 200-day MA trend filter | 36.1% | 32.5% | 1.11 | −45.4% | −41.5% | 37.0× | 5,834 |
| 12-1 momentum, top half, monthly | 52.0% | 43.6% | 1.18 | −55.1% | −55.1% | 23.1× | 3,579 |
| Inverse-vol weights, monthly | 52.9% | 38.5% | **1.30** | −49.9% | −49.9% | 13.4× | 7,060 |

Equity curves: [artifacts/task3_equity_curves.png](artifacts/task3_equity_curves.png); per-run artifacts under [runs/](runs/); summary: [artifacts/task3_summary.json](artifacts/task3_summary.json).

**Comparison to buy-and-hold, after costs:**
- **MA200 trend filter: clearly worse.** It gives up 17.5 CAGR points for a drawdown improvement of only 10 points (−45% vs −55% through 2022 — it re-entered late after every 2022 bear rally and got whipsawed; 37× turnover). Lower Sharpe too (1.11 vs 1.25).
- **12-1 momentum: no improvement.** Slightly lower CAGR, *higher* vol, same drawdown, 23× turnover. Concentrating in 4 of 8 correlated names diversifies less and did not pick winners persistently enough.
- **Inverse-vol: the only (marginal) improvement.** Sharpe 1.30 vs 1.25, vol 38.5% vs 41.0%, drawdown −50% vs −55%, at 13× turnover. This is a modest risk-adjusted gain from de-emphasizing the most volatile name — but its CAGR still trails buy-and-hold, and the Sharpe gap is well within noise for 7.6 years of data.

**Honest answer: no.** Nothing simple beat buy-and-hold on total return; inverse-vol edged it on risk-adjusted terms by an amount too small to be statistically meaningful. In a window where the basket compounded at ~54%/yr, every dollar of turnover and every day out of the market was expensive; even the −55% 2022 drawdown was cheaper to sit through than to time. This says as much about the window (an extraordinary semis bull with hindsight-selected survivors — NVDA is in the basket *because* it won) as about the strategies.

---

## 6. Limitations, quirks, and incidents

**Data sources actually used** (from run cards / bench meta):
- Task 1/2: repo `yahoo` loader (direct HTTP), 501/503 current S&P constituents, **unadjusted prices** — dividends appear as price gaps. For daily cross-sectional IC this is second-order; it slightly penalizes high-yield names in momentum rankings.
- Task 3: `local` Data Bridge ← yfinance `auto_adjust=True` (adjusted OHLC ≈ total-return proxy).
- Smoke test: `yahoo`, unadjusted.

**Survivorship bias:** the SP500 bench universe is current membership only (Wikipedia snapshot 2026-05-17); the repo discloses this in logs, JSON meta, and the HTML report. Point-in-time membership is only implemented for CSI300 (Tushare token required, not used). Consequences: all Task 1/2 return levels and long-only Sharpes are inflated; IC-based results are biased in the same direction. The Task 3 basket is also hand-picked with hindsight (survivor selection at its purest).

**Engine quirks hit (none required repo modification):**
1. **"insufficient capital for position rebalance"** — with `position_adjustment: "rebalance"`, `rebalance_tolerance > 0`, and fully-invested targets, drift days where only the *buy* side crosses the tolerance band plan unfunded buys, and the engine (correctly) hard-fails rather than partial-fill. Diagnosed with a monkeypatch probe ([scripts/debug_rebalance_fail.py](scripts/debug_rebalance_fail.py)): equity had grown 10.7% while cash stayed fixed at entry level. Resolution: challengers hold a 1% cash buffer (`invest_frac = 0.99`) **and** run `rebalance_tolerance: 0.0`, under which buys and sells always net within a bar. Side effect: "monthly rebalance" strategies are executed as *monthly-recomputed targets, daily re-trimmed* — the fill counts in the table reflect that, and their cost load is therefore conservative (overstated).
2. `alpha bench`'s naive gate (`ic_mean > 0.02`) labels a t≈4.3 momentum factor `dead`; the strict gate is the meaningful one. Also, its multiple-testing/deflated-Sharpe block is computed internally but not printed by the CLI.
3. The engine's US cost model has hardcoded $0 commission (slippage only), and a bare `"commission"` config key is silently ignored by the daily engine — costs were set via `slippage_us`.
4. OHLC validation dropped 2 invalid bars (of ~18.6k) from the adjusted local CSVs — rounding artifacts of adjustment; immaterial.
5. CHANGELOG review: this build (0.1.14 + fixes to `80ffdda4`) already contains the recent correctness fixes that would otherwise matter here — Shadow-Account PnL=0.00 misread (fixed 2026-08-25), tushare adjustment + CSI300 PIT masking (0.1.13), halt-gap return erasure (0.1.13), post-fill position reporting (#1082), `--strict` being unreachable before 0.1.13 (#796). No suspicious behaviour observed that matched an open bug.

**Not completed / out of scope:**
- Point-in-time S&P 500 membership (repo doesn't support it for this universe; would need external membership history).
- BAB with the paper's full construction (leverage to beta-1 legs, shrunk betas, separate correlation/vol windows) — the repo factor is an explicit price-only proxy.
- ADV/capacity-aware costs (`adv_value=None` throughout — infinite liquidity assumed, stated per the cost model's own docs) and borrow beyond the flat 0.30%/yr US default.
- The `validation` config block (Monte-Carlo/bootstrap/walk-forward on engine runs) — redundant with the purged-CV and split analyses for this study's purpose.
- No broker-credential steps were encountered anywhere in these paths, so nothing had to be skipped on that front.

**Reproducibility notes:** bench panel cache at `~/.vibe-trading/cache/sp500_2010-01-01_2025-12-31.pkl` (delete `.pkl` + `.sha256` to force refetch); loader cache under `~/.vibe-trading/cache/loaders/`. The two ~40MB factor/forward-return panel CSVs are gitignored (regenerated by the Task 1/2 script). The Task 3 local CSVs *are* committed ([data/local/](data/local/)) so those runs re-execute offline byte-identically; `~/.vibe-trading/data-bridge/config.yaml` was created by this study (machine-local, absolute paths — regenerate with the snippet in the study's git history if needed).

## 7. Conclusions

- **Task 1**: The evidence supports cross-sectional momentum on this universe/period — positive IC (0.0158, t≈4.3 vs shuffled control), winners' quantile dominant — directionally consistent with the literature. It does **not** support BAB in this sample: beta sorting works, the low-beta Sharpe premium doesn't appear; attributed to the proxy construction, the 2010–2025 regime, and survivorship bias rather than an engine defect.
- **Task 2**: The momentum *signal* is robust to every stress applied (random controls, OOS gate, half-samples, purged CV, 1-day timing shift). The *long-short implementation* is not robust to costs: 15 bps/side × 11× turnover consumes more than the entire gross spread. What the evidence supports: momentum as information. What it doesn't: momentum as a retail-tradable long-short strategy at this rebalance frequency.
- **Task 3**: After identical costs, no simple overlay beat buy-and-hold on this basket for 2019–2026. Inverse-vol offered a marginal, statistically fragile Sharpe improvement; trend-following was decisively worse in a market this strong. The honest generalization is limited: this window is a best-case for buy-and-hold, and the basket itself is survivor-selected.
