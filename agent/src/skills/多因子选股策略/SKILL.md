---
name: 多因子选股策略
description: 多因子横截面选股框架，结合因子标准化、等权或 IC 加权打分，以及 TopN 组合构建，适用于多标的组合策略。
category: strategy
---
# Multi-Factor Cross-Sectional Stock Ranking

## Purpose

On the same time cross-section, compute multiple factor values for many stocks, standardize them, combine them into a composite score, and select the top-ranked stocks to build a portfolio.

## Signal Logic

1. **Factor calculation**: calculate N factors for each stock (such as momentum, value, and quality)
2. **Cross-sectional standardization**: standardize each factor on the cross-section with Z-score normalization (subtract mean, divide by standard deviation)
3. **Composite scoring**: sum the factors with equal weights (or custom weights) to obtain a composite score
4. **Rank and select**: go long the TopN names, with weight = 1/N for each

## Built-In Factors

| Factor Name | Calculation Method | Direction |
|--------|---------|------|
| momentum | Return over the past N days | Positive (higher is better) |
| reversal | Return over the past 5 days | Negative (lower is better) |
| volatility | Standard deviation of returns over the past N days | Negative (lower is better) |
| volume_ratio | Today's volume / N-day average volume | Positive |

If `extra_fields` are available (China A-shares), you can also add:
- `pe_factor`: 1/PE (the larger, the cheaper)
- `pb_factor`: 1/PB
- `roe_factor`: ROE (the larger, the better)

## Parameters

| Parameter | Default | Description |
|------|--------|------|
| momentum_window | 20 | Momentum lookback window |
| vol_window | 20 | Volatility lookback window |
| top_n | 3 | Number of selected stocks |
| rebalance_freq | 20 | Rebalancing frequency (trading days) |

## Common Pitfalls

- Cross-sectional standardization requires at least 3 stocks, otherwise Z-scores are meaningless
- Keep the previous signal unchanged between rebalance dates (do not rerank every day)
- Factors have different directions: momentum is positively sorted, volatility is negatively sorted, so directions must be aligned before standardization
- Portfolio weights must be normalized: each TopN stock gets 1/N, all others get 0

## Dependencies

```bash
pip install pandas numpy
```

## Signal Convention

- `1/N` = selected into TopN (equal-weight long), `0` = not selected
