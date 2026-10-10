---
name: strategy-dev-manager
description: "Strategy Development Manager: convert academic papers and research reports into validated factors and strategies with automated backtesting, persistent storage, and decay monitoring."
category: research
---

# Strategy Development Manager

## Purpose

SDM orchestrates the full lifecycle from academic paper or research report to validated factor or strategy. It ingests documents, extracts quantitative signals, implements and backtests them through the existing tool chain, evaluates results against statistical thresholds, and monitors long-term decay. SDM does not reinvent any step. It delegates to the tools already available (read_document, factor_analysis, backtest, alpha_bench, and the hypothesis/autopilot stack) and adds a thin coordination layer with persistent artifact tracking.

Use this skill whenever a user wants to go from "here is a paper" to "I have a working, monitored factor or strategy in the system."

## When to Use

Decision tree for routing user requests:

- User provides a paper or report path → **Phase 1: INGEST**
- User says "extract factors from this paper" → **Phase 2: EXTRACT**
- User says "implement and backtest" or "run the backtest" → **Phase 3: IMPLEMENT**
- User says "evaluate results" or "check if it works" → **Phase 4: EVALUATE**
- User says "check decay" or "monitor factors" → **Phase 5: MONITOR**
- User says "disable factor" → `sdm_status(action="disable", artifact_id=...)`
- User says "enable factor" → `sdm_status(action="enable", artifact_id=...)`
- User says "list my factors" or "show status" → `sdm_status(action="list")`

When the user's intent spans multiple phases (for example "read this paper and build a factor"), run the phases sequentially from INGEST through EVALUATE.

## Workflow

### Phase 1: INGEST

Parse the source document and classify its content.

1. Call `read_document(paper_path)` to extract the full text from the PDF or report.
2. Classify the paper type:
   - **factor-research**: the paper proposes one or more cross-sectional factors with formulas (for example Jegadeesh and Titman 1993, Fama-French 1993)
   - **strategy**: the paper describes entry/exit rules, position sizing, and risk management (for example Avramov and Chordia 2006, turtle trading)
   - **mixed**: the paper contains both factor definitions and strategy rules
3. Extract key information from the parsed text:
   - Methodology description
   - Mathematical formulas (preserve LaTeX notation)
   - Variable definitions and data requirements
   - Universe and time period studied
   - Performance metrics reported in the paper

### Phase 2: EXTRACT

Turn the parsed content into structured artifact definitions.

1. **For factors**, extract:
   - `name`: short identifier (for example "momentum_12_1")
   - `formula_latex`: the mathematical formula as written in the paper
   - `variables`: list of input variables and their meanings
   - `columns_required`: OHLCV columns or fundamental fields needed
   - `universe`: target market (for example "equity_us", "equity_cn")
   - `decay_horizon`: recommended holding period in trading days

2. **For strategies**, extract:
   - `name`: short identifier
   - `entry_rules`: conditions that trigger a long or short position
   - `exit_rules`: conditions that close a position
   - `position_sizing`: how to allocate capital across selected instruments
   - `risk_management`: stop-loss, max drawdown, exposure limits
   - `universe`: target market
   - `columns_required`: data fields needed

3. **Deduplication check**: call `alpha_bench` or check `sdm_status(action="list")` to see if a similar artifact already exists. If the Pearson IC between the new factor and an existing alpha exceeds 0.99, treat it as a duplicate and stop. IC between 0.90 and 0.99 may be a variant worth keeping with a note.

4. **Register the artifact**: call `sdm_register(artifact_type, name, universe, ...)` to persist the extracted definition with status "extracted".

### OCR Quality Check

After ingesting a paper via `read_document`, check the `ocr_quality` field in the response:

- `quality_flag == "good"`: proceed with extraction
- `quality_flag == "degraded"`: warn user that some pages could not be OCR'd, suggest manual review
- `quality_flag == "no_ocr_engine"`: suggest installing an OCR engine — `pip install rapidocr_onnxruntime` for local, or set `VIBE_TRADING_OCR_ENGINE=llm-vision` to use a vision-capable LLM model (GPT-4o, Qwen-VL, etc.) via your existing provider config
- `text_density < 100`: flag as potentially low-quality extraction, suggest verifying formulas manually

