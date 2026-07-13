"""Auth dependencies, CORS parsing, DNS-rebinding guard, and shell-tools gating."""

from __future__ import annotations

import hmac
import ipaddress
import logging
import re
import secrets
import threading
import time
import urllib.parse
from pathlib import Path
from typing import List, Optional

from fastapi import HTTPException, Query, Request, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api._compat import host_attr as _host_attr
from src.config.accessor import get_env_config


# ============================================================================
# Constants
# ============================================================================

_DEFAULT_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
)

_DEFAULT_LOOPBACK_HOSTS = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]",
    "testserver",
})

_SAFE_BROWSER_METHODS = {"GET", "HEAD", "OPTIONS"}


# ============================================================================
# CORS / host parsing
# ============================================================================


def _parse_cors_origins(raw: Optional[str]) -> List[str]:
    """Parse CORS origins and reject credentialed wildcard configuration."""
    if raw is None or not raw.strip():
        return list(_DEFAULT_CORS_ORIGINS)
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    if "*" in origins:
        raise RuntimeError(
            "CORS_ORIGINS='*' is not allowed while credentials are enabled; "
            "configure explicit Web UI origins instead."
        )
    return origins


def _parse_extra_loopback_hosts(raw: Optional[str]) -> set[str]:
    """Return additional trusted Host names for loopback API traffic."""
    if raw is None or not raw.strip():
        return set()
    return {host.strip().lower().rstrip(".") for host in raw.split(",") if host.strip()}


def _get_extra_loopback_hosts() -> set[str]:
    from src.config.accessor import get_env_config
    return _parse_extra_loopback_hosts(get_env_config().api.api_allowed_hosts or None)


def _host_without_port(host: str) -> str:
    """Normalize a Host header to a lowercase hostname without a port."""
    value = host.strip().lower().rstrip(".")
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        if end != -1:
            return value[: end + 1]
        return value
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


def _is_allowed_loopback_host(host: str) -> bool:
    """Return whether *host* is allowed for loopback-trusted API requests."""
    normalized = _host_without_port(host)
    return normalized in _DEFAULT_LOOPBACK_HOSTS or normalized in _get_extra_loopback_hosts()


def _is_loopback_bind_host(host: str) -> bool:
    """Return whether *host* resolves to a loopback interface."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _get_cors_origins() -> List[str]:
    from src.config.accessor import get_env_config
    return _parse_cors_origins(get_env_config().api.cors_origins or None)


# ============================================================================
# DNS-rebinding middleware
# ============================================================================


async def _reject_untrusted_loopback_host(request: Request, call_next):
    """Block DNS-rebinding Host headers before loopback auth bypasses run."""
    if _is_local_client(request) and not _is_allowed_loopback_host(request.headers.get("host", "")):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "Untrusted local API host"},
        )
    return await call_next(request)


# ============================================================================
# Security-headers middleware
# ============================================================================

# Deny powerful browser features the app never uses.
_PERMISSIONS_POLICY = (
    "geolocation=(), camera=(), microphone=(), payment=(), usb=(), "
    "magnetometer=(), gyroscope=(), accelerometer=()"
)

# Report-Only first: a later switch to enforcing mode can be validated against
# real traffic without risking a broken app. Scoped to what the built SPA needs:
# same-origin scripts/styles/fonts/img plus same-origin fetch & EventSource.
# Inline styles are allowed because ECharts and React ``style={}`` props set
# them; fonts are self-hosted (@fontsource) so no external font host is listed.
_CSP_REPORT_ONLY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


async def _apply_security_headers(request: Request, call_next):
    """Attach baseline security response headers to every response.

    HSTS is deliberately NOT set here: the app is commonly deployed behind a
    TLS-terminating reverse proxy and cannot guarantee it is always served over
    HTTPS. Set ``Strict-Transport-Security`` at the proxy/ingress layer that
    terminates TLS instead.
    """
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("Content-Security-Policy-Report-Only", _CSP_REPORT_ONLY)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Permissions-Policy", _PERMISSIONS_POLICY)
    headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


# ============================================================================
# Access-log secret redaction
# ============================================================================

# Redact the VALUES of sensitive query params (keeping the name) from access
# logs. Uvicorn's default access logger writes the full request line including
# the query string, so without this an ``api_key=`` / ``ticket=`` value would
# land in logs verbatim.
_QUERY_SECRET_RE = re.compile(r"((?:api_key|ticket)=)[^&\s\"']+", re.IGNORECASE)


def _redact_query_secrets(text: str) -> str:
    """Replace ``api_key=``/``ticket=`` values with a fixed placeholder."""
    return _QUERY_SECRET_RE.sub(r"\1***REDACTED***", text)


class _AccessLogRedactionFilter(logging.Filter):
    """Strip secret query-param values from log records before they are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _redact_query_secrets(a) if isinstance(a, str) else a
                for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = _redact_query_secrets(record.msg)
        return True


