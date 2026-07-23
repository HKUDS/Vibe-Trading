import asyncio
import base64
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import src.channels.weixin as wrapper_impl
import src.channels.weixin_account as account_impl
from src.channels.bus.events import InboundMessage, OutboundMessage
from src.channels.bus.queue import MessageBus
from src.channels.pairing.store import approve_code, list_pending
from src.channels.registry import discover_channel_names
from src.channels.weixin import WeixinChannel, WeixinConfig
from src.channels.weixin_account import WeixinAccountConfig, WeixinAccountRuntime
from src.channels.weixin_routing import (
    PRIMARY_ACCOUNT_ID,
    decode_aux_route,
    encode_aux_route,
    validate_account_alias,
)


class RecordingWeixinRuntime:
    def __init__(
        self,
        config: WeixinAccountConfig,
        bus: MessageBus,
        *,
        account_id: str = "primary",
    ) -> None:
        self.config = config
        self.bus = bus
        self.account_id = account_id
        self.calls: list[tuple[Any, ...]] = []
        self.flag_snapshots: list[tuple[str, bool, bool, bool]] = []
        self.fail_on: set[str] = set()
        self.running_result = object()
        self.send_progress = False
        self.send_tool_hints = False
        self.show_reasoning = False
        self.saved_credentials = True

    def _record(self, method: str, *args: Any) -> tuple[Any, ...]:
        call = (method, *args)
        self.calls.append(call)
        if method in {"login", "start", "send", "send_delta"}:
            self.flag_snapshots.append(
                (
                    method,
                    self.send_progress,
                    self.send_tool_hints,
                    self.show_reasoning,
                )
            )
        if method in self.fail_on:
            raise RuntimeError(method)
        return call

    async def login(self, force: bool = False) -> bool:
        self._record("login", force)
        return True

    async def start(self, *, allow_qr_login: bool = True) -> None:
        self._record("start", allow_qr_login)

    async def stop(self) -> None:
        self._record("stop")

    async def send(self, msg: Any) -> None:
        self._record("send", msg)

    async def send_delta(
        self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None,
    ) -> None:
        self._record("send_delta", chat_id, delta, metadata)

    @property
    def has_saved_credentials(self) -> bool:
        return self.saved_credentials

    @property
    def is_running(self) -> object:
        self._record("is_running")
        return self.running_result


@pytest.fixture
def recording_runtime(monkeypatch) -> type[RecordingWeixinRuntime]:
    monkeypatch.setattr(
        wrapper_impl.account_impl,
        "WeixinAccountRuntime",
        RecordingWeixinRuntime,
    )
    return RecordingWeixinRuntime


@pytest.fixture
def isolated_weixin_state_dir(monkeypatch, tmp_path: Path) -> Path:
    runtime_root = tmp_path / "runtime"
    monkeypatch.setattr(
        wrapper_impl,
        "get_runtime_subdir",
        lambda name: runtime_root / name,
    )
    return runtime_root / "weixin"


def test_no_accounts_builds_only_legacy_primary(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.channels.weixin_account.get_runtime_root",
        lambda: tmp_path,
    )
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=[]),
        MessageBus(),
    )
    assert list(channel.account_ids) == ["primary"]
    assert (
        channel.account("primary").state_file
        == tmp_path / "runtime" / "weixin" / "account.json"
    )


def test_auxiliary_accounts_have_confined_state_dirs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "src.channels.weixin.get_runtime_subdir",
        lambda name: tmp_path / name,
    )
    channel = WeixinChannel(
        {
            "enabled": True,
            "accounts": {
                "account2": {"enabled": False, "allow_from": []},
                "account3": {"enabled": True, "allow_from": []},
            },
        },
        MessageBus(),
    )
    assert channel.account_ids == ("primary", "account2", "account3")
    assert channel.account("account2").state_file == (
        tmp_path / "weixin" / "accounts" / "account2" / "account.json"
    )


@pytest.mark.parametrize("alias", ["primary", "../escape", "Account2"])
def test_invalid_auxiliary_alias_is_rejected(alias: str) -> None:
    with pytest.raises(ValidationError):
        WeixinConfig.model_validate({"accounts": {alias: {"enabled": True}}})


