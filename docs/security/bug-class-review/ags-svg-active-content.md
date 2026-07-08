# Bug Class Review: AGS SVG Active Content

## Class

SVG and HTML uploads are active browser content even when they look like images or documents.

## Fix

`agent/src/api/uploads_routes.py` now rejects `.svg`, `.html`, `.htm`, and `.xhtml`. `agent/src/channels/weixin.py` no longer treats `.svg` as outbound image media.

## Regression Coverage

- `agent/tests/security/test_image_upload_clipboard_security.py`
- `docs/ags-image-paste-regression-matrix.md`
