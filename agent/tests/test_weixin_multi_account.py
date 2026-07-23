import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import src.channels.weixin as wrapper_impl
import src.channels.weixin_account as account_impl
from src.channels.bus.queue import MessageBus
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

    async def start(self) -> None:
        self._record("start")

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


def test_one_account_failure_does_not_cancel_siblings(monkeypatch) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )

    async def exercise() -> None:
        primary_started = asyncio.Event()
        auxiliary_failed = asyncio.Event()

        async def primary_start() -> None:
            primary_started.set()
            await asyncio.Event().wait()

        async def auxiliary_start() -> None:
            auxiliary_failed.set()
            raise RuntimeError("isolated failure")

        monkeypatch.setattr(channel.account("primary"), "start", primary_start)
        monkeypatch.setattr(channel.account("account2"), "start", auxiliary_start)
        channel.account("primary")._token = "primary-test-token"
        channel.account("account2")._token = "auxiliary-test-token"
        task = asyncio.create_task(channel.start())
        await asyncio.wait_for(primary_started.wait(), 1)
        await asyncio.wait_for(auxiliary_failed.wait(), 1)
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())


def test_enabled_account_without_credentials_never_starts_qr_login(monkeypatch) -> None:
    channel = WeixinChannel(
        {"enabled": True, "accounts": {"account2": {"enabled": True}}},
        MessageBus(),
    )
    starts: list[str] = []

    async def record_start() -> None:
        starts.append("started")

    monkeypatch.setattr(channel.account("account2"), "start", record_start)
    asyncio.run(channel.start())
    assert starts == []
    assert "account2" in channel.login_required_accounts


def test_primary_wrapper_preserves_raw_route() -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    assert channel.route_for("primary", "peer-1") == "peer-1"


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
    message = object()
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
        ("start",),
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
            return await channel.send(object())
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
