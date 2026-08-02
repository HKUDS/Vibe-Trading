"""Packaging dependency regression tests."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _normalized_requirement_name(requirement: str) -> str:
    name = requirement.split(";", 1)[0]
    for marker in ("[", "<", ">", "="):
        name = name.split(marker, 1)[0]
    return name.strip().lower()


def test_harmonic_backend_is_not_a_core_install_dependency() -> None:
    """Keep optional harmonic plotting deps from breaking baseline installs."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    core_dependencies = {
        _normalized_requirement_name(requirement) for requirement in pyproject["project"]["dependencies"]
    }
    requirements_txt = {
        _normalized_requirement_name(line)
        for line in (ROOT / "agent" / "requirements.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }

    assert "pyharmonics" not in core_dependencies
    assert "pyharmonics" not in requirements_txt


def test_harmonic_backend_is_available_as_an_optional_extra() -> None:
    """Users who need harmonic pattern detection can still opt in explicitly."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    harmonic_extra = {
        _normalized_requirement_name(requirement)
        for requirement in pyproject["project"]["optional-dependencies"]["harmonic"]
    }

    assert "pyharmonics" in harmonic_extra


def test_longbridge_sdk_is_optional_and_available_as_an_extra() -> None:
    """Broker SDK dependencies must not perturb every baseline installation."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    core_dependencies = {
        _normalized_requirement_name(requirement) for requirement in pyproject["project"]["dependencies"]
    }
    requirements_txt = {
        _normalized_requirement_name(line)
        for line in (ROOT / "agent" / "requirements.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }
    longbridge_extra = {
        _normalized_requirement_name(requirement)
        for requirement in pyproject["project"]["optional-dependencies"]["longbridge"]
    }

    assert "longbridge" not in core_dependencies
    assert "longbridge" not in requirements_txt
    assert "longbridge" in longbridge_extra


def test_channel_core_websocket_dependency_is_declared_for_baseline_installs() -> None:
    """The built-in WebSocket gateway imports websockets at module import time."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

    core_dependencies = {
        _normalized_requirement_name(requirement) for requirement in pyproject["project"]["dependencies"]
    }
    requirements_txt = {
        _normalized_requirement_name(line)
        for line in (ROOT / "agent" / "requirements.txt").read_text().splitlines()
        if line and not line.startswith("#")
    }

    assert "websockets" in core_dependencies
    assert "websockets" in requirements_txt


def test_channel_optional_extras_cover_all_sdk_backed_adapters() -> None:
    """Keep install hints and packaging extras in sync for IM adapters."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    extras = pyproject["project"]["optional-dependencies"]

    expected_extras = {
        "channels",
        "dingtalk",
        "discord",
        "feishu",
        "matrix",
        "mochat",
        "msteams",
        "napcat",
        "qq",
        "slack",
        "telegram",
        "wecom",
        "weixin",
        "whatsapp",
    }
    assert expected_extras.issubset(set(extras))

    channel_extra = {_normalized_requirement_name(requirement) for requirement in extras["channels"]}
    expected_packages = {
        "aiohttp",
        "cryptography",
        "dingtalk-stream",
        "discord.py",
        "lark-oapi",
        "matrix-nio",
        "mistune",
        "msgpack",
        "neonize",
        "nh3",
        "pyjwt",
        "python-socketio",
        "python-telegram-bot",
        "qrcode",
        "qq-botpy",
        "slack-sdk",
        "slackify-markdown",
        "websockets",
        "wecom-aibot-sdk",
    }
    assert expected_packages.issubset(channel_extra)


def test_development_extra_includes_bounded_style_tools() -> None:
    """Contributor style commands should be installed by the dev extra."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    dev_extra = pyproject["project"]["optional-dependencies"]["dev"]

    assert "black>=24.0,<27" in dev_extra
    assert "ruff>=0.9,<1" in dev_extra


def test_slack_markdown_dependency_uses_a_published_version_range() -> None:
    """Both Slack extras should use the same resolvable dependency range."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    extras = pyproject["project"]["optional-dependencies"]

    expected = "slackify-markdown>=0.2.4,<1"
    assert expected in extras["slack"]
    assert expected in extras["channels"]
