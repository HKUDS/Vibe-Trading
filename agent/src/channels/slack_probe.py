"""Standalone Slack credential probe, mirroring ``feishu_probe.py``.

The probe validates a (possibly unsaved) credential set with a two-leg
request sequence against the Slack Web API without touching the channel's
``slack_sdk`` clients. Everything here is stateless: functions take the
``SlackConfig`` explicitly so the module never imports the adapter at
runtime (only under ``TYPE_CHECKING``) — ``slack.py`` imports ``slack_sdk``
unconditionally at module top, and a credential check never needs it.
``sdk_available`` is still threaded through so the caller's envelope
carries it unchanged (the adapter passes a constant ``True``; see the
delegate in ``slack.py``). The request/classification logic lives in
:mod:`src.channels.token_probe`, the shared building block for
token-endpoint probes.

Slack authenticates via an ``Authorization: Bearer`` header rather than a
JSON body, so both legs pass the shared probe's optional ``headers`` with
an empty payload. Note that Slack answers HTTP 200 with ``{"ok": false,
"error": "invalid_auth"}`` for bad tokens; ``token_key="ok"`` routes that
through the shared "200 but no token" branch, which already classifies it
as ``invalid_credentials``. Requiring the documented ``bot_id`` field also
refuses a user token, whose successful ``auth.test`` response has no bot identity.

Leg 1 (``auth.test``) validates the bot token. Leg 2
(``apps.connections.open``) validates the app token AND that Socket Mode
is enabled on the Slack app — the exact failure class that bites users (a
valid ``xoxb-`` bot token with Socket Mode never turned on). Its ``ok:
true`` body contains a ``wss://`` connection URL, a credential-adjacent
value: the shared probe keeps nothing but ``ok``/``code`` from a success
body, so the URL is never returned, logged, or cached.

Missing tokens short-circuit before any HTTP call, mirroring the
``start()`` guard in ``slack.py`` (``if not self.config.bot_token or not
self.config.app_token`` → logs "bot/app token not configured" and returns
without connecting).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.channels.token_probe import probe_token_endpoint

if TYPE_CHECKING:
    from src.channels.slack import SlackConfig

SLACK_AUTH_TEST_URL = "https://slack.com/api/auth.test"
SLACK_CONNECTIONS_OPEN_URL = "https://slack.com/api/apps.connections.open"


async def test_connection(
    config: SlackConfig, *, sdk_available: bool
) -> dict[str, Any]:
    """Validate the Slack credentials with a standalone two-leg probe.

    Uses fresh ``httpx.AsyncClient`` requests rather than the channel's
    ``slack_sdk`` clients (which only exist after
    :meth:`SlackChannel.start`), so an unsaved credential set can be
    checked before the channel is started. A successful leg 2 response
    carries a ``wss://`` URL; it is discarded: never returned, logged, or
    cached.

    Args:
        config: The Slack credential set to validate.
        sdk_available: Whether the ``slack_sdk`` package imported; echoed
            back so the caller's envelope carries it unchanged.

    Returns:
        A JSON-serializable envelope with ``ok`` and a ``code`` of ``ok`` /
        ``invalid_credentials`` / ``network``, plus an ``sdk_available``
        flag. Any ``detail`` is scrubbed of both token values and names
        the failing leg with a ``"bot token: "`` / ``"app token: "``
        prefix.
    """
    secrets = (config.bot_token, config.app_token)

    if config.mode != "socket":
        return {
            "ok": False,
            "code": "invalid_credentials",
            "detail": "Slack supports socket mode only",
            "sdk_available": sdk_available,
        }
    if not config.bot_token:
        return {
            "ok": False,
            "code": "invalid_credentials",
            "detail": "missing bot token",
            "sdk_available": sdk_available,
        }
    if not config.app_token:
        return {
            "ok": False,
            "code": "invalid_credentials",
            "detail": "missing app token",
            "sdk_available": sdk_available,
        }

    result = await probe_token_endpoint(
        url=SLACK_AUTH_TEST_URL,
        payload={},
        headers={"Authorization": f"Bearer {config.bot_token}"},
        token_key="ok",
        required_fields=("bot_id",),
        secrets=secrets,
        sdk_available=sdk_available,
    )
    if not result["ok"]:
        return {**result, "detail": f"bot token: {result.get('detail', '')}"}

    result = await probe_token_endpoint(
        url=SLACK_CONNECTIONS_OPEN_URL,
        payload={},
        headers={"Authorization": f"Bearer {config.app_token}"},
        token_key="ok",
        secrets=secrets,
        sdk_available=sdk_available,
    )
    if not result["ok"]:
        return {**result, "detail": f"app token: {result.get('detail', '')}"}

    return {"ok": True, "code": "ok", "sdk_available": sdk_available}
