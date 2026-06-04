# ETH s3 Dynamic-Exit Iteration Report

**Date:** 2026-06-02
**Symbol:** ETH-USDT-SWAP
**Period:** 2022-06 → 2026-06 (≈4y), oos_start=2025-01-01
**Parent strategy:** `eth_s2_stablecoin_funding_gated`
**Hypothesis (from ETH pipeline report §5 improvement #2):** Replace fixed -3% stop-loss with `signal_invalidation` exits (close on factor percentile returning to neutral band 40-60) to reduce ATR-noise whipsaw losses, recover OOS win_rate.

---

## TL;DR

**Hypothesis confirmed.** Walk-forward OOS shows large improvement vs eth_s2 across all key metrics — same 2 factors, same archetype, only exit logic changed.

| Metric | eth_s2 OOS | **eth_s3 OOS** | Δ |
|---|---|---|---|
| Total return | -3.2% | **+4.5%** | **+7.7pp** |
| Sharpe | 0.12 | **0.25** | **2.1x** |
| Max DD | -37.8% | **-25.7%** | **-12pp better** |
| Win rate | 36.2% | **50.6%** | **+14.4pp** |
| Profit factor | 1.01 | 1.09 | +0.08 |
| Avg holding (days) | 65.3 | **17.9** | **-73%** (3.6x turnover) |
| Trades | 69 | 89 | +20 |
| ETH benchmark | -40.4% | -40.4% | — |
| **Excess (alpha)** | **+37.1pp** | **+44.8pp** | **+7.7pp** |

ETH 熊市 OOS (-40%) 期間，s3 賺 +4.5% — 從「防禦性 hedge」升級為「能小賺的多空策略」。

---

## 改動內容

僅 yaml 級變更，無 code 改動：

### Exit rules 對比

**eth_s2** (parent):
```yaml
exit_rules:
- condition: time_based
  max_hold_hours: 120
- condition: take_profit_pct
  value: 7.0
- condition: stop_loss_pct
  value: 2.5
```

**eth_s3** (this iteration):
```yaml
exit_rules:
- condition: time_based
  max_hold_hours: 144
- condition: take_profit_pct
  value: 9.0
- condition: stop_loss_pct
  value: 4.0          # 放寬 SL 2.5 → 4.0（讓 signal_invalidation 先觸發）
- condition: signal_invalidation
  expression: stablecoin_supply_z_percentile_120d between 40,60
- condition: signal_invalidation
  expression: funding_z_percentile_120d between 40,60
```

Entry / 因子 / persistence / position_sizing 完全相同。

### 最佳參數 (sweep_092)

```yaml
lookback_days: 90
entry_high_pct: 70
entry_low_pct: 15
hold_max_hours: 168     # 1 週
sl_pct: 3.0
tp_pct: 8.5
```

注意：sweep 自動選 SL=3 (在 [3-5] 範圍下緣)，意思是 SL 主要是 backstop、絕大多數出場由 signal_invalidation 觸發。

---

## Train (2.5y in-sample, 2022-06 → 2025-01)

| Metric | s2 train | s3 train | Δ |
|---|---|---|---|
| Total return | +263.5% | +127.0% | -136pp |
| Sharpe | 1.55 | **1.41** | -0.14 |
| Max DD | -37.8% | **-30.7%** | -7pp better |
| Win rate | 48.7% | **57.4%** | **+8.7pp** |
| Profit factor | 1.74 | **2.12** | **+0.38** |
| Avg holding | 81.6 day | 27.6 day | -66% |
| Trades | 117 | 122 | +5 |

Train 總報酬退 (s2 263% → s3 127%)，但是 sharpe / DD / win_rate / PF 全部更好。s2 的高 total_return 來自少數大贏單騎；s3 信號分散度高、單筆贏小但勝率高、 risk-adjusted 才是真贏家。

---

## OOS Walk-Forward (held-out 2025-01 → 2026-06, 1.4y)

| Metric | Value |
|---|---|
| Final value | $1,044,580 |
| Total return | **+4.46%** |
| Annual return | +3.13% |
| Sharpe | **+0.249** |
| Sortino | 0.113 |
| Calmar | 0.122 |
| Max DD | **-25.7%** |
| Win rate | **50.6%** |
| Profit factor | 1.09 |
| Avg holding | 17.9 days |
| Trades | 89 (~64/yr) |
| ETH benchmark | -40.4% |
| **Excess vs ETH** | **+44.8 pp** |
| Information ratio | +0.25 |

### 為何 s3 在 OOS 比 s2 好

1. **SL whipsaw 減少**: ETH 1-week ATR ~7-9%；s2 SL=2.5% 在熊市中被噪音震出小虧。s3 SL 放寬 + signal_invalidation 主動出場 = 不被 ATR 拍下車。
2. **勝率回到 train 水準**: s2 train 48.7% → OOS 36.2%（崩 12.5pp），s3 train 57.4% → OOS 50.6%（崩 6.8pp）。OOS 衰退仍在但約一半。
3. **DD 自然壓縮**: 動態出場讓部位提早平倉，連續虧損段被切短。
4. **持倉週期短**: 17.9 day vs 65.3 day = 同樣資本更高 turnover、更敏捷。

---

## Stage 5 selection 預估

Score formula:
```
score = 0.4×(sharpe/1.5) + 0.3×(1−|dd|/0.10) + 0.2×(pf/1.5) + 0.1×(trades/100)
```

s3 OOS:
- sharpe 0.25 / 1.5 = 0.17
- (1 − 0.257/0.10) = 1 − 2.57 = -1.57 → clamp 0
- pf 1.09 / 1.5 = 0.73
- trades 89/100 = 0.89

DD 25.7% 仍 > 10% 基準 → DD 項 clamp 0 → 0.3 權重浪費 → **stage 5 仍會標 selected=False**。

但 stage 3-diag 給的 verdict 是 `back_to_stage_4`（不是 `back_to_stage_2`），表示概念可繼續迭代，不是死路。

---

## 下一步建議

s3 確認 #2 改進方向正確；接續可做：

1. **#3 regime filter**: 在 entry 前加 stage2.5 regime mask — 只在 bull/neutral 做多、bear 做空（ETH benchmark 在 OOS 是 -40% 大熊，做多顯然該收斂）。可能再降 DD 並提升 win_rate。
2. **降 leverage 0.5x** (對 s3 套用): DD 25% → ~13% (接近 stage 5 selectable 門檻)。代價是年化從 3.1% 降到 1.6%，仍打贏 benchmark 40pp。
3. **TP 8.5% 是否可降到 6%**: 多放幾個贏單先入袋。需單獨 sweep tp_pct 範圍 [5-8]。

---

## 檔案 paths

- 策略 YAML: `research/strategies/strategy_eth_s3_dynamic_exit.yaml`
- 編譯信號: `research/manifests/eth_s3_dynamic_exit/signal_engine.py`
- 診斷: `research/manifests/eth_s3_dynamic_exit/diagnosis.json` (`back_to_stage_4`)
- 最佳化: `research/manifests/eth_s3_dynamic_exit/optimization.json`
- Train best run: `runs/eth_s3_dynamic_exit_sweep_092/`
- OOS run: `runs/eth_s3_dynamic_exit_oos_holdout/`
- Parent comparison: `research/manifests/eth_s2_stablecoin_funding_gated/REPORT.md`

---

*Generated 2026-06-02 — improvement iteration #2 of ETH pipeline.*
