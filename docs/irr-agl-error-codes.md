# IRR-AGL Error Codes

IRR-AGL warnings and hard failures are structured codes. Free-text messages may
explain the condition, but code fields are the stable API for tests, UI, cards,
and audit review.

## Governance

| Code or rule | Severity | Meaning |
| --- | --- | --- |
| `P10` | deny | UNKNOWN live connector fails closed. |
| `P20` | deny | Remote/channel/MCP HTTP/SSE shell denial. |
| `P30` | deny | Scheduler live-write or shell denial. |
| `P35` | deny | Swarm prompt-injected external MCP URL denial. |
| `P40` | allow/deny | Live write requires mandate, kill switch clear, consent, order guard, and connector profile. |
| `P50` | deny | Explicit local market data fallback to network. |
| `P900` | warn/deny | Unclassified tool review gate. |
| `P999` | deny | No matching policy rule. |
| `policy_exception` | warn/deny | Policy exception handled fail-safe. |

## Data and PIT

| Code | Severity | Meaning |
| --- | --- | --- |
| `DATA_NON_DATAFRAME_RESULT` | warning | Loader returned a non-DataFrame value. |
| `DATA_VALIDATOR_SAMPLED` | info | Data audit used bounded sampling. |
| `DATA_ALL_SOURCES_OPEN` | hard_failure | Every fallback source was circuit-open. |
| `PIT_FUTURE_DATA` | hard_failure | Data was not available as of the decision time. |

## Quant

| Code | Severity | Meaning |
| --- | --- | --- |
| `QUANT_SCORECARD_DIMENSION_DEFAULTED` | warning | Missing score dimensions defaulted to zero. |
| `QUANT_COST_MODEL_MISSING` | warning | Cost model evidence is missing. |
| `QUANT_OOS_MISSING` | warning | OOS or walk-forward evidence is missing. |
| `QUANT_BENCHMARK_MISSING` | warning | Benchmark evidence is missing. |
| `QUANT_TRIAL_COUNT_MISSING` | warning | Trial count evidence is missing. |
| `QUANT_RANDOM_CONTROL_MISSING` | warning | Strict random-control evidence is missing. |
| `QUANT_NO_COST_MODEL_TRADABLE_CLAIM` | hard_failure | Tradability claim without cost model. |
| `QUANT_NO_BENCHMARK_ALPHA_CLAIM` | hard_failure | Alpha claim without benchmark. |
| `QUANT_NO_OOS_GENERALIZATION_CLAIM` | hard_failure | Generalization claim without OOS. |
| `QUANT_HISTORICAL_UNIVERSE_MISSING` | hard_failure | Historical universe membership is missing. |
| `QUANT_EXECUTION_TIMESTAMPS_MISSING` | warning/hard_failure | Required execution timestamps are missing. |
| `QUANT_TRIAL_COUNT_MISSING_BEST_TRIAL` | hard_failure | Best trial presented without trial count. |
| `QUANT_ASHARE_MARKET_RULES_MISSING` | hard_failure | A-share critical market rules are missing. |
| `POLICY_DENY_IGNORED` | hard_failure | Policy deny was ignored. |
| `QUANT_SCORECARD_LLM_OVERRIDE_ATTEMPT` | hard_failure | LLM attempted to override scorecard or conclusion gate. |
| `QUANT_HIGH_CROWDING_NO_STRESS_TEST` | hard_failure | High crowding lacks stress testing. |
| `QUANT_REGIME_NEGATIVE_IC_NO_ACTIVATION` | hard_failure | Negative regime IC lacks activation logic. |
| `QUANT_IS_IC_NEAR_ZERO` | hard_failure | IS IC denominator is too close to zero for safe ratio. |

## Research Card

| Code | Severity | Meaning |
| --- | --- | --- |
| `RESEARCH_CARD_SCORECARD_MISSING` | warning | Card has no scorecard. |
| `RESEARCH_CARD_ARTIFACT_MISSING` | warning | Referenced artifact was unavailable. |
| `RESEARCH_CARD_ALPHA_CLAIM_WITHOUT_BENCHMARK` | warning | Alpha claim lacks benchmark evidence. |

## Experimental Metrics

`dsr` and `pbo` may appear under `experimental_metrics`. They are not error
codes and must not be used as production gate codes.
