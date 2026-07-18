---
name: correlation-regime
description: Correlation-regime detection and crisis attribution — edge-density regime states with hysteresis, causal (no look-ahead) smoothing, regime-aware exposure context, first-mover crisis attribution with honest NAME / MACRO / AMBIGUOUS / ABSTAIN verdicts, and a correlation-rewiring leaderboard that catches slow bleed-outs
category: analysis
---

# Correlation-Regime Detection and Crisis Attribution

## Overview

The `correlation-analysis` skill answers *"how correlated are these assets?"* — a snapshot.
This skill answers the temporal questions a snapshot cannot:

1. **When** did the market fuse into one highly-correlated bloc, and when did it release?
   (Mode 1 — regime detection)
2. **What** does a fused regime mean for position sizing? (Mode 2 — risk context)
3. **Who** moved first when a crisis broke — is there a nameable trigger asset?
   (Mode 3 — first-mover attribution)
4. **Who** quietly rewired their relationship to the rest of the market, even without a
   violent move? (Mode 4 — rewiring leaderboard)

The methodology comes from an open-source streaming pipeline (see References)
whose public repository pins the regime machinery's math and an eight-event
historical replay regression (COVID, May-2021, China ban, Nov-2021 top, LUNA,
FTX, SVB, yen-carry — 17 crypto symbols, 1-minute bars) that its CI reproduces
bit-for-bit. The finer-grained numbers quoted in this skill — 13 fused/defused
regime cycles on the continuous 2020–2024 tape at a ~0.008/day calm false-alarm
rate, and zero wrong culprit names across 10 labeled crises (2 held
out-of-sample), including naming FTT roughly two days before the November 2022
collapse — are the **author's unpublished internal replays** on that same
pipeline and are not independently verifiable. All of it is historical replay,
never live results, and the method is market-agnostic even though the
validation tape is crypto.

**What this skill is NOT**: a trade-timing signal. The same validation program tested
regime-based exits head-to-head against a plain price stop and lost — correlation
regimes cannot time tops, and the give-up cost of selling into a crash is a property
of the tape, not of any signal. Use these modes for risk context, monitoring, and
post-hoc attribution; never present them as buy/sell triggers.

---

## Mode 1: Correlation-Regime Detection (Edge Density + Hysteresis)

**Use case**: Maintain a live, causal answer to "is the market currently one bloc?"
Diversification quietly disappears when pairwise correlations fuse; a regime state
machine turns that into an explicit, monitorable state with few false alarms.

### Workflow

```
1. Compute rolling-window pairwise correlations of returns
2. Reduce each correlation matrix to one number: edge density
   = fraction of asset pairs with |ρ| ≥ edge_threshold
3. Smooth the density series with a TRAILING window (causal — see warning below)
4. Run a hysteresis (Schmitt-trigger) state machine over the smoothed series:
   enter FUSED when density ≥ enter_threshold, exit only when ≤ exit_threshold
5. Emit regime state + transition timestamps for monitoring / reporting
```

Two thresholds with a dead band between them are the entire trick: a single
threshold chatters (fires dozens of times as density oscillates around it), while
hysteresis yields a handful of clean regime cycles per market cycle.

