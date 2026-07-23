import pytest

from src.channels.weixin_routing import (
    PRIMARY_ACCOUNT_ID,
    decode_aux_route,
    encode_aux_route,
    validate_account_alias,
)


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
