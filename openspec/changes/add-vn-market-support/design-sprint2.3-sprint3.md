# Design: Sprint 2.3 + Sprint 3 — VN Market Support (Phần còn lại)

> Tài liệu này bổ sung cho `design.md` và `design-vn-futures.md` đã có.  
> Phạm vi: những tính năng **chưa triển khai** sau Sprint 2.2.

---

## Bối cảnh & Trạng thái hiện tại

Sau Sprint 2.2 (hoàn thành 2026-05-10), branch `feat/vn-market-support` có:
- ✅ `VNStockLoader` — dữ liệu giá từ vnstock (VCI/TCBS/MSN fallback)
- ✅ `VNEquityEngine` — T+2, biên độ, lô 100, thuế 0.1%
- ✅ `VNFuturesEngine` — VN30F F1M/F2M/F1Q/F2Q, mark-to-market, margin call
- ✅ 5 VN broker journal parsers (SSI, HSC, VNDirect, TCBS, DNSE)
- ✅ 3 skills cơ bản (vn-data-routing, vn-foreign-room, vn-financial-statements-vas)
- **1062 tests pass, 0 fail**

**Còn lại (Sprint 2.3 + Sprint 3):**

| Sprint | Nhóm | Công việc |
|--------|------|-----------|
| 2.3 | Swarm | 3 VN swarm presets |
| 2.3 | i18n | Locale vi-VN |
| 2.3 | Dữ liệu | `VNFundamentalProvider` (báo cáo tài chính VAS) |
| 3 | Xuất | Amibroker AFL exporter |
| 3 | Skills | 5 advanced VN skills |
| 3 | Compliance | UBCK disclaimer |
| 3 | Docs | Hoàn thiện tài liệu + PyPI release |

---

## Sprint 2.3 — Chi tiết kỹ thuật

### A. Ba VN Swarm Presets

**Kiến trúc chung:**  
Mỗi preset là file YAML trong `agent/src/swarm/presets/`, giống cấu trúc `commodity_research_team.yaml`. Sẽ auto-discovered bởi `--swarm-presets` ngay sau khi thêm file.

#### A1. `vn_investment_committee.yaml`

DAG 5 nút:
```
research_analyst (root)
    ├── bull_analyst (song song)
    └── bear_analyst (song song)
         ↓ (chờ cả 2)
vas_fundamental_analyst
         ↓
foreign_room_risk_reviewer
         ↓
chief_investment_officer (terminal — ra khuyến nghị)
```

Biến đầu vào: `{ticker}`, `{horizon}` (ví dụ: "FPT", "3 tháng")  
Nút risk_reviewer phải gọi `load_skill("vn-foreign-room")` và `load_skill("vn-financial-statements-vas")`.

#### A2. `vn_derivatives_desk.yaml`

DAG 3 nút:
```
spot_analyst (VN equity technical)
futures_analyst (basis, roll yield, OI)
         ↓ (song song)
derivatives_strategist (terminal — arb/hedge signal)
```

Biến: `{equity_ticker}` (ví dụ "VNM.HOSE"), `{futures_contract}` (ví dụ "VN30F1M.HNX")  
Nút futures_analyst gọi `load_skill("vn-data-routing")` để lấy basis real-time.

#### A3. `vn_value_screener.yaml`

Pipeline tuyến tính (không song song):
```
fundamental_screener (VAS P/B, P/E, ROE thresholds)
         ↓
quality_filter (nợ/vốn, FCF, biên lợi nhuận)
         ↓
technical_timer (MA + RSI timing)
         ↓
screener_report (terminal — danh sách mua/theo dõi/loại)
```

Biến: `{sector}` (ví dụ "ngân hàng", "bất động sản"), `{min_market_cap_bn_vnd}`

**Verification:**
- `vibe-trading --swarm-presets` → tổng ≥ 32 presets (29 hiện tại + 3 VN)
- Mỗi preset chạy smoke với `vars_json` mẫu → không crash trước khi LLM gọi

---

### B. i18n vi-VN

**Phạm vi nhỏ:** Không phải toàn bộ UI — chỉ các template báo cáo của backtest và trade journal.

**File cần tạo:**
- `agent/locales/vi-VN.json` — từ điển thuật ngữ tài chính VN (xem mục C.2)
- Cập nhật `agent/src/tools/trade_journal_parsers.py`: nếu `locale == "vi-VN"`, dùng template tiếng Việt

**Số formatter vi-VN:**  
`1.000.000,50` (dấu chấm = phân cách nghìn, dấu phẩy = thập phân) — ngược với US locale.

**Template báo cáo vi-VN:**
```
## Bức tranh giao dịch của bạn — {khoảng thời gian}
- Số lệnh: {total_trades} (hoàn chỉnh {total_roundtrips} vòng)
- Giữ lệnh TB: {avg_holding_days} ngày
- Tần suất: {trade_frequency_per_week} lần/tuần
- Tỉ lệ thắng: {win_rate}
- Tỉ lệ lãi/lỗ: {profit_loss_ratio}
- Tổng lãi/lỗ: {total_pnl} VNĐ
- Max drawdown: {max_drawdown} VNĐ
```

---

### C. VNFundamentalProvider

**Mục đích:** Cho phép `vn-financial-statements-vas` skill thực sự tải dữ liệu (hiện tại là stub).