```python
import numpy as np
import pandas as pd


def compute_edge_density(
    returns: pd.DataFrame,
    corr_window: int = 60,
    edge_threshold: float = 0.5,
) -> pd.Series:
    """Reduce rolling correlation matrices to an edge-density series.

    Edge density is the fraction of distinct asset pairs whose rolling
    |correlation| clears ``edge_threshold`` — a scalar "how fused is the
    market" gauge in [0, 1].

    Args:
        returns: Multi-asset return matrix, columns are symbols
        corr_window: Rolling window length (bars) for pairwise correlation
        edge_threshold: |ρ| level at which a pair counts as an "edge"

    Returns:
        Edge-density series aligned to ``returns.index`` (NaN during warmup)
    """
    n_assets = returns.shape[1]
    n_pairs = n_assets * (n_assets - 1) // 2
    upper_mask = np.triu(np.ones((n_assets, n_assets), dtype=bool), k=1)

    density = pd.Series(np.nan, index=returns.index)
    for i in range(corr_window, len(returns) + 1):
        corr = returns.iloc[i - corr_window:i].corr().abs().to_numpy()
        density.iloc[i - 1] = float((corr[upper_mask] >= edge_threshold).sum()) / n_pairs
    return density


def detect_regimes(
    density: pd.Series,
    smooth_window: int = 5,
    enter_threshold: float = 0.65,
    exit_threshold: float = 0.45,
) -> pd.DataFrame:
    """Hysteresis (Schmitt-trigger) regime state machine on smoothed density.

    The market is FUSED once smoothed density reaches ``enter_threshold`` and
    stays FUSED until it falls back to ``exit_threshold``. The dead band
    between the two thresholds is what suppresses chatter.

    Args:
        density: Edge-density series from :func:`compute_edge_density`
        smooth_window: Trailing smoothing window (causal; never centered)
        enter_threshold: Density level that opens a FUSED regime
        exit_threshold: Density level that closes it (must be < enter_threshold)

    Returns:
        DataFrame with columns ``density``, ``smoothed``, ``fused`` (0/1)
    """
    if exit_threshold >= enter_threshold:
        raise ValueError("exit_threshold must be below enter_threshold")

    # Trailing mean = causal. A centered window here silently reads the future.
    smoothed = density.rolling(smooth_window, min_periods=1).mean()

    fused = False
    states = np.zeros(len(smoothed), dtype=int)
    for i, value in enumerate(smoothed.to_numpy()):
        if np.isnan(value):
            states[i] = int(fused)
            continue
        if not fused and value >= enter_threshold:
            fused = True
        elif fused and value <= exit_threshold:
            fused = False
        states[i] = int(fused)

    return pd.DataFrame(
        {"density": density, "smoothed": smoothed, "fused": states},
        index=density.index,
    )
```

### Threshold Selection Guide

| Parameter | Guidance |
|------|------|
| `edge_threshold` | 0.5 works for raw daily/intraday return correlations in crypto and equities. It does **not** transfer to partial/residual correlations, whose edges are systematically smaller — recalibrate per estimator. |
| `enter_threshold` / `exit_threshold` | Anchor to the calm-period density distribution: enter near a high calm percentile (e.g. 90–95th), exit near the calm median. Keep a wide dead band; a narrow one reintroduces chatter. |
| `corr_window` | Shorter reacts faster but is noisier. 30–90 bars is a reasonable band for daily data; on intraday bars use hundreds. |
| `smooth_window` | Just enough to kill single-bar spikes. Oversmoothing delays regime onsets. |

### Look-Ahead Warning

The single most common silent bug in regime detection is **centered smoothing**
(e.g. `rolling(..., center=True)` or any symmetric filter). It leaks up to half a
window of future data into each point, making historical regime onsets appear
earlier and cleaner than anything achievable live. Every smoothing step in a regime
pipeline must be trailing-only, and any claimed onset lead time should be re-checked
after replacing each filter with its causal version — in the author's internal
replays that re-check moved onsets later by 1–2 days and the detector still passed,
which is the honest number to quote.

---

## Mode 2: Regime-Aware Risk Context (De-Grossing)

**Use case**: Translate the FUSED state into portfolio-risk language for a report or
a monitoring dashboard.

A fused regime means cross-asset diversification is effectively gone: the portfolio
has collapsed into a single position with leverage. The defensible, replay-tested
framing for what to do about it:

- **De-gross, don't liquidate.** In the author's internal replays, halving gross exposure
  during fused regimes improved risk-adjusted outcomes versus buy-and-hold, while
  going fully to cash destroyed them — regime onset lags the price top, so full
  liquidation locks in the worst prints.
- **State the anti-claim in the same breath**: fused-regime detection cannot time
  tops. Tested against a plain trailing price stop, regime-based exits lost; the
  ~double-digit "give-up" between a crash's start and any regime confirmation is a
  property of crash tapes themselves.

```python
def regime_exposure_context(
    regimes: pd.DataFrame,
    base_gross: float = 1.0,
    fused_gross: float = 0.5,
) -> pd.Series:
    """Descriptive gross-exposure context per bar (NOT a trade signal).

    Args:
        regimes: Output of :func:`detect_regimes`
        base_gross: Reference gross exposure during defused (calm) regimes
        fused_gross: Reference gross exposure during fused regimes

    Returns:
        Per-bar reference gross-exposure series for risk reporting
    """
    return pd.Series(
        np.where(regimes["fused"] == 1, fused_gross, base_gross),
        index=regimes.index,
        name="reference_gross",
    )
```

