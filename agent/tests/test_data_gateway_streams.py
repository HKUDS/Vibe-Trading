"""Bounded subscriptions, event identity, cancellation and full-chain coverage."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.data_gateway.config import Config
from src.data_gateway.streams import StreamHub, Topic, okx_quote


async def no_snapshot(topic):
    await asyncio.Future()


def test_shared_subscription_drops_intermediate_updates_and_releases_last_reader(tmp_path):
    async def run():
        started, stopped = [], []

        async def feed(topic, publish):
            started.append(topic.key)
            try:
                for i in range(10000):
                    publish("snapshot", {"i": i})
                await asyncio.Future()
            finally:
                stopped.append(topic.key)

        hub = StreamHub(SimpleNamespace(config=Config(tmp_path)), crypto_feed=feed, snapshot_feed=no_snapshot)
        topic = Topic.parse("crypto:BTC-USDT")
        first = hub.subscribe([topic])
        second = hub.subscribe([topic, topic])
        latest = await asyncio.wait_for(first.take(), 1)
        assert started == [topic.key]
        assert hub.status()["pending_updates"] == 1
        assert latest[0]["payload"]["i"] == 9999
        await hub.unsubscribe(first)
        assert not stopped
        await hub.unsubscribe(second)
        assert stopped == [topic.key]
        assert hub.status()["clients"] == 0 and not hub.channels
        await hub.close()

    asyncio.run(run())


def test_capacity_failure_is_atomic_and_sse_close_releases_topics(tmp_path):
    async def run():
        async def feed(*args):
            await asyncio.Future()

        hub = StreamHub(
            SimpleNamespace(config=replace(Config(tmp_path), stream_topics=1)),
            crypto_feed=feed,
            snapshot_feed=no_snapshot,
        )
        listener = hub.subscribe([Topic.parse("crypto:BTC-USDT")])
        with pytest.raises(ValueError):
            hub.subscribe([Topic.parse("crypto:ETH-USDT")])
        assert hub.status()["clients"] == 1

        async def connected():
            return False

        stream = hub.events(listener, connected)
        assert "retry:" in await anext(stream)
        await stream.aclose()
        assert not hub.channels and not hub.listeners
        await hub.close()

    asyncio.run(run())


def test_source_failure_is_visible_then_reconnects(tmp_path):
    async def run():
        attempts = []

        async def feed(topic, publish):
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("sensitive upstream body")
            publish("snapshot", {"ok": True})
            await asyncio.Future()

        hub = StreamHub(SimpleNamespace(config=Config(tmp_path)), crypto_feed=feed, snapshot_feed=no_snapshot)
        listener = hub.subscribe([Topic.parse("crypto:BTC-USDT")])
        first = await asyncio.wait_for(listener.take(), 1)
        assert first[0]["event"] == "source_error"
        assert "sensitive" not in str(first)
        second = await asyncio.wait_for(listener.take(), 2)
        assert second[0]["event"] == "snapshot" and len(attempts) == 2
        await hub.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "topic", ["options:../etc", "options:AAPL:0", "quotes:0700.HK", "crypto:BTCUSD", "crypto:*", "options:AAPL:abc"]
)
def test_unknown_market_and_wildcard_are_not_silently_subscribed(topic):
    with pytest.raises(ValueError):
        Topic.parse(topic)


def test_quote_identity_and_nonfinite_values_are_rejected():
    topic = Topic.parse("crypto:BTC-USDT")
    message = {
        "arg": {"channel": "tickers", "instId": "BTC-USDT"},
        "data": [
            {
                "instId": "BTC-USDT",
                "instType": "SPOT",
                "bidPx": "10",
                "askPx": "11",
                "last": "10.5",
                "ts": "1800000000000",
            }
        ],
    }
    assert okx_quote(topic, message)["data"]["quote_currency"] == "USDT"
    message["data"][0]["bidPx"] = "NaN"
    assert okx_quote(topic, message) is None
    message["data"][0]["bidPx"] = "10"
    message["data"][0]["instId"] = "ETH-USDT"
    assert okx_quote(topic, message) is None


def test_bar_topics_preserve_case_sensitive_intervals_and_never_subscribe_local_files():
    assert Topic.parse("bars:AAPL.US:1m").interval == "1m"
    assert Topic.parse("bars:AAPL.US:1M").interval == "1M"
    assert Topic.parse("bars:00700.HK").key == "bars:00700.HK:1D"
    with pytest.raises(ValueError):
        Topic.parse("bars:local:file.csv")


def test_bar_subscription_polls_again_and_keeps_historical_quality(tmp_path):
    async def run():
        calls = []

        class Gateway:
            config = replace(Config(tmp_path), stream_poll=0.02, ttl=0.02)

            def bars(self, **params):
                calls.append(params)
                return {"ok": True, "data": {"AAPL.US": [{"close": 100}]}, "gateway": {}}

        hub = StreamHub(Gateway())
        listener = hub.subscribe([Topic.parse("bars:AAPL.US:1m")])
        first = (await asyncio.wait_for(listener.take(), 1))[0]
        second = (await asyncio.wait_for(listener.take(), 1))[0]
        assert len(calls) >= 2 and calls[0]["interval"] == "1m"
        assert first["payload"]["gateway"]["quality"] == "historical_bars"
        assert second["id"] > first["id"]
        await hub.close()

    asyncio.run(run())


def test_repeated_subscribe_cancel_releases_snapshot_objects(tmp_path):
    import weakref

    async def run():
        class Payload(dict):
            pass

        references = []

        async def feed(topic, publish):
            payload = Payload(ok=True, data={"blob": "x" * 100000})
            references.append(weakref.ref(payload))
            publish("snapshot", payload)
            await asyncio.Future()

        hub = StreamHub(SimpleNamespace(config=Config(tmp_path)), crypto_feed=feed, snapshot_feed=no_snapshot)
        for _ in range(100):
            listener = hub.subscribe([Topic.parse("crypto:BTC-USDT")])
            await asyncio.wait_for(listener.take(), 1)
            await hub.unsubscribe(listener)
        assert len(references) == 100
        assert all(ref() is None for ref in references)
        assert hub.status()["clients"] == hub.status()["pending_updates"] == 0
        assert not hub.channels
        await hub.close()

    asyncio.run(run())


def test_connection_logging_does_not_retain_the_connection_after_close():
    import gc
    import weakref
    from websockets.client import ClientProtocol
    from websockets.uri import parse_uri
    from src.data_gateway.streams import _public_connection
    from src.data_gateway.transport import tls_context
    import ssl

    async def run():
        enabled = gc.isenabled()
        gc.disable()
        try:
            protocol = ClientProtocol(parse_uri("wss://example.org"))
            connection = _public_connection(protocol, ping_interval=None)
            reference = weakref.ref(connection)
            assert connection.keepalive_task is None
            assert connection.logger.extra == {"websocket_id": str(connection.id)}
            del connection
            assert reference() is None  # Would fail with the SDK's self-referencing adapter.
        finally:
            if enabled:
                gc.enable()

    asyncio.run(run())
    context = tls_context()
    assert tls_context() is context
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_aborted_real_socket_releases_connection_without_cyclic_gc():
    import gc
    import weakref
    from websockets.asyncio.server import serve
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed
    from src.data_gateway.websocket import PublicConnection

    async def abort(connection):
        await connection.recv()
        connection.transport.abort()

    async def run():
        enabled = gc.isenabled()
        gc.disable()
        try:
            async with serve(abort, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                for _ in range(5):
                    async with connect(
                        f"ws://127.0.0.1:{port}",
                        create_connection=PublicConnection,
                        ping_interval=None,
                        compression=None,
                    ) as connection:
                        reference = weakref.ref(connection)
                        await connection.send("abort")
                        try:
                            await connection.recv()
                        except ConnectionClosed:
                            pass
                    del connection
                    await asyncio.sleep(0)
                    assert reference() is None
        finally:
            if enabled:
                gc.enable()

    asyncio.run(run())