def install_access_log_redaction_filter() -> None:
    """Attach the redaction filter to Uvicorn's access/error loggers.

    Idempotent: skips a logger that already carries the filter so repeated
    server starts in one process don't stack duplicate filters.
    """
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        target = logging.getLogger(name)
        if any(isinstance(f, _AccessLogRedactionFilter) for f in target.filters):
            continue
        target.addFilter(_AccessLogRedactionFilter())


# ============================================================================
# SSE tickets (short-lived, single-use browser EventSource credentials)
# ============================================================================

# EventSource cannot send an Authorization header, so a browser exchanges the
# header-authenticated API key for a one-shot ticket via POST /auth/sse-ticket
# and passes it as ?ticket=. This keeps the long-lived key out of URLs and logs.
_SSE_TICKET_TTL_SECONDS = 60.0
_sse_tickets: dict[str, float] = {}  # ticket -> monotonic expiry timestamp
_sse_tickets_lock = threading.Lock()


def _sweep_expired_sse_tickets_locked(now: float) -> None:
    """Drop expired tickets. Caller must hold ``_sse_tickets_lock``."""
    expired = [t for t, exp in _sse_tickets.items() if exp <= now]
    for t in expired:
        _sse_tickets.pop(t, None)


def _mint_sse_ticket() -> str:
    """Mint a single-use, ~60s ticket for one browser EventSource connection."""
    ticket = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _sse_tickets_lock:
        _sweep_expired_sse_tickets_locked(now)
        _sse_tickets[ticket] = now + _SSE_TICKET_TTL_SECONDS
    return ticket


def _consume_sse_ticket(ticket: str) -> bool:
    """Validate and invalidate a ticket; True iff it was valid and unexpired.

    Single-use: the ticket is removed on the first lookup whether or not it had
    expired, so a captured ticket can never be replayed.
    """
    if not ticket:
        return False
    now = time.monotonic()
    with _sse_tickets_lock:
        _sweep_expired_sse_tickets_locked(now)
        expiry = _sse_tickets.pop(ticket, None)
    return expiry is not None and expiry > now


# ============================================================================
# API Key Authentication
# ============================================================================

_security = HTTPBearer(auto_error=False)


def _get_api_key() -> str:
    from src.config.accessor import get_env_config
    return get_env_config().api.api_auth_key


def _configured_api_key() -> str:
    """Return the current API auth key, if configured.

    Resolves the ``VIBE_TRADING_API_KEY`` alias server-side via
    :func:`get_env_config` so both ``API_AUTH_KEY`` and the legacy
    alias produce the same key.
    """
    return (
        get_env_config().api.api_auth_key
        or _host_attr("_API_KEY", _get_api_key())
        or ""
    )


def _auth_credential_from_header_or_query(
    cred: Optional[HTTPAuthorizationCredentials],
    query_api_key: Optional[str],
    *,
    allow_query: bool,
) -> str:
    """Return the supplied API credential from the permitted source."""
    if cred and cred.credentials:
        return cred.credentials
    if allow_query and query_api_key:
        return query_api_key
    return ""


