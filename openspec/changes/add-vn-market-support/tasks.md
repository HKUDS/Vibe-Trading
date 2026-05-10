# Implementation Checklist — add-vn-market-support

> Order strictly by dependency. Each task = 15-60 min. Verify before next.

## Sprint 1 — Core Equity (2 weeks)

### 1. Provider Foundation
- [ ] 1.1 Add `vnstock>=3.0` to `pyproject.toml`, update lock
- [ ] 1.2 Define common `DataProvider` interface contract test (if not exists)
- [ ] 1.3 Implement `VNStockProvider` skeleton with `is_available`, `get_bars`, `get_symbol_meta`
- [ ] 1.4 Sub-provider `VNStockLib` (vnstock wrapper) — happy path
- [ ] 1.5 Sub-provider `TCBSPublic` (HTTP client, public endpoints)
- [ ] 1.6 Sub-provider `SSIIBoard` (HTTP client)
- [ ] 1.7 Sub-provider `DNSELightSpeed` (gated by creds, optional)
- [ ] 1.8 Fallback chain logic + 3s health-check timeout
- [ ] 1.9 Symbol normalizer (`VNM` ↔ `VNM.HOSE` ↔ `HOSE:VNM`)
- [ ] 1.10 Unit test: mock 4 sub-providers, assert fallback order

### 2. Equity Engine
- [ ] 2.1 Scaffold `VNEquityEngine(Engine)` with config dataclass
- [ ] 2.2 Implement T+2 settlement (cash availability ledger)
- [ ] 2.3 Biên độ truncation per exchange (HOSE/HNX/UPCOM lookup)
- [ ] 2.4 Lô 100 rounding on order placement
- [ ] 2.5 Commission + tax 0.1% on sell side
- [ ] 2.6 ATO/ATC pre-market order support
- [ ] 2.7 Property tests: T+2 invariant, biên độ never exceeded
- [ ] 2.8 Snapshot test: backtest VNM 1y MA20/50, compare metrics with hand-computed reference

### 3. Foundational Skills (3)
- [ ] 3.1 `vn-data-routing` skill manifest + prompt + test
- [ ] 3.2 `vn-foreign-room` skill (fetch from vnstock/TCBS, alert at >95% full)
- [ ] 3.3 `vn-financial-statements-vas` skill (fetch + VAS↔IFRS label mapping JSON)
- [ ] 3.4 Register 3 skills in registry, verify hot-load via `/skills`

### 4. Sprint 1 Verification
- [ ] 4.1 End-to-end: `vibe-trading run -p "Backtest VNM 1y MA20/50"` succeeds
- [ ] 4.2 Report renders (English fallback OK for now)
- [ ] 4.3 Internal alpha share with 3-5 retail traders
- [ ] 4.4 Tag `v0.2.0-alpha-vn-equity`

---

## Sprint 2 — Derivatives + Journal + Swarm + i18n (3 weeks)

### 5. Futures Engine
- [ ] 5.1 Scaffold `VNFuturesEngine` with VN30F contract metadata (F1M/F2M/F1Q/F2Q)
- [ ] 5.2 Margin model (initial 17%, maintenance, daily mark-to-market)
- [ ] 5.3 Margin call simulator (forced liquidation logic)
- [ ] 5.4 Cash settlement at expiry (use VN30 close)
- [ ] 5.5 Snapshot test: VN30F1M 6-month backtest vs DNSE reference
- [ ] 5.6 Composite test: VN equity portfolio + VN30F hedge

### 6. Fundamental Provider
- [ ] 6.1 `VNFundamentalProvider` PIT contract impl
- [ ] 6.2 VAS account code mapping JSON (~50 key fields)
- [ ] 6.3 Test: fetch FPT Q4 2024 statements, validate against published filings