---

## Mode 3: Crisis First-Mover Attribution

**Use case**: A crisis episode has opened (Mode 1 fired, or an exogenous alert
arrived). Answer "who broke first?" without ever guessing.

### The Honesty Protocol

The protocol's defining property is that it prefers silence to a wrong name. Every
episode resolves to exactly one of four verdicts:

| Verdict | Meaning | Condition |
|------|------|------|
| `NAME` | One asset is the likely trigger | Exactly one asset crossed the alarm bar with a clear lead over the pack |
| `MACRO` | Market-wide shock, no culprit | The pack crossed together within a tight window |
| `AMBIGUOUS` | Multiple candidates, refuses to pick | Several assets crossed close together, ahead of the rest |
| `ABSTAIN` | Nothing to say | No asset crossed the alarm bar |

In the author's internal 10-crisis replays (unpublished — see Overview) this
protocol never emitted a wrong `NAME` — because the alarm bar is set very high
and everything below it downgrades to `AMBIGUOUS`, `MACRO`, or `ABSTAIN`.

### Workflow

```
1. For each asset, compute a short-horizon move-intensity series
   (rolling sum of |returns|)
2. Score it as a robust z-score against the asset's OWN calm baseline
   (median/MAD, baseline strictly prior to the bar being scored)
3. Watch tier (low z): informational watchlist only — never allowed to accuse
4. Alarm tier (very high z): record each asset's first crossing time
5. Apply the verdict rules: lead-gap ⇒ NAME, pack-together ⇒ MACRO,
   near-tie leaders ⇒ AMBIGUOUS, no crossings ⇒ ABSTAIN
```

```python
def first_mover_attribution(
    returns: pd.DataFrame,
    baseline_window: int = 120,
    move_window: int = 3,
    alarm_z: float = 8.0,
    watch_z: float = 3.0,
    lead_gap: int = 2,
    macro_span: int = 1,
    macro_fraction: float = 0.6,
) -> dict:
    """First-mover crisis attribution with abstention.

    Each asset's short-horizon move intensity is scored as a robust z-score
    against its own trailing calm baseline (median / MAD, shifted so the move
    being scored never contaminates its own baseline). Verdicts follow the
    honesty protocol: NAME only on a clear solo lead, otherwise MACRO /
    AMBIGUOUS / ABSTAIN.

    Args:
        returns: Multi-asset return matrix, columns are symbols
        baseline_window: Trailing window (bars) for the per-asset calm baseline
        move_window: Short horizon (bars) of the move-intensity sum
        alarm_z: Robust z at which an asset counts as "in violent collapse"
        watch_z: Informational watch-tier level (never used for naming)
        lead_gap: Minimum lead (bars) of the first crosser over the second
            required to NAME it
        macro_span: If the pack crosses within this many bars of the first
            crossing, the episode is MACRO
        macro_fraction: Fraction of assets that must cross to call MACRO

    Returns:
        Dict with ``verdict`` (NAME / MACRO / AMBIGUOUS / ABSTAIN),
        ``named`` (symbol or None), ``candidates``, ``crossings``
        (symbol → first alarm timestamp), ``watchlist``, and ``z`` (the
        full z-score DataFrame for inspection)
    """
    intensity = returns.abs().rolling(move_window).sum()
    # Proper rolling MAD: each window's deviations from its OWN median.
    # (Nesting two full-length rolling medians instead stacks their warmups —
    # the score would silently stay NaN for 2x baseline_window bars.)
    # shift(1) keeps the bar being scored out of its own baseline.
    med = intensity.rolling(baseline_window).median().shift(1)
    mad = intensity.rolling(baseline_window).apply(
        lambda window: np.median(np.abs(window - np.median(window))), raw=True
    ).shift(1)
    z = (intensity - med) / (1.4826 * mad.replace(0.0, np.nan))

    crossings: dict[str, pd.Timestamp] = {}
    for symbol in z.columns:
        hits = z.index[z[symbol] >= alarm_z]
        if len(hits) > 0:
            crossings[symbol] = hits[0]

    watch_hits = (z >= watch_z).any()
    watchlist = sorted(watch_hits.index[watch_hits])

    if not crossings:
        return {
            "verdict": "ABSTAIN", "named": None, "candidates": [],
            "crossings": {}, "watchlist": watchlist, "z": z,
        }

    ordered = sorted(crossings.items(), key=lambda item: item[1])
    first_symbol, first_time = ordered[0]
    positions = {ts: i for i, ts in enumerate(z.index)}
    first_pos = positions[first_time]

    pack_size = sum(
        1 for _, ts in ordered if positions[ts] - first_pos <= macro_span
    )
    if pack_size >= max(2, int(np.ceil(macro_fraction * returns.shape[1]))):
        return {
            "verdict": "MACRO", "named": None,
            "candidates": [s for s, _ in ordered],
            "crossings": crossings, "watchlist": watchlist, "z": z,
        }

    leaders = [
        symbol for symbol, ts in ordered if positions[ts] - first_pos < lead_gap
    ]
    if len(leaders) == 1 and (
        len(ordered) == 1 or positions[ordered[1][1]] - first_pos >= lead_gap
    ):
        return {
            "verdict": "NAME", "named": first_symbol, "candidates": leaders,
            "crossings": crossings, "watchlist": watchlist, "z": z,
        }

    return {
        "verdict": "AMBIGUOUS", "named": None, "candidates": leaders,
        "crossings": crossings, "watchlist": watchlist, "z": z,
    }
```

