"""SDK client ownership and endpoint-scoped capability keys."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Iterator
from importlib.metadata import PackageNotFoundError, version
from typing import Any, TypeVar

from packaging.version import InvalidVersion, Version


def _endpoint_model(client: Any) -> tuple[str, str, str]:
    """Scope learned wire behavior to a protocol, endpoint and model."""
    openai = hasattr(client, "model_name")
    return (
        "openai" if openai else "anthropic",
        str(getattr(client, "openai_api_base" if openai else "anthropic_api_url", "") or "").rstrip("/"),
        str(client.model_name if openai else client.model),
    )


def _default_async_client_is_instance_owned(package: str, first_version: str) -> bool:
    """Return whether LangChain creates a default async client per model."""
    try:
        return Version(version(package)) >= Version(first_version)
    except (InvalidVersion, PackageNotFoundError):
        return False


Chunk = TypeVar("Chunk")


def retry_stream(
    stream: Callable[[], Iterator[Chunk]],
    should_retry: Callable[[Exception], bool],
    retry: Callable[[], Iterator[Chunk]] | None = None,
) -> Iterator[Chunk]:
    """Restart a rejected stream only before it emits a chunk."""
    emitted = False
    try:
        for chunk in stream():
            emitted = True
            yield chunk
    except Exception as exc:
        if emitted or not should_retry(exc):
            raise
        yield from (retry or stream)()


async def retry_async_stream(
    stream: Callable[[], AsyncIterator[Chunk]],
    should_retry: Callable[[Exception], bool],
    retry: Callable[[], AsyncIterator[Chunk]] | None = None,
) -> AsyncIterator[Chunk]:
    """Apply the same pre-emission retry rule to an async stream."""
    emitted = False
    try:
        async for chunk in stream():
            emitted = True
            yield chunk
    except Exception as exc:
        if emitted or not should_retry(exc):
            raise
        async for chunk in (retry or stream)():
            yield chunk
