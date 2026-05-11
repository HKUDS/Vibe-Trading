# CONTINUITY — Working Memory

## Active Goal
Add Vietnam Stock Market support (HOSE/HNX/UPCoM + VN30F) to Vibe-Trading as a first-class market line, per OpenSpec proposal `add-vn-market-support`.

## Current Phase
sprint-2.2 complete (5 VN broker journal parsers merged on `feat/vn-market-support`)

## Working Tree
- Branch: `feat/vn-market-support`
- Worktree path: `/Volumes/Data/Stock/Vibe-Trading-vn`
- Main checkout: `/Volumes/Data/Stock/Vibe-Trading` (untouched)
- 6 commits ahead of `main`

## Sprint 1 — Done (overnight autonomous run, 2026-05-10)

| Task | Status | Files |
|------|--------|-------|
| Add `vnstock>=4.0` to `pyproject.toml` | done | `pyproject.toml` |
| `VNStockLoader` (multi-source internal: VCI→TCBS→MSN) | done | `agent/backtest/loaders/vnstock_loader.py` (178 LOC) |
| Registry: `vn_equity`/`vn_index`/`vn_futures` chains | done | `agent/backtest/loaders/registry.py` |
| `VNEquityEngine` (T+2, biên độ HOSE/HNX/UPCoM, lô 100, thuế 0.1%) | done | `agent/backtest/engines/vn_equity.py` (165 LOC) |
| `CompositeEngine` routes `.HOSE/.HNX/.UPCOM` → vn_equity | done | `agent/backtest/engines/composite.py` |
| 3 VN skills (data-routing, foreign-room, financial-statements-vas) | done | `agent/src/skills/vn-*/SKILL.md` |
| Tests: engine 32 / loader 28 / skills 14 = **74 new tests** | done | `agent/tests/test_vn_*.py` |
| Full regression suite | done | 913 pass, 0 fail (44s) |

## Sprint 2 status

### Sprint 2.1 — VNFuturesEngine (DONE 2026-05-10)

| Phase | Commit | Outcome |
|-------|--------|---------|
| 1. `_after_bar_close` hook on BaseEngine | `c743bc4` | 913 tests still pass — hook lives in `_execute_bars` (not `run_backtest` directly) at `base.py:466-469` |
| 2a. VNFuturesEngine + composite routing | `76f0140` | 250 LOC, all smoke values correct |
| 2b. vnstock_loader VN30F detection | `b66bbce` | +30/-8 LOC, 28 existing loader tests still pass |
| 3. Comprehensive tests | `b022552` | 86 new tests across 14 groups, all green first run |

**Final state:** 999 tests pass (913 baseline + 86 new), 0 fail. Engine ≤ 250 LOC. No regressions.

**Codebase deviations discovered during execution (preserved in code):**
1. `BaseEngine` exposes `self.capital` (not `self.cash`) — used `self.capital` for MTM
2. `_after_bar_close(bar)` receives a Series of close prices keyed by symbol with `bar.name` = timestamp (NOT a single OHLCV bar). Engine indexes via `bar[symbol]`.
3. On expiry, MTM realizes P&L to close THEN engine releases margin via `_calc_margin(...)` to avoid double-counting
4. Margin-call gate restricts to `direction == 0` (close-only); opens are blocked once `_pending_liquidation` is set

**Symbol routing precedence (verified):** `VN30F1M.HNX` → vn_futures (NOT vn_equity), `SHB.HNX` → vn_equity (unchanged)

### Sprint 2.2 — VN Broker Journal Readers (DONE 2026-05-10)

| Phase | Commit | Outcome |
|-------|--------|---------|
| 1. Registry foundation (`journal_parsers_vn/`) | `b913ea0` | sub-package + auto-registry + 5 stubs + `_common.py` helpers; 999 tests still pass |
| 2-SSI | `55b0628` | parser + 7-row fixture + 11 tests |
| 2-HSC | `87c5e80` | parser + 6-row fixture + 13 tests |
| 2-VNDirect | `da2e8d3` | parser + 7-row fixture + 13 tests (DGC routes to .HNX) |
| 2-TCBS | `48b7099` | parser + 7-row fixture + 13 tests |
| 2-DNSE | `5ca7d35` | parser + 7-row fixture + 13 tests (no Tax column) |
| 3. SSI EN false-positive fix + skill doc | `aef7c81` | SSI EN match now requires `Match Volume` AND rejects HSC's `Quantity` |

**Final state:** 1062 tests pass (999 baseline + 63 new), 0 fail. 5 brokers cross-detected with no false positives.