def test_one_account_failure_does_not_cancel_siblings(
    monkeypatch, isolated_weixin_state_dir: Path,
) -> None:
    channel = WeixinChannel(
        {
            "enabled": True,
            "state_dir": str(isolated_weixin_state_dir),
            "accounts": {"account2": {"enabled": True}},
        },
        MessageBus(),
    )

    async def exercise() -> None:
        primary_started = asyncio.Event()
        auxiliary_failed = asyncio.Event()
        stops: list[str] = []

        async def primary_start(*, allow_qr_login: bool = True) -> None:
            primary_started.set()
            await asyncio.Event().wait()

        async def auxiliary_start(*, allow_qr_login: bool = True) -> None:
            auxiliary_failed.set()
            raise RuntimeError("isolated failure")

        async def primary_stop() -> None:
            stops.append("primary")

        async def auxiliary_stop() -> None:
            stops.append("account2")

        monkeypatch.setattr(channel.account("primary"), "start", primary_start)
        monkeypatch.setattr(channel.account("account2"), "start", auxiliary_start)
        monkeypatch.setattr(channel.account("primary"), "stop", primary_stop)
        monkeypatch.setattr(channel.account("account2"), "stop", auxiliary_stop)
        channel.account("primary")._token = "primary-test-token"
        channel.account("account2")._token = "auxiliary-test-token"
        task = asyncio.create_task(channel.start())
        await asyncio.wait_for(primary_started.wait(), 1)
        await asyncio.wait_for(auxiliary_failed.wait(), 1)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not channel._account_tasks["primary"].done()
        await channel.stop()
        assert sorted(stops) == ["account2", "primary"]
        assert channel._account_tasks == {}
        assert channel._account_waiter is None

    asyncio.run(exercise())


def test_enabled_account_without_credentials_never_starts_qr_login(
    monkeypatch, isolated_weixin_state_dir: Path,
) -> None:
    channel = WeixinChannel(
        {
            "enabled": True,
            "state_dir": str(isolated_weixin_state_dir),
            "accounts": {"account2": {"enabled": True}},
        },
        MessageBus(),
    )
    starts: list[str] = []

    async def record_start(*, allow_qr_login: bool = True) -> None:
        starts.append("started")

    monkeypatch.setattr(channel.account("account2"), "start", record_start)
    asyncio.run(channel.start())
    assert starts == []
    assert "account2" in channel.login_required_accounts


