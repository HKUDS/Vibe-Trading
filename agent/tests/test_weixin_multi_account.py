import asyncio
import base64
import logging
import traceback
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import src.channels.weixin as wrapper_impl
import src.channels.weixin_account as account_impl
import src.channels.manager as manager_impl
import src.channels.pairing.store as pairing_store
import src.channels.utils as channel_utils
from src.channels.base import BaseChannel
from src.channels.bus.events import InboundMessage, OutboundMessage
from src.channels.bus.queue import MessageBus
from src.channels.manager import ChannelManager
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


class RecordingBaseChannel(BaseChannel):
    name = "redaction-test"
    display_name = "Redaction Test"

    def __init__(self, bus: MessageBus) -> None:
        super().__init__({"allow_from": []}, bus)
        self.sent: list[OutboundMessage] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


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
        self.login_result = True

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
        return self.login_result

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


def test_status_details_are_account_scoped_and_sanitized(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        wrapper_impl,
        "get_runtime_subdir",
        lambda name: tmp_path / "runtime" / name,
    )
    channel = WeixinChannel(
        {
            "enabled": True,
            "state_dir": str(tmp_path / "primary"),
            "accounts": {
                "account2": {"enabled": True},
                "account3": {"enabled": False},
            },
        },
        MessageBus(),
    )

    details = channel.status_details()

    assert set(details["accounts"]) == {"primary", "account2", "account3"}
    assert set(details["accounts"]["account2"]) == {
        "configured",
        "enabled",
        "loaded",
        "running",
        "login_required",
        "error",
    }
    assert details["accounts"]["primary"]["login_required"] is True
    assert details["accounts"]["account2"]["login_required"] is True
    assert details["accounts"]["account3"]["login_required"] is False
    serialized = repr(details)
    assert "token" not in serialized.lower()
    assert "context" not in serialized.lower()
    assert "peer" not in serialized.lower()


def test_status_details_omit_sensitive_runtime_state(recording_runtime) -> None:
    channel = WeixinChannel(
        WeixinConfig(
            enabled=True,
            accounts={"account2": {"enabled": True}},
        ),
        MessageBus(),
    )
    sensitive_values: list[str] = []
    for index, runtime in enumerate(channel._accounts.values()):
        values = [f"private-value-{index}-{suffix}" for suffix in range(6)]
        sensitive_values.extend(values)
        runtime._token = values[0]
        runtime._context_tokens = {values[1]: values[2]}
        runtime._typing_tickets = {values[1]: {"ticket": values[3]}}
        runtime._raw_peer = {"peer": values[4]}
        runtime._state_dir = Path(values[4])
        runtime._route = values[5]

    serialized = repr(channel.status_details())

    for field_name in ("token", "context", "typing", "ticket", "peer", "state", "route"):
        assert field_name not in serialized.lower()
    for value in sensitive_values:
        assert value not in serialized