def _is_loopback_origin(origin: str) -> bool:
    """Return whether a browser Origin header names a loopback web UI."""
    try:
        parsed = urllib.parse.urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _origin_matches_request_host(origin: str, request: Request) -> bool:
    """Return whether *origin* is the same site serving this request."""
    try:
        parsed = urllib.parse.urlsplit(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False

    origin_host = parsed.hostname.rstrip(".").lower()
    origin_port = parsed.port
    request_host = _host_without_port(request.headers.get("host", ""))
    if origin_host != request_host:
        return False

    if origin_port is None:
        origin_port = 443 if parsed.scheme == "https" else 80
    request_port = request.url.port
    if request_port is None:
        request_port = 443 if request.url.scheme == "https" else 80
    return origin_port == request_port


def _reject_cross_site_browser_request(request: Request) -> None:
    """Reject unsafe browser requests from untrusted cross-site origins."""
    sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if sec_fetch_site == "cross-site":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site request denied")

    origin = request.headers.get("origin")
    if origin and not (_is_loopback_origin(origin) or _origin_matches_request_host(origin, request)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cross-site request denied")


def _require_shutdown_authorization(
    *,
    request: Request,
    cred: Optional[HTTPAuthorizationCredentials],
) -> None:
    """Authorize the local shutdown control-plane action."""
    _reject_cross_site_browser_request(request)
    api_key = _configured_api_key()
    if api_key:
        token = _auth_credential_from_header_or_query(cred, None, allow_query=False)
        if not token or not hmac.compare_digest(token, api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return
    if not _is_local_client(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API_AUTH_KEY is required for non-local API access",
        )


def _validate_api_auth(
    *,
    request: Request,
    cred: Optional[HTTPAuthorizationCredentials],
    query_api_key: Optional[str] = None,
    allow_query: bool = False,
) -> None:
    """Validate configured auth, preserving loopback-only dev mode."""
    if request.method.upper() not in _SAFE_BROWSER_METHODS:
        _reject_cross_site_browser_request(request)

    if _is_local_client(request):
        return

    api_key = _configured_api_key()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API_AUTH_KEY is required for non-local API access",
        )

    token = _auth_credential_from_header_or_query(cred, query_api_key, allow_query=allow_query)
    if not token or not hmac.compare_digest(token, api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def _is_local_client(request: Request) -> bool:
    """Return whether the request originates from a loopback client."""
    host = request.client.host if request.client else ""
    if host in {"localhost", "testclient"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    return _trusted_docker_loopback_ip(ip)


# ============================================================================
# Docker / shell helpers
# ============================================================================


def _default_gateway_ips() -> set[ipaddress.IPv4Address]:
    """Return IPv4 default gateway addresses from Linux procfs."""
    gateways: set[ipaddress.IPv4Address] = set()
    try:
        lines = Path("/proc/net/route").read_text(encoding="utf-8").splitlines()
    except OSError:
        return gateways

    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 3 or fields[1] != "00000000":
            continue
        try:
            raw = int(fields[2], 16).to_bytes(4, byteorder="little")
            gateways.add(ipaddress.IPv4Address(raw))
        except ValueError:
            continue
    return gateways


def _trusted_docker_loopback_ip(ip: ipaddress._BaseAddress) -> bool:
    """Return whether an IP is the trusted Docker host gateway."""
    if not isinstance(ip, ipaddress.IPv4Address):
        return False
    if not get_env_config().api.vibe_trading_trust_docker_loopback:
        return False
    gateway_fn = _host_attr("_default_gateway_ips", _default_gateway_ips)
    return ip in gateway_fn()


def _env_shell_tools_enabled() -> bool:
    """Return whether server-side shell tools are explicitly enabled."""
    return get_env_config().api.vibe_trading_enable_shell_tools


def _shell_tools_enabled_for_request(request: Request) -> bool:
    """Return whether this API request may expose shell tools to the agent."""
    return _env_shell_tools_enabled()


# ============================================================================
# Auth dependencies (FastAPI Depends)
# ============================================================================


async def require_auth(
    request: Request,
    cred: Optional[HTTPAuthorizationCredentials] = Security(_security),
) -> None:
    """Validate Bearer token for sensitive API endpoints."""
    _validate_api_auth(request=request, cred=cred)


async def require_event_stream_auth(
    request: Request,
    ticket: Optional[str] = Query(None),
    cred: Optional[HTTPAuthorizationCredentials] = Security(_security),
) -> None:
    """Validate auth for browser EventSource streams.

    EventSource cannot send an ``Authorization`` header, so a browser first
    mints a short-lived, single-use ticket via ``POST /auth/sse-ticket`` (which
    is itself header-authenticated) and passes it as ``?ticket=``. Non-browser
    callers keep using the bearer header unchanged. The long-lived API key is
    never accepted in the query string — that would leak it into browser
    history, proxy/access logs, and Referer headers.
    """
    if request.method.upper() not in _SAFE_BROWSER_METHODS:
        _reject_cross_site_browser_request(request)

    if _is_local_client(request):
        return

    api_key = _configured_api_key()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API_AUTH_KEY is required for non-local API access",
        )

    token = cred.credentials if (cred and cred.credentials) else ""
    if token and hmac.compare_digest(token, api_key):
        return

    if ticket and _consume_sse_ticket(ticket):
        return

    raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def require_local_or_auth(
    request: Request,
    cred: Optional[HTTPAuthorizationCredentials] = Security(_security),
) -> None:
    """Protect settings access when dev-mode auth is disabled."""
    if _configured_api_key():
        await require_auth(request, cred)
        return
    if not _is_local_client(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Settings access requires API_AUTH_KEY or a local loopback client",
        )


async def require_settings_write_auth(
    request: Request,
    cred: Optional[HTTPAuthorizationCredentials] = Security(_security),
) -> None:
    """Require explicit authorization before changing credential-routing settings."""
    api_key = _configured_api_key()
    if api_key:
        token = _auth_credential_from_header_or_query(cred, None, allow_query=False)
        if not token or not hmac.compare_digest(token, api_key):
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return

    if not _is_local_client(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Settings writes require API_AUTH_KEY or a local loopback client",
        )


_LEGACY_LAZY_NAMES = {
    "_API_KEY": _get_api_key,
    "_CORS_ORIGINS": _get_cors_origins,
    "_EXTRA_LOOPBACK_HOSTS": _get_extra_loopback_hosts,
}


def __getattr__(name: str):
    if name in _LEGACY_LAZY_NAMES:
        return _LEGACY_LAZY_NAMES[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
