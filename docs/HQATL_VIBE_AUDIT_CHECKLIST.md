# HQATL Vibe Audit Checklist

Use this checklist in Phase 1. Nothing below is audited by this foundation task.

## Repository and runtime

- [ ] Map applications, services, packages, entry points, configuration, and deployment assets.
- [ ] Record supported runtimes, dependency locks, and development/test commands.
- [ ] Identify generated, vendored, legacy, and inactive paths.

## Capability verification

- [ ] Inventory user-visible and backend capabilities.
- [ ] Trace every claimed capability to executable code or classify it `PROMPT ONLY`.
- [ ] Identify duplicated frontend/backend calculations.
- [ ] Map current Elliott, indicator, data, chart, backtest, and confidence behavior.
- [ ] Record primary/alternate count handling and invalidation behavior.
- [ ] Record completed-bar versus provisional behavior.

## Data and providers

- [ ] Map data sources, schemas, instruments, timestamps, timeframes, sessions, and caching.
- [ ] Identify provider-specific logic inside analytical or strategy code.
- [ ] Audit missing, stale, duplicate, adjusted, and out-of-order data handling.
- [ ] Confirm that no credentials are tracked.

## Validation quality

- [ ] Inventory unit, integration, regression, backtest, and end-to-end tests.
- [ ] Check for look-ahead, survivorship, selection, and optimization bias.
- [ ] Verify analytical and backtesting calculations share implementations.
- [ ] Identify untested analytical calculations and undocumented parameters.

## Safety and preservation

- [ ] Baseline existing Vibe behavior that must be preserved.
- [ ] Locate order-capable code and confirm defaults and approval boundaries.
- [ ] Review logs, prompts, screenshots, fixtures, and docs for secrets/private data.
- [ ] Record dependencies, licenses, vulnerabilities, and supply-chain risks.

## Audit output

- [ ] Update the master requirements with evidence-backed statuses.
- [ ] Produce an architecture/data-flow map and executable gap list.
- [ ] Separate findings from recommendations.
- [ ] Stop for human review without implementing fixes.
