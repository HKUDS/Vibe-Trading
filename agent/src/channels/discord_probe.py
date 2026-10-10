"""Standalone Discord credential probe, mirroring ``slack_probe.py``.

The probe validates a (possibly unsaved) bot token with a single request
to the Discord REST API without touching the channel's ``discord.py``
client. Everything here is stateless: functions take the ``DiscordConfig``
explicitly so the module never imports the adapter at runtime (only under
``TYPE_CHECKING``) — ``discord.py`` guards the heavy ``discord`` SDK behind
``DISCORD_AVAILABLE``, and a credential check never needs it.
``sdk_available`` is still threaded through so the caller's envelope
carries it unchanged (the adapter passes the real ``DISCORD_AVAILABLE``
flag; see the delegate in ``discord.py``). The request/classification
logic lives in :mod:`src.channels.token_probe`, the shared building block
for token-endpoint probes.

Discord authenticates via an ``Authorization: Bot`` header rather than a
JSON body, so the leg passes the shared probe's optional ``headers`` with
``method="GET"`` and an empty payload. ``token_key="bot"`` is deliberate:
a valid bot token returns the bot's user object carrying ``"bot": true``,
while a pasted OAuth *user* token answers HTTP 200 WITHOUT the flag — the
shared "200 but token_key missing/falsy" branch classifies that as
``invalid_credentials``, catching the wrong-token-type failure at probe
time (a user token cannot open a bot gateway session, so it would
otherwise only fail later at ``start()``). The success body (bot username,
id) is credential-adjacent: the shared probe keeps nothing but
``ok``/``code`` from a success body, so it is never returned, logged, or
cached — the same guarantee ``slack_probe.py`` relies on for the
``wss://`` URL.

Scope note: privileged-intent enablement (e.g. MESSAGE CONTENT INTENT) is
NOT probeable via REST — it only surfaces at gateway IDENTIFY (close code
4014) — so this probe deliberately does not attempt a gateway/WebSocket
leg; the Web UI setup guide covers the intent switches instead.

A missing token short-circuits before any HTTP call, mirroring the
``start()`` guard in ``discord.py`` (``if not self.config.token`` → logs
"bot token not configured" and returns without connecting).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.channels.token_probe import probe_token_endpoint

if TYPE_CHECKING:
    from src.channels.discord import DiscordConfig

DISCORD_USERS_ME_URL = "https://discord.com/api/v10/users/@me"


async def test_connection(
    config: DiscordConfig, *, sdk_available: bool
) -> dict[str, Any]:
    """Validate the Discord bot token with a standalone REST probe.

    Uses a fresh ``httpx.AsyncClient`` request rather than the channel's
    ``discord.py`` client (which only exists after
    :meth:`DiscordChannel.start`), so an unsaved credential set can be
    checked before the channel is started. A successful response carries
    the bot's user object; it is discarded: never returned, logged, or
    cached.

    Args:
        config: The Discord credential set to validate.
        sdk_available: Whether the optional ``discord`` SDK imported;
            echoed back so the caller's envelope carries it unchanged.

    Returns:
        A JSON-serializable envelope with ``ok`` and a ``code`` of ``ok`` /
        ``invalid_credentials`` / ``network``, plus an ``sdk_available``
        flag. Any ``detail`` is scrubbed of the token value.
    """
    if not config.token:
        return {
            "ok": False,
            "code": "invalid_credentials",
            "detail": "missing bot token",
            "sdk_available": sdk_available,
        }

    return await probe_token_endpoint(
        url=DISCORD_USERS_ME_URL,
        payload={},
        method="GET",
        headers={"Authorization": f"Bot {config.token}"},
        token_key="bot",
        secrets=(config.token,),
        sdk_available=sdk_available,
    )
