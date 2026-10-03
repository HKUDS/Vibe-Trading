"""Every channel must satisfy the authoring contract (#1625).

A new channel ships as a ``BaseChannel`` subclass plus field metadata, and the
generic Web UI renders it with no per-channel frontend code. This suite walks
every built-in channel the registry discovers and checks the contract points
the UI and settings flows depend on, so a channel that breaks the recipe fails
here instead of in the browser.
"""

from __future__ import annotations

from src.channels.config_meta import SECRET_KEY_RE, channel_field_hints, is_secret_key
from src.channels.registry import discover_channel_names, load_channel_class


def test_every_discovered_channel_satisfies_the_authoring_contract() -> None:
    names = discover_channel_names()
    assert names, "registry discovered no channels"

    checked = 0
    for name in names:
        try:
            cls = load_channel_class(name)
        except ImportError:
            # Optional stack not installed here (e.g. matrix needs [nio]); an
            # environment gate, not a contract violation.
            continue
        checked += 1

        # A concrete adapter: start/stop/send are abstract on BaseChannel.
        assert not cls.__abstractmethods__, f"{name} leaves BaseChannel abstracts unset"

        default_config = cls.default_config()
        assert isinstance(default_config, dict), f"{name} default_config is not a dict"

        # The generic form renders from hints; every configurable scalar key
        # must resolve one. Dict-valued fields are exempt by design: the form
        # cannot edit them, so they stay file-configured (see _derive_hints).
        hints = channel_field_hints(name)
        configurable = {k for k, v in default_config.items() if k != "enabled" and not isinstance(v, dict)}
        hint_keys = {h["key"] for h in hints}
        missing = configurable - hint_keys
        assert not missing, f"{name} has scalar config keys with no field hint: {sorted(missing)}"

        # Secret masking: hand-written hints are authoritative for their keys
        # (an audited declaration may subtract an over-match, e.g. websocket's
        # token_* path names); for every key no hint covers, the SECRET_KEY_RE
        # fail-safe must fire.
        hint_flags = {h["key"]: bool(h["secret"]) for h in hints}
        for key in configurable:
            if key in hint_flags:
                continue
            if SECRET_KEY_RE.search(key):
                assert is_secret_key(name, key), f"{name}.{key} is credential-shaped, uncovered by hints, and unmasked"
        for hint in hints:
            if hint["type"] == "password":
                assert hint["secret"], f"{name}.{hint['key']} is a password field not marked secret"

    assert checked > 0, "every discovered channel failed to import"


def test_test_connection_envelope_shape_is_documented_by_default() -> None:
    # The base contract: a channel that does not override the probe reports
    # "unsupported" rather than crashing the settings UI.
    from src.channels.base import BaseChannel

    assert "test_connection" not in BaseChannel.__abstractmethods__
