# Bug Class Review: AGS Markdown Rendering XSS

## Class

Research report fields can be copied or exported as Markdown. If untrusted strings are concatenated directly, HTML tags and dangerous URI schemes can become active in downstream renderers.

## Fix

`agent/src/alpha_foundry/reports/render_markdown.py` now escapes field values, removes control characters, neutralizes dangerous URI schemes, and escapes Markdown metacharacters.

## Regression Coverage

- `agent/tests/security/test_paste_markdown_html_security.py`
- `frontend/src/lib/__tests__/paste-markdown-security.test.tsx`
