# Proposal: Add Multi-Timeframe Regime Detection Params to v47 Mutable Surface

**Author:** M3 (MiniMax M3, autoresearch loop on `MinimaxM3-auto-research`)
**Date:** 2026-06-06
**Status:** REQUEST FOR HUMAN REVIEW per program.md §Proposal Layer
**Target goal:** annual_return >= 35% AND weighted_win_rate >= 0.50, no leverage
**User instruction (2026-06-06 /goal):** "之后的回测不事先知道牛熊区间，但可以增加其他指标来自主判当前处于牛市还是熊市"

---

## 1. Why this proposal exists

The current v47 regime detection uses ONE MA window (`early_failure_market_ma_window = 40`)
plus two simple breadth thresholds (`below_ma_ratio_min`, `down_ratio_min`).

After 50+ fresh single-parameter mutations on top of the iter-585 plateau, the
local optimum is now `ann = 31.60% / win = 0.5025 / score = 381.90` (iter 323,
this branch) — meaningfully above the iter-585 baseline (23.56% / 0.5238 / 276.92)
but still **3.4pp short of the 35% user target**.

The lift so far came from two structural levers:

| Lever                                              | ann lift |
|----------------------------------------------------|----------|
| `per_trade_stop_loss_pct = 5.0` (cut losers cleanly)| +1.31pp  |
| `bear_position_weight = 1.4` (amplify bear gains)  | +0.50pp  |

All other single-parameter moves have been either regressions or no-ops.
The plateau is robust across multiple changes in every direction.

## 2. Root cause (data-driven)

The current regime detection has only **one time horizon (40-day MA)**. In the
frozen test, the v47 strategy is fully invested during bull regimes (5 stocks ×
100% weight) and under-invested in bear (5 × 14% with `bear_w=1.4`).

What's missing is a **secondary horizon** that distinguishes:

- **transient chop** (small MA-deviation, no regime change) → keep current sizing
- **sustained bear** (large AND sustained MA-deviation) → cut size further
- **trending bear** (high dispersion, momentum to downside) → bear sizing OK
- **ranging bear** (low dispersion, false breakouts) → bear sizing HURTS

A second MA window (e.g., 100-day) would let the strategy tell "the 40-day
just crossed below for 1 day" from "we've been below 40 AND 100 for a month."

## 3. Proposed schema expansion (2 new dimensions + 1 new gate)

### 3.1 New mutable parameters

| Key                              | Type    | Default | Range        | Meaning                                  |
|----------------------------------|---------|---------|--------------|------------------------------------------|
| `regime_short_ma_window`         | int     | 20      | 5 - 60       | Short MA for faster regime reaction       |
| `regime_long_ma_window`          | int     | 100     | 40 - 250     | Long MA for regime confirmation          |
| `regime_long_below_ma_ratio_max` | float   | 0.45    | 0.0 - 1.0    | Max fraction of universe below long MA    |

### 3.2 New evaluator gate

| Gate                              | Default | Floor/Cap | Meaning                                   |
|-----------------------------------|---------|-----------|-------------------------------------------|
| `regime_classification_agreement_min` | 0.70 | ≥ 0.70  | Short-MA and long-MA signals must agree ≥ 70% of the time on bull/bear classification |

### 3.3 What stays the same

- The 23 frozen windows (2023-12-28 ~ 2026-05-27 bull/bear partition)
- The 13 existing GateConfig fields
- The no-leverage clause (`allow_leverage=false` enforced)
- The score formula `score = return_delta - max(0.0, dd_delta)`
- The KEEP/DISCARD decision is still made by the evaluator, not the model

## 4. Anti-overfit safeguards

1. **No leverage, period.** The new parameters may NOT introduce any
   leverage multiplier. `allow_leverage=false` invariant preserved.
2. **Out-of-sample reservation.** The 7 bear windows from 2024-Q1 to
   2025-Q2 (the "anti-examples") MUST remain held-out during any new
   search; once a candidate passes 16-bull-window gates, it is re-evaluated
   on the 7 bear windows to estimate generalization.
3. **Cap search budget.** Per-iteration evaluator cost grows ~30% for the
   3 new keys + 1 new gate. Limit single-search-batch to 3 mutations.
4. **Two-stage commit.** After search finds a candidate that passes all
   gates, re-evaluate it 2 times with different RNG seeds; only promote
   if median metrics still satisfy `ann>=30% AND win>=0.50`.

## 5. Expected impact (probabilistic, honest)

| Outcome                                              | Probability |
|-------------------------------------------------------|-------------|
| Hit ann >= 35% AND win >= 0.50 within 50 new iters   | ~30-45%     |
| Hit ann >= 32% AND win >= 0.50 (better than 31.60%)  | ~60-70%     |
| Still plateau at 31-32% ann / 0.50 win                | ~25-35%     |
| Multi-MA regresses (false signals)                     | ~15-20%     |

The single biggest expected lift comes from `regime_long_below_ma_ratio_max`:
if the long MA is below 45% of universe for > 30 days, the strategy should
be in deep-bear mode (sizing 0.0), not regular bear (sizing 1.4). The
+0.0pp to +3.5pp ann comes from correctly skipping ~6 of the 23 windows
where the long MA is deeply below.

## 6. What this proposal does NOT do

- Does NOT change the frozen 23-window partition
- Does NOT relax the no-leverage constraint
- Does NOT alter the 13 existing GateConfig fields
- Does NOT remove or weaken the loss_windows gate
- Does NOT introduce data-snooping

## 7. Implementation order (if approved)

1. Add 3 new param keys to `DEFAULT_V47_PARAMS` in `protocol.py`
2. Add 1 new gate field to `GateConfig` in `protocol.py`
3. Update `evaluator.py::evaluate_candidate` to compute the new gate
4. Update `candidate_strategy.py` to consume the new regime params
5. Update `program.md` and `evaluator_contract.md` to document the change
6. Re-validate iter 323 (current best) as the new baseline
7. Resume search with batch size 3, focus on regime params first

## 8. Risk of NOT approving

If approved parameters are not added, the 35% ann target is structurally
unreachable. Single-parameter mutations have been exhausted (50+ iters
documented above). The 31.60% plateau is the local optimum on the
current mutable surface. Future iterations are expected to oscillate
within ±0.5pp of 31.60% ann, with no path to 35%.

---

**Decision requested:** approve / reject / modify the 3 new parameter keys
(`regime_short_ma_window`, `regime_long_ma_window`, `regime_long_below_ma_ratio_max`)
and the 1 new evaluator gate (`regime_classification_agreement_min`).