### Phase 3: IMPLEMENT

Build the SignalEngine, run the backtest, and link results.

1. Call `create_hypothesis(title, thesis, universe, signal_definition)` to create a research hypothesis that tracks this work.
2. Call `generate_backtest_config(hypothesis_id, start_date, end_date)` to produce the `config.json` for the backtest runner. For an artifact registered with `sdm_register`, add its `artifact_id` to `config.json` so the backtest is recorded in the artifact's bench history. Add `"bench_type": "initial"` for the first evaluation run and `"periodic"` for scheduled re-benches; without it the run is recorded as `manual`, which decay monitoring ignores.
3. Call `scaffold_signal_engine(hypothesis_id, run_dir)` to generate the skeleton `signal_engine.py` in the run directory.
4. Implement the full `signal_engine.py` using the appropriate template from `templates/`:
   - Factor artifacts → `templates/factor_signal_engine.py`
   - Strategy artifacts → `templates/strategy_signal_engine.py`
5. Validate syntax: `bash("python -c \"import ast; ast.parse(open('code/signal_engine.py').read()); print('OK')\"")`
6. Call `backtest(run_dir)` to execute the backtest. When `config.json` declares an `artifact_id`, the result carries a `bench_record` that reports whether the run was `recorded`, `skipped` (failed run, no trades, missing metrics, or an identical row already stored) or `failed` (for example an unregistered `artifact_id`), with a `reason`.
7. Call `link_autopilot_backtest(hypothesis_id, run_dir)` to link the run results back to the hypothesis.
8. Call `sdm_status(action="detail", artifact_id=...)` and update the artifact status to "benching".

### Phase 4: EVALUATE

Judge the backtest output against quality thresholds.

1. **For factors**: call `factor_analysis` with the factor CSV and return CSV. Check:
   - IC mean > 0.03 (basic predictive power)
   - IR > 0.5 (stable effectiveness)
   - IC positive ratio > 55% (directional stability)

2. **For strategies**: read `artifacts/metrics.csv` and `run_card.json`. Check:
   - Sharpe ratio > 0.5 (minimum acceptable)
   - Max drawdown < 30% (risk tolerance)
   - Win rate and profit factor for additional context

3. **If the artifact is alive** (meets thresholds):
   - For factors: register into `factors/zoo/` and update status to "active"
   - For strategies: update status to "active" with the run metrics attached

4. **If the artifact is dead** (fails thresholds):
   - Update status to "disabled" with a reason string
   - Record what failed (for example "IC mean 0.012, below 0.03 threshold")

5. Check the bench record: the backtest itself writes the bench row when `config.json` declares the `artifact_id`. Confirm `bench_record.status` is `recorded` in the backtest result, or list the rows with `sdm_status(action="detail", artifact_id=...)`. If the run was not recorded, fix the config and re-run the backtest.

### Phase 5: MONITOR

Track artifact health over time and handle decay.

1. Call `sdm_decay_scan(universe=...)` for batch monitoring across all active artifacts in a universe.
2. Review decay signals per artifact:
   - **healthy**: all metrics above "Healthy" thresholds (see `references/decay_thresholds.md`)
   - **warning**: metrics have dropped into the "Warning" band
   - **decayed**: metrics are in the "Decayed" band
   - **critical**: metrics are in the "Critical" band
3. Auto-transitions follow the state machine:
   - `active` → `monitoring` when any metric enters "Warning"
   - `monitoring` → `decayed` when metrics stay in "Decayed" for 3+ consecutive scans
   - `decayed` → `disabled` when metrics enter "Critical"
   - `monitoring` → `active` when metrics recover to "Healthy" for 2+ consecutive scans
4. Recovery: a decayed artifact can be re-evaluated by re-running Phase 3 with updated parameters.
5. Generate a decay report summarizing all artifact statuses and recent transitions.

## Tool Reference