**Thiết kế:**
```python
# agent/backtest/providers/vn_fundamental.py
class VNFundamentalProvider:
    """Point-in-Time VAS financial data via vnstock."""

    def get_income_statement(self, symbol: str, period: str = "quarter") -> pd.DataFrame:
        ...  # vnstock.finance.IncomeStatement

    def get_balance_sheet(self, symbol: str, period: str = "quarter") -> pd.DataFrame:
        ...  # vnstock.finance.BalanceSheet

    def get_cash_flow(self, symbol: str, period: str = "quarter") -> pd.DataFrame:
        ...  # vnstock.finance.CashFlow

    def get_ratios(self, symbol: str) -> pd.DataFrame:
        ...  # P/E, P/B, ROE, ROA, NIM (ngân hàng)
```

**VAS key fields mapping JSON** (`agent/data/vas_fields.json`):
```json
{
  "income": {
    "revenue": ["Doanh thu thuần", "10. Doanh thu"],
    "gross_profit": ["Lợi nhuận gộp"],
    "operating_profit": ["Lợi nhuận từ HĐKD"],
    "net_profit": ["Lợi nhuận sau thuế"]
  },
  "balance": {
    "total_assets": ["Tổng tài sản"],
    "equity": ["Vốn chủ sở hữu"],
    "short_term_debt": ["Vay và nợ thuê tài chính ngắn hạn"],
    "long_term_debt": ["Vay và nợ thuê tài chính dài hạn"]
  }
}
```

**Point-in-Time (PIT) contract:** Chỉ trả về dữ liệu đã được công bố trước `as_of_date`. Tránh lookahead bias trong backtest.

---

## Sprint 3 — Chi tiết kỹ thuật

### D. Amibroker AFL Exporter

**Luồng:**
```
Strategy AST (JSON từ SignalEngine)
    → AFL Transformer (Python)
    → strategy.afl (text file)
```

**Mapping operators:**
| Python/SignalEngine | AFL |
|--------------------|-----|
| `MA(close, 20)` | `MA(C, 20)` |
| `RSI(14) < 30` | `RSI(14) < 30` |
| `crossabove(ma20, ma50)` | `Cross(MA(C,20), MA(C,50))` |
| `buy = condition` | `Buy = condition;` |
| `sell = condition` | `Sell = condition;` |

**Wire vào `/pine`:** Route thêm `--format afl` để emit `strategy.afl` cùng với `.pine`/`.mq5`.

**Verification:** 5 chiến lược mẫu → AFL → import manual vào Amibroker.

---

### E. 5 Advanced VN Skills

Mỗi skill = 1 file `SKILL.md` + 1 tool function + 1 test.

| Skill | Nguồn dữ liệu | Đầu ra |
|-------|--------------|--------|
| `vn-ex-rights-calendar` | vnstock.events | Lịch GDKHQ, cổ tức tiền mặt sắp tới |
| `vn-margin-list` | UBCK + broker APIs | Danh sách cổ phiếu được margin, tỉ lệ per broker |
| `vn-vn30-arbitrage` | VN30F + VN30 index | Basis, roll yield, tín hiệu arb |
| `vn-sector-rotation-vn` | ICB sector indices | Momentum ngành, luân chuyển dòng tiền |
| `vn-pre-warning-stocks` | HOSE/HNX thông báo | Danh sách cảnh báo/kiểm soát/hạn chế giao dịch |

---

### F. UBCK Compliance & Disclaimer

**Text disclaimer bắt buộc:**
```
CẢNH BÁO: Nội dung này chỉ mang tính chất tham khảo, không phải khuyến nghị đầu tư.
Đầu tư chứng khoán tiềm ẩn rủi ro. Nhà đầu tư cần tự quyết định dựa trên điều kiện
tài chính cá nhân. Dữ liệu lịch sử không đảm bảo kết quả trong tương lai.
```

**Nơi cần inject:**
1. Header/footer của tất cả báo cáo backtest VN
2. Báo cáo phân tích sao kê VN broker
3. CLI banner khi lần đầu chạy lệnh VN: `export VN_DISCLAIMER_SHOWN=1`
4. README — mục "Thị trường Việt Nam"

---

### G. Tài liệu hoàn chỉnh

| File | Nội dung |
|------|---------|
| `docs/vi/HUONG_DAN.md` | ✅ Đã tạo (Sprint hiện tại) |
| `docs/vn-market.md` | Quick start tiếng Anh (cho upstream PR) |
| `docs/vn-skills.md` | 8 skill reference (EN) |
| `docs/vn-broker-journals.md` | Hướng dẫn xuất file từ 5 broker |
| `README.md` | Thêm mục "Vietnam Market" + badge |

---

## Phụ thuộc & Thứ tự ưu tiên

```
Sprint 2.3:
  VNFundamentalProvider  ← phụ thuộc: vnstock.finance (đã có)
  Swarm presets          ← phụ thuộc: VNFundamentalProvider (cho investment_committee)
  i18n vi-VN             ← độc lập, có thể song song

Sprint 3:
  AFL Exporter           ← phụ thuộc: SignalEngine AST (đã có từ Phase 4c)
  5 Advanced Skills      ← phụ thuộc: VNFundamentalProvider (1 trong 5)
  UBCK Compliance        ← độc lập (chỉ text injection)
  Docs                   ← sau cùng, sau khi features stable
```

---

## Verification tổng thể

```bash
# Sau Sprint 2.3
pytest agent/tests/ -x                    # ≥ 1100 tests pass
vibe-trading --swarm-presets | grep vn_   # thấy 3 presets VN
vibe-trading run -p "Phân tích FPT theo VAS" # VNFundamentalProvider hoạt động

# Sau Sprint 3
pytest agent/tests/ -x                    # ≥ 1200 tests pass
vibe-trading pine <run_id> --format afl   # tạo được file .afl
vibe-trading run -p "Danh sách cổ phiếu cảnh báo" # vn-pre-warning-stocks hoạt động
```
