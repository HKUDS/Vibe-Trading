---
name: hft-risk-alpha
description: "Risk-first short-horizon / HFT-proxy alpha design — risk budgets, overlays, adverse-selection stress, and risk-adjusted ranking (bar/tick proxy; not co-lo)."
category: strategy
---

# Risk-First HFT / Short-Horizon Alphas

## Honest limits

This stack **does not** simulate exchange co-location, matching-engine queue priority, or nanosecond latency. It provides the best **bar / tick-proxy** risk controls the backtest engine supports (typically `1m`–`1H` bars, plus synthetic paths).

Use it when the goal is: **cut drawdowns and ruin probability while still seeking profit** on high-turnover / short-horizon styles.

## Risk budgets (design before coding signals)

Before writing `signal_engine.py`, lock numeric budgets:

| Knob | Typical short-horizon range | Meaning |
|------|----------------------------|---------|
| `vol_target` | 0.08–0.20 ann. | Scale book to target vol |
| `max_gross_leverage` | ≤ 1.0–2.0 | Gross exposure cap |
| `max_net_exposure` | ≤ 0.3–0.6 | Directional inventory cap |
| `max_name_weight` | ≤ 0.15–0.35 | Concentration |
| `max_turnover` | 0.1–0.5 / bar | Turnover throttle |
| `max_drawdown_kill` | 0.08–0.15 | Flatten kill-switch |
| `kill_cooldown_bars` | 3–20 | Stay flat after kill |
| `kill_reset_drawdown` | 0.01–0.05 | Hysteresis: re-arm only after DD recovers |
| `stop_loss` | 0.02–0.06 | Per-name adverse move stop |
| `ohlc_stop` | true (short-horizon) | Trigger stop on bar high/low wick (not close-only) |
| `inventory_mean_reversion` | 0.05–0.25 | Pull net exposure toward 0 (scales with \|net\|) |
| `partial_fill_rate` | 0.4–0.9 | Intrabar-ish: only fraction of Δw fills this bar |
| `next_bar_open_slippage_bps` | 2–10 | Haircut increments on adverse open gaps |
| `max_name_vol` | 0.3–0.8 ann. | Per-name trailing vol budget |
| `max_portfolio_cvar` | 0.02–0.05 | Trailing portfolio CVaR budget |
| `hft_costs.max_adv_participation` | 0.05–0.25 | Cap \|Δw_i\| vs trailing dollar ADV (when volume present) |
| `hft_costs.fill_slippage_mode` | `replace` (preferred) / `additive` | `replace` uses only HFT spread+AS on fills (no double-count with native slippage); `additive` stacks both |
| `hft_costs.adv_fallback_notional` | e.g. 5e6 | Constant dollar ADV when loaders omit `volume`/`amount` so ADV clips still apply |

## Hard requirements (emitted configs)

`strategy-generate` + this skill **must** emit:

1. Active ``risk_overlay`` with at least ``max_drawdown_kill`` + ``max_gross_leverage``
2. ``validation.risk_adjusted_ranking`` with a risk-aware ``objective`` and ``max_dd_limit``
3. For minute / high-turnover: ``hft_costs`` (spread + impact + adverse selection)

**Reject** return-only objectives (`total_return`, `pnl`, `raw_return`, …).
Gate helper: ``backtest.hft_config_gate.validate_risk_first_config`` /
``inject_risk_first_defaults``.

## `config.json` — risk overlay

```json
{
  "risk_overlay": {
    "enabled": true,
    "vol_target": 0.12,
    "vol_lookback": 20,
    "max_gross_leverage": 1.0,
    "max_net_exposure": 0.4,
    "max_name_weight": 0.25,
    "max_turnover": 0.3,
    "max_drawdown_kill": 0.10,
    "kill_cooldown_bars": 5,
    "kill_reset_drawdown": 0.03,
    "stop_loss": 0.04,
    "ohlc_stop": true,
    "inventory_mean_reversion": 0.15,
    "partial_fill_rate": 0.7,
    "next_bar_open_slippage_bps": 5.0,
    "max_name_vol": 0.55,
    "max_portfolio_cvar": 0.035,
    "cvar_lookback": 40
  },
  "hft_costs": {
    "enabled": true,
    "spread_bps": 2.0,
    "impact_coeff": 8.0,
    "impact_power": 0.5,
    "adverse_selection_bps": 1.5,
    "participation_cap": 0.5,
    "max_adv_participation": 0.2,
    "adv_lookback": 20,
    "fill_slippage_mode": "replace",
    "adv_fallback_notional": 5000000.0
  },
  "commission": 0.0005,
  "slippage": 0.0005,
  "validation": {
    "stress": {},
    "monte_carlo_paths": {"method": "block_bootstrap", "n_paths": 10000},
    "risk_metrics": {"n_trials": 20, "include_pbo": true},
    "risk_adjusted_ranking": {
      "objective": "sharpe_dd_penalty",
      "max_dd_limit": 0.15,
      "min_psr": 0.55,
      "max_cvar": 0.04,
      "dd_penalty": 2.0
    },
    "signal_parameter_grid": {
      "strategy": "rsi_mean_reversion",
      "collect_trial_returns": true,
      "cost_bps": 10,
      "risk_ranking": {
        "objective": "sharpe_dd_penalty",
        "max_dd_limit": 0.15,
        "min_psr": 0.55
      }
    }
  }
}
```

Modules: `backtest.risk_overlay` (pre-fill), `backtest.hft_costs` (spread/impact/AS on **live fills**;
`fill_slippage_mode=replace|additive`; ADV from `volume` → `amount` → `adv_fallback_notional`),
`backtest.hft_config_gate` (emit/validate; runner auto-enforces for `1s`/minute/HFT-tagged).

## Objectives (profit under risk)

Prefer ranking / selection by:

1. **Sharpe with DD penalty** (`sharpe − dd_penalty × |max_dd|`) — default
2. Sortino / Calmar
3. **PSR** / **DSR** (reject low probabilistic Sharpe)
4. **CVaR / ES** hard caps

Never select alphas on raw return alone. Return-only objectives are hard-rejected.

## HFT-proxy research checklist

1. Microstructure: spread, impact, adverse selection (`hft_costs` + skill `market-microstructure`)
2. Execution realism: slippage / participation (skill `execution-model`)
3. Inventory: net exposure + mean-reversion pull (scales with |net|)
4. Intrabar proxies: `partial_fill_rate`, `next_bar_open_slippage_bps` (not LOB)
5. Latency proxy: `stress` scenarios `adverse_selection_burst`, `latency_slippage_tax`
6. Kill-switches: `max_drawdown_kill` + cooldown + `kill_reset_drawdown` hysteresis
7. Budgets: `max_name_vol`, `max_portfolio_cvar`
8. Swarm: preset `hft_short_horizon_desk`

## Demo

```bash
cd agent && python scripts/demo_risk_overlay_hft.py
```

Compares unconstrained vs risk-overlay books under HFT cost stack; reports
risk-adjusted score ↑ and drawdown / ruin reductions.
