# HQATL Dashboard Vision

This is a future visual specification only. No dashboard code is authorized in Phase 0.

## Side-by-side layout

### Left — Research and chart workspace

The research side will support exploration and validation with:

- Linked 4H and 1H charts
- Optional 15M futures execution-research chart
- Elliott Wave labels with separate primary and alternate counts
- Fibonacci retracements and extensions
- EMA 9, 21, 89, 200, and 233
- EMA-89 standard-deviation channel
- EMA-200 standard-deviation channel
- KAMA adaptive bands
- Linear-regression deviation channel
- iFVG
- Volume and RVOL
- CVD
- Dow/intermarket confirmation
- Backtest evidence
- Data-quality status

Layers should be independently toggled, disclose parameters and provenance, and avoid visual confirmation by indicator quantity.

### Right — Trade Decision Workspace

The decision side will summarize Bullish Bias, Bearish Bias, or Neutral Bias; confidence; risk references; Elliott scenarios; supporting, opposing, and missing evidence; data warnings; and stand-aside status. It must remain decision support rather than an autonomous trading command system.

## Interaction principles

- Symbol, timestamp, and timeframe context remain synchronized where meaningful.
- Confirmed and provisional evidence are visibly distinct.
- The interface retrieves shared backend calculations; it does not recreate formulas.
- Confidence expands into contributing evidence rather than hiding behind a score.
- Missing or unreliable evidence is prominent enough to support waiting.
