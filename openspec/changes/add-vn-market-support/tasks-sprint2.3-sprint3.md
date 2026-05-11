# Kế hoạch Triển khai — Sprint 2.3 & Sprint 3

> Tiếp theo sau Sprint 2.2 (hoàn thành 2026-05-10, 1062 tests pass).  
> Mỗi task ≈ 15–60 phút. Xác minh sau mỗi bước trước khi tiếp tục.  
> Thiết kế kỹ thuật chi tiết: xem `design-sprint2.3-sprint3.md`.

---

## Sprint 2.3 — Swarm + i18n + Fundamental Data

**Mục tiêu:** Hoàn thiện tầng dữ liệu và AI-multi-agent cho thị trường VN.  
**Ước tính:** 2 tuần  
**Baseline:** 1062 tests pass

---

### Nhóm A: VNFundamentalProvider (làm trước — Swarm phụ thuộc)

- [ ] **A.1** Tạo `agent/backtest/providers/vn_fundamental.py`
  - Class `VNFundamentalProvider` với 4 method: `get_income_statement`, `get_balance_sheet`, `get_cash_flow`, `get_ratios`
  - Wrap `vnstock.finance` với lazy import (giữ pattern tránh ImportError)
  - PIT filter: chỉ trả dữ liệu có `report_date <= as_of_date`
  - _Verify:_ `from agent.backtest.providers.vn_fundamental import VNFundamentalProvider` không lỗi

- [ ] **A.2** Tạo `agent/data/vas_fields.json` — mapping ~50 key VAS fields
  - Các nhóm: income / balance / cashflow / ratios
  - Label tiếng Việt ↔ key tiếng Anh
  - _Verify:_ `json.load` không lỗi

- [ ] **A.3** Nâng cấp skill `vn-financial-statements-vas` từ stub → live
  - Gọi `VNFundamentalProvider.get_income_statement()` và `get_ratios()`
  - Format kết quả thành bảng markdown
  - _Verify:_ `load_skill("vn-financial-statements-vas")` trả kết quả thực (cần mạng/mock)

- [ ] **A.4** Viết tests `agent/tests/test_vn_fundamental_provider.py`
  - Mock `vnstock.finance` để test offline
  - Test PIT filter: dữ liệu Q4 2024 không xuất hiện nếu `as_of_date = "2024-10-01"`
  - Test `get_ratios`: P/E, P/B, ROE đều có
  - _Verify:_ `pytest agent/tests/test_vn_fundamental_provider.py` → tất cả pass

---

### Nhóm B: Ba VN Swarm Presets

- [ ] **B.1** Tạo `agent/src/swarm/presets/vn_investment_committee.yaml`
  - DAG: research → bull+bear (song song) → vas_fundamental → foreign_room_risk → CIO
  - Biến: `{ticker}`, `{horizon}`
  - Nút risk_reviewer load `vn-foreign-room` và `vn-financial-statements-vas`
  - _Verify:_ `vibe-trading --swarm-presets | grep vn_investment_committee`

- [ ] **B.2** Tạo `agent/src/swarm/presets/vn_derivatives_desk.yaml`
  - DAG: spot_analyst + futures_analyst (song song) → derivatives_strategist
  - Biến: `{equity_ticker}`, `{futures_contract}`
  - Nút futures_analyst load `vn-data-routing`
  - _Verify:_ `vibe-trading --swarm-presets | grep vn_derivatives_desk`

- [ ] **B.3** Tạo `agent/src/swarm/presets/vn_value_screener.yaml`
  - Pipeline: fundamental_screener → quality_filter → technical_timer → screener_report
  - Biến: `{sector}`, `{min_market_cap_bn_vnd}`
  - _Verify:_ `vibe-trading --swarm-presets | grep vn_value_screener`