def test_concurrent_starts_reuse_active_account_tasks(
    monkeypatch, isolated_weixin_state_dir: Path,
) -> None:
    channel = WeixinChannel(
        {
            "enabled": True,
            "state_dir": str(isolated_weixin_state_dir),
            "accounts": {"account2": {"enabled": True}},
        },
        MessageBus(),
    )

    async def exercise() -> None:
        release = asyncio.Event()
        primary_started = asyncio.Event()
        auxiliary_started = asyncio.Event()
        second_start_entered = asyncio.Event()
        starts: list[tuple[str, bool]] = []
        sync_calls = 0

        original_sync_flags = channel._sync_flags

        def sync_flags() -> None:
            nonlocal sync_calls
            sync_calls += 1
            original_sync_flags()
            if sync_calls == 2:
                second_start_entered.set()

        async def primary_start(*, allow_qr_login: bool = True) -> None:
            starts.append(("primary", allow_qr_login))
            primary_started.set()
            await release.wait()

        async def auxiliary_start(*, allow_qr_login: bool = True) -> None:
            starts.append(("account2", allow_qr_login))
            auxiliary_started.set()
            await release.wait()

        monkeypatch.setattr(channel.account("primary"), "start", primary_start)
        monkeypatch.setattr(channel.account("account2"), "start", auxiliary_start)
        monkeypatch.setattr(channel, "_sync_flags", sync_flags)
        channel.account("primary")._token = "primary-test-token"
        channel.account("account2")._token = "auxiliary-test-token"

        first = asyncio.create_task(channel.start())
        await asyncio.wait_for(primary_started.wait(), 1)
        await asyncio.wait_for(auxiliary_started.wait(), 1)
        original_tasks = dict(channel._account_tasks)
        second = asyncio.create_task(channel.start())
        try:
            await asyncio.wait_for(second_start_entered.wait(), 1)
            assert channel._account_tasks == original_tasks
            assert sorted(starts) == [
                ("account2", False),
                ("primary", False),
            ]
        finally:
            release.set()
            await asyncio.gather(first, second, return_exceptions=True)
        assert len(starts) == 2

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "cancelled_index",
    [0, 1],
    ids=["first-waiter", "second-waiter"],
)
def test_cancelled_start_waiter_does_not_cancel_shared_account_tasks(
    monkeypatch, isolated_weixin_state_dir: Path, cancelled_index: int,
) -> None:
    channel = WeixinChannel(
        {
            "enabled": True,
            "state_dir": str(isolated_weixin_state_dir),
            "accounts": {"account2": {"enabled": True}},
        },
        MessageBus(),
    )

    async def exercise() -> None:
        primary_started = asyncio.Event()
        auxiliary_started = asyncio.Event()
        second_start_entered = asyncio.Event()
        starts: list[tuple[str, bool]] = []
        stops: list[str] = []
        sync_calls = 0

        original_sync_flags = channel._sync_flags

        def sync_flags() -> None:
            nonlocal sync_calls
            sync_calls += 1
            original_sync_flags()
            if sync_calls == 2:
                second_start_entered.set()

        async def primary_start(*, allow_qr_login: bool = True) -> None:
            starts.append(("primary", allow_qr_login))
            primary_started.set()
            await asyncio.Event().wait()

        async def auxiliary_start(*, allow_qr_login: bool = True) -> None:
            starts.append(("account2", allow_qr_login))
            auxiliary_started.set()
            await asyncio.Event().wait()

        async def primary_stop() -> None:
            stops.append("primary")

        async def auxiliary_stop() -> None:
            stops.append("account2")

        monkeypatch.setattr(channel.account("primary"), "start", primary_start)
        monkeypatch.setattr(channel.account("account2"), "start", auxiliary_start)
        monkeypatch.setattr(channel.account("primary"), "stop", primary_stop)
        monkeypatch.setattr(channel.account("account2"), "stop", auxiliary_stop)
        monkeypatch.setattr(channel, "_sync_flags", sync_flags)
        channel.account("primary")._token = "primary-test-token"
        channel.account("account2")._token = "auxiliary-test-token"

        waiters = [asyncio.create_task(channel.start())]
        await asyncio.wait_for(primary_started.wait(), 1)
        await asyncio.wait_for(auxiliary_started.wait(), 1)
        shared_tasks = dict(channel._account_tasks)
        waiters.append(asyncio.create_task(channel.start()))
        await asyncio.wait_for(second_start_entered.wait(), 1)
        try:
            cancelled = waiters[cancelled_index]
            survivor = waiters[1 - cancelled_index]
            cancelled.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            await asyncio.sleep(0)

            assert sorted(starts) == [
                ("account2", False),
                ("primary", False),
            ]
            assert channel._account_tasks == shared_tasks
            assert all(not task.done() for task in shared_tasks.values())
            assert not survivor.done()

            await channel.stop()

            assert sorted(stops) == ["account2", "primary"]
            assert channel._account_tasks == {}
            assert channel._account_waiter is None
            await asyncio.wait_for(survivor, 1)
        finally:
            if channel._account_tasks:
                await channel.stop()
            for waiter in waiters:
                if not waiter.done():
                    waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)

    asyncio.run(exercise())


def test_stop_failure_does_not_skip_siblings_or_task_cleanup(
    monkeypatch, isolated_weixin_state_dir: Path,
) -> None:
    channel = WeixinChannel(
        {
            "enabled": True,
            "state_dir": str(isolated_weixin_state_dir),
            "accounts": {"account2": {"enabled": True}},
        },
        MessageBus(),
    )

    async def exercise() -> None:
        primary_started = asyncio.Event()
        auxiliary_started = asyncio.Event()
        auxiliary_stopped = asyncio.Event()

        async def primary_start(*, allow_qr_login: bool = True) -> None:
            primary_started.set()
            await asyncio.Event().wait()

        async def auxiliary_start(*, allow_qr_login: bool = True) -> None:
            auxiliary_started.set()
            await asyncio.Event().wait()

        async def primary_stop() -> None:
            raise RuntimeError("primary stop failed")

        async def auxiliary_stop() -> None:
            auxiliary_stopped.set()

        monkeypatch.setattr(channel.account("primary"), "start", primary_start)
        monkeypatch.setattr(channel.account("account2"), "start", auxiliary_start)
        monkeypatch.setattr(channel.account("primary"), "stop", primary_stop)
        monkeypatch.setattr(channel.account("account2"), "stop", auxiliary_stop)
        channel.account("primary")._token = "primary-test-token"
        channel.account("account2")._token = "auxiliary-test-token"

        start_task = asyncio.create_task(channel.start())
        await asyncio.wait_for(primary_started.wait(), 1)
        await asyncio.wait_for(auxiliary_started.wait(), 1)
        try:
            await channel.stop()
            assert auxiliary_stopped.is_set()
            assert channel._account_errors["primary"] == "RuntimeError"
            assert channel._account_tasks == {}
            await asyncio.wait_for(start_task, 1)
        finally:
            if not start_task.done():
                start_task.cancel()
            await asyncio.gather(start_task, return_exceptions=True)
            for task in channel._account_tasks.values():
                task.cancel()
            await asyncio.gather(
                *channel._account_tasks.values(),
                return_exceptions=True,
            )

    asyncio.run(exercise())