| Tool | Phase | Purpose |
|------|-------|---------|
| `read_document` | 1 | Parse PDF papers and reports |
| `sdm_register` | 2 | Register extracted factor or strategy |
| `sdm_status` | 2, 3, 4, 5 | Query or update artifact lifecycle status |
| `alpha_bench` | 2 | Deduplication check against existing alphas |
| `create_hypothesis` | 3 | Create a research hypothesis |
| `generate_backtest_config` | 3 | Generate backtest config.json |
| `scaffold_signal_engine` | 3 | Generate SignalEngine skeleton |
| `backtest` | 3 | Execute the backtest |
| `link_autopilot_backtest` | 3 | Link backtest results to hypothesis |
| `factor_analysis` | 4 | IC/IR analysis for factor artifacts |
| `sdm_decay_scan` | 5 | Batch decay monitoring |

## SignalEngine Contract

The generated `signal_engine.py` MUST satisfy the backtest runner contract:

```python
class SignalEngine:
    def __init__(self):
        """No-arg constructor. All parameters must have defaults."""
        ...

    def generate(self, data_map: dict[str, pd.DataFrame]) -> dict[str, pd.Series]:
        """
        Args:
            data_map: symbol -> DataFrame (columns: open, high, low, close, volume,
                      DatetimeIndex). May include extra fields from config.extra_fields
                      or config.fundamental_fields.
        Returns:
            symbol -> signal Series (float, clipped to [-1.0, 1.0])
            1.0 = fully long, 0.5 = half position, 0.0 = flat, -1.0 = fully short
        """
        ...
```

Hard constraints:
- Class MUST be named `SignalEngine`
- Constructor MUST take no arguments (all params have defaults)
- Signal Series index must align exactly with the input DataFrame index
- Include all required imports (numpy, pandas, typing)
- Do not hardcode dates or stock codes
- Do not include an `if __name__ == "__main__"` block
- Pure pandas/numpy implementation, no external signal libraries

## Quality Checklist

Self-check before marking any phase complete:

- [ ] Paper type correctly classified (factor-research / strategy / mixed)
- [ ] Factor formula matches the paper text (no LLM hallucination)
- [ ] Deduplication check passed (IC < 0.99 against existing alphas)
- [ ] SignalEngine passes AST validation
- [ ] Backtest completed without errors
- [ ] IC/IR or Sharpe meets minimum thresholds
- [ ] Artifact registered in the strategy store with correct status

## Common Pitfalls

### Formula Hallucination
LLMs may generate plausible-looking formulas that do not appear in the paper. ALWAYS cross-check the extracted formula against the original document text. If the paper uses notation you cannot parse, ask the user to confirm.

### Factor Deduplication
IC > 0.99 means the factor is a duplicate. IC between 0.90 and 0.99 may be a variant. Use judgment: if the formula is structurally different but produces similar signals, note it as a variant rather than rejecting it outright.

### Decay Baseline
Decay monitoring requires at least 3 `initial` or `periodic` bench history entries to establish a baseline; `manual` entries are kept for reference and do not count. A newly registered artifact with only one backtest cannot be meaningfully scanned for decay.

### Template Mismatch
Strategy-type artifacts need the strategy SignalEngine template (with entry/exit/position logic), not the factor template. Using the wrong template produces a SignalEngine that compiles but generates meaningless signals.

### Look-Ahead Bias
Factor values must use data from day T and earlier. Returns must use data from T+1 onward. The `delta(df, d)` operator enforces `d >= 1` to prevent lookahead. Never use `Ref(df, -n)` style negative shifts.

## Templates

Two SignalEngine templates are provided in `templates/`:

- `factor_signal_engine.py`: for factor-type artifacts. Computes a cross-sectional factor value per instrument per date, then ranks and clips to [-1.0, 1.0].
- `strategy_signal_engine.py`: for strategy-type artifacts. Implements entry/exit rules with position sizing and risk management.

## References

- Decay thresholds and state machine: `references/decay_thresholds.md`
- Example workflows: `examples.md`
- Base operators for factor computation: `src/factors/base.py` (rank, zscore, scale, ts_mean, ts_std, ts_rank, ts_corr, ts_cov, ts_max, ts_min, ts_argmax, ts_argmin, delta, decay_linear, signed_power, safe_div, vwap)