- [ ] **B.4** Smoke test cả 3 presets
  - Chạy với `vars_json` mẫu, không cần LLM thật (mock hoặc dry-run)
  - Tổng số presets sau khi thêm: ≥ 32
  - _Verify:_ `vibe-trading --swarm-presets | wc -l` ≥ 32

- [ ] **B.5** Viết tests `agent/tests/test_vn_swarm_presets.py`
  - Test mỗi preset load được YAML hợp lệ
  - Test DAG topology (nút, edge, thứ tự thực thi)
  - _Verify:_ pytest → pass

---

### Nhóm C: i18n vi-VN

- [ ] **C.1** Tạo `agent/locales/vi-VN.json` — từ điển thuật ngữ tài chính
  - Tối thiểu 60 thuật ngữ: chứng khoán, báo cáo tài chính, kỹ thuật
  - Ví dụ: `"win_rate": "Tỉ lệ thắng"`, `"drawdown": "Sụt giảm tối đa"`
  - _Verify:_ `json.load` không lỗi

- [ ] **C.2** Tạo `agent/locales/vi_VN_formatter.py` — số và ngày VN
  - `format_number(1000000.5) → "1.000.000,50"`
  - `format_currency(1500000) → "1.500.000 VNĐ"`
  - `format_date("2024-06-03") → "03/06/2024"`
  - _Verify:_ unit tests trực tiếp

- [ ] **C.3** Cập nhật `trade_journal_parsers.py`: template báo cáo vi-VN
  - Khi `locale == "vi-VN"`: dùng template tiếng Việt
  - Số tiền format theo `vi_VN_formatter`
  - _Verify:_ parse một file SSI, kết quả báo cáo có tiếng Việt

- [ ] **C.4** Viết tests `agent/tests/test_vi_vn_locale.py`
  - Test formatter với các edge case: số âm, số 0, số lớn
  - Test báo cáo trade journal với locale vi-VN
  - _Verify:_ pytest → pass

---

### Sprint 2.3 — Tổng kết

- [ ] **Z.1** Chạy full regression: `pytest agent/tests/ -x --tb=short`
  - _Mục tiêu:_ ≥ 1130 tests pass, 0 fail
- [ ] **Z.2** Cập nhật `CONTINUITY.md` → Current Phase: "sprint-2.3 complete"
- [ ] **Z.3** Commit với tag `v0.2.0-beta-vn-full` (tuỳ chọn)

---

## Sprint 3 — Export + Advanced Skills + Compliance + Release

**Mục tiêu:** Hoàn thiện tính năng chuyên sâu, tuân thủ pháp lý, phát hành v0.2.0.  
**Ước tính:** 2–3 tuần  
**Baseline:** Sprint 2.3 done

---

### Nhóm D: Amibroker AFL Exporter

- [ ] **D.1** Tạo `agent/src/tools/strategy_exporters/afl_transformer.py`
  - Nhận Strategy AST (dict/JSON từ SignalEngine)
  - Emit AFL code string (text)
  - Mapping operator table: MA, RSI, Cross, Buy/Sell conditions
  - _Verify:_ `from agent.src.tools.strategy_exporters.afl_transformer import to_afl` không lỗi

- [ ] **D.2** Implement mapping các indicator phổ biến
  - MA, EMA, RSI, MACD, Bollinger Bands, ATR
  - Crossover / crossunder
  - Toán tử so sánh và logic (AND/OR)
  - _Verify:_ unit test 5 chiến lược mẫu

- [ ] **D.3** Wire vào `/pine` endpoint hoặc tạo `/export` mới
  - `GET /export/{run_id}?format=afl` → trả file `.afl`
  - Cũng hỗ trợ emit cùng lúc với pine/mq5
  - _Verify:_ `curl http://localhost:8899/export/{run_id}?format=afl` → file hợp lệ

- [ ] **D.4** Viết tests `agent/tests/test_afl_exporter.py`
  - 5 chiến lược mẫu → AFL, so sánh với expected output
  - _Verify:_ pytest → pass