**Architecture:** Sub-package `agent/src/tools/journal_parsers_vn/` with `BrokerParser` Protocol + lazy auto-registry mirrors `backtest.loaders.registry`. Each broker is a 50-80 LOC module; `_common.py` provides `_qualify_vn_symbol` (HOSE/HNX/UPCoM), `_normalize_vn_side` (Mua/Bán/BUY/SELL), `_parse_vn_date`, `_to_float_vn` (handles VN `1.234,5` + US `1,234.5`).

**Integration with existing parser dispatch:** `trade_journal_parsers.py::detect_format()` falls back to `detect_vn_format()` after existing 4 parsers; `parse_file()` dispatches VN formats via `parse_vn()`. Zero impact on existing Tonghuashun/Eastmoney/Futu/Generic flow.

**Execution note:** 4/5 Phase-2 sub-agents hit rate limit mid-run. SSI agent committed successfully (commit `55b0628`); HSC + VNDirect agents wrote files but didn't commit (recovered via main thread); TCBS + DNSE were written entirely in main thread. Net throughput delivered same result with mixed parallel/sequential execution.

### Sprint 2.3 — NOT YET PLANNED
- 3 swarm presets (`vn_investment_committee`, `vn_derivatives_desk`, `vn_value_screener`)
- i18n locale `vi-VN`
- `VNFundamentalProvider` (VAS PIT — `vn-financial-statements-vas` skill is currently just a manifest stub)

## Sprint 3 — NOT STARTED
- Amibroker AFL exporter
- 5 advanced skills (ex-rights-calendar, margin-list, vn30-arbitrage, sector-rotation-vn, pre-warning-stocks)
- UBCK compliance disclaimer pass

## Key Decisions Made During Sprint 1

1. **vnstock single Python lib over MCP servers.** User suggested 3 MCP repos (`vnstock-agent-guide`, `vnstock-mcp-server`, `vn-stock-api-mcp`). For Sprint 1 we used the official `vnstock` PyPI lib directly — adds 1 pip dep vs an MCP server with deployment complexity. MCP integration deferred to optional future enhancement.
2. **Conservative ticker routing.** Bare 3-letter tickers (`VNM`) STILL route to `a_share` for backwards compat. Only explicit `.HOSE/.HNX/.UPCOM` suffix routes to `vn_equity`. Documented in `composite.py`.
3. **Lazy `import vnstock`.** Loader registers even when `vnstock` package is not installed (verified by tests). Avoids breaking the loader chain on missing optional deps.
4. **Multi-source inside loader, not registry.** vnstock's VCI/TCBS/MSN sources are an *internal* fallback within `VNStockLoader.fetch()`, not separate loaders in the registry. Cleaner API surface.
5. **Single-loader chain.** `FALLBACK_CHAINS["vn_equity"] = ["vnstock"]` — only one outer loader. Adding `akshare` as VN fallback was considered but rejected (akshare's VN coverage is poor/unreliable).
6. **Position model uses `direction: int` not `side: str`.** Discovered during test authoring; fixtures aligned to existing model.

## Known Issues / Tech Debt

- **Proposal/design `.md` files reference outdated paths.** Original proposal said `agent/src/providers/data/vn_stock_provider.py` but actual codebase uses loader pattern at `agent/backtest/loaders/`. Code is correct; docs need updating before final archive of OpenSpec change.
- **No live network test.** All tests are mock-based. Recommend `pytest -m integration` smoke test against real vnstock VCI source before public release. Fixture: `VNM` over a known historical window.
- **Existing `test_registry.py::test_all_expected_markets_present` was updated** to include 3 new markets.

## Next Actions (when human returns)

1. **Review the 6 commits** on `feat/vn-market-support`: `git log --oneline main..HEAD`
2. **Update OpenSpec docs** to reflect actual loader pattern (proposal.md and design.md)
3. **Run integration smoke** with `vnstock` installed: `uv pip install vnstock && pytest -m integration`
4. **Decide:** push to remote + open PR? (NOT auto-pushed per safety rules)
5. **Sprint 2 kickoff:** VNFuturesEngine first (highest user value), then journal readers, then swarm presets

## Open Questions (unanswered, parked)

1. Default broker fee fallback when broker not specified? (currently 0.15% in engine config)
2. DNSE LightSpeed auth model — OAuth or API key? (deferred to Sprint 2)
3. Should vnstock be a hard dep or `[project.optional-dependencies] vn = ["vnstock>=4.0"]`? (currently hard dep — reconsider before final release)
