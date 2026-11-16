"""Demand-driven quote distribution; shared acquisition and bounded latest state.

SSE clients receive current snapshots, not a lossless trade/event history.
A topic has one upstream task regardless of its subscriber count. Nothing is
subscribed at import or when no clients remain; stream ticks never go to disk.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import json
import math
import re
import time
from typing import Callable


@dataclass(frozen=True)
class Topic:
    """Explicit namespace prevents cross-market symbol guessing."""

    kind: str
    symbol: str
    expiration: int | None = None
    interval: str | None = None

    @property
    def key(self):
        if self.kind == "bars":
            return f"bars:{self.symbol}:{self.interval}"
        return f"{self.kind}:{self.symbol}" + (f":{self.expiration}" if self.expiration else "")

    @classmethod
    def parse(cls, value: str):
        raw = value.strip().split(":")
        parts = [p.upper() for p in raw]
        if len(parts) in (2, 3) and parts[0] == "BARS":
            from src.market_data import _SOURCE_PATTERNS

            interval = raw[2] if len(raw) == 3 else "1D"
            if interval not in {"1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W", "1M"}:
                raise ValueError("Unsupported bar interval; 1m is a minute and 1M is a month")
            if parts[1].startswith("LOCAL") or not any(pattern.match(parts[1]) for pattern, _ in _SOURCE_PATTERNS):
                raise ValueError("Expected a public symbol with its market suffix")
            return cls("bars", parts[1], interval=interval)
        if len(parts) in (2, 3) and parts[0] == "OPTIONS" and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,15}", parts[1]):
            expiration = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else None
            if len(parts) == 3 and (expiration is None or not 0 < expiration < 32503680000):
                raise ValueError("Invalid expiration")
            return cls("options", parts[1].removesuffix(".US"), expiration)
        if len(parts) == 2 and parts[0] == "CRYPTO" and re.fullmatch(r"[A-Z0-9]{2,12}-[A-Z0-9]{2,12}", parts[1]):
            return cls("crypto", parts[1])
        raise ValueError("Supported topics: options:AAPL[:expiration], crypto:BTC-USDT (OKX spot)")


@dataclass(eq=False)
class Listener:
    """One pending update per subscribed topic, regardless of upstream speed."""

    topics: tuple[Topic, ...]
    pending: dict = field(default_factory=dict)
    wake: asyncio.Event = field(default_factory=asyncio.Event)

    def put(self, key, value):
        self.pending[key] = value
        self.wake.set()

    async def take(self):
        await self.wake.wait()
        result = list(self.pending.values())
        self.pending.clear()
        self.wake.clear()
        return result


@dataclass
class Channel:
    listeners: set = field(default_factory=set)
    task: asyncio.Task | None = None
    latest: dict | None = None


def okx_quote(topic: Topic, message: dict) -> dict | None:
    """Validate public ticker events; never manufacture a missing bid or ask."""
    if message.get("arg") != {"channel": "tickers", "instId": topic.symbol}:
        return None
    rows = message.get("data")
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    if row.get("instId") != topic.symbol or row.get("instType") != "SPOT":
        return None
    try:
        bid, ask, last = (float(row[k]) for k in ("bidPx", "askPx", "last"))
        stamp = int(row["ts"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) and v > 0 for v in (bid, ask, last)) or bid > ask or stamp <= 0:
        return None
    return {
        "ok": True,
        "source": "okx",
        "market": "crypto",
        "data": {
            "symbol": topic.symbol,
            "quote_currency": topic.symbol.split("-")[1],
            "bid": bid,
            "ask": ask,
            "last": last,
            "source_time_ms": stamp,
        },
        "gateway": {
            "transport": "websocket",
            "quality": "realtime",
            "executable": False,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _public_connection(protocol, **kwargs):
    """Create an SDK connection without its self-referencing logging adapter.

    The SDK's default adapter stores the connection in ``extra['websocket']``;
    connection -> adapter -> connection retains closed TLS buffers until cyclic
    GC. Logging an immutable id preserves correlation without retaining sockets.
    """
    from .websocket import PublicConnection

    return PublicConnection(protocol, **kwargs)


async def okx_feed(topic: Topic, publish: Callable):
    """Consume OKX's unauthenticated public ticker channel; no order transport."""
    from websockets.asyncio.client import connect
    from .transport import tls_context

    async with connect(
        "wss://ws.okx.com/ws/v5/public",
        open_timeout=8,
        close_timeout=2,
        max_size=262144,
        max_queue=4,
        ssl=tls_context(),
        compression=None,
        ping_interval=None,  # The receive timeout below sends OKX application pings.
        create_connection=_public_connection,
    ) as ws:
        await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "tickers", "instId": topic.symbol}]}))
        previous = 0
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
            except asyncio.TimeoutError:
                await ws.send("ping")
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
            if raw == "pong":
                continue
            message = json.loads(raw)
            if message.get("event") == "error":
                raise ConnectionError("Public ticker subscription rejected")
            value = okx_quote(topic, message)
            if value and value["data"]["source_time_ms"] >= previous:
                previous = value["data"]["source_time_ms"]
                publish("snapshot", value)


