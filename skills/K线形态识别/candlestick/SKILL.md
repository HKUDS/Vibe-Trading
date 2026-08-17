---
name: K线形态识别
description: K 线形态识别引擎，使用纯 pandas 向量化实现 15 种经典 K 线形态（5 种单根、5 种双根、4 种三根与 1 种趋势确认），并基于多空形态得分生成综合信号。
category: strategy
---
# Candlestick Pattern Recognition

## Purpose

Identifies 15 classic candlestick patterns and generates trading signals:

### Single-Candle Patterns (5)
| Pattern | Signal | Description |
|------|------|------|
| Hammer | Bullish | Long lower shadow with a small body at the top |
| Inverted Hammer | Bullish | Long upper shadow with a small body at the bottom |
| Shooting Star | Bearish | Long upper shadow with a small body at the bottom (appears after an uptrend) |
| Doji | Neutral | Open and close are nearly equal |
| Spinning Top | Neutral | Small body with roughly equal upper and lower shadows |

### Double-Candle Patterns (5)
| Pattern | Signal |
|------|------|
| Bullish Engulfing | Bullish |
| Bearish Engulfing | Bearish |
| Bullish Harami | Bullish |
| Bearish Harami | Bearish |
| Piercing Line | Bullish |
| Dark Cloud Cover | Bearish |

### Triple-Candle Patterns (4)
| Pattern | Signal |
|------|------|
| Morning Star | Bullish |
| Evening Star | Bearish |
| Three White Soldiers | Bullish |
| Three Black Crows | Bearish |

## Signal Logic

Bullish patterns score +1, bearish patterns score -1. Go long when the total score is > 0, go short when it is < 0, and stand aside when it equals 0.

## Parameters

| Parameter | Default | Description |
|------|--------|------|
| body_pct | 0.1 | Threshold for body-to-range ratio in a doji |
| shadow_ratio | 2.0 | Ratio of shadow length to body length |

## Dependencies

```bash
pip install pandas numpy requests
```

## Signal Convention

- `1` = long, `-1` = short, `0` = stand aside