### Calibration Discipline

- **The alarm bar must be chosen walk-forward** on historical events whose culprit
  labels come from the public record (post-mortems, filings) — never from the
  system's own output. "The culprit is whoever we named" is circular and voids any
  zero-false-names claim.
- **Baseline from detected calm, not from a blind trailing window**, in production:
  source the median/MAD baseline from Mode 1's defused regimes. Trailing windows
  that overlap a previous crisis produce contaminated baselines and inflated bars —
  this was a real failure class in validation (post-crisis "calm" that wasn't).
- Set the bar high and let the protocol abstain. A bar low enough to catch every
  event mislabels non-events; the validated posture is "when it names, it has been
  right; when it cannot know, it says so."

---

## Mode 4: Correlation-Rewiring Leaderboard

**Use case**: Catch the slow bleed-outs. Some collapses (weeks-long, grinding) never
move violently enough to trip Mode 3's alarm — but the dying asset's *correlation
profile* to the rest of the market rewires dramatically. Rank assets by how much
their correlation row changed versus calm.

Modes 3 and 4 cover each other's blind spots — fast violent collapses trip the
alarm, slow bleeds top the rewiring board — so report them together, never alone.

Choose the event window with care: during a full-market fusion episode *every*
asset rewires by construction and the leaderboard degenerates into "everyone".
The mode is most informative on the run-up window before a regime onset, or on a
suspect stretch that never fused at all (the classic slow-bleed shape).

```python
def rewiring_leaderboard(
    returns: pd.DataFrame,
    calm_mask: pd.Series,
    event_mask: pd.Series,
    min_bars: int = 40,
) -> pd.DataFrame:
    """Per-asset correlation-rewiring score: event vs calm baseline.

    Score = row mean of |Δρ| between the event-window correlation matrix and
    the calm-baseline correlation matrix. High score = the asset's
    relationship to the rest of the market changed the most.

    Args:
        returns: Multi-asset return matrix, columns are symbols
        calm_mask: Boolean series marking calm-baseline bars
            (e.g. ``regimes["fused"] == 0`` from Mode 1)
        event_mask: Boolean series marking the episode under examination
        min_bars: Minimum bars required in each window

    Returns:
        DataFrame indexed by symbol with ``rewiring_score``, sorted descending
    """
    calm = returns.loc[calm_mask.reindex(returns.index, fill_value=False)]
    event = returns.loc[event_mask.reindex(returns.index, fill_value=False)]
    if len(calm) < min_bars or len(event) < min_bars:
        raise ValueError(
            f"need >= {min_bars} bars in each window "
            f"(calm={len(calm)}, event={len(event)})"
        )

    delta = (event.corr() - calm.corr()).abs()
    matrix = delta.to_numpy(copy=True)  # copy: DataFrame internals may be read-only
    np.fill_diagonal(matrix, np.nan)
    scores = pd.Series(np.nanmean(matrix, axis=1), index=delta.index)
    return scores.sort_values(ascending=False).to_frame("rewiring_score")
```

---

## Dependencies

```bash
pip install pandas numpy
```

(matplotlib only if you plot the regime timeline.)

---

## Output Format

```markdown
## Correlation-Regime and Attribution Report

### Universe: [N assets] ([Start Date] - [End Date], [bar size])

#### Regime Summary (Mode 1)
| Metric | Value |
|------|-----|
| Regime cycles (fused/defused) | 5 |
| Time in fused regime | 18% |
| Current state | DEFUSED (density 0.31, smoothed 0.34) |
| Last transition | 2024-08-05 fused → 2024-08-19 defused |

#### Risk Context (Mode 2)
| Regime | Reference gross | Rationale |
|------|-----|------|
| Defused | 1.00 | Diversification intact |
| Fused | 0.50 | Portfolio ≈ one levered position; de-gross, don't liquidate |

> Not a trade signal: regime detection cannot time tops (validated).

#### Episode Attribution (Mode 3)
| Field | Value |
|------|-----|
| Verdict | NAME |
| Named asset | [SYMBOL] (alarm z = 9.4, lead 2 bars over the pack) |
| Watchlist (informational) | [SYM1], [SYM2] |

#### Rewiring Leaderboard (Mode 4)
| Rank | Asset | Rewiring score |
|------|------|------|
| 1 | [SYMBOL] | 0.42 |
| 2 | [SYMBOL] | 0.19 |
```

---

## Notes

1. **Causality is the whole game.** No centered smoothing, no same-bar baselines,
   no thresholds tuned on the episode being scored. Every historical claim should
   survive the question "could this have been computed at that bar?"
2. **Not a trading signal.** Regime exits were tested against a plain price stop
   and lost. Present Modes 1–4 as risk context and attribution, never as buy/sell.
3. **Thresholds do not port across correlation estimators.** An `edge_threshold`
   calibrated on raw-return correlations is wrong for partial/residual
   correlations (their edges are systematically smaller). Recalibrate per estimator.
4. **Event-window scans are left-censored.** Markets often re-fuse faster than a
   short scan can see; prefer one continuous tape over stitched event windows when
   validating regime counts.
5. **Survivor bias truncates attribution.** Delisted assets vanish from vendor
   tapes precisely when they matter most (the dying asset is the story). Pull raw
   histories that include delisted symbols before validating Mode 3/4 claims.
6. **Scope of the attribution claim.** The alarm mechanically names only fast,
   violent collapses; slow bleeds surface in the watch tier and Mode 4; macro
   shocks resolve to MACRO by construction. Quote the calm-period false-alarm rate
   (per day) as the honesty metric.
7. **Labels are human, walk-forward.** Culprit labels for calibration events come
   from the public record before scoring runs, and future re-calibration uses only
   events fully adjudicated in the past.
8. **MAD can be zero** in dead markets (stale prints); guard the denominator (the
   snippet maps 0 → NaN) rather than letting z-scores explode.

---

## References

- Streaming reference implementation (JVM): the corrcalc-graphs pipeline —
  https://github.com/tarvyn-analytics/corrcalc-graphs-pipeline (Apache-2.0). Its
  README's "The math — from bars to a fire" section derives the density/hysteresis
  regime machinery, and "Validation — a pinned historical-event regression" pins an
  eight-event crypto replay regression (17 symbols, 1-minute bars) reproduced by
  its CI. The finer-grained numbers quoted in this skill (regime-cycle count,
  false-alarm rate, attribution results) are the author's unpublished internal
  replays on that pipeline — they are not part of the public regression and the
  public repo ships no crisis-naming system.
- Maven Central artifacts for JVM users:
  `io.github.tarvyn-analytics.corrcalc:corrcalc-lib-core` (streaming correlation
  engine), `io.github.tarvyn-analytics.graphs:graphs-algos-lib` (graph analyses on
  correlation matrices), `io.github.tarvyn-analytics.corrcalc.graphs:corrcalc-graphs-pipeline`
  (the replay pipeline).
- For static pair analysis, cointegration, and pair-trading signals, see the
  `correlation-analysis` skill; for volatility-based regime work, see `volatility`.
