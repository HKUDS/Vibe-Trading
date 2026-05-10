# Design: Vietnam Market Support

## Context & Technical Approach

Vietnam market khác biệt với A-shares ở 6 trục kỹ thuật cốt lõi mà code hiện tại hardcode A-share assumptions:

1. **Settlement:** T+2 (HOSE/HNX/UPCoM từ 2024) vs T+1 (A-shares)
2. **Biên độ:** ±7% HOSE / ±10% HNX / ±15% UPCoM (động theo sàn) vs ±10%/±5% ST cố định
3. **Lô giao dịch:** 100 (HOSE), 100 (HNX) vs 100 nhưng ticker format khác
4. **Thuế/phí:** Bán 0.1% giá trị giao dịch + phí broker (0.15-0.35%) vs thuế stamp duty 0.05% TQ
5. **Phái sinh:** VN30F ký quỹ 17% (HSC), daily mark-to-market, cash settlement vs CFFEX margin model
6. **Báo cáo tài chính:** VAS (Vietnamese Accounting Standards) vs Trung Quốc CAS

Giải pháp: KHÔNG override A-share engine. Tạo 2 engine VN độc lập kế thừa `Engine` interface, dùng config-driven cho biên độ/thuế/lô để tương lai dễ thêm Lào/Cambodia.

### Data flow (Sprint 1)

```
User prompt "Backtest VNM 1 năm"
    ↓
agent harness → data-routing skill
    ↓
detect ticker format `VNM` (no exchange suffix, 3 chars uppercase)
    ↓
VNStockProvider.get_bars("VNM", "1y")
    ├─ try vnstock (free, primary)
    ├─ fallback TCBS public API
    ├─ fallback SSI iBoard
    └─ fallback DNSE LightSpeed (if creds)
    ↓
VNEquityEngine.run(bars, strategy)
    ├─ apply T+2 settlement
    ├─ apply biên độ động (lookup exchange of VNM → HOSE → ±7%)
    ├─ apply lô 100 rounding
    ├─ apply commission (config: ssi=0.15%, default=0.25%)
    ├─ apply tax 0.1% on sell
    └─ produce trades + equity curve
    ↓
report renderer (locale=vi-VN)
    ├─ format số 1.000.000,50
    ├─ thuật ngữ VN: "Sharpe", "Sụt giảm tối đa", "Tỷ lệ thắng"
    └─ disclaimer UBCK
```

## Proposed Changes

### `agent/src/providers/data/vn_stock_provider.py` (NEW)
- Class `VNStockProvider(DataProvider)`
- Sub-providers: `VNStockLib`, `TCBSPublic`, `SSIIBoard`, `DNSELightSpeed`
- Health check `is_available()` per sub-provider, 3s timeout
- Symbol normalization: accept `VNM`, `VNM.HOSE`, `HOSE:VNM` → canonical `VNM.HOSE`
- Bar schema normalize sang common schema

### `agent/src/providers/data/vn_fundamental_provider.py` (NEW)
- Class `VNFundamentalProvider` — point-in-time VAS reports
- Mapping VAS account codes → IFRS-equivalent labels (config JSON)
- Gated by `TCBS_TOKEN` (optional, free tier dùng vnstock)

### `backtest/engines/vn_equity_engine.py` (NEW)
- Class `VNEquityEngine(Engine)`
- Config: `t_plus=2`, `price_band={"HOSE":0.07,"HNX":0.10,"UPCOM":0.15}`, `lot_size=100`, `tax_sell=0.001`
- Biên độ truncation hook ở mỗi tick (giả lập sàn)
- Hỗ trợ pre-market ATO/ATC orders (đặc thù VN)

### `backtest/engines/vn_futures_engine.py` (NEW)
- Class `VNFuturesEngine(Engine)`
- Hỗ trợ 4 hợp đồng VN30F1M/F2M/F1Q/F2Q
- Daily mark-to-market settlement, margin call simulator
- Cash settlement at expiry (lấy VN30 close)

### `backtest/composite_engine.py` (MODIFY)
- Add VN engines vào registry
- Test cross-market: VN30F hedge danh mục cổ phiếu VN

