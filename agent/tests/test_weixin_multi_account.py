import asyncio
from pathlib import Path
from typing import Any

import pytest

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
        self.fail_on: set[str] = set()
        self.running_result = object()
        self.send_progress = False
        self.send_tool_hints = False
        self.show_reasoning = False

    def _record(self, method: str, *args: Any) -> tuple[Any, ...]:
        call = (method, *args)
        self.calls.append(call)
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
        "src.channels.weixin_account.get_runtime_subdir",
        lambda name: tmp_path / name,
    )
    channel = WeixinChannel(
        WeixinConfig(enabled=True, allow_from=[]),
        MessageBus(),
    )
    assert list(channel.account_ids) == ["primary"]
    assert channel.account("primary").state_file == tmp_path / "weixin" / "account.json"


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
        raising=False,
    )
    monkeypatch.setattr(
        account_impl,
        "get_runtime_subdir",
        lambda name: runtime_root / "runtime" / name,
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


def test_wrapper_ignores_accounts_and_copies_primary_config(recording_runtime) -> None:
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

    assert channel.account_ids == ("primary",)
    runtime = channel.account("primary")
    assert runtime.account_id == "primary"
    assert runtime.config.enabled is True
    assert runtime.config.allow_from == ["allowed-peer"]
    assert runtime.config.base_url == "https://primary.invalid"
    assert runtime.config.route_tag == 7
    assert runtime.config.poll_timeout == 9
    assert not hasattr(runtime.config, "accounts")


def test_wrapper_syncs_flags_to_primary_runtime(recording_runtime) -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    runtime = channel.account("primary")
    channel.send_progress = False
    channel.send_tool_hints = True
    channel.show_reasoning = False

    channel._sync_flags()

    assert runtime.send_progress is False
    assert runtime.send_tool_hints is True
    assert runtime.show_reasoning is False


def test_wrapper_delegates_primary_lifecycle_and_sends(recording_runtime) -> None:
    channel = WeixinChannel(WeixinConfig(enabled=True), MessageBus())
    runtime = channel.account("primary")
    message = object()
    metadata = {"stream": "value"}

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


@pytest.mark.parametrize(
    "method",
    ["login", "start", "stop", "send", "send_delta", "is_running"],
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
