"""Adapters for existing public-data readers, sharing the gateway's resources.

Readers retain their provider-specific parsing and fallback contracts. Nested
provider calls already inside a source slot run inline, never enqueue behind
that same occupied pool. Mutable files, credential-scoped reads and full pandas
frames are not persisted as public snapshots.
"""

from concurrent.futures import TimeoutError
from contextvars import ContextVar
from copy import deepcopy
from functools import wraps
import inspect
import hashlib
import json
import os
import time
import uuid

owned_source = ContextVar("gateway_owned_source", default=False)
current_gateway = ContextVar("gateway_current", default=None)


def _usable(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return False
    if not isinstance(value, (dict, list)):
        return False

    def incomplete(item):
        if isinstance(item, dict):
            if (
                item.get("error")
                or item.get("errors")
                or item.get("ok") is False
                or item.get("status") == "error"
                or item.get("complete") is False
                or item.get("_unresolved")
            ):
                return True
            return any(incomplete(child) for child in item.values())
        return isinstance(item, list) and any(incomplete(child) for child in item)

    return not incomplete(value)


def read(gateway, operation, params, acquire, *, cacheable=True):
    """Acquire an existing reader using the shared bounded queues and cache.

    Args:
        gateway: Process-wide gateway; no additional pool or cache is created.
        operation: Stable public reader identity, including its schema version.
        params: JSON request identity, never a credential or account payload.
        acquire: Zero-argument provider operation with its existing return type.
        cacheable: Whether successful JSON snapshots may be reused. Opaque
            results pass through without truncation or persistent retention.

    Returns:
        The original reader result, or a fresh decoded cached JSON value.

    Raises:
        GatewayBusy: Shared capacity is exhausted.
        TimeoutError: The existing request/source budget expired.
        Exception: The original provider exception, for its existing fallback.
    """
    from .service import GatewayBusy

    if owned_source.get():
        return acquire()
    # A source probe invoked by an existing coordinator must use that gateway's
    # source pool directly, not queue behind its own occupied coordinator.
    if current_gateway.get() is gateway:
        from .scheduling import deadline

        until = deadline.get()
        remaining = (
            gateway.config.source_timeout
            if until is None
            else min(gateway.config.source_timeout, until - time.monotonic())
        )
        if remaining <= 0:
            raise TimeoutError("Data request expired before nested acquisition")
        return gateway.invoke(lambda: acquire(), {}, remaining)
    # Only reusable snapshots need configuration/argument cache identity.
    # Opaque acquisitions keep caller validation and never share cached data.
    if cacheable:
        policy = {k: v for k, v in os.environ.items() if k.startswith("MARKET_DATA_ORDER_")}
        from src.config.accessor import get_env_config

        configuration = hashlib.sha256(get_env_config().data.model_dump_json().encode()).hexdigest()
        identity = {"arguments": params, "routing_policy": policy, "configuration": configuration}
        try:
            key = gateway._key("reader:v1:" + operation, identity)
        except (TypeError, ValueError):
            # Invalid arguments must still reach the reader's existing validation
            # inside the bounded source slot, without cache reuse or persistence.
            cacheable = False
    if not cacheable:
        key = "reader:uncached:" + uuid.uuid4().hex
    cached = gateway.cache.get(key) if cacheable else None
    if cached and time.time() - cached["stored_at"] <= gateway.config.ttl:
        return cached["payload"]["value"]
    from backtest.loaders.acquisition import source_deadline

    until = time.monotonic() + gateway.config.request_timeout
    parent_deadline = source_deadline.get()
    if parent_deadline is not None:
        until = min(until, parent_deadline)

    def execute():
        from .scheduling import deadline

        current_gateway.set(gateway)
        deadline.set(until)
        remaining = until - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Data request expired in queue")
        value = gateway.invoke(lambda: acquire(), {}, min(remaining, gateway.config.source_timeout))
        fits = not isinstance(value, str) or len(value) <= gateway.config.entry_bytes
        if cacheable and fits and _usable(value):
            # iterencode avoids building an oversized serialized duplicate of
            # a response just to discover it cannot fit in the existing cache.
            size = 0
            try:
                for part in json.JSONEncoder(allow_nan=False).iterencode({"value": value}):
                    size += len(part.encode())
                    if size > gateway.config.entry_bytes:
                        break
                else:
                    gateway.cache.put(key, {"value": value})
            except (TypeError, ValueError, OSError):
                pass
        return value

    with gateway.lock:
        flight = gateway.flights.get(key)
        if flight is None:
            if len(gateway.flights) >= gateway.config.pending:
                raise GatewayBusy("Data gateway request capacity reached; retry shortly")
            try:
                flight = gateway.coordinators.submit(execute)
            except RuntimeError as exc:
                raise GatewayBusy("Data gateway queue full or closed") from exc
            gateway.flights[key] = flight

            def release(_):
                with gateway.lock:
                    gateway.flights.pop(key, None)

            flight.add_done_callback(release)
    try:
        value = flight.result(timeout=max(0, until - time.monotonic()))
        return deepcopy(value) if cacheable and isinstance(value, (dict, list)) else value
    except TimeoutError as exc:
        flight.cancel()
        raise TimeoutError("Data gateway deadline exceeded; retry shortly") from exc


def public_data_read(*, cacheable=True):
    """Decorate a public JSON data tool without changing its public schema."""

    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def execute(self, *args, **kwargs):
            if owned_source.get():
                return function(self, *args, **kwargs)
            from . import get_gateway
            from .service import GatewayError

            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            params = {k: v for k, v in bound.arguments.items() if k != "self"}
            operation = f"tool:{type(self).__module__}.{type(self).__qualname__}"
            try:
                return read(
                    (current_gateway.get() or get_gateway()),
                    operation,
                    params,
                    lambda: function(self, *args, **kwargs),
                    cacheable=cacheable,
                )
            except (GatewayError, TimeoutError) as exc:
                return json.dumps(
                    {
                        "ok": False,
                        "status": "error",
                        "error_code": "data_gateway_unavailable",
                        "error": str(exc) or "Data source timed out; retry shortly",
                    }
                )

        execute.gateway_public_read = True
        return execute

    return decorate


def loader_read(function):
    """Bound legacy loader consumers (backtests, charts, paper and analysis).

    DataFrames keep their index, dtype and attrs. They belong to the caller,
    not the gateway cache; large frames are never silently sampled to fit it.
    """

    signature = inspect.signature(function)

    @wraps(function)
    def fetch(self, *args, **kwargs):
        if owned_source.get():
            return function(self, *args, **kwargs)
        from . import get_gateway

        gateway = current_gateway.get() or get_gateway()
        arguments = signature.bind(self, *args, **kwargs)
        codes = arguments.arguments.get("codes")
        batch_size = gateway.config.http_batch_symbols
        if not isinstance(codes, (list, tuple)) or len(codes) <= batch_size:
            return read(gateway, "loader:" + self.name, {}, lambda: function(self, *args, **kwargs), cacheable=False)
        # Existing analysis callers can ask for hundreds of symbols. Submit
        # bounded chunks sequentially instead of spending one source budget on
        # that entire universe. No extra worker, retry or timeout is introduced.
        from .scheduling import background

        combined, errors = {}, {}
        lane = background.set(True)
        try:
            for offset in range(0, len(codes), batch_size):
                arguments = signature.bind(self, *args, **kwargs)
                arguments.arguments["codes"] = codes[offset : offset + batch_size]
                part = read(
                    gateway,
                    "loader:" + self.name,
                    {},
                    lambda args=arguments.args, kwargs=arguments.kwargs: function(*args, **kwargs),
                    cacheable=False,
                )
                combined.update(part)
                if isinstance(getattr(self, "fetch_errors", None), dict):
                    errors.update(self.fetch_errors)
        finally:
            background.reset(lane)
            if isinstance(getattr(self, "fetch_errors", None), dict):
                self.fetch_errors = {**errors, **self.fetch_errors}
        return combined

    fetch.gateway_public_read = True
    return fetch


def managed_reader(function):
    """Bound a low-level reader, preserving its return type and exceptions.

    Used for reusable HTTP clients and non-JSON read results. Cache reuse belongs
    to the validated public snapshot above this boundary, never raw credentials
    or an HTTP response object.
    """

    @wraps(function)
    def acquire(*args, **kwargs):
        if owned_source.get():
            return function(*args, **kwargs)
        from . import get_gateway

        return read(
            current_gateway.get() or get_gateway(),
            getattr(function, "__module__", type(function).__module__)
            + "." + getattr(function, "__qualname__", type(function).__qualname__),
            {},
            lambda: function(*args, **kwargs),
            cacheable=False,
        )

    acquire.gateway_public_read = True
    return acquire


def public_http_get(*args, **kwargs):
    """Serve standalone skill/example GETs through shared acquisition capacity."""
    import requests
    from backtest.loaders.acquisition import source_deadline
    from .service import GatewayError

    @managed_reader
    def acquire():
        from . import get_gateway

        remaining = (source_deadline.get() or time.monotonic() + get_gateway().config.source_timeout) - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Source acquisition deadline exceeded before dispatch")
        requested = kwargs.get("timeout", remaining)
        if isinstance(requested, tuple):
            requested = tuple(min(value or remaining, remaining) for value in requested)
        else:
            requested = min(requested or remaining, remaining)
        return requests.get(*args, **{**kwargs, "timeout": requested})

    try:
        return acquire()
    except (GatewayError, TimeoutError) as exc:
        raise requests.exceptions.Timeout(str(exc) or "Data gateway acquisition timed out") from exc


def managed_async_reader(function):
    """Run a self-contained async collector in the existing bounded source pool.

    The collector must create and close its async clients inside its body.
    No private SDK object or lazy iterator may escape to the caller's loop.
    """
    import asyncio

    @wraps(function)
    async def acquire(*args, **kwargs):
        from . import get_gateway
        from backtest.loaders.acquisition import source_deadline

        gateway = current_gateway.get() or get_gateway()

        async def collect():
            until = source_deadline.get()
            remaining = gateway.config.source_timeout if until is None else until - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Async data acquisition expired")
            return await asyncio.wait_for(function(*args, **kwargs), timeout=remaining)

        if owned_source.get():
            return await collect()
        future = gateway.submit_source(lambda: asyncio.run(collect()), {}, gateway.config.source_timeout)
        return await asyncio.wait_for(asyncio.wrap_future(future), timeout=gateway.config.source_timeout)

    acquire.gateway_public_read = True
    return acquire


def availability_probe(function):
    """Keep a network availability probe bounded and preserve its boolean API."""
    wrapped = managed_reader(function)

    @wraps(function)
    def probe(*args, **kwargs):
        from .service import GatewayError

        try:
            return wrapped(*args, **kwargs)
        except (GatewayError, TimeoutError):
            return False

    probe.gateway_public_read = True
    return probe