### `agent/skills/vn/*` (NEW — 8 skills)
1. `vn-data-routing` — Category: Data Source — route VN tickers tới VNStockProvider
2. `vn-foreign-room` — Category: Risk Analysis — track room ngoại còn lại, cảnh báo full room
3. `vn-financial-statements-vas` — Category: Analysis — fetch + parse báo cáo VAS PIT
4. `vn-ex-rights-calendar` — Category: Flow — GDKHQ, ngày chốt cổ tức
5. `vn-margin-list` — Category: Risk Analysis — danh mục margin UBCK + tier theo broker
6. `vn-vn30-arbitrage` — Category: Strategy — basis VN30 spot vs F1M/F2M
7. `vn-sector-rotation-vn` — Category: Analysis — sector rotation theo phân ngành ICB/GICS VN
8. `vn-pre-warning-stocks` — Category: Risk Analysis — cổ phiếu cảnh báo/kiểm soát/hạn chế giao dịch

### `src/swarm/vn_*.yaml` (NEW — 3 presets)
1. `vn_investment_committee.yaml` — root research → bull/bear (parallel) → risk-review (margin + foreign room)
2. `vn_derivatives_desk.yaml` — VN30 spot analyst → VN30F basis → arb opportunity → risk
3. `vn_value_screener.yaml` — fundamental filter (VAS) → quality screen → entry timing (TA)

### `agent/src/journals/vn_*.py` (NEW — 5 readers)
- `ssi_journal.py`, `hsc_journal.py`, `vndirect_journal.py`, `tcbs_journal.py`, `dnse_journal.py`
- Mỗi reader normalize sang common journal schema
- Multi-format: CSV + Excel (xlsx) — dùng existing `read_document` tool

### `agent/src/exporters/amibroker_afl.py` (NEW)
- AST → AFL converter
- Validation: parse generated `.afl` qua syntax check trước khi ghi
- Bundle vào `/pine <run_id>` flow

### `agent/locales/vi-VN.json` (NEW) + report template updates
- Thuật ngữ tài chính VN chuẩn
- Number format `vi-VN`
- Disclaimer UBCK

### `pyproject.toml` (MODIFY)
- Add `vnstock>=3.0`, `vnquant` (optional)

## Verification

| Component | How to verify |
|-----------|---------------|
| `VNStockProvider` | Unit: mock 4 sub-providers, assert fallback order khi mỗi cái fail |
| `VNEquityEngine` | Property test: T+2 — bán T0 không giảm cash đến T+2, biên độ truncation đúng theo HOSE/HNX/UPCOM |
| `VNFuturesEngine` | Snapshot test: VN30F1M backtest 6 tháng, so với reference từ DNSE |
| 8 skills | 1 regression test per skill (theo Bundled-Skill Regression Coverage) |
| 3 swarm presets | `vibe-trading --swarm-presets` list ra; smoke run với `vars_json` mẫu |
| 5 journal readers | Fixture CSV/XLSX thật ẩn danh từ mỗi broker; assert profile metrics đúng |
| AFL export | Generated `.afl` parse được bằng AmiBroker formula syntax checker (offline lib) |
| i18n | Snapshot test report HTML khi `locale=vi-VN`, kiểm dấu tiếng Việt |
| Compliance | Manual: disclaimer UBCK xuất hiện ở mọi report VN, footer + header |
| End-to-end | `vibe-trading run -p "Backtest VNM 1y MA20/50"` chạy thành công, report VN |

## Open Questions

1. **Có dùng vnquant như backup vnstock không?** → recommend chỉ dùng vnstock để giảm dependency surface; revisit nếu vnstock unstable.
2. **DNSE LightSpeed cần OAuth không?** → cần xác nhận; nếu có thì tích hợp `oauth-cli-kit` như OpenAI Codex provider.
3. **Phí broker config ở đâu?** → mặc định trong engine, override qua `agent/.env` (`VN_BROKER_FEE=0.0015`).
4. **Có cần tách `vibe-trading-vn` PyPI riêng không?** → KHÔNG (per brainstorm Option B vs C). Bundled vào `vibe-trading-ai` chính.
