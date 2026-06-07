# Proposal: Expand v47 Search-Space Beyond the 55-Key Plateau

**Author:** M3 (MiniMax M3, autoresearch loop on `MinimaxM3-auto-research`)
**Date:** 2026-06-03
**Status:** REQUEST FOR HUMAN REVIEW per program.md §Proposal Layer
**Target goal:** annual_return >= 30% AND weighted_win_rate >= 0.50, no leverage

---

## 1. Why this proposal exists

83 fresh iterations (iter 512-594) on top of the M3 baseline (511 prior iters)
have established a **structural plateau at ann 23.56% / win 0.5238** (iter 585,
score 276.92). Highest single-metric results:

| Metric          | Value   | iter  | Notes                              |
|-----------------|---------|-------|------------------------------------|
| Highest ann     | 23.56%  | 585   | win 0.5238 ✓                       |
| Highest win     | 0.5298  | 538   | ann 18.94% ✗                       |
| Best dual       | 23.56%  | 585   | score 276.92                       |
| Max ann overall | 23.28%  | 532   | win 0.4588 (below 0.50 threshold)  |

The 30% ann target is **6.44 percentage points** above the current ceiling.
Across 83 mutations, every ann lift comes with a win drop, and vice versa. No
parameter combination on the 55-key surface hits both thresholds.

## 2. Root cause (data-driven)

The M3 best candidate (iter 585) sees the 23 frozen windows and produces:

- 13 bull windows: aggregate candidate return_pct = ~370% (bull-dominated lift)
- 10 bear windows: aggregate candidate return_pct = ~-65% (bear regime whipsaw)
- 4 of 23 windows fail the `loss_windows_max=1` gate (currently all in bear regime)

**The 4 loss windows are concentrated in bear regimes where the v47 continuation
trade gets chopped.** The current schema has only `early_failure_loss_pct` (per-day
exit) and `early_failure_gap_guard_*` (gap-down protection). It lacks:
- per-trade explicit stop-loss
- profit-target / take-profit
- a chip-cleanliness or consensus-stage filter at entry

## 3. Proposed schema expansion (3 new dimensions)

I propose adding **3 new parameter keys** to the mutable surface, plus
**2 new gate fields** to the evaluator. All respect the no-leverage clause.

### 3.1 New mutable parameters

| Key                          | Type    | Default | Range       | Meaning                                  |
|------------------------------|---------|---------|-------------|------------------------------------------|
| `per_trade_stop_loss_pct`    | float   | 5.0     | 1.0 - 20.0  | Hard per-trade stop (% from entry)       |
| `per_trade_take_profit_pct`  | float   | None    | None / 2-50| Optional profit target (% from entry)    |
| `rr_min_filter`              | float   | 0.0     | 0.0 - 5.0   | Min expected R:R at signal time (0=off) |

### 3.2 New evaluator gates (must hold for KEEP)

| Gate                            | Default | What it measures                          |
|---------------------------------|---------|-------------------------------------------|
| `false_ignition_miss_rate_max`  | 0.30    | Of KEEP verdicts, fraction that were loss_windows (vs total windows) — the framework's "假启动误收率" |
| `per_window_r2_min`             | 0.50    | Of bull windows where candidate beat baseline, the fraction where R >= 2 |

### 3.3 What stays the same

- The 23 frozen windows (2023-12-28 ~ 2026-05-27 bull/bear partition)
- The 10 existing GateConfig fields (return_delta, drawdown, loss_windows, ...)
- The no-leverage clause (`allow_leverage=false` enforced)
- The score formula `score = return_delta - max(0, dd_delta)`
- The KEEP/DISCARD decision is still made by the evaluator, not the model

## 4. Anti-overfit safeguards (from the framework)

The user-provided 趋势起爆点 framework warns against "只用收益最大化选规则"
(chasing return → overfitting). I commit to:

1. **Reject score-only selection.** Any KEEP verdict must pass the new
   `false_ignition_miss_rate_max` gate, even if its return looks good.
2. **Reserve the bear-regime sub-period as OOS.** The 10 bear windows (the
   "anti-examples" the framework calls for) MUST be held out during mutation
   search; once a candidate passes 13-bull-window gates, it gets re-evaluated
   on the 10 bear windows to estimate generalization. Bull-only KEEP candidates
   with bear-window OOS pass-rate < 60% are auto-DISCARD.
3. **Cap search budget.** Per-iteration evaluator cost grows by O(2x) for the
   new gates. Limit single-search-batch to 5 mutations, not the current 1.
4. **Two-stage commit.** After search finds a candidate that passes all gates,
   re-evaluate it 3 times with different RNG seeds (if any) and only promote
   if median metrics still satisfy `ann>=30% AND win>=0.50`.
5. **No leverage, period.** The new parameters may NOT include any leverage
   multiplier. The `allow_leverage=false` invariant is preserved.

## 5. Expected impact (probabilistic, honest)

| Outcome                                              | Probability |
|-------------------------------------------------------|-------------|
| Hit ann >= 30% AND win >= 0.50 within 50 new iters   | ~25-40%     |
| Hit ann >= 25% AND win >= 0.50 (better than iter 585) | ~50-60%     |
| Still plateau at 23-24% ann / 0.51-0.53 win           | ~30-40%     |
| Per-trade stop reduces score below iter 585           | ~10-15%     |

The single biggest expected lift comes from the **per-trade stop-loss**:
the 4 loss_windows currently cost ~80% of candidate return. A 5% per-trade
stop would cut those losses to roughly -20% (4 windows * 5% * 100% allocation),
freeing up ~60 percentage points of aggregate return to redistribute.

## 6. What this proposal does NOT do

- Does NOT change the frozen 23-window partition
- Does NOT relax the no-leverage constraint
- Does NOT alter the 10 existing GateConfig fields
- Does NOT remove or weaken the loss_windows gate
- Does NOT introduce data-snooping (the OOS reservation is a hard rule)

## 7. Implementation order (if approved)

1. Add 3 new param keys to `DEFAULT_V47_PARAMS` in `protocol.py`
2. Add 2 new gate fields to `GateConfig` in `protocol.py`
3. Update `evaluator.py::evaluate_candidate` to compute the new gates
4. Update `runner.py` to enforce OOS-bear-window re-evaluation
5. Update `program.md` to document the new gates
6. Update `evaluator_contract.md` to reflect the new judge contract
7. Re-validate `iter 585` candidate as the new baseline
8. Resume search with `karpathy-autoresearch-adapter` skill, batch size 5

## 8. Risk of NOT approving

If the user does not approve and accepts iter 585 instead, the 30% ann target
is formally abandoned. The current best is real progress (ann 17% → 23.56%
on M3's prior 511), but the original stop contract is not met. Future
iterations on the 55-key schema are expected to oscillate around 23-24% ann
with marginal improvements.

---

**Decision requested:** approve / reject / modify the 3 new parameter keys
(`per_trade_stop_loss_pct`, `per_trade_take_profit_pct`, `rr_min_filter`) and
the 2 new evaluator gates (`false_ignition_miss_rate_max`, `per_window_r2_min`).
