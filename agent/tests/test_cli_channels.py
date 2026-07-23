"""CLI coverage for IM channel commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from cli import _legacy


def test_channels_parser_accepts_status_start_stop_login_and_pairing() -> None:
    parser = _legacy._build_parser()

    status = parser.parse_args(["channels", "status", "--local", "--json"])
    assert status.command == "channels"
    assert status.channels_command == "status"
    assert status.local is True
    assert status.channels_json is True

    start = parser.parse_args(["channels", "start"])
    assert start.channels_command == "start"

    stop = parser.parse_args(["channels", "stop"])
    assert stop.channels_command == "stop"

    login = parser.parse_args(
        ["channels", "login", "weixin", "--account", "account2", "--force"]
    )
    assert login.channels_command == "login"
    assert login.channel_name == "weixin"
    assert login.account_id == "account2"
    assert login.force is True

    legacy_login = parser.parse_args(["channels", "login", "weixin"])
    assert legacy_login.channel_name == "weixin"
    assert legacy_login.account_id == "primary"
    assert legacy_login.force is False

    pairing = parser.parse_args(["channels", "pairing", "--channel", "telegram", "approve", "ABCD-EFGH"])
    assert pairing.channels_command == "pairing"
    assert pairing.channel == "telegram"
    assert pairing.pairing_command == "approve"
    assert pairing.pairing_args == ["ABCD-EFGH"]


def test_channels_login_dispatch_forwards_account_id_and_force(monkeypatch) -> None:
    captured = {}

    def fake_login(
        channel_name: str,
        *,
        account_id: str,
        force: bool,
    ) -> int:
        captured["channel_name"] = channel_name
        captured["account_id"] = account_id
        captured["force"] = force
        return _legacy.EXIT_SUCCESS

    monkeypatch.setattr(_legacy, "cmd_channels_login", fake_login)

    assert (
        _legacy.main(
            ["channels", "login", "weixin", "--account", "account2", "--force"]
        )
        == _legacy.EXIT_SUCCESS
    )
    assert captured == {
        "channel_name": "weixin",
        "account_id": "account2",
        "force": True,
    }


def _install_login_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    channel_name: str,
    section: dict[str, Any],
    adapter: Any,
) -> None:
    import src.channels.config as channel_config
    import src.channels.manager as channel_manager

    monkeypatch.setattr(
        channel_config,
        "load_channels_config",
        lambda: {channel_name: section},
    )

    class FakeManager:
        def __init__(self, config: dict[str, Any], bus: Any) -> None:
            self.config = config
            self.bus = bus

        def get_channel(self, name: str) -> Any:
            assert name == channel_name
            return adapter

    monkeypatch.setattr(channel_manager, "ChannelManager", FakeManager)


def test_channels_login_selects_requested_weixin_account(monkeypatch) -> None:
    calls = []

    class FakeWeixinAdapter:
        async def login_account(
            self,
            account_id: str,
            *,
            force: bool = False,
        ) -> bool:
            calls.append((account_id, force))
            return True

    _install_login_adapter(
        monkeypatch,
        channel_name="weixin",
        section={"enabled": True, "accounts": {"account2": {"enabled": True}}},
        adapter=FakeWeixinAdapter(),
    )

    assert (
        _legacy.cmd_channels_login(
            "weixin",
            account_id="account2",
            force=True,
        )
        == _legacy.EXIT_SUCCESS
    )
    assert calls == [("account2", True)]


def test_channels_login_preserves_default_behavior_for_other_channels(
    monkeypatch,
) -> None:
    calls = []

    class FakeAdapter:
        async def login(self, force: bool = False) -> bool:
            calls.append(force)
            return True

    _install_login_adapter(
        monkeypatch,
        channel_name="feishu",
        section={"enabled": True},
        adapter=FakeAdapter(),
    )

    assert _legacy.cmd_channels_login("feishu", force=True) == _legacy.EXIT_SUCCESS
    assert calls == [True]


def test_channels_login_rejects_account_for_non_weixin_before_loading_config(
    monkeypatch,
    capsys,
) -> None:
    import src.channels.config as channel_config

    def fail_if_loaded():
        raise AssertionError("configuration should not be loaded")

    monkeypatch.setattr(channel_config, "load_channels_config", fail_if_loaded)

    assert (
        _legacy.cmd_channels_login("feishu", account_id="account2")
        == _legacy.EXIT_USAGE_ERROR
    )
    output = capsys.readouterr().out
    assert "--account is supported only for the weixin channel." in output


def test_channels_login_reports_unknown_weixin_account_without_secrets(
    monkeypatch,
    capsys,
) -> None:
    sensitive_values = ["private-config-value", "private-runtime-value"]

    class FakeWeixinAdapter:
        runtime_secret = sensitive_values[1]

        async def login_account(
            self,
            account_id: str,
            *,
            force: bool = False,
        ) -> bool:
            raise KeyError(f"Unknown configured Weixin account: {account_id}")

    _install_login_adapter(
        monkeypatch,
        channel_name="weixin",
        section={"enabled": True, "private": sensitive_values[0]},
        adapter=FakeWeixinAdapter(),
    )

    assert (
        _legacy.cmd_channels_login("weixin", account_id="missing")
        == _legacy.EXIT_USAGE_ERROR
    )
    output = capsys.readouterr().out
    assert "Unknown configured Weixin account: missing" in output
    for value in sensitive_values:
        assert value not in output


def test_channels_pairing_command_runs_against_local_store(tmp_path: Path, monkeypatch) -> None:
    import src.channels.pairing.store as pairing_store

    monkeypatch.setattr(pairing_store, "_store_path", lambda: tmp_path / "pairing.json")

    assert _legacy.main(["channels", "pairing", "--channel", "telegram", "list"]) == _legacy.EXIT_SUCCESS


def test_channels_status_can_render_local_json(monkeypatch) -> None:
    import src.channels.config as channel_config

    monkeypatch.setattr(
        channel_config,
        "load_channels_config",
        lambda: {"websocket": {"enabled": False}, "telegram": {"enabled": False}},
    )

    assert _legacy.main(["channels", "status", "--local", "--json"]) == _legacy.EXIT_SUCCESS


def test_channels_api_call_sends_configured_bearer_token(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"status": "ok"}

    def fake_get(url, *, headers, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResponse()

    import httpx

    monkeypatch.setenv("API_AUTH_KEY", "secret-token")
    monkeypatch.setattr(httpx, "get", fake_get)

    assert _legacy._channels_api_call("GET", "/channels/status") == {"status": "ok"}
    assert captured["headers"] == {"Authorization": "Bearer secret-token"}


@pytest.mark.parametrize(
    "command", [_legacy.cmd_channels_start, _legacy.cmd_channels_stop]
)
@pytest.mark.parametrize("json_mode", [False, True])
def test_channels_start_stop_return_failure_in_every_output_mode(
    command, json_mode, monkeypatch
) -> None:
    monkeypatch.setattr(
        _legacy,
        "_channels_api_call",
        lambda *args, **kwargs: {"status": "error", "error": "offline"},
    )

    assert command(json_mode=json_mode) == _legacy.EXIT_RUN_FAILED


@pytest.mark.parametrize(
    "command", [_legacy.cmd_channels_start, _legacy.cmd_channels_stop]
)
@pytest.mark.parametrize("json_mode", [False, True])
def test_channels_start_stop_return_success_in_every_output_mode(
    command, json_mode, monkeypatch
) -> None:
    monkeypatch.setattr(
        _legacy,
        "_channels_api_call",
        lambda *args, **kwargs: {"status": "ok", "channels": {}},
    )
    monkeypatch.setattr(_legacy, "_print_channels_status", lambda payload: None)

    assert command(json_mode=json_mode) == _legacy.EXIT_SUCCESS
