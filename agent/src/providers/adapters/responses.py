"""OpenAI Responses stream event normalization and protocol negotiation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any


class _ResponsesMappingEvent:
    """Attribute view over a raw OpenAI Responses stream event mapping."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = dict(values)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def model_dump(self, *, exclude_none: bool = False, **_: Any) -> dict[str, Any]:
        """Expose the Pydantic method expected by LangChain's converter."""
        if exclude_none:
            return {key: value for key, value in self._values.items() if value is not None}
        return dict(self._values)


def _normalize_responses_stream_event(event: Any) -> Any:
    """Adapt raw mapping events to the attribute shape LangChain expects.

    Native OpenAI SDK streams yield typed response event objects. Some
    OpenAI-compatible gateways yield the same wire events as plain dicts;
    langchain-openai's Responses converter accesses ``event.type`` and a few
    nested attributes directly. Preserve typed events unchanged and adapt only
    the mapping form.
    """
    if not isinstance(event, Mapping):
        return event

    values = dict(event)
    for key in ("annotation", "item"):
        nested = values.get(key)
        if isinstance(nested, Mapping):
            values[key] = _ResponsesMappingEvent(nested)
    return _ResponsesMappingEvent(values)


class _ResponsesSyncStream:
    """Proxy a sync Responses stream and normalize each yielded event."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._entered: Any = None

    def __enter__(self) -> "_ResponsesSyncStream":
        self._entered = self._stream.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._stream.__exit__(*args)

    def __iter__(self) -> Iterator[Any]:
        source = self._entered if self._entered is not None else self._stream
        for event in source:
            yield _normalize_responses_stream_event(event)

    def parse(self, *args: Any, **kwargs: Any) -> "_ResponsesSyncStream":
        """Keep raw-response ``parse()`` streams behind the same proxy."""
        return _ResponsesSyncStream(self._stream.parse(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _ResponsesAsyncStream:
    """Proxy an async Responses stream and normalize each yielded event."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._entered: Any = None

    async def __aenter__(self) -> "_ResponsesAsyncStream":
        self._entered = await self._stream.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> Any:
        return await self._stream.__aexit__(*args)

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        source = self._entered if self._entered is not None else self._stream
        async for event in source:
            yield _normalize_responses_stream_event(event)

    def parse(self, *args: Any, **kwargs: Any) -> "_ResponsesAsyncStream":
        """Keep async raw-response ``parse()`` streams behind the proxy."""
        return _ResponsesAsyncStream(self._stream.parse(*args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _ResponsesSyncResource:
    """Proxy the sync Responses resource without changing non-stream calls."""

    def __init__(self, resource: Any) -> None:
        self._resource = resource

    def create(self, *args: Any, **kwargs: Any) -> Any:
        result = self._resource.create(*args, **kwargs)
        if kwargs.get("stream"):
            return _ResponsesSyncStream(result)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resource, name)


class _ResponsesAsyncResource:
    """Proxy the async Responses resource without changing non-stream calls."""

    def __init__(self, resource: Any) -> None:
        self._resource = resource

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        result = await self._resource.create(*args, **kwargs)
        if kwargs.get("stream"):
            return _ResponsesAsyncStream(result)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resource, name)


class _ResponsesSyncClient:
    """Shallow client proxy used for one sync stream call."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.responses = _ResponsesSyncResource(client.responses)
        raw_response = getattr(client, "with_raw_response", None)
        if raw_response is not None:
            self.with_raw_response = _ResponsesSyncClient(raw_response)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class _ResponsesAsyncClient:
    """Shallow client proxy used for one async stream call."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.responses = _ResponsesAsyncResource(client.responses)
        raw_response = getattr(client, "with_raw_response", None)
        if raw_response is not None:
            self.with_raw_response = _ResponsesAsyncClient(raw_response)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


# Models whose Chat Completions endpoint refused function tools and named
# /v1/responses as the way out (issue #1473). OpenAI's gpt-5.6-* answer HTTP 400
# "Function tools with reasoning_effort are not supported for <model> in
# /v1/chat/completions. To use function tools, use /v1/responses or set
# reasoning_effort to 'none'" whenever the request carries tools and the effort
# is anything but 'none' -- the model's own default when none is configured
# included. Setting 'none' would run the model without its reasoning, so the
# request is retried on /v1/responses instead, where the effort travels as
# ``reasoning.effort``. Membership is populated on that first refusal and reused
# process-wide so later calls skip the failed request.
_RESPONSES_REQUIRED: set[tuple[str, str, str]] = set()


def _is_responses_required_error(exc: BaseException) -> bool:
    """Return True when an endpoint refused tools and pointed at /v1/responses.

    Matches the endpoint's own instruction, not a model name: the message has
    to name ``reasoning_effort``, say it is not supported, and offer
    ``/v1/responses``. A gateway that merely rejects ``reasoning_effort`` as an
    unknown field does not match, because nothing says its Responses route
    would fare better.
    """
    message = str(getattr(exc, "message", "") or exc).lower()
    if "reasoning_effort" not in message or "/v1/responses" not in message:
        return False
    return "not supported" in message or "unsupported" in message
