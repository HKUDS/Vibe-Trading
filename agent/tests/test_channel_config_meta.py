"""Tests for channel config field metadata and fail-safe secret masking.

Covers the uiHints registry (hand-written for DingTalk and QQ, derived
elsewhere) and the security acceptance criterion: no key matching
:data:`SECRET_KEY_RE` ever survives in the non-secret ``values`` half.
"""

from __future__ import annotations

import pytest

from src.channels import config_meta as _config_meta
from src.channels.config_meta import (
    SECRET_KEY_RE,
    channel_field_hints,
    split_values_secrets,
)
from src.channels.registry import discover_channel_names, load_channel_class

# Discovery already excludes the helper modules (``registry._INTERNAL``), so
# this is the real channel surface. The sweep below locks it at 16.
ADAPTER_NAMES: list[str] = sorted(discover_channel_names())


def _dummy_value(value: object) -> object:
    """Return a non-empty stand-in for a ``default_config()`` value."""
    if isinstance(value, bool):
        return True
    if isinstance(value, list):
        return ["dummy-list-item"]
    if isinstance(value, dict):
        return {"dummy": "dummy-value"}
    if isinstance(value, int):
        return 1234
    if isinstance(value, float):
        return 1.5
    return "dummy-secret-1234"


def _section_for(name: str) -> dict[str, object] | None:
    """Return ``default_config()`` populated with dummies, or None if unloadable."""
    try:
        config = load_channel_class(name).default_config()
    except Exception:  # noqa: BLE001 - adapters with missing SDKs must degrade
        return None
    if not isinstance(config, dict):
        return None
    return {key: _dummy_value(value) for key, value in config.items()}


# --- (a) hand-written DingTalk hints ---------------------------------------- #


def test_dingtalk_field_hints_exact_snapshot() -> None:
    """DingTalk hints match the frozen contract, with ``enabled`` excluded."""
    hints = channel_field_hints("dingtalk")
    assert hints == [
        {
            "key": "client_id",
            "type": "text",
            "secret": False,
            "required": True,
            "help_key": "settings.channels.fields.dingtalk.client_id",
        },
        {
            "key": "client_secret",
            "type": "password",
            "secret": True,
            "required": True,
            "help_key": "settings.channels.fields.dingtalk.client_secret",
        },
        {
            "key": "allow_from",
            "type": "list",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.dingtalk.allow_from",
        },
        {
            "key": "allow_remote_media_redirects",
            "type": "bool",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.dingtalk.allow_remote_media_redirects",
        },
        {
            "key": "remote_media_redirect_allowed_hosts",
            "type": "list",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.dingtalk.remote_media_redirect_allowed_hosts",
        },
        {
            "key": "group_user_isolation",
            "type": "bool",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.dingtalk.group_user_isolation",
        },
        {
            "key": "force_ipv4",
            "type": "bool",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.dingtalk.force_ipv4",
        },
    ]
    assert "enabled" not in {hint["key"] for hint in hints}


def test_qq_field_hints_exact_snapshot() -> None:
    """QQ hints match the frozen contract, with ``enabled`` excluded."""
    hints = channel_field_hints("qq")
    assert hints == [
        {
            "key": "app_id",
            "type": "text",
            "secret": False,
            "required": True,
            "help_key": "settings.channels.fields.qq.app_id",
        },
        {
            "key": "secret",
            "type": "password",
            "secret": True,
            "required": True,
            "help_key": "settings.channels.fields.qq.secret",
        },
        {
            "key": "allow_from",
            "type": "list",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.qq.allow_from",
        },
        {
            "key": "msg_format",
            "type": "text",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.qq.msg_format",
        },
        {
            "key": "ack_message",
            "type": "text",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.qq.ack_message",
        },
        {
            "key": "media_dir",
            "type": "text",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.qq.media_dir",
        },
        {
            "key": "download_chunk_size",
            "type": "text",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.qq.download_chunk_size",
        },
        {
            "key": "download_max_bytes",
            "type": "text",
            "secret": False,
            "required": False,
            "help_key": "settings.channels.fields.qq.download_max_bytes",
        },
    ]
    assert "enabled" not in {hint["key"] for hint in hints}


# --- (b) fallback derivation ------------------------------------------------- #


