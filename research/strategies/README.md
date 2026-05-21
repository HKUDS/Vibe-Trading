# BTC-USDT-SWAP: 4 Rule-based Perp Strategies (Funding & F&G validated factors)

| Strategy | Archetype | Key conditions | Est. trades/yr | Expected Sharpe | Biggest risk |
|---|---|---|---:|---:|---|
| S1_BTC_multifactor_contrarian | multi_factor_consensus | Contrarian when BOTH funding and F&G percentiles align (e.g., fund ≥80th & F&G ≥70th → short; fund ≤20th & F&G ≤30th → long), with 2/3 persistence; exit on reversion to neutral. | 80 | 1.1 | Regime shifts in funding; F&G daily lag |
| S2_BTC_funding_mean_reversion | funding_mean_reversion | Single-factor: fade funding extremes (≥80th short, ≤20th long) with 2/3 persistence; veto only the most extreme opposite F&G to avoid fighting panic/mania. | 120 | 1.0 | Underperforms in strong trends; funding methodology changes |
| S3_BTC_trend_with_factor_filter | trend_with_factor_filter | EMA20>EMA50 (long) / EMA20<EMA50 (short) with 2/3 persistence; allow only if funding not crowded against the trade (block long if fund>60th; block short if fund<40th). | 90 | 1.0 | Trend whipsaws when filter is permissive; slower F&G adds lag if used |
| S4_BTC_dual_extreme_contrarian | dual_extreme_contrarian | RARE: simultaneous extremes — funding ≥85th & F&G ≥80th (short) or funding ≤15th & F&G ≤20th (long), both with persistence; wider holds up to 7d. | 40 | 1.2 | Low frequency; extremes can persist in secular trends |

Recommendation: Backtest S1 first. It best exploits the validated, stable negative IC in both funding and F&G while enforcing persistence to reduce noise, likely delivering the strongest risk-adjusted profile with moderate frequency. Then test S3 to assess incremental value from the funding gate on a classic EMA trend engine. S2 offers simplicity and higher activity for calibration, and S4 can serve as a high-conviction overlay once data confirms tail-behavior edge.

---

## Strategy file naming conventions

### Hand-authored baseline set (`strategy_S*.yaml`)

The four files `strategy_S1.yaml` through `strategy_S4.yaml` are the hand-authored
baseline strategies documented in the table above. Their names follow the short
`strategy_S<N>.yaml` pattern used in early design documents (including the stage
table in `design.md`, which still references `strategy_Sn.yaml` shorthand). These
files remain unchanged as the human-written reference set.

### Stage-2 generated strategies (`strategy_<symbol>_s<N>_<archetype>.yaml`)

The stage-2 runner (`pipeline/stage2_strategies.py`) emits additional strategy files
per coin. These follow the coin-prefixed pattern:

```
strategy_<symbol>_s<N>_<archetype>.yaml
```

Examples:
- `strategy_btc_s1_multi_factor_consensus.yaml`
- `strategy_eth_s1_funding_rate_mean_reversion.yaml`

This naming is consistent with design decision D4's multi-symbol `strategy_id` scheme,
where `<symbol>` is the lowercase coin name, `s<N>` is a 1-based sequence number
within that symbol's generated strategies, and `<archetype>` describes the strategy
logic (e.g. `multi_factor_consensus` for >=2 usable factors, or
`<factor_name>_mean_reversion` for a single-factor strategy).

Note: the `strategy_Sn.yaml` shorthand that appears in `design.md`'s stage table
is a pre-D4 convention and is superseded by this coin-prefixed scheme for all
stage-2-generated files.
