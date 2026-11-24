"""SDK client ownership and endpoint-scoped capability keys."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
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
    """Restart a rejected stream only before it emits a chunk.

    Args:
        stream: Factory for the initial stream, reused if retry is omitted.
        should_retry: Predicate that decides whether to retry the initial error. It is called only
            before the first chunk.
        retry: Optional factory for the one retry stream.

    Yields:
        Chunks from the first stream or its retry.

    Raises:
        Exception: If the initial error is ineligible for retry, occurs after a chunk, or the retry
            fails.
    """
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
    """Apply the same pre-emission retry rule to an async stream.

    Args:
        stream: Factory for the initial async stream, reused if retry is omitted.
        should_retry: Predicate that decides whether to retry the initial error. It is called only
            before the first chunk.
        retry: Optional factory for the one retry stream.

    Yields:
        Chunks from the first stream or its retry.

    Raises:
        Exception: If the initial error is ineligible for retry, occurs after a chunk, or the retry
            fails.
    """
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


Result = TypeVar("Result")


def retry_request(request: Callable[[], Result], should_retry: Callable[[Exception], bool]) -> Result:
    """Retry a rejected request once after the adapter adjusts its payload.

    Args:
        request: Callable that issues a request and is called again if the first error is retryable.
        should_retry: Predicate that decides whether to retry and may update adapter state for the
            next call.

    Returns:
        The result of the successful request.

    Raises:
        Exception: If the initial error is ineligible for retry or the retry fails.
    """
    try:
        return request()
    except Exception as exc:
        if not should_retry(exc):
            raise
        return request()


async def retry_async_request(
    request: Callable[[], Awaitable[Result]],
    should_retry: Callable[[Exception], bool],
) -> Result:
    """Retry a rejected async request once.

    Args:
        request: Callable that produces the awaitable for each attempt.
        should_retry: Predicate that decides whether to retry the initial error.

    Returns:
        The result of the successful request.

    Raises:
        Exception: If the initial error is ineligible for retry or the retry fails.
    """
    try:
        return await request()
    except Exception as exc:
        if not should_retry(exc):
            raise
        return await request()