@pytest.mark.parametrize("name", ["discord", "websocket"])
def test_fallback_derives_types_and_secret_flags(name: str) -> None:
    """Adapters without hand-written hints derive metadata from default_config()."""
    config = _section_for(name)
    assert config is not None, f"{name} should expose default_config()"
    hints = channel_field_hints(name)
    assert hints, f"{name} fallback should derive at least one field"
    by_key = {hint["key"]: hint for hint in hints}
    assert "enabled" not in by_key
    assert any(SECRET_KEY_RE.search(key) for key in config)

    for key, value in config.items():
        if key == "enabled":
            continue
        if isinstance(value, dict):
            assert key not in by_key
            continue
        hint = by_key[key]
        assert hint["required"] is False
        assert hint["help_key"] is None
        if SECRET_KEY_RE.search(key):
            assert hint["secret"] is True
            assert hint["type"] == "password"
        else:
            assert hint["secret"] is False
            if isinstance(value, bool):
                assert hint["type"] == "bool"
            elif isinstance(value, list):
                assert hint["type"] == "list"
            else:
                assert hint["type"] == "text"


def test_dict_valued_defaults_are_excluded_from_derived_hints(monkeypatch) -> None:
    """Dict-valued fields stay out of derived hints (hermetic stub pin).

    The generic form edits text/password/bool/list widgets only; a dict
    field derived as ``text`` rendered as "[object Object]" once the GET
    defaults backfill reached pristine forms. Excluded from hints, still
    present in ``values``, secret masking untouched.
    """

    class _Stub:
        @staticmethod
        def default_config() -> dict:
            return {
                "enabled": False,
                "bot_token": "",
                "dm": {},
                "policies": {"mention": {}},
                "name": "",
            }

    monkeypatch.setattr(_config_meta, "load_channel_class", lambda name: _Stub)

    hints = channel_field_hints("stub_dict_channel")
    assert {hint["key"] for hint in hints} == {"bot_token", "name"}
    by_key = {hint["key"]: hint for hint in hints}
    assert by_key["bot_token"]["type"] == "password"
    assert by_key["bot_token"]["secret"] is True

    values, secrets = split_values_secrets("stub_dict_channel", _Stub.default_config())
    assert {"dm", "policies"} <= set(values)
    assert "bot_token" in secrets


def test_dict_valued_defaults_are_excluded_for_real_adapters() -> None:
    """Same rule against a real adapter shape (signal's dm/group policy maps).

    whatsapp ``lid_mappings``, napcat ``group_policy_overrides`` and mochat
    ``mention``/``groups`` are the same class; signal is the loadable
    representative here.
    """
    config = _section_for("signal")
    if config is None:
        pytest.skip("signal adapter unloadable in this environment")
    dict_keys = {key for key, value in config.items() if isinstance(value, dict)}
    assert dict_keys, "signal should expose dict-valued defaults"

    hint_keys = {hint["key"] for hint in channel_field_hints("signal")}
    assert not (dict_keys & hint_keys)

    values, _ = split_values_secrets("signal", config)
    assert dict_keys <= set(values)


def test_unloadable_adapter_is_handled_gracefully() -> None:
    """Adapters whose SDK is missing yield no hints instead of raising."""
    for name in ADAPTER_NAMES:
        try:
            load_channel_class(name)
        except Exception:  # noqa: BLE001 - this is the branch under test
            assert channel_field_hints(name) == []


# --- (c)/(d) fail-safe secret heuristic ------------------------------------ #


def test_unknown_channel_masks_secret_keys_and_strips_them_from_values() -> None:
    """A secret-shaped key is masked even without any hand-written hint."""
    values, secrets = split_values_secrets(
        "no_such_channel",
        {"webhook_secret": "abc12345", "bot_token": "x", "name": "n"},
    )
    assert values == {"name": "n"}
    assert secrets == {
        "webhook_secret": {"set": True, "masked": "****"},
        "bot_token": {"set": True, "masked": "****"},
    }


def test_short_secret_masking_boundary() -> None:
    """Secrets of 8 characters or fewer disclose nothing; 9 disclose the last 4."""
    for length in range(1, 9):
        _, secrets = split_values_secrets(
            "no_such_channel", {"token": "1234567890"[:length]}
        )
        assert secrets["token"] == {"set": True, "masked": "****"}, length
    _, secrets = split_values_secrets("no_such_channel", {"token": "123456789"})
    assert secrets["token"] == {"set": True, "masked": "****6789"}


def test_empty_secret_is_unset_and_unmasked() -> None:
    """An unset secret reports ``set: false`` and an empty mask."""
    values, secrets = split_values_secrets("no_such_channel", {"api_key": ""})
    assert values == {}
    assert secrets == {"api_key": {"set": False, "masked": ""}}


def test_non_secret_values_pass_through_verbatim() -> None:
    """Non-secret keys (including ``enabled``) are copied unchanged."""
    section = {"client_id": "abc", "allow_from": ["u1"], "enabled": True}
    values, secrets = split_values_secrets("dingtalk", section)
    assert values == section
    assert secrets == {}


