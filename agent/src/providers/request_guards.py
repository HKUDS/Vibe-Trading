"""Transport ownership, redirect checks and outbound header validation."""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from typing import Any
from urllib.parse import urlparse


try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


def _build_http_clients(proxy: str | None = None, *, sdk: Any = None) -> tuple[Any, Any]:
    """Build owned HTTPX clients with explicit proxy routing (None means direct)."""
    if httpx is None:
        raise RuntimeError("Explicit provider transport requires the httpx package")
    http = httpx
    if sdk is not None and not issubclass(sdk.DefaultHttpxClient, httpx.Client):
        http = import_module("httpx2")
    limits = {"limits": sdk.DEFAULT_CONNECTION_LIMITS} if sdk else {}
    sync_transport = http.HTTPTransport(proxy=proxy, trust_env=True, **limits)
    async_transport = http.AsyncHTTPTransport(proxy=proxy, trust_env=True, **limits)
    # Supplying transports bypasses the SDK's ambient proxy discovery while
    # preserving its client defaults (notably Anthropic's redirects).
    sync_cls = sdk.DefaultHttpxClient if sdk else http.Client
    async_cls = sdk.DefaultAsyncHttpxClient if sdk else http.AsyncClient
    return (
        sync_cls(transport=sync_transport),
        async_cls(transport=async_transport),
    )


class ProviderRedirectError(ValueError):
    """A provider redirect would send a request outside its configured origin."""

    status_code = 400


def _check_provider_redirect(response: Any) -> None:
    """Allow redirects only within the same scheme, host and port."""
    if response.has_redirect_location:
        source = response.request.url
        target = source.join(response.headers["location"])
        if (source.scheme, source.host, source.port) != (target.scheme, target.host, target.port):
            raise ProviderRedirectError(
                "Cross-origin provider redirect refused. Configure the final provider base URL explicitly."
            )


async def _check_async_provider_redirect(response: Any) -> None:
    """Apply the same origin check on async HTTP clients."""
    _check_provider_redirect(response)


def _guard_provider_redirects(sync_sdk: Any, async_sdk: Any) -> None:
    """Protect SDK transports without changing their ownership or defaults."""
    # Stateless hooks are safe on LangChain's shared transports; install once.
    for sdk, hook in ((sync_sdk, _check_provider_redirect), (async_sdk, _check_async_provider_redirect)):
        client = getattr(sdk, "_client", None)
        if client is not None and hook not in client.event_hooks["response"]:
            client.event_hooks["response"].append(hook)


def unwrap_provider_error(error: Exception) -> Exception:
    """Preserve a deterministic redirect refusal through SDK connection wrappers.

    Args:
        error: Exception to inspect along its explicit cause chain.

    Returns:
        The first ProviderRedirectError found, or the original exception.
    """
    cause = error
    seen = set()
    while cause is not None and id(cause) not in seen:
        if isinstance(cause, ProviderRedirectError):
            return cause
        seen.add(id(cause))
        cause = cause.__cause__
    return error


_OPENCODE_PROVIDER_NAMES = frozenset({"opencode", "opencode-go", "opencode-zen"})
_OPENCODE_SESSION_HEADER = "x-opencode-session"


def _targets_opencode(provider: str | None, base_url: str | None) -> bool:
    """Report whether requests go to the OpenCode relay."""
    normalized = (provider or "").strip().lower().replace("_", "-")
    if normalized in _OPENCODE_PROVIDER_NAMES:
        return True
    raw = (base_url or "").strip()
    if not raw:
        return False
    host = (urlparse(raw if "//" in raw else f"https://{raw}").hostname or "").lower()
    return host == "opencode.ai" or host.endswith(".opencode.ai")


_AMBIENT_OPENAI_HEADER_ENV_VARS = (
    "OPENAI_CUSTOM_HEADERS",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT_ID",
)


def _openai_custom_header_names(raw: str | None) -> tuple[str, ...]:
    """Return header names parsed by the OpenAI SDK environment format."""
    names: list[str] = []
    for line in (raw or "").split("\n"):
        colon = line.find(":")
        if colon >= 0:
            names.append(line[:colon].strip())
    return tuple(dict.fromkeys(names))


def _validate_authorization_credential(value: str, *, source: str) -> None:
    """Reject credentials that cannot form a legal ASCII Bearer header."""
    if not value:
        return
    if not value.isascii():
        raise RuntimeError(
            f"{source} contains non-ASCII characters and cannot be sent in an "
            "HTTP Authorization header. Replace it with the raw provider API key "
            "instead of pasted JSON, HTML, or formatted text."
        )
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise RuntimeError(
            f"{source} contains whitespace or control characters and cannot be "
            "sent in an HTTP Authorization header. Replace it with the raw "
            "provider API key."
        )


def _validate_explicit_headers(headers: Mapping[str, str], *, source: str) -> None:
    """Reject explicit provider headers that HTTPX cannot encode safely."""
    for name, value in headers.items():
        if not name.isascii() or not value.isascii():
            raise RuntimeError(f"{source} produces a non-ASCII HTTP header ({name!r}). Use an ASCII-only header value.")
        if "\r" in value or "\n" in value:
            raise RuntimeError(f"{source} produces an invalid multiline HTTP header ({name!r}).")
