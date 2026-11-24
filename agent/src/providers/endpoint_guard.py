"""Keep a user-supplied model endpoint on the public internet at connect time."""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from typing import Any
from urllib.parse import urlsplit

import anyio
import httpcore
import httpx


# Fake-IP proxies use the RFC 2544 range and resolve the real endpoint themselves.
_FAKE_IP_RANGE = ipaddress.ip_network("198.18.0.0/15")


def is_non_public_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address, *, resolved: bool = False
) -> bool:
    """Return whether an endpoint address is outside the public internet."""
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if resolved and address in _FAKE_IP_RANGE:
        return False
    return not address.is_global or address.is_multicast


def proxy_applies(url: str) -> bool:
    """Return whether the process proxy settings route ``url`` through a proxy."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    proxies = urllib.request.getproxies()
    if not (proxies.get(parts.scheme) or proxies.get("all")):
        return False
    return not urllib.request.proxy_bypass(host)


def _checked_address(host: str, port: int) -> str:
    """Resolve ``host`` and return one address, refusing any non-public one."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise httpcore.ConnectError(f"Provider host {host!r} could not be resolved") from exc
    addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses or any(is_non_public_address(address, resolved=True) for address in addresses):
        raise httpcore.ConnectError(
            f"Provider host {host!r} resolves to a local or private network address"
        )
    return str(addresses[0])


class _PublicOnlyBackend(httpcore.NetworkBackend):
    """Sync network backend that connects only to checked public addresses."""

    def __init__(self, inner: httpcore.NetworkBackend) -> None:
        self._inner = inner

    def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                    local_address: str | None = None, socket_options: Any = None) -> httpcore.NetworkStream:
        return self._inner.connect_tcp(
            _checked_address(host, port), port, timeout=timeout,
            local_address=local_address, socket_options=socket_options,
        )

    def connect_unix_socket(self, path: str, timeout: float | None = None,
                            socket_options: Any = None) -> httpcore.NetworkStream:
        raise httpcore.ConnectError("Unix sockets are not provider endpoints")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class _AsyncPublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """Async network backend that connects only to checked public addresses."""

    def __init__(self, inner: httpcore.AsyncNetworkBackend) -> None:
        self._inner = inner

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None,
                          local_address: str | None = None, socket_options: Any = None) -> httpcore.AsyncNetworkStream:
        address = await anyio.to_thread.run_sync(_checked_address, host, port)
        return await self._inner.connect_tcp(
            address, port, timeout=timeout,
            local_address=local_address, socket_options=socket_options,
        )

    async def connect_unix_socket(self, path: str, timeout: float | None = None,
                                  socket_options: Any = None) -> httpcore.AsyncNetworkStream:
        raise httpcore.ConnectError("Unix sockets are not provider endpoints")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _guard_pool(transport: httpx.HTTPTransport | httpx.AsyncHTTPTransport) -> None:
    """Wrap the transport's connection pool backend in the public-only check."""
    pool = getattr(transport, "_pool", None)
    inner = getattr(pool, "_network_backend", None)
    if inner is None:
        raise RuntimeError("httpx transport layout changed; cannot install the endpoint guard")
    wrapper = _AsyncPublicOnlyBackend if isinstance(transport, httpx.AsyncHTTPTransport) else _PublicOnlyBackend
    pool._network_backend = wrapper(inner)


def public_only_async_client(**client_kwargs: Any) -> httpx.AsyncClient:
    """Build an async client whose every direct connection is checked."""
    transport = httpx.AsyncHTTPTransport(proxy=None, trust_env=True)
    _guard_pool(transport)
    return httpx.AsyncClient(transport=transport, **client_kwargs)


def build_public_only_clients(**client_kwargs: Any) -> tuple[httpx.Client, httpx.AsyncClient]:
    """Build sync and async clients whose every direct connection is checked."""
    sync_transport = httpx.HTTPTransport(proxy=None, trust_env=True)
    _guard_pool(sync_transport)
    return (
        httpx.Client(transport=sync_transport, **client_kwargs),
        public_only_async_client(**client_kwargs),
    )