def test_status_details_are_read_only_for_missing_account_state(
    monkeypatch, tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    primary_state = runtime_root / "primary"
    auxiliary_state = runtime_root / "weixin" / "accounts" / "account2"
    monkeypatch.setattr(
        wrapper_impl,
        "get_runtime_subdir",
        lambda name: runtime_root / name,
    )
    channel = WeixinChannel(
        {
            "enabled": True,
            "state_dir": str(primary_state),
            "accounts": {"account2": {"enabled": True}},
        },
        MessageBus(),
    )

    details = channel.status_details()

    assert details["accounts"]["primary"]["login_required"] is True
    assert details["accounts"]["account2"]["login_required"] is True
    assert not primary_state.exists()
    assert not auxiliary_state.exists()
    for runtime in channel._accounts.values():
        assert runtime._client is None
        assert runtime._poll_task is None


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
    assert channel.is_running is True
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


def test_login_account_selects_only_requested_runtime_and_forwards_force(
    recording_runtime,
) -> None:
    channel = WeixinChannel(
        WeixinConfig(
            enabled=True,
            accounts={"account2": {"enabled": True}},
        ),
        MessageBus(),
    )
    channel.send_progress = False
    channel.send_tool_hints = True
    channel.show_reasoning = False
    channel._login_required = {"primary", "account2"}

    assert asyncio.run(channel.login_account("account2", force=True)) is True

    assert channel.account("primary").calls == []
    auxiliary = channel.account("account2")
    assert auxiliary.calls == [("login", True)]
    assert auxiliary.flag_snapshots == [("login", False, True, False)]
    assert channel.login_required_accounts == frozenset({"primary"})


def test_legacy_login_selects_primary_when_auxiliary_is_configured(
    recording_runtime,
) -> None:
    channel = WeixinChannel(
        WeixinConfig(
            enabled=True,
            accounts={"account2": {"enabled": True}},
        ),
        MessageBus(),
    )

    assert asyncio.run(channel.login(force=True)) is True

    assert channel.account("primary").calls == [("login", True)]
    assert channel.account("account2").calls == []


def test_failed_login_keeps_account_marked_as_login_required(
    recording_runtime,
) -> None:
    channel = WeixinChannel(
        WeixinConfig(
            enabled=True,
            accounts={"account2": {"enabled": True}},
        ),
        MessageBus(),
    )
    channel._login_required = {"account2"}
    channel.account("account2").login_result = False

    assert asyncio.run(channel.login_account("account2")) is False
    assert channel.login_required_accounts == frozenset({"account2"})


def test_login_account_rejects_unknown_alias_without_leaking_configuration(
    recording_runtime,
) -> None:
    sensitive_values = ["private-peer-value", "https://private.invalid"]
    channel = WeixinChannel(
        WeixinConfig(
            enabled=True,
            allow_from=[sensitive_values[0]],
            base_url=sensitive_values[1],
            accounts={"account2": {"enabled": True}},
        ),
        MessageBus(),
    )

    with pytest.raises(KeyError) as exc_info:
        asyncio.run(channel.login_account("missing"))

    message = str(exc_info.value)
    assert message == "'Unknown configured Weixin account: missing'"
    for value in sensitive_values:
        assert value not in message


@pytest.mark.parametrize(
    ("primary_running", "auxiliary_running", "expected"),
    [
        (False, True, True),
        (False, False, False),
    ],
)
def test_wrapper_running_aggregates_all_accounts(
    recording_runtime,
    primary_running: bool,
    auxiliary_running: bool,
    expected: bool,
) -> None:
    channel = WeixinChannel(
        WeixinConfig(
            enabled=True,
            accounts={"account2": {"enabled": True}},
        ),
        MessageBus(),
    )
    channel.account("primary").running_result = primary_running
    channel.account("account2").running_result = auxiliary_running

    assert channel.is_running is expected


@pytest.mark.parametrize(
    "method",
    ["login", "is_running"],
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


@pytest.mark.parametrize("delivery_kind", ["send", "send_delta"])
def test_weixin_delivery_boundary_hides_runtime_exception_from_manager_logs(
    delivery_kind: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_peer = "FAKE-BOUNDARY-RAW-PEER-SENTINEL"
    route = encode_aux_route("account2", raw_peer)
    sentinels = {
        raw_peer,
        route,
        "FAKE-BOUNDARY-CONTEXT-TOKEN-SENTINEL",
        "https://cdn.invalid/FAKE-BOUNDARY-CDN-SENTINEL",
        "/FAKE-BOUNDARY-PRIVATE-PATH-SENTINEL/media.txt",
        "FAKE-BOUNDARY-RUNTIME-ERROR-SENTINEL",
    }
    runtime_error = RuntimeError(" ".join(sorted(sentinels)))
    channel = WeixinChannel(
        {
            "enabled": True,
            "accounts": {"account2": {"enabled": True}},
        },
        MessageBus(),
    )
    runtime = channel.account("account2")
    message = OutboundMessage(
        channel="weixin",
        chat_id=route,
        content="delta" if delivery_kind == "send_delta" else "message",
        media=["/FAKE-BOUNDARY-PRIVATE-PATH-SENTINEL/media.txt"],
        metadata={"_stream_delta": True} if delivery_kind == "send_delta" else {},
    )

    async def fail_send(msg: OutboundMessage) -> None:
        del msg
        raise runtime_error

    async def fail_send_delta(
        chat_id: str,
        delta: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        del chat_id, delta, metadata
        raise runtime_error

    monkeypatch.setattr(runtime, "send", fail_send)
    monkeypatch.setattr(runtime, "send_delta", fail_send_delta)

    async def invoke_wrapper() -> None:
        if delivery_kind == "send_delta":
            await channel.send_delta(route, "delta", message.metadata)
        else:
            await channel.send(message)

    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="src.channels.base.weixin"):
        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(invoke_wrapper())

    assert type(exc_info.value).__name__ == "WeixinDeliveryError"
    assert str(exc_info.value) == "Weixin delivery failed"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert "account=account2" in caplog.text
    assert "RuntimeError" in caplog.text
    for sentinel in sentinels:
        assert sentinel not in caplog.text
    direct_traceback = "".join(
        traceback.format_exception(
            type(exc_info.value),
            exc_info.value,
            exc_info.value.__traceback__,
        )
    )
    for sentinel in sentinels:
        assert sentinel not in direct_traceback

    manager = ChannelManager.__new__(ChannelManager)
    manager.config = {"send_max_retries": 1}
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger=manager_impl.__name__):
        asyncio.run(manager._send_with_retry(channel, message))

    assert "Weixin delivery failed" in caplog.text
    for sentinel in sentinels:
        assert sentinel not in caplog.text


def test_run_account_log_omits_runtime_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    exception_sentinel = "FAKE-RUN-ACCOUNT-EXCEPTION-SENTINEL"
    channel = WeixinChannel(
        {
            "enabled": True,
            "accounts": {"account2": {"enabled": True}},
        },
        MessageBus(),
    )

    async def fail_start(*, allow_qr_login: bool = True) -> None:
        del allow_qr_login
        raise RuntimeError(exception_sentinel)

    monkeypatch.setattr(channel.account("account2"), "start", fail_start)

    with caplog.at_level(logging.ERROR, logger="src.channels.base.weixin"):
        asyncio.run(channel._run_account("account2"))

    assert channel._account_errors == {"account2": "RuntimeError"}
    assert "account=account2" in caplog.text
    assert "RuntimeError" in caplog.text
    assert exception_sentinel not in caplog.text


def test_wrapper_records_primary_start_exception_class(recording_runtime) -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    runtime = channel.account("primary")
    runtime.fail_on.add("start")

    asyncio.run(channel.start())

    assert channel._account_errors == {"primary": "RuntimeError"}
    details = channel.status_details()
    assert details["accounts"]["primary"]["error"] == "RuntimeError"
    assert "start" not in repr(details)


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


def test_opaque_log_id_is_stable_fixed_length_and_hides_original() -> None:
    raw_value = "FAKE-OPAQUE-ID-SENTINEL"

    first = channel_utils.opaque_log_id(raw_value)
    second = channel_utils.opaque_log_id(raw_value)

    assert first == second
    assert first.startswith("id:")
    assert len(first) == 15
    assert raw_value not in first


def test_pairing_mutation_logs_never_include_codes_or_senders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_sender = "FAKE-PAIRING-SENDER-SENTINEL"
    fake_characters = iter("FAKE0000DENY0000")
    monkeypatch.setattr(
        pairing_store,
        "_store_path",
        lambda: tmp_path / "pairing.json",
    )
    monkeypatch.setattr(
        pairing_store.secrets,
        "choice",
        lambda alphabet: next(fake_characters),
    )

    with caplog.at_level(logging.INFO, logger=pairing_store.__name__):
        approved_code = pairing_store.generate_code("weixin", fake_sender)
        assert pairing_store.approve_code(approved_code) == ("weixin", fake_sender)
        assert pairing_store.revoke("weixin", fake_sender) is True
        denied_code = pairing_store.generate_code("weixin", fake_sender)
        assert pairing_store.deny_code(denied_code) is True

    assert approved_code == "FAKE-0000"
    assert denied_code == "DENY-0000"
    assert "weixin" in caplog.text
    for sentinel in (fake_sender, approved_code, denied_code):
        assert sentinel not in caplog.text


def test_base_channel_pairing_reply_keeps_code_but_logs_only_opaque_sender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_sender = "FAKE-BASE-SENDER-SENTINEL"
    raw_chat = "FAKE-BASE-CHAT-SENTINEL"
    fake_characters = iter("PAIR0000")
    monkeypatch.setattr(
        pairing_store,
        "_store_path",
        lambda: tmp_path / "pairing.json",
    )
    monkeypatch.setattr(
        pairing_store.secrets,
        "choice",
        lambda alphabet: next(fake_characters),
    )
    channel = RecordingBaseChannel(MessageBus())

    with caplog.at_level(logging.INFO, logger="src.channels.base"):
        asyncio.run(
            channel._handle_message(
                sender_id=raw_sender,
                chat_id=raw_chat,
                content="",
                is_dm=True,
            )
        )

    assert len(channel.sent) == 1
    outbound = channel.sent[0]
    assert "PAIR-0000" in outbound.content
    assert outbound.metadata == {"_pairing_code": "PAIR-0000"}
    assert channel_utils.opaque_log_id(raw_sender) in caplog.text
    for sentinel in (raw_sender, raw_chat, "PAIR-0000"):
        assert sentinel not in caplog.text


def test_base_channel_group_denial_log_uses_only_opaque_sender(
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_sender = "FAKE-BASE-GROUP-SENDER-SENTINEL"
    raw_chat = "FAKE-BASE-GROUP-CHAT-SENTINEL"
    channel = RecordingBaseChannel(MessageBus())

    with caplog.at_level(logging.WARNING, logger="src.channels.base"):
        asyncio.run(
            channel._handle_message(
                sender_id=raw_sender,
                chat_id=raw_chat,
                content="",
                is_dm=False,
            )
        )

    assert channel.sent == []
    assert "channel=redaction-test" in caplog.text
    assert channel_utils.opaque_log_id(raw_sender) in caplog.text
    assert raw_sender not in caplog.text
    assert raw_chat not in caplog.text


def test_weixin_inbound_log_uses_account_and_opaque_peer_only(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_peer = "FAKE-WEIXIN-RAW-PEER-SENTINEL"
    route = encode_aux_route("account2", raw_peer)
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(
            allow_from=[raw_peer],
            state_dir=str(tmp_path),
        ),
        MessageBus(),
        account_id="account2",
    )

    with caplog.at_level(logging.INFO, logger="src.channels.base.weixin"):
        asyncio.run(
            runtime._process_message(
                {
                    "message_id": "FAKE-INBOUND-MESSAGE",
                    "from_user_id": raw_peer,
                    "context_token": "FAKE-INBOUND-CONTEXT",
                    "item_list": [
                        {
                            "type": account_impl.ITEM_TEXT,
                            "text_item": {"text": "hello"},
                        }
                    ],
                }
            )
        )

    assert "account=account2" in caplog.text
    assert channel_utils.opaque_log_id(raw_peer) in caplog.text
    assert "items=1" in caplog.text
    assert "bodyLen=5" in caplog.text
    assert raw_peer not in caplog.text
    assert route not in caplog.text


def test_weixin_login_success_logs_opaque_bot_and_user_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake_token = "FAKE-LOGIN-TOKEN-SENTINEL"
    fake_bot_id = "FAKE-LOGIN-BOT-ID-SENTINEL"
    fake_user_id = "FAKE-LOGIN-USER-ID-SENTINEL"
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(state_dir=str(tmp_path)),
        MessageBus(),
        account_id="account2",
    )
    runtime._running = True

    async def fake_fetch_qr_code() -> tuple[str, str]:
        return "FAKE-QR-ID", "FAKE-QR-SCAN-URL"

    async def fake_qr_status(**kwargs: Any) -> dict[str, str]:
        del kwargs
        return {
            "status": "confirmed",
            "bot_token": fake_token,
            "ilink_bot_id": fake_bot_id,
            "ilink_user_id": fake_user_id,
        }

    monkeypatch.setattr(runtime, "_fetch_qr_code", fake_fetch_qr_code)
    monkeypatch.setattr(runtime, "_api_get_with_base", fake_qr_status)
    monkeypatch.setattr(runtime, "_print_qr_code", lambda value: None)

    with caplog.at_level(logging.INFO, logger="src.channels.base.weixin"):
        assert asyncio.run(runtime._qr_login()) is True

    assert "account=account2" in caplog.text
    assert channel_utils.opaque_log_id(fake_bot_id) in caplog.text
    assert channel_utils.opaque_log_id(fake_user_id) in caplog.text
    for sentinel in (fake_token, fake_bot_id, fake_user_id):
        assert sentinel not in caplog.text


def test_weixin_message_exception_log_does_not_include_peer_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_peer = "FAKE-EXCEPTION-PEER-SENTINEL"

    class FakeClient:
        timeout: Any = None

    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(state_dir=str(tmp_path)),
        MessageBus(),
        account_id="account2",
    )
    runtime._client = FakeClient()  # type: ignore[assignment]

    async def fake_api_post(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        del endpoint, body
        return {"msgs": [{"from_user_id": raw_peer}]}

    async def fail_processing(msg: dict[str, Any]) -> None:
        raise RuntimeError(f"failed while processing {msg['from_user_id']}")

    monkeypatch.setattr(runtime, "_api_post", fake_api_post)
    monkeypatch.setattr(runtime, "_process_message", fail_processing)

    with caplog.at_level(logging.ERROR, logger="src.channels.base.weixin"):
        asyncio.run(runtime._poll_once())

    assert "account=account2" in caplog.text
    assert "RuntimeError" in caplog.text
    assert raw_peer not in caplog.text


def test_weixin_typing_failure_logs_use_opaque_peer_and_exception_class(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_peer = "FAKE-TYPING-PEER-SENTINEL"
    exception_sentinel = "FAKE-TYPING-EXCEPTION-SENTINEL"
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(state_dir=str(tmp_path)),
        MessageBus(),
        account_id="account2",
    )
    runtime._client = object()  # type: ignore[assignment]
    runtime._token = "FAKE-TYPING-TOKEN"

    async def fail_ticket(chat_id: str, context_token: str = "") -> str:
        del chat_id, context_token
        raise RuntimeError(exception_sentinel)

    async def fail_send_typing(user_id: str, ticket: str, status: int) -> None:
        del user_id, ticket, status
        raise RuntimeError(exception_sentinel)

    monkeypatch.setattr(runtime, "_get_typing_ticket", fail_ticket)
    with caplog.at_level(logging.DEBUG, logger="src.channels.base.weixin"):
        asyncio.run(runtime._start_typing(raw_peer, "FAKE-CONTEXT"))
        runtime._typing_tickets[raw_peer] = {"ticket": "FAKE-TICKET"}
        monkeypatch.setattr(runtime, "_send_typing", fail_send_typing)
        asyncio.run(runtime._stop_typing(raw_peer, clear_remote=True))

    assert "account=account2" in caplog.text
    assert channel_utils.opaque_log_id(raw_peer) in caplog.text
    assert "RuntimeError" in caplog.text
    assert raw_peer not in caplog.text
    assert exception_sentinel not in caplog.text


def test_weixin_media_failure_log_omits_full_path_and_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_peer = "FAKE-MEDIA-PEER"
    private_dir = "/FAKE-PRIVATE-DIR-SENTINEL"
    filename = "东方财富_姓名_账号1234_交易记录.xlsx"
    media_path = f"{private_dir}/{filename}"
    exception_sentinel = "FAKE-MEDIA-EXCEPTION-SENTINEL"
    runtime = WeixinAccountRuntime(
        WeixinAccountConfig(state_dir=str(tmp_path)),
        MessageBus(),
    )
    runtime._client = object()  # type: ignore[assignment]
    runtime._token = "FAKE-MEDIA-TOKEN"
    runtime._context_tokens[raw_peer] = "FAKE-MEDIA-CONTEXT"

    async def keep_context(chat_id: str, context_token: str) -> str:
        del chat_id
        return context_token

    async def no_ticket(chat_id: str, context_token: str = "") -> str:
        del chat_id, context_token
        return ""

    async def fail_media(chat_id: str, path: str, context_token: str) -> None:
        del chat_id, path, context_token
        raise RuntimeError(exception_sentinel)

    fallback_messages: list[str] = []

    async def capture_fallback(chat_id: str, text: str, context_token: str) -> None:
        del chat_id, context_token
        fallback_messages.append(text)

    monkeypatch.setattr(runtime, "_refresh_context_token_if_stale", keep_context)
    monkeypatch.setattr(runtime, "_get_typing_ticket", no_ticket)
    monkeypatch.setattr(runtime, "_send_media_file", fail_media)
    monkeypatch.setattr(runtime, "_send_text", capture_fallback)

    with caplog.at_level(logging.ERROR, logger="src.channels.base.weixin"):
        asyncio.run(
            runtime.send(
                OutboundMessage(
                    channel="weixin",
                    chat_id=raw_peer,
                    content="",
                    media=[media_path],
                )
            )
        )

    assert filename not in caplog.text
    assert fallback_messages == [f"[Failed to send: {filename}]"]
    assert "RuntimeError" in caplog.text
    assert private_dir not in caplog.text
    assert exception_sentinel not in caplog.text


@pytest.mark.parametrize(
    "operation",
    [account_impl._encrypt_aes_ecb, account_impl._decrypt_aes_ecb],
)
def test_weixin_aes_parse_failure_log_omits_exception_text(
    operation: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    exception_sentinel = "FAKE-AES-KEY-EXCEPTION-SENTINEL"

    def fail_key_parse(value: str) -> bytes:
        del value
        raise RuntimeError(exception_sentinel)

    monkeypatch.setattr(account_impl, "_parse_aes_key", fail_key_parse)

    with caplog.at_level(logging.WARNING, logger=account_impl.__name__):
        assert operation(b"fake-data", "FAKE-AES-KEY") == b"fake-data"

    assert "RuntimeError" in caplog.text
    assert exception_sentinel not in caplog.text
