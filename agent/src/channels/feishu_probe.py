"""Standalone Feishu/Lark credential probe, mirroring ``qq_probe.py``.

The probe validates an (possibly unsaved) credential set against the
``tenant_access_token`` endpoint without touching the channel's lark SDK
client. Everything here is stateless: functions take the ``FeishuConfig``
explicitly so the module never imports the adapter at runtime (only under
``TYPE_CHECKING``) — ``feishu.py`` guards the heavy ``lark_oapi`` SDK behind
``FEISHU_AVAILABLE``, and a credential check never needs it. The
request/classification logic lives in :mod:`src.channels.token_probe`, the
shared building block for token-endpoint probes.

Note that Feishu may answer HTTP 200 with an error body (e.g.
``{"code": 10014, "msg": "app secret invalid"}``) for bad credentials; the
shared "200 but no token" branch already classifies that as
``invalid_credentials``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.channels.token_probe import probe_token_endpoint

if TYPE_CHECKING:
    from src.channels.feishu import FeishuConfig

FEISHU_TENANT_TOKEN_URL = (
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
)
LARK_TENANT_TOKEN_URL = (
    "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
)


async def test_connection(
    config: FeishuConfig, *, sdk_available: bool
) -> dict[str, Any]:
    """Validate the Feishu/Lark credentials with a standalone token request.

    Uses a fresh ``httpx.AsyncClient`` rather than any lark SDK client (which
    only exists after :meth:`FeishuChannel.start`), so an unsaved credential
    set can be checked before the channel is started. A successful tenant
    access token is discarded: it is never returned, logged, or cached.

    Args:
        config: The Feishu credential set to validate.
        sdk_available: Whether the optional ``lark-oapi`` SDK imported.

    Returns:
        A JSON-serializable envelope with ``ok`` and a ``code`` of ``ok`` /
        ``invalid_credentials`` / ``network``, plus an ``sdk_available``
        flag. Any ``detail`` is scrubbed of credential values.
    """
    if not config.app_id or not config.app_secret:
        return {
            "ok": False,
            "code": "invalid_credentials",
            "detail": "missing credentials",
            "sdk_available": sdk_available,
        }

    url = LARK_TENANT_TOKEN_URL if config.domain == "lark" else FEISHU_TENANT_TOKEN_URL
    return await probe_token_endpoint(
        url=url,
        payload={"app_id": config.app_id, "app_secret": config.app_secret},
        token_key="tenant_access_token",
        secrets=(config.app_secret, config.app_id),
        sdk_available=sdk_available,
    )
