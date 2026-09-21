"""Standalone DingTalk credential probe, split from ``dingtalk.py`` for size.

The probe validates an (possibly unsaved) credential set against the token
endpoint without touching the channel's shared HTTP client. Everything here
is stateless: functions take the ``DingTalkConfig`` explicitly so the module
never imports the adapter at runtime (only under ``TYPE_CHECKING``). The
request/classification logic lives in :mod:`src.channels.token_probe`, the
shared building block for token-endpoint probes; this module keeps the
DingTalk-specific endpoint, payload shape and IPv4-pinning transport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from src.channels.token_probe import probe_token_endpoint

if TYPE_CHECKING:
    from src.channels.dingtalk import DingTalkConfig

DINGTALK_ACCESS_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/accessToken"


def build_http_transport(config: DingTalkConfig) -> httpx.AsyncHTTPTransport | None:
    """Return an IPv4-bound transport when ``force_ipv4`` is set, else None.

    DingTalk's robot-send API enforces the app's egress-IP whitelist; on
    dual-stack networks the rotating IPv6 prefix keeps falling out of it, so
    operators can pin the egress to the (typically stable) IPv4 address.
    """
    if config.force_ipv4:
        return httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    return None


async def test_connection(
    config: DingTalkConfig, *, sdk_available: bool
) -> dict[str, Any]:
    """Validate the DingTalk credentials with a standalone token request.

    Uses a fresh ``httpx.AsyncClient`` rather than the channel's shared client
    (which only exists after :meth:`DingTalkChannel.start`), so an unsaved
    credential set can be checked before the channel is started. A successful
    access token is discarded: it is never returned, logged, or cached.

    Args:
        config: The DingTalk credential set to validate.
        sdk_available: Whether the optional ``dingtalk-stream`` SDK imported.

    Returns:
        A JSON-serializable envelope with ``ok`` and a ``code`` of ``ok`` /
        ``invalid_credentials`` / ``network``, plus an ``sdk_available``
        flag. Any ``detail`` is scrubbed of credential values.
    """
    if not config.client_id or not config.client_secret:
        return {
            "ok": False,
            "code": "invalid_credentials",
            "detail": "missing credentials",
            "sdk_available": sdk_available,
        }

    return await probe_token_endpoint(
        url=DINGTALK_ACCESS_TOKEN_URL,
        payload={"appKey": config.client_id, "appSecret": config.client_secret},
        token_key="accessToken",
        secrets=(config.client_secret, config.client_id),
        sdk_available=sdk_available,
        transport=build_http_transport(config),
    )
