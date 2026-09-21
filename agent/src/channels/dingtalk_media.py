"""Stateless DingTalk media helpers, split from ``dingtalk.py`` for size.

The helpers classify and package outbound media references (remote URLs or
local paths) before they are uploaded to DingTalk. They hold no channel
state: the extension sets live here and each function takes only the values
it needs. The split keeps ``dingtalk.py`` under the repo's 800-line hard cap
(AGENTS.md: 文件 ≤400 行，800 硬顶).
"""

from __future__ import annotations

import os
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
AUDIO_EXTS = {".amr", ".mp3", ".wav", ".ogg", ".m4a", ".aac"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def is_http_url(value: str) -> bool:
    """Return whether *value* is an ``http``/``https`` URL."""
    return urlparse(value).scheme in ("http", "https")


def guess_upload_type(media_ref: str) -> str:
    """Return the DingTalk upload type for a media reference.

    Args:
        media_ref: Remote URL or local path to classify by extension.

    Returns:
        One of ``image``, ``voice``, ``video``, or ``file``.
    """
    ext = Path(urlparse(media_ref).path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "voice"
    if ext in VIDEO_EXTS:
        return "video"
    return "file"


def guess_filename(media_ref: str, upload_type: str) -> str:
    """Return a filename for a media reference, with an upload-type fallback.

    Args:
        media_ref: Remote URL or local path to derive the basename from.
        upload_type: A ``guess_upload_type`` result used when no name exists.

    Returns:
        The URL/path basename, or a default name for the upload type.
    """
    name = os.path.basename(urlparse(media_ref).path)
    return name or {
        "image": "image.jpg",
        "voice": "audio.amr",
        "video": "video.mp4",
    }.get(upload_type, "file.bin")


def zip_bytes(filename: str, data: bytes) -> tuple[bytes, str, str]:
    """Zip *data* as a single entry named after *filename*.

    Args:
        filename: Original filename; its stem names the zip and its fallback
            entry name is ``attachment.bin``.
        data: Raw payload bytes to compress.

    Returns:
        A ``(zip_payload, zip_filename, content_type)`` tuple.
    """
    stem = Path(filename).stem or "attachment"
    safe_name = filename or "attachment.bin"
    zip_name = f"{stem}.zip"
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(safe_name, data)
    return buffer.getvalue(), zip_name, "application/zip"
