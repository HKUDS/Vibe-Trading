# CONTINUITY — Working Memory

## Active Goal
Add Vietnam Stock Market support (HOSE/HNX/UPCoM + VN30F) to Vibe-Trading as a first-class market line, per OpenSpec proposal `add-vn-market-support`.

## Current Phase
sprint-1 complete (foundation merged on `feat/vn-market-support`, awaiting human review)

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

## Sprint 2 — NOT STARTED (human kickoff needed)
- VNFuturesEngine (VN30F1M/F2M/F1Q/F2Q with daily mark-to-market, margin model)
- 5 broker journal readers (SSI, HSC, VNDirect, TCBS, DNSE)
- 3 swarm presets (vn_investment_committee, vn_derivatives_desk, vn_value_screener)
- i18n locale `vi-VN`
- VNFundamentalProvider (VAS PIT) — currently the `vn-financial-statements-vas` skill is just a manifest stub

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
