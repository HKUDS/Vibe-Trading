"""Utility helpers for channel adapters."""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

from src.config.paths import get_data_dir

_UNSAFE_CHARS = re.compile(r"[/\\:*?\"<>|]")


def get_media_dir(channel_name: str) -> Path:
    """Return a media directory for *channel_name* under the VT data dir."""
    p = get_data_dir() / channel_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_runtime_subdir(name: str) -> Path:
    """Return a runtime subdirectory for *name* under the VT data dir."""
    p = get_data_dir() / "runtime" / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def validate_resolved_url(url: str, *, allow_loopback: bool = False) -> tuple[bool, str]:
    """Validate a URL then resolve and check its IP addresses.

    Thin wrapper around :func:`validate_url_target` for callers that want
    the same behavior under a legacy name.
    """
    return validate_url_target(url, allow_loopback=allow_loopback)


def is_path_within(path: str | Path, root: str | Path) -> bool:
    """Check whether *path* resides within *root* directory."""
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """Split content into chunks within max_len, preferring line breaks.

    Args:
        content: The text content to split.
        max_len: Maximum length per chunk (default 2000 for Discord compatibility).

    Returns:
        List of message chunks, each within max_len.
    """
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # Try to break at newline first, then space, then hard break
        pos = cut.rfind("\n")
        if pos <= 0:
            pos = cut.rfind(" ")
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks


def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def validate_url_target(url: str, *, allow_loopback: bool = False) -> tuple[bool, str]:
    """Validate a URL is safe to fetch: scheme, hostname, and resolved IPs.

    ``allow_loopback`` is intentionally narrow: it only permits literal
    loopback hosts (localhost, 127.0.0.0/8, ::1) when every resolved address is
    loopback. It does not allow RFC1918, link-local, metadata, or public DNS
    names that happen to resolve to loopback.

    Returns (ok, error_message).  When ok is True, error_message is empty.
    """
    try:
        p = urlparse(url)
    except Exception as e:
        return False, str(e)

    if p.scheme not in ("http", "https"):
        return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
    if not p.netloc:
        return False, "Missing domain"

    hostname = p.hostname
    if not hostname:
        return False, "Missing hostname"

    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"Cannot resolve hostname: {hostname}"

    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        addrs.append(addr)

    if allow_loopback and _is_allowed_loopback_target(hostname, addrs):
        return True, ""

    for addr in addrs:
        if _is_private(addr):
            return False, f"Blocked: {hostname} resolves to private/internal address {addr}"

    return True, ""


def _is_allowed_loopback_target(
    hostname: str,
    addrs: list[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> bool:
    """Check that *hostname* is a literal loopback host and every addr is loopback."""
    if hostname.lower() not in ("localhost", "localhost."):
        # Check for literal "127.x.y.z" or "[::1]"
        is_loopback_literal = False
        for addr in addrs:
            if addr.is_loopback:
                is_loopback_literal = True
            else:
                return False
        return is_loopback_literal
    return all(addr.is_loopback for addr in addrs) if addrs else False


def _is_private(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check whether *addr* is private, link-local, or loopback."""
    if addr.is_loopback or addr.is_link_local or addr.is_private:
        return True
    # Also block well-known metadata endpoints
    if isinstance(addr, ipaddress.IPv4Address):
        return False
    # IPv6: block unspecified, multicast, unique-local
    return addr.is_multicast or addr.is_unspecified
