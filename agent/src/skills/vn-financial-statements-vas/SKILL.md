---
name: vn-financial-statements-vas
category: analysis
description: Fetch and interpret Vietnamese Accounting Standards (VAS) point-in-time financial statements. Maps VAS account codes to IFRS-equivalent labels for cross-market comparison.
---

## VAS vs IFRS

Vietnamese listed companies report under **VAS** — Vietnamese Accounting Standards — promulgated by the Ministry of Finance. The current chart of accounts is governed by **Circular 200/2014/TT-BTC** (Thông tư 200/2014/TT-BTC), with sector-specific overlays for credit institutions (Circular 49) and securities firms (Circular 210).

VAS overlaps with IFRS in structure but differs in several important areas:

| Topic | VAS | IFRS |
|-------|-----|------|
| Inventory valuation | Cost or NRV; LIFO not allowed since 2016 | Cost or NRV; LIFO never allowed |
| Operating leases (lessee) | Off-balance-sheet | On-balance-sheet (IFRS 16) — ROU asset + lease liability |
| Financial instruments | Cost-based; limited fair value | IFRS 9 — FVTPL / FVOCI / amortized cost |
| Goodwill | Amortized over ≤ 10 years | Tested for impairment, no amortization |
| Functional currency | VND mandatory | Functional currency choice |
| Revenue recognition | Older transfer-of-risk model | IFRS 15 5-step model |

Vietnam has a multi-year roadmap (Decision 345/QĐ-BTC, 2020) toward full IFRS adoption, with a voluntary phase 2022–2025 and mandatory phase from 2025+ for listed entities. Until then, expect VAS as the primary disclosed basis.

## Statement Types

| English | Vietnamese | Frequency |
|---------|-----------|-----------|
| Balance Sheet | Bảng cân đối kế toán | Quarterly + annual |
| Income Statement | Báo cáo kết quả hoạt động kinh doanh | Quarterly + annual |
| Cash Flow Statement | Báo cáo lưu chuyển tiền tệ | Quarterly + annual |
| Notes to Financial Statements | Thuyết minh báo cáo tài chính | Annual (audited) |

Quarterly statements are typically released ~30 days after period end and are unaudited. Annual statements are audited and released within 90 days of fiscal year end (most VN companies use a calendar year).

## Key VAS Account Codes

Circular 200 uses a 3-digit numeric code system. The first digit denotes the class:

- `1xx` Current assets
- `2xx` Non-current assets
- `3xx` Liabilities
- `4xx` Equity
- `5xx` Revenue
- `6xx` Costs / expenses (operating)
- `7xx` Other income
- `8xx` Other expenses / income tax
- `9xx` Determination of business results

| Code | VAS Name (VI) | English |
|------|---------------|---------|
| 111 | Tiền mặt | Cash on hand |
| 112 | Tiền gửi ngân hàng | Cash in bank |
| 121 | Chứng khoán kinh doanh | Trading securities |
| 131 | Phải thu của khách hàng | Trade receivables |
| 152 | Nguyên liệu, vật liệu | Raw materials inventory |
| 211 | Tài sản cố định hữu hình | Tangible fixed assets |
| 213 | Tài sản cố định vô hình | Intangible fixed assets |
| 311 | Vay ngắn hạn | Short-term loans |
| 331 | Phải trả người bán | Trade payables |
| 411 | Vốn đầu tư của chủ sở hữu | Owner's contributed capital |
| 421 | Lợi nhuận sau thuế chưa phân phối | Retained earnings |
| 511 | Doanh thu bán hàng và cung cấp dịch vụ | Revenue from goods & services |
| 632 | Giá vốn hàng bán | Cost of goods sold |
| 641 | Chi phí bán hàng | Selling expenses |
| 642 | Chi phí quản lý doanh nghiệp | General & administrative expenses |
| 821 | Chi phí thuế thu nhập doanh nghiệp | Corporate income tax expense |

## VAS → IFRS Label Mapping

| VAS line item | IFRS-equivalent label |
|---------------|-----------------------|
| Doanh thu thuần (Revenue 511 − returns/discounts) | Net revenue |
| Lợi nhuận gộp (Revenue 511 − COGS 632) | Gross profit |
| Lợi nhuận thuần từ hoạt động kinh doanh | Operating profit (approximate; VAS includes financial income/expense above this line) |
| Doanh thu hoạt động tài chính (515) | Finance income |
| Chi phí tài chính (635) | Finance costs |
| Lợi nhuận sau thuế (910 result) | Net profit / Profit attributable to owners |
| Vay và nợ thuê tài chính ngắn hạn (311+341 short part) | Short-term borrowings |
| Vốn chủ sở hữu (411 + 421 + reserves) | Total equity |

Note: VAS places financial income/expense **inside** operating profit, while IFRS often segregates them. Adjust before computing comparable EBIT for cross-market screens.

## Point-in-Time Semantics

For backtesting, fetch statements **as of original disclosure date**, NOT the latest restated figures. Restated values (after auditor adjustments or prior-period error corrections) introduce look-ahead bias.

Best practice:

1. Anchor each statement to its **public release date** (`disclosure_date`), not period-end (`period_end`).
2. Use the **first version** released; ignore later restatements.
3. For real-time strategies, accept that today's quarterly figures are unaudited and may be revised in the annual audit.

The vnstock library exposes period-end dates by default; obtaining true PIT vintages may require pairing with HOSE/HNX disclosure timestamps.

## How to Fetch

```python
from vnstock import Finance

# Quarterly balance sheet
bs = Finance(symbol='FPT').balance_sheet(period='quarter')

# Quarterly income statement
is_ = Finance(symbol='FPT').income_statement(period='quarter')

# Quarterly cash flow
cf = Finance(symbol='FPT').cash_flow(period='quarter')

# Annual variants: period='year'
```

The returned DataFrame is wide-format (one column per period). Common columns include `yearReport`, `lengthReport` (quarter index), and the full set of VAS line items.

## Common Pitfalls

- **Quarterly only**: Vietnamese filers do NOT publish monthly statements. Daily/monthly fundamental factors must be interpolated or built from quarterly snapshots.
- **Consolidated vs parent-only (riêng lẻ vs hợp nhất)**: Most listed groups publish both. Use **consolidated** for valuation; parent-only for dividend capacity analysis.
- **Bank / securities firm templates differ**: Credit institutions use Circular 49 codes (e.g. `cash_and_balances_with_sbv`, `loans_to_customers`). Don't try to apply industrial templates to banks.
- **Currency**: All figures are VND. For cross-market comparison, convert at the **statement date** spot rate, not today's spot rate.
- **Unit confusion**: Some feeds report VND in millions (triệu) by default; double-check the unit before computing per-share metrics.
