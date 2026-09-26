"""Field metadata for channel config forms with fail-safe secret masking.

A generic web form renders any channel's configuration from this module
without per-channel frontend code. Hand-written :data:`FIELD_HINTS` supply
i18n-friendly metadata (labels are owned by the frontend via ``help_key``);
channels without hints fall back to their adapter's ``default_config()`` with
type inference and a fail-safe secret heuristic.

Secret detection runs in two directions. A hand-written hint's ``secret``
flag is *authoritative* for the keys it covers — an audited declaration may
add to the regex (a credential-shaped key the pattern misses) or subtract
from it (a benign key the pattern over-matches, e.g. websocket's
``token_ttl_s``). For every key no hand-written hint covers — derived-hint
channels, extra stored keys, manager overrides, unknown channels — the
extended :data:`SECRET_KEY_RE` family is the *unconditional* fail-safe, so
credential-shaped keys such as Feishu's ``encrypt_key`` and Discord's
``proxy_username`` never cross the wire in ``values``. URL userinfo
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
            For hand-written hints this flag is authoritative (see
            :func:`is_secret_key`).
        required: Decorative form affordance only: renders an asterisk and a
            "required" hint next to the field. The frontend does not gate
            submission on it (verified against ``ChannelConfigPanel.tsx``).
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


def _feishu_hints() -> list[FieldHint]:
    """Return the hand-written Feishu field hints (``enabled`` excluded).

    ``app_id``/``app_secret`` are required because
    :meth:`FeishuChannel.start` refuses to connect without them; the
    ``encrypt_key``/``verification_token`` pair stays optional because the
    WebSocket long-connection mode works without them for most apps.
    """
    specs = (
        ("app_id", "text", False, True),
        ("app_secret", "password", True, True),
        ("encrypt_key", "password", True, False),
        ("verification_token", "password", True, False),
        ("allow_from", "list", False, False),
        ("react_emoji", "text", False, False),
        ("done_emoji", "text", False, False),
        ("tool_hint_prefix", "text", False, False),
        ("group_policy", "text", False, False),
        ("reply_to_message", "bool", False, False),
        ("streaming", "bool", False, False),
        ("domain", "text", False, False),
        ("topic_isolation", "bool", False, False),
    )
    return [
        {
            "key": key,
            "type": widget,
            "secret": secret,
            "required": required,
            "help_key": f"{_HELP_KEY_PREFIX}.feishu.{key}",
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


def _email_hints() -> list[FieldHint]:
    """Return the hand-written Email field hints (``enabled`` excluded).

    ``required`` decision: the frontend renders ``required`` as a decorative
    asterisk + hint only (``ChannelConfigPanel.tsx`` never gates submission on
    it, for enabled or disabled channels alike), so marking the six credential
    fields required is safe and consistent with ``EmailChannel._validate_config``
    (which refuses to start without all six) and with the DingTalk/QQ precedent.
    """
    specs = (
        ("consent_granted", "bool", False, False),
        ("imap_host", "text", False, True),
        ("imap_port", "text", False, False),
        ("imap_username", "text", False, True),
        ("imap_password", "password", True, True),
        ("imap_mailbox", "text", False, False),
        ("imap_use_ssl", "bool", False, False),
        ("imap_use_tls", "bool", False, False),
        ("smtp_host", "text", False, True),
        ("smtp_port", "text", False, False),
        ("smtp_username", "text", False, True),
        ("smtp_password", "password", True, True),
        ("smtp_use_tls", "bool", False, False),
        ("smtp_use_ssl", "bool", False, False),
        ("verify_tls", "bool", False, False),
        ("from_address", "text", False, False),
        ("auto_reply_enabled", "bool", False, False),
        ("poll_interval_seconds", "text", False, False),
        ("mark_seen", "bool", False, False),
        ("post_action", "text", False, False),
        ("post_action_move_mailbox", "text", False, False),
        ("post_action_expunge", "bool", False, False),
        ("post_action_ignore_skipped", "bool", False, False),
        ("max_body_chars", "text", False, False),
        ("subject_prefix", "text", False, False),
        ("allow_from", "list", False, False),
        ("verify_dkim", "bool", False, False),
        ("verify_spf", "bool", False, False),
        ("allowed_attachment_types", "list", False, False),
        ("max_attachment_size", "text", False, False),
        ("max_attachments_per_email", "text", False, False),
    )
    return [
        {
            "key": key,
            "type": widget,
            "secret": secret,
            "required": required,
            "help_key": f"{_HELP_KEY_PREFIX}.email.{key}",
        }
        for key, widget, secret, required in specs
    ]


def _websocket_hints() -> list[FieldHint]:
    """Return the hand-written WebSocket field hints (``enabled`` excluded).

    ``required`` decision: nothing is unconditionally required — host/port/path
    carry working defaults and ``unix_socket_path`` is a legitimate alternative
    to host/port, so every field stays ``required=False``. ``ssl_certfile`` /
    ``ssl_keyfile`` are filesystem paths, not secret material (non-secret is
    correct); ``token`` / ``token_issue_secret`` are the secrets.
    """
    specs = (
        ("host", "text", False, False),
        ("port", "text", False, False),
        ("unix_socket_path", "text", False, False),
        ("path", "text", False, False),
        ("token", "password", True, False),
        ("token_issue_path", "text", False, False),
        ("token_issue_secret", "password", True, False),
        ("token_ttl_s", "text", False, False),
        ("websocket_requires_token", "bool", False, False),
        ("allow_from", "list", False, False),
        ("streaming", "bool", False, False),
        ("max_message_bytes", "text", False, False),
        ("ping_interval_s", "text", False, False),
        ("ping_timeout_s", "text", False, False),
        ("ssl_certfile", "text", False, False),
        ("ssl_keyfile", "text", False, False),
    )
    return [
        {
            "key": key,
            "type": widget,
            "secret": secret,
            "required": required,
            "help_key": f"{_HELP_KEY_PREFIX}.websocket.{key}",
        }
        for key, widget, secret, required in specs
    ]


FIELD_HINTS: dict[str, list[FieldHint]] = {
    "dingtalk": _dingtalk_hints(),
    "email": _email_hints(),
    "feishu": _feishu_hints(),
    "qq": _qq_hints(),
    "websocket": _websocket_hints(),
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


def is_secret_key(name: str, key: str) -> bool:
    """Return whether *key* holds a credential for channel *name*.

    A hand-written hint's ``secret`` flag is authoritative for the keys it
    covers (an audited declaration may subtract from the regex fail-safe,
    e.g. websocket's ``token_ttl_s``); derived hints carry the regex verdict
    themselves, and any key no hand-written hint covers — extra stored keys,
    manager overrides, unknown channels — falls back to the unconditional
    :data:`SECRET_KEY_RE` fail-safe.
    """
    hints = FIELD_HINTS.get(name)
    if hints is not None:
        for hint in hints:
            if hint["key"] == key:
                return bool(hint["secret"])
    return bool(SECRET_KEY_RE.search(key))


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

    Each key is classified via :func:`is_secret_key`: a hand-written hint's
    ``secret`` flag is authoritative for the keys it covers, and
    :data:`SECRET_KEY_RE` is the unconditional fail-safe for every key no
    hand-written hint covers, so an unknown channel's ``webhook_secret``
    never leaks.

    Args:
        name: Channel module name.
        section: Raw config section as loaded from disk.

    Returns:
        ``(values, secrets)`` where ``values`` holds non-secret keys with any
        URL userinfo stripped, and each secret is
        ``{"set": bool, "masked": "****"}`` (a suffix is disclosed only for
        values longer than 8 characters).
    """
    values: dict[str, Any] = {}
    secrets: dict[str, dict[str, Any]] = {}
    for key, value in section.items():
        if is_secret_key(name, key):
            secrets[key] = _mask(value)
        else:
            values[key] = _strip_url_userinfo(value)
    return values, secrets
