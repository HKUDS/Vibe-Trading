"""HTTP helpers for the WebSocket channel."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from src.channels.utils import validate_url_target


_LONG_LIVED_TIMEOUT = 300  # seconds for long-lived HTTP connections


def normalize_config_path(path: str | Path) -> str:
    """Normalize an HTTP/WebSocket route path.

    Args:
        path: Path-like route value.

    Returns:
        A leading-slash route without a trailing slash, except for ``"/"``.
    """
    value = str(path).strip() or "/"
    if not value.startswith("/"):
        value = f"/{value}"
    while "//" in value:
        value = value.replace("//", "/")
    if len(value) > 1:
        value = value.rstrip("/")
    return value or "/"


def parse_request_path(path: str) -> tuple[str, dict[str, list[str]]]:
    """Parse an HTTP request path into ``(route_path, query)``."""
    parts = urlsplit(path or "/")
    return normalize_config_path(parts.path or "/"), parse_qs(parts.query, keep_blank_values=True)


def query_first(qs: dict[str, list[str]], key: str) -> str | None:
    """Return the first value for *key* in a query string dict."""
    values = qs.get(key, [])
    return values[0] if values else None


def parse_and_validate_url(url: str, *, allow_loopback: bool = False) -> tuple[bool, str]:
    """Validate a URL target before a channel-side fetch."""
    return validate_url_target(url, allow_loopback=allow_loopback)


async def read_uploaded_file(*args: Any, **kwargs: Any) -> bytes:
    """Read bytes from a file-like upload object.

    The helper accepts common async/sync file objects used by lightweight HTTP
    adapters. It is intentionally conservative and only returns raw bytes.
    """
    del kwargs
    if not args:
        return b""
    obj = args[0]
    if isinstance(obj, bytes):
        return obj
    if isinstance(obj, bytearray):
        return bytes(obj)
    read = getattr(obj, "read", None)
    if read is None:
        raise TypeError("upload object does not provide read()")
    result = read()
    if asyncio.iscoroutine(result):
        result = await result
    if isinstance(result, str):
        return result.encode("utf-8")
    if isinstance(result, bytes):
        return result
    if isinstance(result, bytearray):
        return bytes(result)
    raise TypeError("upload read() did not return bytes")
