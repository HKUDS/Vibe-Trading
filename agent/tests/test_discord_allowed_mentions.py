"""Regression: outbound Discord sends must not let literal @everyone/@here or
role-mention tokens actually ping.

discord.AllowedMentions(replied_user=False) leaves everyone/users/roles at
their True default, so a bare "@everyone" in outbound text (e.g. echoed back
from an LLM response) pinged the whole server on every send path -- both the
explicit reply/file paths and the plain channel.send() calls (streaming
edits, overflow chunks) that pass no allowed_mentions at all and so fell
back to Discord's own parse-from-content default.
"""

from __future__ import annotations

import pytest

discord = pytest.importorskip("discord")

from src.channels.discord import DiscordBotClient  # noqa: E402


class _FakeChannel:
    logger = None


def _client() -> DiscordBotClient:
    return DiscordBotClient(_FakeChannel(), intents=discord.Intents.none())


def test_client_level_default_suppresses_everyone_and_roles():
    client = _client()
    assert client.allowed_mentions is not None
    assert client.allowed_mentions.everyone is False
    assert client.allowed_mentions.roles is False


def test_reply_context_mention_settings_suppress_everyone_and_roles():
    client = _client()
    _, mention_settings = client._build_reply_context(channel=None, reply_to=None)
    assert mention_settings.everyone is False
    assert mention_settings.roles is False
    assert mention_settings.replied_user is False
