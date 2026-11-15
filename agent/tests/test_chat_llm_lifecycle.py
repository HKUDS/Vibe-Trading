"""Regression tests for provider HTTP-client ownership."""

from __future__ import annotations

import asyncio

import pytest

from src.providers.chat import ChatLLM
from src.providers.settings import resolve_config
from tests.provider_helpers import provider_server as provider_server


class _SyncClient:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _AsyncClient:
    def __init__(self) -> None:
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


def _wrapper(adapter: object) -> ChatLLM:
    llm = ChatLLM.__new__(ChatLLM)
    llm._llm = adapter
    return llm


def test_close_leaves_borrowed_langchain_clients_open() -> None:
    """A short-lived wrapper must not close LangChain's shared clients."""
    sync_client = _SyncClient()
    async_client = _AsyncClient()

    class _Adapter:
        _vibe_owned_http_clients: tuple[object, ...] = ()
        root_client = sync_client
        root_async_client = async_client
        client = sync_client

    _wrapper(_Adapter()).close()

    assert sync_client.close_calls == 0
    assert async_client.close_calls == 0


def test_close_releases_only_explicitly_owned_clients() -> None:
    """Proxy-free clients created by Vibe remain instance-owned."""
    sync_client = _SyncClient()
    async_client = _AsyncClient()

    class _Adapter:
        _vibe_owned_http_clients = (sync_client, async_client, sync_client)
        root_client = object()

    _wrapper(_Adapter()).close()

    assert sync_client.close_calls == 1
    assert async_client.close_calls == 1


def test_close_schedules_owned_async_client_inside_running_loop() -> None:
    """The synchronous compatibility API must consume async close methods."""
    async_client = _AsyncClient()

    class _Adapter:
        _vibe_owned_http_clients = (async_client,)

    async def scenario() -> None:
        _wrapper(_Adapter()).close()
        await asyncio.sleep(0)

    asyncio.run(scenario())

    assert async_client.close_calls == 1


def test_aclose_awaits_owned_clients() -> None:
    sync_client = _SyncClient()
    async_client = _AsyncClient()

    class _Adapter:
        _vibe_owned_http_clients = (sync_client, async_client)

    asyncio.run(_wrapper(_Adapter()).aclose())

    assert sync_client.close_calls == 1
    assert async_client.close_calls == 1


def test_native_adapter_without_marker_keeps_legacy_cleanup() -> None:
    """Non-LangChain adapters retain the previous best-effort contract."""
    client = _SyncClient()

    class _Adapter:
        pass

    adapter = _Adapter()
    adapter.root_client = client
    adapter.client = client

    _wrapper(adapter).close()

    assert client.close_calls == 1


@pytest.mark.parametrize("provider", ["openai", "deepseek", "anthropic"])
def test_close_respects_default_transport_ownership(monkeypatch, provider_server, provider) -> None:
    """Closing one adapter releases owned clients without breaking a sibling.

    OpenAI/Anthropic borrow cached transports; DeepSeek owns its transports.
    Both must leave a sibling usable after closing the first adapter.
    """
    if provider != "openai":
        pytest.importorskip(f"langchain_{provider}")
    base_url, _ = provider_server
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    snapshot = resolve_config(environment={
        "LANGCHAIN_PROVIDER": provider, "LANGCHAIN_MODEL_NAME": "m",
        f"{provider.upper()}_API_KEY": "sk-test", f"{provider.upper()}_BASE_URL": base_url,
        "LANGCHAIN_USE_RESPONSES_API": "false", "ANTHROPIC_MAX_TOKENS": "128",
        "MAX_RETRIES": "0", "TIMEOUT_SECONDS": "5",
    })
    first, second = ChatLLM(snapshot=snapshot), ChatLLM(snapshot=snapshot)
    sync_attr, async_attr = ("_client", "_async_client") if provider == "anthropic" else ("root_client", "root_async_client")
    first_http = [getattr(first._llm, attr)._client for attr in (sync_attr, async_attr)]
    second_http = [getattr(second._llm, attr)._client for attr in (sync_attr, async_attr)]

    shared = provider != "deepseek"  # ChatDeepSeek builds its own SDK clients.
    assert all((a is b) == shared for a, b in zip(first_http, second_http))
    first.close()
    assert all(client.is_closed == (not shared) for client in first_http)
    assert all(not client.is_closed for client in second_http)
    assert second.chat([{"role": "user", "content": "still open"}]).content == "m"
    assert asyncio.run(second._llm.ainvoke("still open")).content == "m"
    asyncio.run(second.aclose())
    assert all(client.is_closed == (not shared) for client in second_http)
