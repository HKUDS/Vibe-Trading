---
name: doc-reader
description: Read any common document/data file — PDF, Word (.docx), Excel (.xlsx/.xls), PowerPoint (.pptx), images (OCR), CSV/TSV, plain text, JSON/YAML/TOML, HTML/XML, and most source-code files. Use the `read_document` tool.
category: tool
---
# Universal Document Reader

## Purpose

Return extracted text from any supported file in a single unified JSON
envelope. The tool dispatches by file extension — you always call the same
tool regardless of format.

### Supported formats

| Category | Extensions | Notes |
|---|---|---|
| PDF | `.pdf` | Text pages extracted in ms; scanned/image pages fall back to OCR |
| Word | `.docx` | Paragraphs + table cells |
| Excel | `.xlsx`, `.xls` | All sheets, first 100 rows per sheet as preview |
| PowerPoint | `.pptx` | Slide text content |
| Images | `.png/.jpg/.jpeg/.gif/.bmp/.webp/.tiff` | OCR only |
| CSV / TSV | `.csv`, `.tsv` | Raw text with encoding fallback |
| Plain text | `.txt/.md/.log/.rst` | Encoding fallback |
| Config | `.json/.yaml/.yml/.toml/.ini/.cfg/.env` | Raw text |
| Markup | `.html/.htm/.xml` | Raw text (no HTML stripping) |
| Source code | `.py/.js/.ts/.tsx/.go/.rs/.java/.cpp/.c/.sql/.sh/...` | Raw text |
| Unknown extension | anything else | Best-effort read as UTF-8/GBK text |

**Blocked** (rejected at `/upload`): executables (`.exe/.dll/.so/...`) and
archives (`.zip/.tar/...`). Ask the user to unpack archives locally first.

## Usage

**Always call the tool directly — do not run Python from bash.**

```
read_document(file_path="uploads/paper.pdf")
read_document(file_path="uploads/annual_report.pdf", pages="1-10")
read_document(file_path="uploads/contract.docx")
read_document(file_path="uploads/sales.xlsx")
read_document(file_path="uploads/deck.pptx")
read_document(file_path="uploads/chart.png")     # image → OCR
read_document(file_path="uploads/config.yaml")
read_document(file_path="uploads/notes.md")
```

The `pages` parameter only applies to PDF; other formats ignore it.

## Return envelope

All formats share this shape:

```json
{
  "status": "ok",
  "file": "paper.pdf",
  "format": "pdf",
  "char_count": 52000,
  "truncated": true,
  "text": "..."
}
```

Format-specific extra fields:

| Format | Extra keys |
|---|---|
| `pdf` | `total_pages`, `pages_read`, `ocr_pages`, `ocr_engine`, `ocr_quality`, `skipped_pages` |
| `docx` | `paragraphs`, `tables` |
| `excel` | `sheets` (array of `{name, rows, cols}`) |
| `pptx` | `slides` |
| `text` | `encoding`, `size` |

Content longer than 15000 chars is truncated; for PDFs use the `pages`
parameter to read slices.

## Workflows

### Paper / report summary
```
1. read_document(file_path="paper.pdf")  → full text
2. Extract abstract, methodology, conclusion → summarize
```

### Contract review
```
1. read_document(file_path="contract.docx")  → paragraphs + tables
2. Flag key clauses (termination, liability, payment, IP)
```

### Spreadsheet quick-look
```
1. read_document(file_path="sales.xlsx")  → all sheet previews
2. If user wants trade journal analysis specifically, pivot to
   `analyze_trade_journal` tool instead (see trade-journal skill).
```

### Chart / screenshot / scanned PDF
```
1. read_document(file_path="scan.png")  → OCR text
2. If OCR returns empty, tell the user; don't fabricate.
```

## OCR Configuration

The `read_document` tool automatically uses OCR for PDF pages with insufficient extractable text.

### OCR Threshold

Use `min_text_per_page` to control when OCR is triggered (default: 50 characters):

```python
read_document("scanned_report.pdf", min_text_per_page=10)  # More aggressive OCR
read_document("mixed_pdf.pdf", min_text_per_page=100)  # Less aggressive OCR
```

### OCR Engine Configuration

Two OCR engines are built in — no extra packages needed beyond the engine SDK:

| Engine | Type | Requires | Install |
|--------|------|----------|---------|
| `rapid` | Local (offline) | `rapidocr_onnxruntime` | `pip install rapidocr_onnxruntime` |
| `llm-vision` | Cloud | A vision-capable LLM model + API key | No extra install — uses your existing LLM provider config |

The `llm-vision` engine works with **any OpenAI-compatible vision model** (GPT-4o, Qwen-VL, Gemini, Claude, GLM-4V, etc.). It reuses your existing `LANGCHAIN_PROVIDER` / `LANGCHAIN_MODEL_NAME` / API key configuration — no separate provider mapping needed. If you explicitly set `VIBE_TRADING_OCR_ENGINE=llm-vision`, your model choice is trusted; a real API error from the provider is clearer feedback than a heuristic guess.

To override the model used for OCR (without changing your agent's main model):
```
VIBE_TRADING_OCR_LLM_MODEL=qwen3.7-plus
```

Set `VIBE_TRADING_OCR_ENGINE` to select the engine:
- `auto` (default): use local engines only, never cloud (privacy: document pages never leave the machine)
- `rapid`: force RapidOCR (local, ONNX)
- `llm-vision`: force LLM vision OCR (cloud — pages are sent to your configured LLM provider)
- `none`: disable OCR entirely

### Response Fields

PDF responses include OCR metadata:
- `ocr_engine`: name of the OCR engine used (e.g. "rapid", "llm-vision") or `null`
- `ocr_pages`: number of pages processed via OCR
- `skipped_pages`: number of pages skipped (no OCR engine available)
- `ocr_quality`: object with `quality_flag` (`good`/`degraded`/`no_ocr_engine`/`no_ocr_needed`), `ocr_pages`, and `text_density` (chars per page)

## Notes

- **Encoding fallback** order for text: utf-8 → utf-8-sig → gbk → gb2312 → big5 → latin-1.
- **OCR** uses the configured engine (RapidOCR for local, or LLM vision for
  cloud). If no engine is available, image/scanned files return empty `text`
  with a `note` field — tell the user to install `rapidocr-onnxruntime` or
  set `VIBE_TRADING_OCR_ENGINE=llm-vision` with a vision-capable model.
- **Excel previews** are limited to 100 rows per sheet to stay in budget.
  If the user needs full data (e.g. trade journals), call
  `analyze_trade_journal` instead.
- **Source-code files** are returned raw; do not re-format or re-indent.
