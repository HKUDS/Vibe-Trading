# Factor-research run contract

The factor bench entry points attach an additive `meta.research` object to
their existing result envelope. The contract is versioned as
`factor-research.run/v1` and is defined by
`src.factors.research_contract.build_research_contract`.

```json
{
  "schema": "factor-research.run/v1",
  "mode": "explore",
  "stage": "single_factor_evaluation",
  "universe": "csi300",
  "period": "2020-2025",
  "factor_ids": ["alpha101_001"],
  "factor_count": 1,
  "lineage": [
    {"kind": "alpha_registry", "zoo": "alpha101"}
  ],
  "transformations": [],
  "evaluation": {
    "horizon": 1,
    "forward_return_sampling": "daily",
    "method": "rank_ic"
  },
  "locked_test": {}
}
```

## Modes and stages

`mode` records the intended evidence standard:

- `explore`: exploratory research; warnings and incomplete provenance may be
  acceptable while developing a signal.
- `strict`: a research result intended for stronger data and statistical
  review.
- `locked`: a result intended for a locked evaluation set.

In v1 these values are declarations only. They do not change IC calculations,
factor weights, or backtest behavior. CLI, agent tools and MCP expose both mode
and stage. The strict runner and `alpha bench --strict` default to `strict`;
the ordinary runner defaults to `explore`. An explicit `--research-mode`
overrides that label. A later policy layer can enforce modes without changing
the result schema; `locked` currently declares intent, never certification.

`stage` identifies where the result sits in the factor lifecycle:
`factor_screening`, `single_factor_evaluation`, `neutralization`,
`combination`, `composite_evaluation`, `backtest`, or `monitoring`.

## Lineage and transformations

Both `lineage` and `transformations` accept either a short string or a JSON
object. Use an object when a future stage needs to record artifact IDs,
parameter hashes, controls, weights, or diagnostic paths. Keep large panels and
raw data outside the contract; reference them by stable artifact path or hash.

The contract is additive. Existing consumers can ignore `meta.research`, while
new consumers can use `schema` to opt into the structured fields.
