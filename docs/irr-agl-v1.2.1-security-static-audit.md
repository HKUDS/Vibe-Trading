# IRR-AGL v1.2.1 Phase 10.1 Security Static Audit

This audit records the required static searches from the post-416/420 security gate. Searches were run locally on `phase/121-10a-post416-420-security-compat` with `--untracked` where needed so the new Phase 10.1 tests were included.

## Search Summary

| command | finding count | suspicious findings | classification | action taken | tests proving behavior |
|---|---:|---|---|---|---|
| `git grep -n --untracked "self\\.inner\\|\\.inner\\|_inner" -- agent/src agent/cli frontend/src` | 34 | `agent/src/governance/runtime.py` uses `_inner`; frontend `innerHTML` appears only in tests | SAFE_PRIVATE_ONLY | Public `.inner` removed; `_inner` private | `test_public_inner_attribute_is_not_available`, `test_proxy_does_not_expose_raw_tool_private_members` |
| `git grep -n --untracked "ToolRegistry(" -- agent/src agent/cli agent/tests` | 31 | `agent/src/api/live_routes.py` constructs a local pseudo-tool registry before wrapping it; tests construct registries | SAFE_INTENDED | Live write pseudo-tool is immediately wrapped by `GovernedToolRegistry` | `test_live_submit_goes_through_governed_pseudotool`, `test_api_server_remote_tool_route_uses_governed_registry` |
| `git grep -n --untracked "\\.get(.*\\.execute\\|get(.*execute" -- agent/src agent/tests` | 0 | None | SAFE_INTENDED | No raw `get().execute()` call sites found | `test_get_execute_routes_through_governance_for_r5_shell` |
| `git grep -n --untracked "RuntimeContext\\|live_state\\|user_auth_state\\|budget_state\\|state_authoritative\\|GovernanceStateProvider" -- agent/src agent/tests` | 77 | `RuntimeContext` still accepts dict fields for compatibility; P40 gates ignore forged dicts | SAFE_INTENDED | Added authoritative provider gate for R4 writes | `pytest agent/tests/governance/test_state_provider_p40_security.py -v` |
| `git grep -n --untracked "adapter.call_tool\\|submit\\|cancel\\|LIVE_CONNECTOR" -- agent/src agent/tests` | 559 | Direct live reads in `live_routes.py`; submit/cancel in runtime flatten paths | SAFE_INTENDED / PATCHED_WITH_TEST | Submit/cancel through route runner now use governed pseudo-tool; read-only account/positions/orders remain direct | `pytest agent/tests/governance/test_live_connector_route_governance.py -v` |
| `git grep -n --untracked "eval(\\|exec(\\|compile(\\|importlib\\|getattr(.*predicate\\|yaml.load" -- agent/src agent/tests` | 198 | Most `compile(` hits are `re.compile`; `importlib` used for module/plugin discovery; generated-code tests use explicit exec | SAFE_INTENDED / TEST_ONLY_ACCEPTABLE | Scorecard policy path checked for no eval/exec/compile/importlib | `test_no_eval_exec_compile_in_scorecard_policy_path`, `test_malicious_scorecard_yaml_cannot_execute_code` |
| `git grep -n --untracked "subprocess\\|shell=True\\|os.environ\\|environ.copy\\|Popen" -- agent/src agent/tests` | 150 | Shell-capable tools and MCP subprocess helpers exist | SAFE_INTENDED | R5 shell denied by governed surfaces; generated backtest subprocess env allowlist verified | `test_subprocess_env_excludes_llm_api_broker_live_secrets`, `test_backtest_subprocess_env_builder_uses_allowlist` |
| `git grep -n --untracked "Path(\\|resolve()\\|relative_to\\|artifact_root\\|\\.\\.\\|%2e%2e" -- agent/src agent/tests` | 1230 | Many ordinary path operations; artifact traversal tests include `%2e%2e` and dot-dot payloads | SAFE_INTENDED / PATCHED_WITH_TEST | Research-card artifact and runs API path traversal hardened | `pytest agent/tests/research_card/test_research_card_api_security.py -v` |
| `git grep -n --untracked "dangerouslySetInnerHTML\\|innerHTML\\|outerHTML\\|javascript:" -- frontend/src` | 10 | `innerHTML` checks in tests, including sentinel absence | TEST_ONLY_ACCEPTABLE | No `dangerouslySetInnerHTML` added | `npx vitest run src/components/research/__tests__/ResearchPanels.security.test.tsx --reporter=verbose` |
| `git grep -n --untracked "skip\\|xfail\\|TODO\\|FIXME\\|not implemented\\|pass$" -- agent/tests frontend/src` | 199 | Existing skips/TODOs in unrelated tests; new concurrency tests contain intentional `pass` in connection close probes | SAFE_INTENDED / TEST_ONLY_ACCEPTABLE | No unjustified skip/xfail added for Phase 10.1 | Targeted and global test suites passed |

## Suspicious Finding Triage

| finding | classification | reason | action |
|---|---|---|---|
| `agent/src/governance/runtime.py` private `_inner` access | SAFE_PRIVATE_ONLY | Required private implementation detail for wrapping existing `ToolRegistry` without changing public API | Public `.inner` remains absent and tested |
| `agent/src/api/live_routes.py` direct `adapter.call_tool` for account/positions/orders | SAFE_INTENDED | Read-only broker reads do not mutate broker state | Documented by `test_live_readonly_account_positions_orders_do_not_get_write_manifest` |
| `agent/src/api/live_routes.py` submit/cancel path | VULNERABLE_PATCHED | Would be P0 if adapter was called before governance | Patched through `_LiveConnectorWriteTool` and P40 provider gate |
| `agent/src/reliability/data/circuit_breaker.py` SQLite update path | VULNERABLE_PATCHED | Prior pattern risked lost updates and connection leaks | Atomic concurrency and close-on-error tests added |
| Research-card artifact path handling | VULNERABLE_PATCHED | Prior traversal could return unsafe status or leak paths | Safe 404/no-leak tests added |
| Frontend research panel export path | VULNERABLE_PATCHED | Redacted display with raw export would leak secrets | Payload redaction now shared by display/export helpers |
| `agent/src/tools/bash_tool.py` and `background_tools.py` shell usage | SAFE_INTENDED | Existing R5 tools are allowed only through governed policy surfaces | Surface tests prove R5 denial and execution counter zero |
| `agent/tests/*` `pytest.skip` and `importorskip` | TEST_ONLY_ACCEPTABLE | Existing dependency/platform guards outside this security gate | No Phase 10.1 release blocker |

## Static Quality

- `git diff --check`: passed with line-ending warnings only.
- `ruff check` on Phase 10.1 touched Python files: passed after removing three unused imports.
- `ruff check agent/src agent/tests`: failed with 281 pre-existing repo-wide style findings. The failures are broad legacy lint debt in channels, factor zoo, and older tests, not a Phase 10.1 security behavior blocker. The full command output was recorded in the final acceptance update.

