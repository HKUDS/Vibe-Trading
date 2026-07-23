from pathlib import Path

import pytest

from src.channels.bus.queue import MessageBus
from src.channels.registry import discover_channel_names
from src.channels.weixin import WeixinChannel, WeixinConfig
from src.channels.weixin_routing import (
    PRIMARY_ACCOUNT_ID,
    decode_aux_route,
    encode_aux_route,
    validate_account_alias,
)


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