async def okx_snapshot(topic):
    """Poll the same venue as WS; regional host failover never changes currency."""
    import httpx
    from .transport import tls_context

    async with httpx.AsyncClient(timeout=5, verify=tls_context()) as client:
        for host in ("https://www.okx.com", "https://openapi.okx.com"):
            try:
                async with client.stream(
                    "GET", host + "/api/v5/market/ticker", params={"instId": topic.symbol}
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise ValueError("Oversized ticker")
                payload = json.loads(body)
                if payload.get("code") != "0":
                    continue
                value = okx_quote(
                    topic, {"arg": {"channel": "tickers", "instId": topic.symbol}, "data": payload.get("data")}
                )
                if value:
                    value["gateway"]["transport"] = "rest_poll"
                    return value
            except (httpx.HTTPError, ValueError, KeyError):
                continue
    raise ConnectionError("Public snapshot unavailable")


class StreamHub:
    """Event-loop-owned subscription registry with reference-counted cleanup."""

    def __init__(self, gateway, crypto_feed=okx_feed, snapshot_feed=okx_snapshot):
        self.gateway = gateway
        self.config = gateway.config
        self.crypto_feed = crypto_feed
        self.snapshot_feed = snapshot_feed
        self.channels: dict[str, Channel] = {}
        self.listeners: set[Listener] = set()
        self.sequence = 0
        self.closed = False
        # Only two synchronous acquisitions may occupy the shared async executor.
        # Remaining topics wait as cancellable tasks, not blocked OS threads.
        self.acquisitions = asyncio.Semaphore(2)

    def subscribe(self, topics):
        topics = tuple(dict.fromkeys(topics))
        if not topics or len(topics) > 8:
            raise ValueError("Subscribe to between one and eight topics per connection")
        if self.closed or len(self.listeners) >= self.config.stream_clients:
            raise ValueError("Subscriber capacity reached")
        if len(set(self.channels) | {t.key for t in topics}) > self.config.stream_topics:
            raise ValueError("Topic capacity reached")
        listener = Listener(topics)
        self.listeners.add(listener)
        for topic in topics:
            channel = self.channels.setdefault(topic.key, Channel())
            channel.listeners.add(listener)
            if channel.latest:
                listener.put(topic.key, channel.latest)
            if channel.task is None:
                channel.task = asyncio.create_task(self._run(topic), name=f"market-stream:{topic.key}")
        return listener

    async def unsubscribe(self, listener):
        self.listeners.discard(listener)
        tasks = []
        for topic in listener.topics:
            channel = self.channels.get(topic.key)
            if not channel:
                continue
            channel.listeners.discard(listener)
            if not channel.listeners:
                del self.channels[topic.key]
                channel.latest = None
                channel.task.cancel()
                tasks.append(channel.task)
                channel.task = None
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            tasks.clear()
            # Let cancellation callbacks release their exception frames before
            # returning ownership to an idle caller.
            await asyncio.sleep(0)
        listener.pending.clear()
        listener.wake.clear()

    def publish(self, topic, event, payload):
        channel = self.channels.get(topic.key)
        if channel is None:
            return
        self.sequence += 1
        value = {"event": event, "id": self.sequence, "topic": topic.key, "payload": payload}
        channel.latest = value
        for listener in channel.listeners:
            listener.put(topic.key, value)

    async def _acquire(self, function, *args, **kwargs):
        from functools import partial

        await self.acquisitions.acquire()
        try:
            future = asyncio.get_running_loop().run_in_executor(None, partial(function, *args, **kwargs))
        except BaseException:
            self.acquisitions.release()
            raise

        def finished(result):
            self.acquisitions.release()
            if not result.cancelled():
                result.exception()  # Retrieve errors even after the subscriber leaves.

        future.add_done_callback(finished)
        # Cancellation detaches the subscriber, not the running thread. Keep its
        # slot until real completion so churn cannot multiply blocked workers.
        return await asyncio.shield(future)

    def _bar_snapshot(self, topic, today, days):
        from backtest.loaders.base import resample_bars, source_interval

        value = self.gateway.bars(
            codes=[topic.symbol],
            start_date=(today - timedelta(days=days)).isoformat(),
            end_date=today.isoformat(),
            interval=source_interval(topic.interval),
            max_rows=100,
        )
        if value.get("ok") and topic.interval in {"1W", "1M"}:
            import pandas as pd

            rows = value.get("data", {}).get(topic.symbol)
            if not isinstance(rows, list) or not rows:
                return {"ok": False, "error": "Cannot aggregate sampled or missing daily bars"}
            frame = pd.DataFrame(rows).set_index("trade_date")
            frame.index = pd.to_datetime(frame.index)
            frame = resample_bars(frame, topic.interval)
            frame.index = frame.index.strftime("%Y-%m-%d")
            value["data"][topic.symbol] = json.loads(frame.reset_index().to_json(orient="records"))
            value.setdefault("gateway", {}).update(base_interval="1D", derived_interval=topic.interval)
        return value

    async def _run(self, topic):
        retry = 1
        while True:
            try:
                if topic.kind == "crypto":
                    await self._hybrid(topic)
                    return
                if topic.kind == "bars":
                    today = datetime.now(timezone.utc).date()
                    days = 2 if topic.interval in {"1m", "5m", "15m", "30m", "1H", "4H"} else 40
                    value = await self._acquire(
                        self._bar_snapshot,
                        topic,
                        today,
                        days,
                    )
                    value.setdefault("gateway", {}).update({"quality": "historical_bars", "transport": "rest_poll"})
                else:
                    value = await self._acquire(
                        self.gateway.options_chain, topic.symbol, topic.expiration, full=True, allow_stale=True
                    )
                self.publish(topic, "snapshot" if value.get("ok") else "source_error", value)
                if not value.get("ok"):
                    await asyncio.sleep(min(30, max(retry, value.get("retry_after_seconds", 1))))
                    retry = min(30, retry * 2)
                    continue
                retry = 1
                refreshing = value.get("gateway", {}).get("refreshing")
                await asyncio.sleep(3 if refreshing else max(self.config.stream_poll, self.config.ttl))
            except asyncio.CancelledError:
                raise
            except Exception:
                self.publish(
                    topic,
                    "source_error",
                    {"ok": False, "error": "Source disconnected; reconnecting", "retry_after_seconds": retry},
                )
                await asyncio.sleep(retry)
                retry = min(30, retry * 2)

    async def _hybrid(self, topic):
        last_ws = 0.0
        last_source_time = 0

        def accept(event, value):
            nonlocal last_ws, last_source_time
            stamp = value.get("data", {}).get("source_time_ms", 0)
            if stamp and stamp < last_source_time:
                return
            last_source_time = max(last_source_time, stamp)
            if stamp:
                age = max(0, time.time() - stamp / 1000)
                value = {**value, "gateway": {**value.get("gateway", {}), "source_age_seconds": round(age, 3)}}
                if age > self.config.stream_quote_age:
                    value["gateway"]["quality"] = "stale"
            if value.get("gateway", {}).get("transport") == "websocket":
                last_ws = time.monotonic()
            self.publish(topic, event, value)

        async def socket_loop():
            delay = 1
            while True:
                try:
                    await self.crypto_feed(topic, accept)
                    raise ConnectionError("Feed ended")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self.publish(
                        topic,
                        "source_error",
                        {
                            "ok": False,
                            "error": "WebSocket disconnected; snapshot fallback active",
                            "retry_after_seconds": delay,
                        },
                    )
                    await asyncio.sleep(delay)
                    delay = min(30, delay * 2)

        socket = asyncio.create_task(socket_loop())
        try:
            while True:
                if time.monotonic() - last_ws >= self.config.stream_snapshot_interval:
                    started = time.monotonic()
                    try:
                        value = await asyncio.wait_for(self.snapshot_feed(topic), timeout=12)
                        # A newer socket event may have arrived during the REST request.
                        if last_ws < started:
                            accept("snapshot", value)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        if last_ws < started:
                            self.publish(
                                topic, "source_error", {"ok": False, "error": "Snapshot unavailable; reconnecting"}
                            )
                await asyncio.sleep(self.config.stream_snapshot_interval)
        finally:
            socket.cancel()
            await asyncio.gather(socket, return_exceptions=True)

    def status(self):
        return {
            "clients": len(self.listeners),
            "topics": sorted(self.channels),
            "pending_updates": sum(len(c.pending) for c in self.listeners),
            "topic_limit": self.config.stream_topics,
            "client_limit": self.config.stream_clients,
            "delivery": "latest_snapshot",
            "replay": False,
            "capabilities": {
                "bars": "existing market routes; periodically refreshed bars, not quote ticks",
                "options": "US standard contracts; delayed/unknown snapshots",
                "crypto": "OKX spot; public WebSocket with same-venue REST fallback",
            },
        }

    async def close(self):
        self.closed = True
        for listener in list(self.listeners):
            await self.unsubscribe(listener)

    async def events(self, listener, disconnected):
        """Send conflated state and heartbeats; always release abandoned subscriptions."""
        try:
            yield "retry: 3000\n\n"
            while not await disconnected():
                try:
                    values = await asyncio.wait_for(listener.take(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                for value in values:
                    yield (
                        f"id: {value['id']}\nevent: {value['event']}\n"
                        f"data: {json.dumps(value, allow_nan=False, separators=(',', ':'))}\n\n"
                    )
                await asyncio.sleep(self.config.stream_interval)
        finally:
            await self.unsubscribe(listener)