def test_credentials_are_probed_once_per_enabled_account_per_cycle(
    monkeypatch, isolated_weixin_state_dir: Path,
) -> None:
    channel = WeixinChannel(
        {
            "enabled": True,
            "state_dir": str(isolated_weixin_state_dir),
            "accounts": {"account2": {"enabled": True}},
        },
        MessageBus(),
    )
    probes = {"primary": 0, "account2": 0}
    starts: list[tuple[str, bool]] = []

    def has_saved_credentials(runtime: WeixinAccountRuntime) -> bool:
        probes[runtime.account_id] += 1
        return runtime.account_id == "primary"

    async def primary_start(*, allow_qr_login: bool = True) -> None:
        starts.append(("primary", allow_qr_login))

    async def auxiliary_start(*, allow_qr_login: bool = True) -> None:
        starts.append(("account2", allow_qr_login))

    monkeypatch.setattr(
        WeixinAccountRuntime,
        "has_saved_credentials",
        property(has_saved_credentials),
    )
    monkeypatch.setattr(channel.account("primary"), "start", primary_start)
    monkeypatch.setattr(channel.account("account2"), "start", auxiliary_start)

    asyncio.run(channel.start())

    assert probes == {"primary": 1, "account2": 1}
    assert starts == [("primary", False)]
    assert channel.login_required_accounts == frozenset({"account2"})
    assert {alias for alias, _ in starts}.isdisjoint(channel.login_required_accounts)


def test_account_runtime_noninteractive_start_skips_qr_and_closes_client(
    monkeypatch, tmp_path: Path,
) -> None:
    class FakeAsyncClient:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    client = FakeAsyncClient()
    qr_calls: list[str] = []
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(enabled=True, state_dir=str(tmp_path)),
        MessageBus(),
    )

    async def qr_login() -> bool:
        qr_calls.append("called")
        return True

    monkeypatch.setattr(account_impl.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(runtime, "_qr_login", qr_login)

    asyncio.run(runtime.start(allow_qr_login=False))

    assert qr_calls == []
    assert client.closed is True
    assert runtime._client is None
    assert runtime._running is False


def test_new_start_cycle_clears_stale_account_errors(recording_runtime) -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    runtime = channel.account("primary")

    async def exercise() -> None:
        runtime.fail_on.add("start")
        await channel.start()
        assert channel._account_errors == {"primary": "RuntimeError"}

        runtime.fail_on.clear()
        await channel.start()
        assert channel._account_errors == {}

    asyncio.run(exercise())


def test_primary_wrapper_preserves_raw_route() -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    assert channel.route_for("primary", "peer-1") == "peer-1"


def test_primary_and_auxiliary_route_selection() -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )

    assert channel.route_for("primary", "peer") == "peer"
    route = channel.route_for("account2", "peer")
    assert route == encode_aux_route("account2", "peer")
    assert channel.account_for_route(route).account_id == "account2"
    assert channel.account_for_route("peer").account_id == "primary"


def test_primary_route_rejects_auxiliary_namespace() -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )
    auxiliary_route = encode_aux_route("account2", "peer")

    with pytest.raises(ValueError):
        channel.route_for("primary", auxiliary_route)


@pytest.mark.parametrize(
    "route",
    [None, 7, {"peer": "fictional"}, "", "bad\x00peer"],
)
def test_wrapper_rejects_invalid_primary_routes(route: Any) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )

    with pytest.raises(ValueError):
        channel.account_for_route(route)


