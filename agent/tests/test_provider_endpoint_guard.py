"""A custom provider endpoint is re-checked when each connection is made.

Saving a profile checks the host once; without a connect-time check a name
that later re-resolves to a private address (DNS rebinding) would reach it.
"""

from __future__ import annotations

import asyncio

import httpcore
import httpx
import pytest

from src.providers import endpoint_guard


_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy")


def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)


def _resolve_to(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    monkeypatch.setattr(
        endpoint_guard.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, "", (address, 0)) for address in addresses],
    )


class _RecordingAsyncBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.hosts: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.hosts.append(host)
        raise httpcore.ConnectError("recorded, not connected")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise NotImplementedError

    async def sleep(self, seconds):
        return None


class _RecordingSyncBackend(httpcore.NetworkBackend):
    def __init__(self) -> None:
        self.hosts: list[str] = []

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.hosts.append(host)
        raise httpcore.ConnectError("recorded, not connected")

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise NotImplementedError

    def sleep(self, seconds):
        return None


@pytest.mark.parametrize("resolved", [("10.0.0.5",), ("100.100.100.200",), ("8.8.8.8", "127.0.0.1"), ("::ffff:169.254.169.254",)])
def test_guarded_client_refuses_a_name_that_resolves_to_a_private_address(
    monkeypatch: pytest.MonkeyPatch, resolved: tuple[str, ...]
) -> None:
    _resolve_to(monkeypatch, *resolved)

    async def run() -> None:
        async with endpoint_guard.public_only_async_client() as client:
            await client.get("https://provider.example/v1/models")

    with pytest.raises(httpx.ConnectError, match="local or private network address"):
        asyncio.run(run())


def test_guarded_backends_connect_to_the_address_they_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    _resolve_to(monkeypatch, "93.184.216.34")
    async_inner, sync_inner = _RecordingAsyncBackend(), _RecordingSyncBackend()

    with pytest.raises(httpcore.ConnectError, match="recorded"):
        asyncio.run(endpoint_guard._AsyncPublicOnlyBackend(async_inner).connect_tcp("provider.example", 443))
    with pytest.raises(httpcore.ConnectError, match="recorded"):
        endpoint_guard._PublicOnlyBackend(sync_inner).connect_tcp("provider.example", 443)

    # No second lookup by name: the inner backend dials the checked address.
    assert async_inner.hosts == ["93.184.216.34"]
    assert sync_inner.hosts == ["93.184.216.34"]


def test_guard_is_installed_on_both_clients() -> None:
    sync_client, async_client = endpoint_guard.build_public_only_clients()
    try:
        assert isinstance(sync_client._transport._pool._network_backend, endpoint_guard._PublicOnlyBackend)
        assert isinstance(async_client._transport._pool._network_backend, endpoint_guard._AsyncPublicOnlyBackend)
    finally:
        sync_client.close()
        asyncio.run(async_client.aclose())


def test_proxy_applies_follows_the_process_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_proxy(monkeypatch)
    assert not endpoint_guard.proxy_applies("https://provider.example/v1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    assert endpoint_guard.proxy_applies("https://provider.example/v1")
    monkeypatch.setenv("NO_PROXY", "provider.example")
    assert not endpoint_guard.proxy_applies("https://provider.example/v1")


def test_custom_model_uses_guarded_clients_unless_a_proxy_resolves_the_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.providers import llm, settings

    monkeypatch.setattr(settings, "_ensure_dotenv", lambda: None)
    monkeypatch.setattr(
        settings,
        "get_llm_credentials",
        lambda provider, model, **kwargs: {"provider": "custom", "model": "m", "base_url": "https://provider.example/v1", "api_key": "k"},
    )
    monkeypatch.setenv("LANGCHAIN_PROVIDER", "custom")
    monkeypatch.setenv("LANGCHAIN_MODEL_NAME", "m")
    monkeypatch.delenv("VIBE_TRADING_DISABLE_HTTP_PROXY", raising=False)
    settings.reset_env_config()

    _no_proxy(monkeypatch)
    direct = llm.build_llm()
    assert isinstance(direct.http_async_client._transport._pool._network_backend, endpoint_guard._AsyncPublicOnlyBackend)

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    proxied = llm.build_llm()
    assert proxied.http_async_client is None


def test_a_fake_ip_proxy_answer_is_allowed_but_a_written_fake_ip_is_not(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clash / Surge TUN answer every lookup from 198.18.0.0/15 (2026-10-21:
    every custom provider was refused on such a host at save time)."""
    import ipaddress

    from src.providers import custom_profiles as custom_provider_routes

    fake = ipaddress.ip_address("198.18.0.4")
    assert endpoint_guard.is_non_public_address(fake)
    assert not endpoint_guard.is_non_public_address(fake, resolved=True)
    assert endpoint_guard.is_non_public_address(ipaddress.ip_address("198.20.0.1"), resolved=True) is False
    assert endpoint_guard.is_non_public_address(ipaddress.ip_address("10.0.0.5"), resolved=True)

    _resolve_to(monkeypatch, "198.18.0.4")
    inner = _RecordingAsyncBackend()
    with pytest.raises(httpcore.ConnectError, match="recorded"):
        asyncio.run(endpoint_guard._AsyncPublicOnlyBackend(inner).connect_tcp("provider.example", 443))
    assert inner.hosts == ["198.18.0.4"]

    monkeypatch.setattr(
        custom_provider_routes.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, "", ("198.18.0.4", 0))],
    )
    custom_provider_routes._reject_private_dns_targets("https://provider.example/v1")
    with pytest.raises(ValueError, match="local or private"):
        custom_provider_routes._validate_custom_base_url("http://198.18.0.4/v1")
