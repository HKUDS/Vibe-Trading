# Rollback Plan

## Scope

Rollback is additive-only. No live/order/broker/mandate/kill-switch runtime
files are required for rollback.

## Steps

1. Revert the latest AGS hardening commit.
2. If needed, revert the prior AGS acceptance commit.
3. Remove AGS docs only if release packaging must be fully backed out.
4. Re-run:
   - `git diff --check`
   - `python -m compileall -q agent/src agent/cli`
   - `pytest agent/tests/factors/test_alpha_purity.py agent/tests/factors/test_lookahead.py -q`
   - `npm.cmd run test:run`
5. Confirm no changed files remain under live/order/broker/mandate/kill-switch
   surfaces.

## Expected Impact

Rollback removes research-only AGS report/CLI/test hardening and evidence docs.
Existing bench, factor zoo, API runtime, connector registry, AgentLoop,
ToolRegistry, broker, mandate, and kill-switch behavior remain outside the
change scope.