### 7. Trade Journal Readers (5)
- [ ] 7.1 `ssi_journal.py` — CSV + XLSX, anonymized fixture
- [ ] 7.2 `hsc_journal.py` — CSV, fixture
- [ ] 7.3 `vndirect_journal.py` — XLSX, fixture
- [ ] 7.4 `tcbs_journal.py` — CSV, fixture
- [ ] 7.5 `dnse_journal.py` — CSV, fixture
- [ ] 7.6 Each reader: 1 regression test asserting profile metrics
- [ ] 7.7 Update `analyze_trade_journal` MCP tool to accept all 5 formats

### 8. Swarm Presets (3)
- [ ] 8.1 `vn_investment_committee.yaml` — DAG with bull/bear parallel + risk-review
- [ ] 8.2 `vn_derivatives_desk.yaml` — VN30 spot/F1M basis arb
- [ ] 8.3 `vn_value_screener.yaml` — VAS fundamental → quality → TA timing
- [ ] 8.4 Bundle in `src.swarm`, verify discoverability after fresh `pip install`
- [ ] 8.5 Smoke run each with `vars_json` example

### 9. i18n vi-VN
- [ ] 9.1 `agent/locales/vi-VN.json` — finance terminology dict
- [ ] 9.2 Number formatter `vi-VN` (1.000.000,50)
- [ ] 9.3 Report template — locale-switchable header/footer
- [ ] 9.4 Snapshot test report HTML in vi-VN, validate Vietnamese diacritics

### 10. Sprint 2 Verification
- [ ] 10.1 End-to-end: VN30F1M backtest + journal SSI import + swarm `vn_investment_committee`
- [ ] 10.2 Internal beta with 10 traders
- [ ] 10.3 Tag `v0.2.0-beta-vn-full`

---

## Sprint 3 — Export + Advanced Skills + Compliance (2-3 weeks)

### 11. Amibroker AFL Exporter
- [ ] 11.1 Strategy AST → AFL transformer
- [ ] 11.2 AFL syntax validator (offline lib or regex-based for v1)
- [ ] 11.3 Wire into `/pine <run_id>` — emit `strategy.afl` alongside `.pine`/.tdx`/`.mq5`
- [ ] 11.4 Test: 5 sample strategies → AFL → manual import into Amibroker

### 12. Advanced Skills (5)
- [ ] 12.1 `vn-ex-rights-calendar` (GDKHQ + dividend dates)
- [ ] 12.2 `vn-margin-list` (UBCK margin list + per-broker tiers)
- [ ] 12.3 `vn-vn30-arbitrage` (basis monitoring, signal generation)
- [ ] 12.4 `vn-sector-rotation-vn` (ICB phân ngành VN)
- [ ] 12.5 `vn-pre-warning-stocks` (cảnh báo/kiểm soát/hạn chế lookup)
- [ ] 12.6 Each skill: 1 regression test

### 13. Compliance & Disclaimers
- [ ] 13.1 UBCK disclaimer text (legal review if available)
- [ ] 13.2 Inject disclaimer header + footer in all VN reports
- [ ] 13.3 CLI banner when first VN run: "Output is research, not investment advice"
- [ ] 13.4 README.md update — VN section + supported brokers + disclaimer
- [ ] 13.5 Audit pass: every VN code path has disclaimer surface

### 14. Documentation
- [ ] 14.1 `docs/vn-market.md` — quick start
- [ ] 14.2 `docs/vn-skills.md` — 8 skill reference
- [ ] 14.3 `docs/vn-broker-journals.md` — how to export from each broker
- [ ] 14.4 Update `openspec/specs/data-sources/spec.md` with VN provider requirements (post-merge archive)
- [ ] 14.5 Update `openspec/specs/backtest/spec.md` with VN engine requirements

### 15. Sprint 3 Verification & Release
- [ ] 15.1 Full regression suite green
- [ ] 15.2 PyPI release `v0.2.0` with VN module
- [ ] 15.3 ClawHub + Docker image rebuild
- [ ] 15.4 README News entry: VN market support
- [ ] 15.5 GitHub Release notes
- [ ] 15.6 Archive `openspec/changes/add-vn-market-support/` per OpenSpec workflow
