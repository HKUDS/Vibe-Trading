# AGS Image And Paste Regression Matrix

| Vector | Expected Behavior | Regression Test |
| --- | --- | --- |
| SVG upload with script | Reject with no file persisted. | `agent/tests/security/test_image_upload_clipboard_security.py::test_upload_blocks_svg_active_content` |
| Safe PNG upload | Continue to accept and store under `uploads/<uuid>.png`. | `agent/tests/security/test_image_upload_clipboard_security.py::test_upload_still_allows_safe_png` |
| Clipboard/data URL SVG | MIME parsed but not allowed as an image. | `test_clipboard_data_url_svg_is_not_an_allowed_websocket_image` |
| Weixin outbound SVG | Not classified as image media. | `test_weixin_outbound_media_does_not_classify_svg_as_image` |
| Markdown HTML injection | HTML is escaped before rendering/export. | `agent/tests/security/test_paste_markdown_html_security.py` |
| Markdown `javascript:`/`data:` link | Dangerous scheme is neutralized and link syntax escaped. | backend + `frontend/src/lib/__tests__/paste-markdown-security.test.tsx` |
| Image EXIF/OCR/prompt/path metadata | Redacted before preview/export display. | `frontend/src/lib/__tests__/image-preview-redaction-security.test.tsx` |
| Report export secrets | Nested secret-like keys redacted; evidence fields preserved. | `frontend/src/lib/__tests__/report-export-redaction-consistency.test.tsx` |

All rows preserve existing safe-media functionality and target only active content, prompt injection, private path, OCR, and secret leakage risks.