@pytest.mark.parametrize(
    "route",
    [None, 7, {"peer": "fictional"}, "", "bad\x00peer"],
)
def test_wrapper_invalid_route_does_not_send(
    route: Any, monkeypatch,
) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )
    sent: list[str] = []

    async def capture_primary(msg: OutboundMessage) -> None:
        sent.append("primary")

    async def capture_auxiliary(msg: OutboundMessage) -> None:
        sent.append("account2")

    monkeypatch.setattr(channel.account("primary"), "send", capture_primary)
    monkeypatch.setattr(channel.account("account2"), "send", capture_auxiliary)

    with pytest.raises(ValueError):
        asyncio.run(
            channel.send(
                OutboundMessage(channel="weixin", chat_id=route, content="ok")
            )
        )

    assert sent == []


def test_auxiliary_outbound_uses_selected_account(monkeypatch) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )
    sent: list[tuple[str, str]] = []

    async def capture_primary(msg: OutboundMessage) -> None:
        sent.append(("primary", msg.chat_id))

    async def capture_auxiliary(msg: OutboundMessage) -> None:
        sent.append(("account2", msg.chat_id))

    monkeypatch.setattr(channel.account("primary"), "send", capture_primary)
    monkeypatch.setattr(channel.account("account2"), "send", capture_auxiliary)
    route = encode_aux_route("account2", "peer")

    asyncio.run(
        channel.send(
            OutboundMessage(channel="weixin", chat_id=route, content="ok")
        )
    )

    assert sent == [("account2", route)]


def test_auxiliary_delta_uses_selected_account(monkeypatch) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )
    sent: list[tuple[str, str]] = []

    async def capture_primary(
        chat_id: str, delta: str, metadata: dict[str, Any] | None = None,
    ) -> None:
        sent.append(("primary", chat_id))

    async def capture_auxiliary(
        chat_id: str, delta: str, metadata: dict[str, Any] | None = None,
    ) -> None:
        sent.append(("account2", chat_id))

    monkeypatch.setattr(channel.account("primary"), "send_delta", capture_primary)
    monkeypatch.setattr(
        channel.account("account2"), "send_delta", capture_auxiliary,
    )
    route = encode_aux_route("account2", "peer")

    asyncio.run(channel.send_delta(route, "delta", {"_stream_end": True}))

    assert sent == [("account2", route)]


@pytest.mark.parametrize(
    "route",
    [
        encode_aux_route("account3", "peer"),
        "weixin-route:v1:account2:not-base64***",
    ],
)
def test_unknown_or_malformed_auxiliary_route_fails_closed(route: str) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )

    with pytest.raises(ValueError):
        channel.account_for_route(route)


def test_auxiliary_pairing_identity_is_account_scoped(tmp_path, monkeypatch) -> None:
    import src.channels.pairing.store as pairing_store

    monkeypatch.setattr(
        pairing_store,
        "_store_path",
        lambda: tmp_path / "pairing.json",
    )
    route2 = encode_aux_route("account2", "same-peer")
    route3 = encode_aux_route("account3", "same-peer")

    code2 = pairing_store.generate_code("weixin", route2)
    pending = list_pending(restrict_channel="weixin")
    assert [item["sender_id"] for item in pending] == [route2]
    assert approve_code(code2, restrict_channel="weixin") is not None
    assert pairing_store.is_approved("weixin", route2)
    assert not pairing_store.is_approved("weixin", route3)


def test_auxiliary_inbound_routes_identity_but_keeps_raw_transport_state(
    tmp_path: Path,
) -> None:
    bus = MessageBus()
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(
            enabled=True,
            allow_from=["same-peer"],
            state_dir=str(tmp_path),
        ),
        bus,
        account_id="account2",
    )
    route = encode_aux_route("account2", "same-peer")

    asyncio.run(
        runtime._process_message(
            {
                "message_id": "fictional-message",
                "from_user_id": "same-peer",
                "context_token": "fictional-context",
                "item_list": [
                    {"type": account_impl.ITEM_TEXT, "text_item": {"text": "hi"}}
                ],
            }
        )
    )
    inbound = asyncio.run(bus.consume_inbound())

    assert inbound == InboundMessage(
        channel="weixin",
        sender_id=route,
        chat_id=route,
        content="hi",
        timestamp=inbound.timestamp,
        metadata={"message_id": "fictional-message"},
    )
    assert runtime._context_tokens == {"same-peer": "fictional-context"}
    assert route not in runtime._context_tokens