---

### Nhóm E: 5 Advanced VN Skills

- [ ] **E.1** `vn-ex-rights-calendar`
  - Nguồn: `vnstock.events` (GDKHQ, cổ tức, phát hành thêm)
  - Output: danh sách sự kiện 30 ngày tới, highlight GDKHQ gần nhất
  - Tests: mock data, 2 sự kiện trong window
  - _Verify:_ skill load được, test pass

- [ ] **E.2** `vn-margin-list`
  - Nguồn: HOSE/HNX thông báo danh sách ký quỹ; fallback scrape
  - Output: `{symbol, max_ratio, brokers: [{name, ratio}]}`
  - Tests: mock danh sách, kiểm tra format
  - _Verify:_ skill load được, test pass

- [ ] **E.3** `vn-vn30-arbitrage`
  - Nguồn: VN30 index close + VN30F ask/bid qua vnstock
  - Tính: basis = F - S, roll yield, annualized basis
  - Tín hiệu: basis > threshold → long spot / short futures
  - Tests: basis tính đúng với dữ liệu mock
  - _Verify:_ skill load được, test pass

- [ ] **E.4** `vn-sector-rotation-vn`
  - Nguồn: ICB sector index từ vnstock (VN-BANK, VN-REALESTATE, VN-TECH, ...)
  - Tính: momentum 20 ngày per ngành, rank, dòng tiền ròng
  - Output: top 3 ngành tích cực, top 3 tiêu cực
  - Tests: mock 5 ngành, kiểm tra rank
  - _Verify:_ skill load được, test pass

- [ ] **E.5** `vn-pre-warning-stocks`
  - Nguồn: HOSE/HNX official announcements (scrape hoặc vnstock.listing)
  - Output: danh sách cổ phiếu theo trạng thái (cảnh báo / kiểm soát / hạn chế)
  - Tests: mock danh sách, filter đúng trạng thái
  - _Verify:_ skill load được, test pass

- [ ] **E.6** Register tất cả 5 skills vào registry
  - _Verify:_ `vibe-trading run -p "list vn skills"` → thấy 8 VN skills tổng cộng

---

### Nhóm F: UBCK Compliance & Disclaimer

- [ ] **F.1** Tạo `agent/locales/ubck_disclaimer.py`
  - Constants: `DISCLAIMER_VI` (tiếng Việt), `DISCLAIMER_EN` (tiếng Anh)
  - Helper: `inject_disclaimer(report_html: str, locale: str) → str`
  - _Verify:_ unit test inject → disclaimer xuất hiện ở đầu và cuối

- [ ] **F.2** Inject disclaimer vào báo cáo backtest VN
  - Trong `VNEquityEngine` và `VNFuturesEngine`: thêm disclaimer section khi render report
  - _Verify:_ chạy backtest VNM.HOSE → HTML report có disclaimer

- [ ] **F.3** Inject disclaimer vào báo cáo trade journal VN
  - Sau khi parse bằng VN broker parser: thêm disclaimer footer
  - _Verify:_ phân tích file SSI → báo cáo có disclaimer

- [ ] **F.4** CLI banner khi chạy lần đầu lệnh VN
  - Check env var `VN_DISCLAIMER_SHOWN`; nếu chưa → print banner + set var
  - _Verify:_ `VN_DISCLAIMER_SHOWN="" vibe-trading run -p "backtest VNM"` → thấy banner

---

### Nhóm G: Tài liệu hoàn chỉnh

- [ ] **G.1** Tạo `docs/vn-market.md` (tiếng Anh — cho upstream PR)
  - Quick start, symbol format, supported brokers, links
  - _Verify:_ markdown render không lỗi

- [ ] **G.2** Tạo `docs/vn-skills.md` (tiếng Anh)
  - 8 skills: mô tả, cách dùng, example output
  - _Verify:_ markdown render không lỗi

