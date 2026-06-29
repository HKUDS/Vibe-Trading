"""Media decoding helpers for channel adapters."""

from __future__ import annotations

import base64
import binascii
import re
import uuid
from pathlib import Path


class FileSizeExceeded(ValueError):
    """Raised when a file exceeds the max size limit."""

_DATA_URL_RE = re.compile(r"^data:([^;,]+)((?:;[^,]*)*);base64,(.*)$", re.IGNORECASE | re.DOTALL)
_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "text/plain": ".txt",
    "application/pdf": ".pdf",
}


def save_base64_data_url(data_url: str, output_dir: Path, *, max_bytes: int = 0) -> Path:
    """Decode a base64 data URL and save it to *output_dir*.

    Args:
        data_url: A ``data:<mime>;base64,...`` URL.
        output_dir: Directory where the decoded file should be written.
        max_bytes: Optional maximum decoded byte length. ``0`` disables the
            limit.

    Returns:
        The path of the decoded file.

    Raises:
        FileSizeExceeded: If decoded data exceeds ``max_bytes``.
        ValueError: If the URL is malformed or uses an unsupported MIME type.
    """
    match = _DATA_URL_RE.match(data_url)
    if not match:
        raise ValueError("expected data:<mime>;base64,<payload>")
    mime = match.group(1).strip().lower()
    ext = _EXT_BY_MIME.get(mime)
    if not ext:
        raise ValueError(f"unsupported data URL MIME type: {mime}")

    payload = match.group(3).strip()
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 payload") from exc

    if max_bytes and len(decoded) > max_bytes:
        raise FileSizeExceeded(f"decoded media exceeds {max_bytes} bytes")

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{uuid.uuid4().hex}{ext}"
    path.write_bytes(decoded)
    return path