def test_auxiliary_authorization_uses_raw_allowlist_and_routed_pairing(
    tmp_path: Path, monkeypatch,
) -> None:
    import src.channels.pairing.store as pairing_store

    monkeypatch.setattr(
        pairing_store,
        "_store_path",
        lambda: tmp_path / "pairing.json",
    )
    route = encode_aux_route("account2", "same-peer")
    other_route = encode_aux_route("account3", "same-peer")
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(allow_from=["same-peer"], state_dir=str(tmp_path)),
        MessageBus(),
        account_id="account2",
    )

    assert runtime.is_allowed(route)
    with pytest.raises(ValueError):
        runtime.is_allowed(other_route)

    runtime.config = runtime.config.model_copy(update={"allow_from": []})
    code = pairing_store.generate_code("weixin", route)
    assert pairing_store.approve_code(code, restrict_channel="weixin") is not None
    assert runtime.is_allowed(route)


def test_auxiliary_send_decodes_route_before_transport(monkeypatch, tmp_path: Path) -> None:
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(state_dir=str(tmp_path)),
        MessageBus(),
        account_id="account2",
    )
    runtime._client = object()
    runtime._token = "fictional-token"
    runtime._context_tokens["same-peer"] = "fictional-context"
    sent: list[tuple[str, str]] = []
    refreshed: list[str] = []

    async def capture_text(chat_id: str, content: str, context_token: str) -> None:
        sent.append((chat_id, context_token))

    async def no_typing_ticket(chat_id: str, context_token: str = "") -> str:
        return ""

    async def keep_context(chat_id: str, context_token: str) -> str:
        refreshed.append(chat_id)
        return context_token

    monkeypatch.setattr(runtime, "_send_text", capture_text)
    monkeypatch.setattr(runtime, "_get_typing_ticket", no_typing_ticket)
    monkeypatch.setattr(runtime, "_refresh_context_token_if_stale", keep_context)
    route = encode_aux_route("account2", "same-peer")

    asyncio.run(
        runtime.send(
            OutboundMessage(channel="weixin", chat_id=route, content="ok")
        )
    )

    assert refreshed == ["same-peer"]
    assert sent == [("same-peer", "fictional-context")]


def test_auxiliary_send_delta_decodes_route_before_flushing(
    monkeypatch, tmp_path: Path,
) -> None:
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(state_dir=str(tmp_path)),
        MessageBus(),
        account_id="account2",
    )
    flushed: list[str] = []

    async def capture_flush(chat_id: str) -> None:
        flushed.append(chat_id)

    monkeypatch.setattr(runtime, "_flush_tool_hints", capture_flush)
    route = encode_aux_route("account2", "same-peer")

    asyncio.run(runtime.send_delta(route, "", {"_stream_end": True}))

    assert flushed == ["same-peer"]


@pytest.mark.parametrize(
    ("account_id", "route"),
    [
        ("primary", encode_aux_route("account2", "same-peer")),
        ("account2", encode_aux_route("account3", "same-peer")),
        ("account2", "same-peer"),
    ],
)
def test_account_runtime_rejects_routes_owned_by_another_account(
    account_id: str, route: str,
) -> None:
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(),
        MessageBus(),
        account_id=account_id,
    )

    with pytest.raises(ValueError):
        asyncio.run(
            runtime.send(
                OutboundMessage(channel="weixin", chat_id=route, content="ok")
            )
        )


@pytest.mark.parametrize(
    "route",
    [None, 7, {"peer": "fictional"}, "", "bad\x00peer"],
)
def test_primary_account_runtime_rejects_invalid_raw_outbound_route(
    route: Any,
) -> None:
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(),
        MessageBus(),
        account_id="primary",
    )

    with pytest.raises(ValueError):
        asyncio.run(
            runtime.send(
                OutboundMessage(channel="weixin", chat_id=route, content="ok")
            )
        )


@pytest.mark.parametrize("sender_id", [None, ""])
def test_empty_primary_inbound_peer_has_no_side_effects(
    sender_id: Any, tmp_path: Path,
) -> None:
    bus = MessageBus()
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(
            allow_from=["*"],
            state_dir=str(tmp_path),
        ),
        bus,
        account_id="primary",
    )

    asyncio.run(
        runtime._process_message(
            {
                "message_id": "fictional-empty-peer-message",
                "from_user_id": sender_id,
                "context_token": "fictional-context",
                "item_list": [
                    {"type": account_impl.ITEM_TEXT, "text_item": {"text": "hi"}}
                ],
            }
        )
    )

    assert bus.inbound_size == 0
    assert not runtime._processed_ids
    assert not runtime._context_tokens
    assert not runtime._context_token_at
    assert not runtime.state_file.exists()


