"""Field metadata for channel config forms with fail-safe secret masking.

A generic web form renders any channel's configuration from this module
without per-channel frontend code. Hand-written :data:`FIELD_HINTS` supply
i18n-friendly metadata (labels are owned by the frontend via ``help_key``);
channels without hints fall back to their adapter's ``default_config()`` with
type inference and a fail-safe secret heuristic.

Secret detection is the extended :data:`SECRET_KEY_RE` family plus per-channel
hint flags, so credential-shaped keys such as Feishu's ``encrypt_key`` and
Discord's ``proxy_username`` never cross the wire in ``values``. URL userinfo
(``user:password@``) is stripped from non-secret values before they are
returned.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from typing import TypedDict
from urllib.parse import urlsplit, urlunsplit

from src.channels.registry import load_channel_class

logger = logging.getLogger(__name__)

SECRET_KEY_RE = re.compile(
    r"secret|token|password|api_?key|encrypt_?key|signing_?key|credential|private|proxy_?username",
    re.IGNORECASE,
)

_HELP_KEY_PREFIX = "settings.channels.fields"
_EXCLUDED_KEYS = frozenset({"enabled"})


class FieldHint(TypedDict):
    """UI metadata for one channel config field.

    Attributes:
        key: Config key as the adapter serializes it (aliases already applied).
        type: Widget type: ``text``, ``password``, ``bool`` or ``list``.
        secret: Whether the value must never cross the wire in ``values``.
        required: Whether the form must not submit an empty value.
        help_key: i18n key for the frontend label, or ``None`` when the
            channel has no hand-written label.
    """

    key: str
    type: str
    secret: bool
    required: bool
    help_key: str | None


def _dingtalk_hints() -> list[FieldHint]:
    """Return the hand-written DingTalk field hints (``enabled`` excluded)."""
    specs = (
        ("client_id", "text", False, True),
        ("client_secret", "password", True, True),
        ("allow_from", "list", False, False),
        ("allow_remote_media_redirects", "bool", False, False),
        ("remote_media_redirect_allowed_hosts", "list", False, False),
        ("group_user_isolation", "bool", False, False),
        ("force_ipv4", "bool", False, False),
    )
    return [
        {
            "key": key,
            "type": widget,
            "secret": secret,
            "required": required,
            "help_key": f"{_HELP_KEY_PREFIX}.dingtalk.{key}",
        }
        for key, widget, secret, required in specs
    ]


def _qq_hints() -> list[FieldHint]:
    """Return the hand-written QQ field hints (``enabled`` excluded)."""
    specs = (
        ("app_id", "text", False, True),
        ("secret", "password", True, True),
        ("allow_from", "list", False, False),
        ("msg_format", "text", False, False),
        ("ack_message", "text", False, False),
        ("media_dir", "text", False, False),
        ("download_chunk_size", "text", False, False),
        ("download_max_bytes", "text", False, False),
    )
    return [
        {
            "key": key,
            "type": widget,
            "secret": secret,
            "required": required,
            "help_key": f"{_HELP_KEY_PREFIX}.qq.{key}",
        }
        for key, widget, secret, required in specs
    ]


FIELD_HINTS: dict[str, list[FieldHint]] = {
    "dingtalk": _dingtalk_hints(),
    "qq": _qq_hints(),
}


def _infer_type(key: str, value: Any, *, secret: bool) -> str:
    """Infer a widget type; secret keys always become ``password``."""
    if secret:
        return "password"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, list):
        return "list"
    return "text"


def _derive_hints(name: str) -> list[FieldHint]:
    """Derive hints from an adapter's ``default_config()``, or ``[]`` if unknown."""
    try:
        config = load_channel_class(name).default_config()
    except Exception:  # noqa: BLE001 - unknown names and missing SDKs degrade
        logger.debug("No config metadata for channel '%s'", name, exc_info=True)
        return []
    if not isinstance(config, dict):
        return []

    hints: list[FieldHint] = []
    for key, value in config.items():
        if key in _EXCLUDED_KEYS:
            continue
        if isinstance(value, dict):
            # The generic form edits text/password/bool/list widgets only;
            # a dict-valued field cannot be represented and would render as
            # "[object Object]". Such fields stay file-configured (their
            # values still travel in GET ``values``, the form just omits
            # them). Secret masking is unaffected: derived hints only mark
            # what SECRET_KEY_RE already catches unconditionally.
            continue
        secret = bool(SECRET_KEY_RE.search(key))
        hints.append(
            {
                "key": key,
                "type": _infer_type(key, value, secret=secret),
                "secret": secret,
                "required": False,
                "help_key": None,
            }
        )
    return hints


def channel_field_hints(name: str) -> list[FieldHint]:
    """Return UI field metadata for one channel.

    Hand-written hints win when present; otherwise the adapter's
    ``default_config()`` is inspected. Unknown or unloadable channels return an
    empty list, and ``enabled`` is always excluded (it is the toggle rendered
    separately).

    Args:
        name: Channel module name, e.g. ``dingtalk`` or ``telegram``.

    Returns:
        Field hints in the adapter's serialized config-key order.
    """
    hand_written = FIELD_HINTS.get(name)
    if hand_written is not None:
        return list(hand_written)
    return _derive_hints(name)


def _mask(value: Any) -> dict[str, Any]:
    """Return the ``{set, masked}`` descriptor for one secret value."""
    is_set = bool(value)
    if not is_set:
        return {"set": False, "masked": ""}
    text = str(value)
    return {"set": True, "masked": "****" if len(text) <= 8 else "****" + text[-4:]}


def _strip_url_userinfo(value: Any) -> Any:
    """Return a URL string without embedded credentials; non-URLs pass through."""
    if not isinstance(value, str) or "://" not in value:
        return value
    try:
        parts = urlsplit(value)
        if parts.username is None and parts.password is None:
            return value
        host = parts.hostname or ""
        port = parts.port  # raises ValueError on a malformed port
        if port is not None:
            host = f"{host}:{port}"
        return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    except ValueError:
        return value


def split_values_secrets(
    name: str, section: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Split a raw config section into non-secret values and masked secrets.

    A key is treated as a secret when it matches :data:`SECRET_KEY_RE` or is
    marked secret in :func:`channel_field_hints`. The strip from ``values`` is
    unconditional, so an unknown channel's ``webhook_secret`` never leaks.

    Args:
        name: Channel module name.
        section: Raw config section as loaded from disk.

    Returns:
        ``(values, secrets)`` where ``values`` holds non-secret keys with any
        URL userinfo stripped, and each secret is
        ``{"set": bool, "masked": "****"}`` (a suffix is disclosed only for
        values longer than 8 characters).
    """
    secret_hint_keys = {
        hint["key"] for hint in channel_field_hints(name) if hint["secret"]
    }
    values: dict[str, Any] = {}
    secrets: dict[str, dict[str, Any]] = {}
    for key, value in section.items():
        if SECRET_KEY_RE.search(key) or key in secret_hint_keys:
            secrets[key] = _mask(value)
        else:
            values[key] = _strip_url_userinfo(value)
    return values, secrets