def test_proxy_url_userinfo_is_stripped_from_values() -> None:
    """URL userinfo is stripped from non-secret values; other strings stay put."""
    values, secrets = split_values_secrets(
        "telegram",
        {
            "proxy": "http://user:pw@proxy.local:8080",
            "webhook_url": "https://example.com/hook",
            "note": "plain text",
            "bad_proxy": "http://user:pw@host:notaport",
            "token": "abc",
        },
    )
    assert values["proxy"] == "http://proxy.local:8080"
    assert "user" not in values["proxy"]
    assert "pw" not in values["proxy"]
    assert values["webhook_url"] == "https://example.com/hook"
    assert values["note"] == "plain text"
    assert values["bad_proxy"] == "http://user:pw@host:notaport"
    assert secrets["token"] == {"set": True, "masked": "****"}


def test_hint_marked_secret_is_masked_for_known_channel() -> None:
    """A hint-declared secret is masked and never reaches values."""
    values, secrets = split_values_secrets(
        "dingtalk", {"client_secret": "dummy-secret-1234"}
    )
    assert values == {}
    assert secrets == {"client_secret": {"set": True, "masked": "****1234"}}


def test_secret_key_regex_is_case_insensitive() -> None:
    """Credential-shaped keys match case-insensitively; identifiers do not."""
    for key in (
        "API_KEY",
        "WebhookSecret",
        "bot_token",
        "db_password",
        "encrypt_key",
        "ENCRYPT_KEY",
        "signing_key",
        "private_key",
        "credential",
        "proxy_username",
        "apikey",
    ):
        assert SECRET_KEY_RE.search(key), key
    for key in ("allow_from", "client_id", "imap_username", "domain"):
        assert not SECRET_KEY_RE.search(key), key


# --- (e) security sweep over every discovered adapter ---------------------- #

_EXPECTED_SECRET_KEYS: dict[str, set[str]] = {
    "dingtalk": {"client_secret"},
    "discord": {"token", "proxy_password", "proxy_username"},
    "email": {"imap_password", "smtp_password"},
    "feishu": {"app_secret", "verification_token", "encrypt_key"},
    "matrix": {"password", "access_token"},
    "mochat": {"claw_token"},
    "msteams": {"app_password"},
    "napcat": {"access_token"},
    "qq": {"secret"},
    "signal": set(),
    "slack": {"bot_token", "app_token", "user_token_read_only"},
    "telegram": {"token", "webhook_secret_token"},
    "wecom": {"secret"},
    "weixin": {"token"},
    "whatsapp": set(),
    "websocket": {"token", "token_issue_secret"},
}

_IDENTIFIER_KEYS = frozenset(
    {"client_id", "app_id", "bot_id", "phone_number", "imap_username", "smtp_username"}
)


def test_discovered_adapter_surface_is_locked() -> None:
    """The sweep below covers the frozen set of 16 built-in adapters."""
    assert len(ADAPTER_NAMES) == 16


@pytest.mark.parametrize("name", ADAPTER_NAMES)
def test_split_never_leaks_secret_keys_in_values(name: str) -> None:
    """No SECRET_KEY_RE key may appear in ``values`` for any adapter."""
    section = _section_for(name)
    if section is None:
        # Missing SDK (e.g. matrix today): hints degrade to empty and masking
        # must still be fail-safe.
        assert channel_field_hints(name) == []
        section = {"webhook_secret": "dummy-secret-1234", "bot_token": "dummy-token"}

    values, secrets = split_values_secrets(name, section)
    assert [key for key in values if SECRET_KEY_RE.search(key)] == []
    assert set(values) | set(secrets) == set(section)
    assert not (set(values) & set(secrets))


@pytest.mark.parametrize("name", ADAPTER_NAMES)
def test_every_adapter_credential_key_lands_in_secrets(name: str) -> None:
    """Every credential-shaped field lands in ``secrets``, never in ``values``."""
    section = _section_for(name)
    if section is None:
        pytest.skip(f"{name} adapter is not loadable in this environment")
    values, secrets = split_values_secrets(name, section)
    expected = _EXPECTED_SECRET_KEYS[name]
    assert expected <= set(secrets)
    assert set(expected) & set(values) == set()


@pytest.mark.parametrize("name", ADAPTER_NAMES)
def test_identifier_fields_stay_visible(name: str) -> None:
    """Identifier-shaped fields stay in ``values``, not ``secrets``."""
    section = _section_for(name)
    if section is None:
        pytest.skip(f"{name} adapter is not loadable in this environment")
    values, secrets = split_values_secrets(name, section)
    for key in _IDENTIFIER_KEYS & set(section):
        assert key in values, f"{name}.{key} must stay visible"
        assert key not in secrets, f"{name}.{key} must not be masked"


# --- (f) unknown channel ---------------------------------------------------- #


def test_unknown_channel_has_no_hints() -> None:
    assert channel_field_hints("definitely_not_a_real_channel") == []
