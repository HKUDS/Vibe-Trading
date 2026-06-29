"""CLI coverage for IM channel commands."""

from __future__ import annotations

from pathlib import Path

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

    login = parser.parse_args(["channels", "login", "weixin", "--force"])
    assert login.channels_command == "login"
    assert login.channel_name == "weixin"
    assert login.force is True

    pairing = parser.parse_args(["channels", "pairing", "--channel", "telegram", "approve", "ABCD-EFGH"])
    assert pairing.channels_command == "pairing"
    assert pairing.channel == "telegram"
    assert pairing.pairing_command == "approve"
    assert pairing.pairing_args == ["ABCD-EFGH"]


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
