"""Shared redaction helpers (CWE-209/497, P10).

Two independent concerns live here:

1. ``redact_internal_paths`` — replaces internal root prefixes with a
   ``'<redacted>'`` sentinel, keeping the relative tail. Caller-supplied or
   external absolute paths stay intact for diagnosability; only our own
   topology is hidden. Idempotent and regex-free (zero ReDoS surface).
2. ``redact_payload`` / ``is_sensitive_arg`` — recursively scrub sensitive
   keys from structured tool-call payloads before they reach any event
   stream, trace, or live audit ledger. Two key classes are scrubbed:
   credential keys (OAuth tokens, ``api_key``, ``authorization``, secrets)
   matched by exact name or ``*token*``-style marker, and a curated set of
   exact account/PII field names (``account_number``, ``ssn``,
   ``routing_number`` …). The opaque ``account_ref`` provenance field is
   deliberately preserved (SPEC §5 accountability chain).
   Promoted from the swarm worker's private copies (#142) so
   the swarm worker, the live-action audit, the main agent loop, and the
   paper-trading surfaces all consume one shared implementation.
"""

from __future__ import annotations

import os
import re
import sys
import sysconfig
from pathlib import Path
from typing import Any

_SENTINEL = "<redacted>"

_REDACTED = "[redacted]"

#: Curated EXACT-MATCH PII / account-identifier field names (SPEC Consent §5 /
#: §8 #2). These are scrubbed in addition to the credential-marker keys below.
#: Matching is exact (normalized) on purpose: a broad ``"account"`` substring
#: marker would over-redact benign codebase fields (account balances, account
#: config, etc.), and — critically — would clobber the audit record's own
#: ``account_ref`` provenance field, which is an OPAQUE broker reference that
#: SPEC §5 intentionally keeps as the mandate→consent accountability chain.
#: ``account_ref`` is deliberately absent from this set so it survives.
_PII_EXACT_KEYS = {
    # Generic brokerage account identifiers.
    "account_number",
    "account_id",
    "account_no",
    "account_num",
    "brokerage_account_number",
    "brokerage_account_id",
    # Robinhood-style account fields (raw broker request/response payloads).
    "account_url",
    "rhs_account_number",
    # Government / tax identifiers.
    "ssn",
    "social_security_number",
    "tax_id",
    "taxpayer_id",
    "tin",
    # Bank routing / account.
    "routing_number",
    "bank_account_number",
}

_SENSITIVE_ARG_KEYS = {
    "api_key",
    "authorization",
    "headers",
    "passphrase",
    "password",
    "secret",
    "token",
} | _PII_EXACT_KEYS

_SENSITIVE_ARG_MARKERS = ("api_key", "authorization", "password", "secret", "token")