- [ ] **G.3** Tạo `docs/vn-broker-journals.md` (tiếng Anh + hướng dẫn tiếng Việt)
  - 5 broker: cách xuất file, screenshot/mô tả, cột nhận dạng
  - _Verify:_ markdown render không lỗi

- [ ] **G.4** Cập nhật `docs/vi/HUONG_DAN.md` ← đã tạo (Sprint 2.3)
  - Bổ sung phần về 5 advanced skills và AFL exporter sau khi D/E xong
  - _Verify:_ nội dung đồng bộ với features đã triển khai

- [ ] **G.5** Cập nhật `README.md` (upstream)
  - Thêm mục "🇻🇳 Vietnam Market" sau mục News
  - Thêm badge: `VN Market: HOSE/HNX/UPCoM + VN30F`
  - Thêm link đến `docs/vn-market.md`
  - _Verify:_ README render đúng

---

### Sprint 3 — Release

- [ ] **H.1** Full regression suite xanh
  - `pytest agent/tests/ --tb=short`
  - _Mục tiêu:_ ≥ 1200 tests pass, 0 fail

- [ ] **H.2** Cập nhật `pyproject.toml` version → `0.2.0`
  - Thêm `[project.optional-dependencies] vn = ["vnstock>=4.0"]`
  - Cân nhắc: giữ vnstock là hard dep hay optional?

- [ ] **H.3** Cập nhật `CONTINUITY.md` → Current Phase: "sprint-3 complete, ready for merge"

- [ ] **H.4** Tạo PR vào `main`
  - Title: `feat: Add Vietnam market support (HOSE/HNX/UPCoM + VN30F + 5 brokers)`
  - Body: summary Sprint 1/2/3, test count, breaking changes (none)

- [ ] **H.5** Sau khi merge: archive OpenSpec
  - `git mv openspec/changes/add-vn-market-support openspec/changes/archive/add-vn-market-support`
  - _Verify:_ `openspec/changes/` không còn `add-vn-market-support/`

- [ ] **H.6** PyPI release `v0.2.0`
  - `uv build && uv publish`
  - _Verify:_ `pip install vibe-trading-ai==0.2.0` → `vibe-trading --swarm-presets | grep vn_`

- [ ] **H.7** Docker image rebuild
  - `docker build -t vibe-trading:0.2.0 .`
  - Smoke test container: `docker run -e LLM_API_KEY=... vibe-trading:0.2.0 --help`

- [ ] **H.8** README News entry
  ```
  - **2026-XX-XX** 🇻🇳 **Vietnam market v0.2.0**: Full support for HOSE/HNX/UPCoM equities
    (T+2, biên độ, lot 100, 0.1% tax) + VN30F futures (F1M/F2M/F1Q/F2Q, daily MTM,
    margin call) + 5 broker journal parsers (SSI/HSC/VNDirect/TCBS/DNSE) + 3 VN swarm
    presets + 8 VN skills + AFL exporter.
  ```

---

## Tóm tắt ước tính

| Sprint | Tasks | Thời gian ước tính | Tests mới (ước tính) |
|--------|-------|-------------------|--------------------|
| 2.3 Fundamental | A.1–A.4 | 2 ngày | +20 |
| 2.3 Swarm | B.1–B.5 | 2 ngày | +15 |
| 2.3 i18n | C.1–C.4 | 1 ngày | +10 |
| 3 AFL | D.1–D.4 | 3 ngày | +20 |
| 3 Skills | E.1–E.6 | 3 ngày | +30 |
| 3 Compliance | F.1–F.4 | 1 ngày | +10 |
| 3 Docs + Release | G.1–H.8 | 2 ngày | 0 (docs) |
| **Tổng** | **~35 tasks** | **~14 ngày** | **+105 tests** |

**Mục tiêu cuối:** ~1167+ tests pass, phát hành v0.2.0 PyPI.
