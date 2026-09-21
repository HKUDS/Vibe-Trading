"""Standalone QQ credential probe, mirroring ``dingtalk_probe.py``.

The probe validates an (possibly unsaved) credential set against QQ's
``getAppAccessToken`` endpoint without touching the channel's shared HTTP
client. Everything here is stateless: functions take the ``QQConfig``
explicitly so the module never imports the adapter at runtime (only under
``TYPE_CHECKING``) — ``qq.py`` pulls ``aiohttp``/``botpy``, neither of which
a credential check needs. The request/classification logic lives in
:mod:`src.channels.token_probe`, the shared building block for
token-endpoint probes.

Note that QQ may answer HTTP 200 with an error body (e.g.
``{"code": 100007, "message": "..."}``) for bad credentials; the shared
"200 but no token" branch already classifies that as ``invalid_credentials``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.channels.token_probe import probe_token_endpoint

if TYPE_CHECKING:
    from src.channels.qq import QQConfig

QQ_ACCESS_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"


async def test_connection(config: QQConfig, *, sdk_available: bool) -> dict[str, Any]:
    """Validate the QQ credentials with a standalone token request.

    Uses a fresh ``httpx.AsyncClient`` rather than the channel's shared client
    (which only exists after :meth:`QQChannel.start`), so an unsaved
    credential set can be checked before the channel is started. A successful
    access token is discarded: it is never returned, logged, or cached.

    Args:
        config: The QQ credential set to validate.
        sdk_available: Whether the optional ``qq-botpy`` SDK imported.

    Returns:
        A JSON-serializable envelope with ``ok`` and a ``code`` of ``ok`` /
        ``invalid_credentials`` / ``network``, plus an ``sdk_available``
        flag. Any ``detail`` is scrubbed of credential values.
    """
    if not config.app_id or not config.secret:
        return {
            "ok": False,
            "code": "invalid_credentials",
            "detail": "missing credentials",
            "sdk_available": sdk_available,
        }

    return await probe_token_endpoint(
        url=QQ_ACCESS_TOKEN_URL,
        payload={"appId": config.app_id, "clientSecret": config.secret},
        token_key="access_token",
        secrets=(config.secret, config.app_id),
        sdk_available=sdk_available,
    )