@pytest.mark.parametrize(
    "sender_id",
    [
        7,
        0,
        False,
        {"peer": "fictional"},
        "bad\x00peer",
        encode_aux_route("account2", "peer"),
    ],
)
def test_invalid_primary_inbound_peer_fails_without_side_effects(
    sender_id: Any, tmp_path: Path,
) -> None:
    bus = MessageBus()
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(
            allow_from=["*"],
            state_dir=str(tmp_path),
        ),
        bus,
        account_id="primary",
    )

    with pytest.raises(ValueError):
        asyncio.run(
            runtime._process_message(
                {
                    "message_id": "fictional-invalid-peer-message",
                    "from_user_id": sender_id,
                    "context_token": "fictional-context",
                    "item_list": [
                        {
                            "type": account_impl.ITEM_TEXT,
                            "text_item": {"text": "hi"},
                        }
                    ],
                }
            )
        )

    assert bus.inbound_size == 0
    assert not runtime._processed_ids
    assert not runtime._context_tokens
    assert not runtime._context_token_at
    assert not runtime.state_file.exists()


def test_saved_credentials_probe_does_not_create_default_state_dir(
    monkeypatch, tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime-root"
    state_dir = runtime_root / "runtime" / "weixin"
    monkeypatch.setattr(
        account_impl,
        "get_runtime_root",
        lambda: runtime_root,
    )
    runtime = WeixinAccountRuntime(WeixinAccountConfig(), MessageBus())

    assert runtime.has_saved_credentials is False
    assert not state_dir.exists()


def test_saved_credentials_probe_accepts_valid_token_json(tmp_path: Path) -> None:
    state_dir = tmp_path / "weixin-state"
    state_dir.mkdir()
    (state_dir / "account.json").write_text('{"token": "present"}', encoding="utf-8")
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(state_dir=str(state_dir)),
        MessageBus(),
    )

    assert runtime.has_saved_credentials is True


def test_saved_credentials_probe_rejects_damaged_json(tmp_path: Path) -> None:
    state_dir = tmp_path / "weixin-state"
    state_dir.mkdir()
    (state_dir / "account.json").write_text("{broken", encoding="utf-8")
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(state_dir=str(state_dir)),
        MessageBus(),
    )

    assert runtime.has_saved_credentials is False


@pytest.mark.parametrize("payload", ["null", "[]", '"value"', "1"])
def test_saved_credentials_probe_rejects_non_object_json(
    tmp_path: Path, payload: str,
) -> None:
    state_dir = tmp_path / "weixin-state"
    state_dir.mkdir()
    (state_dir / "account.json").write_text(payload, encoding="utf-8")
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(state_dir=str(state_dir)),
        MessageBus(),
    )

    assert runtime.has_saved_credentials is False


def test_wrapper_builds_accounts_and_copies_primary_config(recording_runtime) -> None:
    channel = WeixinChannel(
        WeixinConfig(
            enabled=True,
            allow_from=["allowed-peer"],
            base_url="https://primary.invalid",
            route_tag=7,
            poll_timeout=9,
            accounts={"desk": {"enabled": True}},
        ),
        MessageBus(),
    )

    assert channel.account_ids == ("primary", "desk")
    runtime = channel.account("primary")
    assert runtime.account_id == "primary"
    assert runtime.config.enabled is True
    assert runtime.config.allow_from == ["allowed-peer"]
    assert runtime.config.base_url == "https://primary.invalid"
    assert runtime.config.route_tag == 7
    assert runtime.config.poll_timeout == 9
    assert not hasattr(runtime.config, "accounts")
    auxiliary = channel.account("desk")
    assert auxiliary.account_id == "desk"
    assert auxiliary.config.enabled is True
    assert auxiliary.config.allow_from == []
    assert auxiliary.config.route_tag is None