def _fold_key(name: str) -> str:
    """Fold a key to its alphanumeric core (lower-case, separators stripped).

    Collapses snake_case, camelCase, kebab-case and spaced variants to one form
    so ``account_number``, ``accountNumber``, ``account-number`` and
    ``Account Number`` all match the same curated entry — without resorting to a
    broad ``"account"`` substring that would over-redact benign fields. Regex-free
    (zero ReDoS surface), consistent with the rest of this module.

    Args:
        name: Raw key name.

    Returns:
        The lower-cased, alphanumeric-only fold of ``name``.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


#: Separator-folded forms of the sensitive keys + markers, matched against a
#: folded candidate key so camelCase/kebab variants are caught too.
_SENSITIVE_ARG_KEYS_FOLDED = frozenset(_fold_key(k) for k in _SENSITIVE_ARG_KEYS)
_SENSITIVE_ARG_MARKERS_FOLDED = tuple(_fold_key(m) for m in _SENSITIVE_ARG_MARKERS)


# NOTE: deliberately NOT @cache-decorated. ``Path.cwd()`` is captured at
# import time by a cached version, and a later ``os.chdir`` would silently
# invalidate the cached root set. The list is small (<10 paths) and this
# runs on tool-result hot paths, so the recomputation cost is negligible
# compared to the up-to-date redaction guarantee.
def _internal_roots() -> list[str]:
    # AGENT_DIR derived like agent/src/providers/llm.py:90
    # (Path(__file__).resolve().parents[2]); redaction.py is agent/src/tools/
    # so parents[2] == the agent/ dir. Anchor tracks layout, not hardcoded.
    agent_dir = Path(__file__).resolve().parents[2]
    cands = [
        Path.home(),
        Path.cwd(),
        agent_dir,
        agent_dir.parent,
        Path(sys.prefix),
        Path(sys.base_prefix),
        Path(sysconfig.get_paths().get("purelib", "")),
        Path(sysconfig.get_paths().get("platlib", "")),
    ]
    roots: set[str] = set()
    for c in cands:
        s = str(c)
        if len(s) > 3 and s not in (".", "/", "\\"):
            roots.add(s)
            roots.add(s.replace("\\", "/"))
            roots.add(s.replace("/", "\\"))
    return sorted(roots, key=len, reverse=True)


def redact_internal_paths(text: object) -> str:
    """Replace internal root prefixes with '<redacted>', keep relative tail."""
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    if not s:
        return s
    for root in _internal_roots():
        # Path-aware boundary check: ``"/Users/alice"`` is a prefix of
        # ``"/Users/alice/foo"`` but NOT of ``"/Users/alicetest/bar"``. A
        # naive ``root in s`` substring match over-redacts the unrelated
        # second path; match ``root`` followed by a path separator (or the
        # root appearing as the entire string) anywhere in the input.
        for sep in (os.sep, "\\"):
            boundary = root + sep
            idx = 0
            while True:
                pos = s.find(boundary, idx)
                if pos < 0:
                    break
                s = s[:pos] + _SENTINEL + s[pos + len(root):]
                # Advance past the sentinel so we don't re-match inside it.
                idx = pos + len(_SENTINEL)
    return s


def is_sensitive_arg(name: str) -> bool:
    """Return whether a tool-argument / payload key name should be redacted.

    A key is sensitive when its normalized (stripped, lower-cased) form either

    * is an exact match for a known credential key (``api_key`` …) or a curated
      account/PII field (``account_number``, ``ssn``, ``routing_number`` … see
      :data:`_PII_EXACT_KEYS`), or
    * contains a credential marker substring (so ``api_token``,
      ``access_token``, ``x-authorization`` all redact).

    Account/PII matching is intentionally exact-only — never a broad
    ``"account"`` substring — so benign fields are not over-redacted and the
    audit record's opaque ``account_ref`` provenance field (the
    mandate→consent accountability chain, SPEC §5) is preserved.

    Args:
        name: Argument or payload key name to classify.

    Returns:
        ``True`` when the key holds a credential, account number, or other PII
        value and its value must be replaced with ``'[redacted]'`` before
        surfacing.
    """
    normalized = name.strip().lower()
    if normalized in _SENSITIVE_ARG_KEYS or any(
        marker in normalized for marker in _SENSITIVE_ARG_MARKERS
    ):
        return True
    # Separator-folded match catches camelCase / kebab / spaced variants
    # (accountNumber, account-number, socialSecurityNumber) that the exact
    # snake_case set would miss, without a broad substring over-redaction.
    folded = _fold_key(name)
    return folded in _SENSITIVE_ARG_KEYS_FOLDED or any(
        marker in folded for marker in _SENSITIVE_ARG_MARKERS_FOLDED
    )


def redact_payload(obj: Any) -> Any:
    """Recursively redact sensitive keys in a structured payload.

    Walks dicts and lists; any dict value whose key :func:`is_sensitive_arg`
    is replaced with the ``'[redacted]'`` sentinel. Non-container values pass
    through unchanged. Used before event-preview stringification and before
    writing broker request/response payloads to the live audit ledger.

    Scrubs two key classes (see :func:`is_sensitive_arg`): credential keys
    (OAuth tokens, ``api_key``, ``authorization``, ``password``/``secret``,
    and any ``*token*``-style markers) and a curated set of exact account/PII
    field names (``account_number``, ``ssn``, ``routing_number`` …). It does
    NOT redact the audit record's opaque ``account_ref`` provenance field,
    which is kept for the mandate→consent accountability chain (SPEC §5).

    Args:
        obj: Arbitrary payload (dict / list / scalar) to scrub.

    Returns:
        A new structure of the same shape with sensitive values replaced. The
        input is never mutated.
    """
    if isinstance(obj, dict):
        return {
            key: _REDACTED if is_sensitive_arg(str(key)) else redact_payload(item)
            for key, item in obj.items()
        }
    if isinstance(obj, list):
        return [redact_payload(item) for item in obj]
    return obj


#: Pattern-based redactor for free-form text surfaces (shell command output,
#: error messages, log lines) that :func:`redact_payload` cannot scrub because
#: it only walks structured keys. Each entry is ``(regex, label)``; the regex
#: matches ``key=value``, ``key: value``, or bare token-shaped values, and the
#: match is replaced with ``"<label>=<redacted>"``. The patterns are scoped to
#: known credential / PII field names so a benign number like a price or
#: timestamp in shell output is never mangled.
#
#: Ordering matters: ``bearer`` runs first so the ``authorization:`` /
#: ``token=`` key=value pattern downstream does not consume the literal
#: ``Bearer`` keyword as part of the value (which would leave the JWT body
#: visible).
_TEXT_REDACT_PATTERNS: tuple[tuple[str, str], ...] = (
    # Bearer / OAuth header values (run first; see note above).
    (r"(?i)\bbearer\s+([A-Za-z0-9._\-]+)",
     "Bearer [REDACTED]"),
    # Common credential key=value / key:value pairs. Negative lookahead skips
    # ``Bearer`` so it falls through to the bearer regex above.
    (r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret"
     r"|passphrase|password|secret|token|authorization)\b\s*[:=]\s*"
     r"(?!Bearer\b)([^\s,;\"']+)",
     r"\1=[REDACTED]"),
)


def redact_text(text: object) -> str:
    """Scrub credential-shaped values from a free-form string.

    Used for shell command output, error messages, and log lines where
    :func:`redact_payload` is a no-op (it only walks structured keys). Each
    :data:`_TEXT_REDACT_PATTERNS` entry replaces the matched secret value with
    ``[REDACTED]`` while leaving the surrounding text — labels, paths, error
    context — readable.

    Args:
        text: Free-form string (or any object coerced via :func:`str`).
            ``None`` becomes the empty string to match
            :func:`redact_internal_paths`.

    Returns:
        The redacted string. Never raises on non-string input.
    """
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    if not s:
        return s
    for pattern, replacement in _TEXT_REDACT_PATTERNS:
        s = re.sub(pattern, replacement, s)
    return s
