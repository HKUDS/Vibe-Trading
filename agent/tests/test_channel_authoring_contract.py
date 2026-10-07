"""Every channel must satisfy the authoring contract (#1625).

A new channel ships as a ``BaseChannel`` subclass plus field metadata, and the
generic Web UI renders it with no per-channel frontend code. This suite walks
every built-in channel the registry discovers and checks the contract points
the UI and settings flows depend on, so a channel that breaks the recipe fails
here instead of in the browser.
"""

from __future__ import annotations

import asyncio
import re
import tomllib
from pathlib import Path

import pytest

from src.channels.config_meta import channel_field_hints, split_values_secrets
from src.channels.registry import discover_channel_names, load_channel_class


@pytest.mark.parametrize("name", discover_channel_names())
def test_every_discovered_channel_satisfies_the_authoring_contract(name) -> None:
    try:
        cls = load_channel_class(name)
    except ImportError as exc:
        # Only the adapter's explicit missing-dependency envelope can skip.
        # An arbitrary import or missing BaseChannel subclass must fail.
        project = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())["project"]
        optional = project["optional-dependencies"].get(name, [])
        modules = {re.split(r"[<>=!\[; ]", requirement)[0].replace("-", "_") for requirement in optional}
        direct_missing = isinstance(exc, ModuleNotFoundError) and (exc.name or "").split(".")[0] in modules
        declared_missing = isinstance(exc.__cause__, ModuleNotFoundError) and "dependencies not installed" in str(exc)
        if not (direct_missing or declared_missing):
            raise
        pytest.skip(str(exc))

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

    # Test the serialized form consumed by the settings UI, rather than
    # only asking the same classifier that supplied the hints.
    sentinel = "credential-contract-sentinel"
    configured = {hint["key"]: sentinel for hint in hints if hint["secret"]}
    configured["extra_api_token"] = sentinel
    values, secrets = split_values_secrets(name, configured)
    assert not (set(configured) & set(values)), f"{name} exposes a credential in values"
    assert set(configured) <= set(secrets)
    assert sentinel not in str(secrets)
    for hint in hints:
        if hint["type"] == "password":
            assert hint["secret"], f"{name}.{hint['key']} is a password field not marked secret"


def test_test_connection_envelope_shape_is_documented_by_default() -> None:
    # The base contract: a channel that does not override the probe reports
    # "unsupported" rather than crashing the settings UI.
    from src.channels.base import BaseChannel

    assert "test_connection" not in BaseChannel.__abstractmethods__
    assert asyncio.run(BaseChannel.test_connection(None)) == {"ok": False, "code": "unsupported"}