def test_wrapper_delegates_primary_lifecycle_and_sends(recording_runtime) -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    runtime = channel.account("primary")
    message = OutboundMessage(
        channel="weixin",
        chat_id="primary-peer",
        content="ok",
    )
    metadata = {"stream": "value"}
    channel.send_progress = False
    channel.send_tool_hints = True
    channel.show_reasoning = False

    async def exercise() -> tuple[Any, ...]:
        return (
            await channel.login(force=True),
            await channel.start(),
            await channel.stop(),
            await channel.send(message),
            await channel.send_delta("chat", "delta", metadata),
        )

    assert asyncio.run(exercise()) == (
        True,
        None,
        None,
        None,
        None,
    )
    assert channel.is_running is runtime.running_result
    assert runtime.calls == [
        ("login", True),
        ("start", False),
        ("stop",),
        ("send", message),
        ("send_delta", "chat", "delta", metadata),
        ("is_running",),
    ]
    assert runtime.flag_snapshots == [
        ("login", False, True, False),
        ("start", False, True, False),
        ("send", False, True, False),
        ("send_delta", False, True, False),
    ]


@pytest.mark.parametrize(
    "method",
    ["login", "send", "send_delta", "is_running"],
)
def test_wrapper_propagates_primary_delegate_exceptions(
    recording_runtime, method: str,
) -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    runtime = channel.account("primary")
    runtime.fail_on.add(method)

    async def invoke() -> Any:
        if method == "login":
            return await channel.login()
        if method == "start":
            return await channel.start()
        if method == "stop":
            return await channel.stop()
        if method == "send":
            return await channel.send(
                OutboundMessage(
                    channel="weixin",
                    chat_id="primary-peer",
                    content="ok",
                )
            )
        return await channel.send_delta("chat", "delta")

    with pytest.raises(RuntimeError, match=method):
        if method == "is_running":
            _ = channel.is_running
        else:
            asyncio.run(invoke())


def test_wrapper_records_primary_start_exception_class(recording_runtime) -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    runtime = channel.account("primary")
    runtime.fail_on.add("start")

    asyncio.run(channel.start())

    assert channel._account_errors == {"primary": "RuntimeError"}


def test_account_alias_validation() -> None:
    assert validate_account_alias("account2") == "account2"
    assert validate_account_alias("desk_user-3") == "desk_user-3"
    for value in ("primary", "Account2", "2account", "../escape", "a" * 33):
        with pytest.raises(ValueError):
            validate_account_alias(value)


def test_aux_route_round_trip_is_account_qualified() -> None:
    route = encode_aux_route("account2", "peer:@chatroom/中文")
    assert route.startswith("weixin-route:v1:account2:")
    assert decode_aux_route(route) == ("account2", "peer:@chatroom/中文")
    assert decode_aux_route("plain-primary-peer") is None


@pytest.mark.parametrize(
    "peer_id",
    [
        None,
        7,
        {"peer": "fictional"},
        "",
        "bad\x00peer",
        encode_aux_route("account3", "peer"),
    ],
)
def test_aux_route_rejects_invalid_raw_peer_ids(peer_id: Any) -> None:
    with pytest.raises(ValueError):
        encode_aux_route("account2", peer_id)


@pytest.mark.parametrize("route", [None, 7, {"route": "fictional"}])
def test_aux_route_decode_rejects_non_string_input(route: Any) -> None:
    with pytest.raises(ValueError):
        decode_aux_route(route)


def test_aux_route_decode_rejects_nested_internal_route() -> None:
    nested_peer = encode_aux_route("account3", "peer")
    outer_route = encode_aux_route("account2", "peer")
    encoded_peer = (
        base64.urlsafe_b64encode(nested_peer.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )
    nested_route = f"{outer_route.rsplit(':', 1)[0]}:{encoded_peer}"

    with pytest.raises(ValueError):
        decode_aux_route(nested_route)


def test_aux_route_rejects_malformed_values() -> None:
    with pytest.raises(ValueError):
        decode_aux_route("weixin-route:v1:account2:not-base64***")
    with pytest.raises(ValueError):
        encode_aux_route(PRIMARY_ACCOUNT_ID, "peer")


@pytest.mark.parametrize("encoded", ["5L+A", "5L6/", "cGVlcg==", "cGVlch"])
def test_aux_route_rejects_noncanonical_base64url(encoded: str) -> None:
    with pytest.raises(ValueError, match="Malformed Weixin auxiliary route"):
        decode_aux_route(f"weixin-route:v1:account2:{encoded}")


def test_channel_discovery_excludes_weixin_helpers() -> None:
    names = set(discover_channel_names())

    assert "weixin" in names
    assert {"weixin_routing", "weixin_account"}.isdisjoint(names)
