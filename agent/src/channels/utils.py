"""Utility helpers for channel adapters."""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.config.paths import get_data_dir

logger = logging.getLogger(__name__)

_UNSAFE_CHARS = re.compile(r"[/\\:*?\"<>|]")
# A CommonMark fence line: up to three leading spaces, then ``` or ~~~.
_FENCE_LINE = re.compile(r"^( {0,3})(`{3,}|~{3,})([^`~]*)$")

# Static client identification for the RFC 2971 IMAP ``ID`` command. NetEase
# mailboxes (163/126/yeah.net) accept ``LOGIN`` but reject the first ``SELECT``
# with ``Unsafe Login`` unless the client has identified itself; other servers
# accept or ignore ``ID``. No user data or secrets are sent.
_IMAP_CLIENT_ID = '("name" "vibe-trading" "version" "1.0" "vendor" "HKUDS")'


def get_media_dir(channel_name: str) -> Path:
    """Return a media directory for *channel_name* under the VT uploads root.

    Inbound media must land inside ``~/.vibe-trading/uploads`` — one of the
    default allowed file roots — so the agent's file-reading tools can open
    what users send over IM channels without extra configuration (#465).
    """
    p = get_data_dir() / "uploads" / channel_name
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


def _unclosed_fence(text: str) -> tuple[str, str] | None:
    """Return ``(opener line, marker)`` when a fence is still open.

    A trailing partial line is ignored, so a cut through the middle of a line
    cannot be mistaken for a fence opener or closer.
    """
    if not text.endswith("\n"):
        newline = text.rfind("\n")
        if newline < 0:
            return None
        text = text[: newline + 1]
    opener: str | None = None
    marker: str | None = None
    for line in text.split("\n"):
        match = _FENCE_LINE.match(line)
        if match is None:
            continue
        ticks = match.group(2)
        if marker is None:
            marker = ticks
            opener = line
            continue
        if ticks[0] == marker[0] and len(ticks) >= len(marker):
            marker = None
            opener = None
    if opener is None or marker is None:
        return None
    return opener, marker


def _close_open_fence(
    piece: str, rest: str, content: str, max_len: int
) -> tuple[str, str]:
    """Close a fence at the end of ``piece`` and reopen it on ``rest``.

    Does nothing when the closer would exceed ``max_len`` or when reopening
    would make the remainder longer than the text just split. The second
    guard is what keeps a long opener from looping.
    """
    found = _unclosed_fence(piece)
    if found is None:
        return piece, rest
    opener, marker = found
    suffix = "\n" + marker
    # Pull complete lines back onto the remainder until the closer fits.
    # Leaving the fence open would show the rest of the code as chat.
    while len(piece) + len(suffix) > max_len:
        newline = piece.rfind("\n")
        if newline <= 0:
            return piece, rest
        moved = piece[newline + 1 :]
        piece = piece[:newline]
        rest = f"{moved}\n{rest}" if moved else rest
        found = _unclosed_fence(piece)
        if found is None:
            return piece, rest
        opener, marker = found
        suffix = "\n" + marker
    if len(opener) + 1 >= max_len or not piece:
        return piece, rest
    candidate = opener + "\n" + rest
    if len(candidate) >= len(content):
        return piece, rest
    return piece + suffix, candidate


def split_message(
    content: str, max_len: int = 2000, *, repair_fences: bool = False
) -> list[str]:
    """Split content into chunks within max_len, preferring line breaks.

    Args:
        content: The text content to split.
        max_len: Maximum length per chunk (default 2000 for Discord compatibility).
        repair_fences: When true, a chunk that ends inside a fenced code block
            closes the fence, and the next chunk reopens it with the same
            opener. Discord and Slack render each chunk as its own message, so
            an unclosed fence turns the rest of the code into chat text and
            swallows the following prose as code. Callers that split plain
            text or HTML leave this off, because the inserted markers would
            shift their own offsets.

    Returns:
        List of message chunks, each within max_len.
    """
    if not content:
        return []
    # Non-positive max_len cannot advance the cut pointer; return unsplit.
    if max_len <= 0:
        return [content]
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
        piece = content[:pos]
        # Drop only the separator we broke on. A blanket lstrip() also ate
        # indentation on the next line (code blocks / nested markdown).
        rest = content[pos:]
        if rest.startswith("\n") or rest.startswith(" "):
            rest = rest[1:]
        if repair_fences:
            piece, rest = _close_open_fence(piece, rest, content, max_len)
        chunks.append(piece)
        content = rest
    return chunks


def safe_filename(name: str) -> str:
    """Replace unsafe path characters with underscores."""
    return _UNSAFE_CHARS.sub("_", name).strip()


def send_imap_id(client: Any) -> None:
    """Send a best-effort RFC 2971 IMAP ``ID`` command; never raises.

    NetEase mailboxes (163/126/yeah.net) accept ``LOGIN`` but reject the
    first ``SELECT`` with ``Unsafe Login`` unless the client has sent an
    ``ID`` command identifying itself. Sending ``ID`` is harmless for
    servers that support it and ignored by those that do not, so this is
    best-effort: any failure (unsupported command, closed socket) is
    swallowed and the caller proceeds to ``SELECT`` regardless.

    Args:
        client: A connected, logged-in ``imaplib.IMAP4`` or ``IMAP4_SSL``.
    """
    try:
        client.xatom("ID", _IMAP_CLIENT_ID)
    except Exception:  # noqa: BLE001 - best-effort; never block the connection
        logger.debug("IMAP ID command failed (non-fatal)", exc_info=True)


def email_tls_context(verify: bool) -> ssl.SSLContext:
    """Return the TLS context for every email connection, implicit SSL or STARTTLS.

    ``verify=True`` (the default) verifies the server certificate and hostname
    against the system CA bundle, so a credential is never sent to an
    unverified server. ``verify=False`` disables verification — an explicit,
    documented opt-out for self-signed or internal-CA mail servers that trades
    MITM protection for connectivity. IMAP and SMTP, implicit SSL and STARTTLS,
    all take their context here, so ``verify_tls`` is one switch for all four.
    """
    if verify:
        return ssl.create_default_context()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # check_hostname must be cleared before CERT_NONE or Python raises ValueError.
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


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
    """Check whether *addr* is non-globally-routable (private/internal/mesh).

    ``addr.is_global`` is False for loopback, link-local, RFC 1918 private,
    unspecified, reserved, and RFC 6598 shared address space
    (``100.64.0.0/10`` — the default Tailscale/mesh range). The previous
    explicit ``is_loopback | is_link_local | is_private`` checks missed the
    100.64/10 block (``is_private`` is False for it), letting CGNAT/mesh hosts
    slip past ``validate_url_target`` and be fetched as channel media. Using
    ``not addr.is_global`` blocks every non-globally-routable range uniformly.
    Multicast is added explicitly because ``is_global`` is True for multicast
    addresses (both ``224.0.0.0/4`` and ``ff00::/8``); the old code only caught
    IPv6 multicast, so this also closes an IPv4-multicast gap and matches
    ``web_reader_tool._url_allowed``.

    Loopback is still permitted when ``validate_url_target(allow_loopback=True)``
    is called — that allowance is evaluated before this function runs.
    """
    return not addr.is_global or addr.is_multicast
