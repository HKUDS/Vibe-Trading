"""Shared redaction helpers (CWE-209/497, P10).

Three independent concerns live here:

1. ``redact_internal_paths`` — replaces internal root prefixes with a
   ``'<redacted>'`` sentinel, keeping the relative tail. Caller-supplied or
   external absolute paths stay intact for diagnosability; only our own
   topology is hidden. Idempotent, regex-free (zero ReDoS surface), and
   path-boundary aware: ``/Users/me`` redacts ``/Users/me/x`` and a bare
   ``/Users/me`` but never the unrelated ``/Users/metest/x``.
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
   Classification is *sink aware*: :data:`ARGUMENTS_SINK` (the fail-closed
   default, used for tool-call arguments and the audit ledger) and
   :data:`RESULT_SINK` (tool results, where a ``content`` envelope is the
   payload the trace exists to explain). See :data:`_RESULT_SAFE_KEYS`.
3. ``redact_text`` / ``redact_tool_result`` — pattern scrub for free-form
   text surfaces (plain-text tool results, shell output, error messages, log
   lines) that :func:`redact_payload` cannot reach because it only walks
   structured keys. :func:`redact_tool_result` is the single choke point for
   a tool result: it dispatches JSON to the key walk and everything else to
   the pattern scrub, so one call covers trace persistence and every event
   preview.
"""

from __future__ import annotations

import json
import re
import sys
import sysconfig
from functools import lru_cache
from pathlib import Path
from typing import Any

_SENTINEL = "<redacted>"

_REDACTED = "[redacted]"

#: Sink identifiers for :func:`is_sensitive_arg` / :func:`redact_payload`.
#: ``ARGUMENTS_SINK`` is both the default and the strict one, so a caller that
#: forgets to pass a sink gets the strongest key set; only a caller that has
#: reasoned about its surface opts into ``RESULT_SINK``. An unrecognized value
#: degrades to the strict behaviour (fail closed).
ARGUMENTS_SINK = "arguments"
RESULT_SINK = "result"

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
    "content",
    "env",
    "headers",
    "passphrase",
    "password",
    "secret",
    "token",
} | _PII_EXACT_KEYS

_SENSITIVE_ARG_MARKERS = ("api_key", "authorization", "password", "secret", "token")

#: Keys that stay sensitive in the ARGUMENTS / audit sink but are released in
#: the tool-RESULT sink.
#:
#: ``content`` is the payload field of the ``read_file`` / ``read_document`` /
#: ``read_url`` / ``load_skill`` result envelopes, so redacting it by name
#: blanks out the very text a trace exists to explain — that is the real
#: over-redaction this relaxation fixes. In the arguments sink the same key
#: carries tool *input*: ``write_file(content=…)`` is a whole user document, a
#: generated credential, or a private skill body, so it stays redacted there
#: and in the live audit ledger.
#:
#: ``env`` is deliberately NOT here: its values are secrets in both directions
#: (an env dump in a result leaks exactly what an env argument would).
_RESULT_SAFE_KEYS = {"content"}


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
#: Folded form of :data:`_RESULT_SAFE_KEYS`. Exact (folded) match only, so
#: ``secret_content`` / ``content_token`` keep redacting everywhere.
_RESULT_SAFE_KEYS_FOLDED = frozenset(_fold_key(k) for k in _RESULT_SAFE_KEYS)


@lru_cache(maxsize=8)
def _internal_roots_for_cwd(cwd: str) -> tuple[str, ...]:
    """Compute the internal root prefixes for one working directory.

    Args:
        cwd: Working directory to include among the roots (the cache key).

    Returns:
        Root prefixes, longest first, in both separator spellings.
    """
    # AGENT_DIR derived like agent/src/providers/llm.py:90
    # (Path(__file__).resolve().parents[2]); redaction.py is agent/src/tools/
    # so parents[2] == the agent/ dir. Anchor tracks layout, not hardcoded.
    agent_dir = Path(__file__).resolve().parents[2]
    cands = [
        Path.home(),
        Path(cwd),
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
    return tuple(sorted(roots, key=len, reverse=True))


def _internal_roots() -> list[str]:
    """Return the internal root prefixes to hide, longest first.

    Memoized per working directory rather than globally: a set cached on first
    call would capture the then-current ``Path.cwd()`` and silently stop
    redacting after an ``os.chdir``, while recomputing unconditionally would
    re-run ``sysconfig.get_paths()`` for every redacted string on a tool-result
    hot path. Keying the cache on the live cwd keeps both properties.

    Returns:
        Root prefixes sorted longest-first, so a nested root is replaced before
        its parent.
    """
    return list(_internal_roots_for_cwd(str(Path.cwd())))


def redact_internal_paths(text: object) -> str:
    """Replace internal root prefixes with '<redacted>', keep relative tail.

    Every occurrence of an internal root is replaced when it ends at a real
    path boundary: a separator (``/Users/me/x`` → ``<redacted>/x``), the end of
    the string (an exact root match — a bare cwd or home path is just as much
    of a topology leak), or any other character that cannot continue a path
    component (quote, comma, whitespace, closing bracket …). A root that is
    merely a *name* prefix of a longer component (``/Users/metest/x``) is left
    intact; that over-redaction is what the boundary check fixes.

    Args:
        text: Value to scrub. ``None`` becomes the empty string; non-strings
            are coerced via :func:`str`.

    Returns:
        The scrubbed string. Idempotent — the sentinel contains no root, so
        re-running never nests replacements.
    """
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    if not s:
        return s
    for root in _internal_roots():
        if root not in s:
            continue
        out: list[str] = []
        idx = 0
        while (pos := s.find(root, idx)) >= 0:
            end = pos + len(root)
            nxt = s[end : end + 1]
            after = s[end + 1 : end + 2]
            # A path component continues on a word character, or on a
            # ``.``/``-`` that is itself followed by one (``/Users/me.bak/x``
            # is a different directory, while a trailing ``/Users/me.`` at the
            # end of a sentence is still the root and must be redacted).
            if nxt and (
                nxt.isalnum()
                or nxt == "_"
                or (nxt in "-." and (after.isalnum() or after == "_"))
            ):
                out.append(s[idx:end])
            else:
                out.append(s[idx:pos])
                out.append(_SENTINEL)
            idx = end
        out.append(s[idx:])
        s = "".join(out)
    return s


def is_sensitive_arg(name: str, *, sink: str = ARGUMENTS_SINK) -> bool:
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
        sink: Where the value is headed. :data:`ARGUMENTS_SINK` (the default)
            is the strict set used for tool-call arguments and the live audit
            ledger; :data:`RESULT_SINK` additionally releases the
            :data:`_RESULT_SAFE_KEYS` result envelopes. Any other value is
            treated as :data:`ARGUMENTS_SINK` (fail closed).

    Returns:
        ``True`` when the key holds a credential, account number, or other PII
        value and its value must be replaced with ``'[redacted]'`` before
        surfacing.
    """
    normalized = name.strip().lower()
    folded = _fold_key(name)
    if sink == RESULT_SINK and folded in _RESULT_SAFE_KEYS_FOLDED:
        return False
    if normalized in _SENSITIVE_ARG_KEYS or any(
        marker in normalized for marker in _SENSITIVE_ARG_MARKERS
    ):
        return True
    # Separator-folded match catches camelCase / kebab / spaced variants
    # (accountNumber, account-number, socialSecurityNumber) that the exact
    # snake_case set would miss, without a broad substring over-redaction.
    return folded in _SENSITIVE_ARG_KEYS_FOLDED or any(
        marker in folded for marker in _SENSITIVE_ARG_MARKERS_FOLDED
    )


def redact_payload(obj: Any, *, sink: str = ARGUMENTS_SINK) -> Any:
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
        sink: Where the payload is headed; forwarded to
            :func:`is_sensitive_arg`. In :data:`RESULT_SINK` the surviving
            string leaves are additionally pattern-scrubbed with
            :func:`redact_text`, because a JSON tool result routinely carries
            free text (shell ``stdout``, error bodies) under a benign key that
            no key-based rule can classify.

    Returns:
        A new structure of the same shape with sensitive values replaced. The
        input is never mutated.
    """
    if isinstance(obj, dict):
        return {
            key: _REDACTED
            if is_sensitive_arg(str(key), sink=sink)
            else redact_payload(item, sink=sink)
            for key, item in obj.items()
        }
    if isinstance(obj, list):
        return [redact_payload(item, sink=sink) for item in obj]
    if isinstance(obj, str):
        # Both sinks: key-based classification cannot see a credential embedded
        # inside an otherwise-benign value, e.g. a bearer token in a shell
        # command argument or in a broker error string bound for the ledger.
        return redact_text(obj)
    return obj


#: Credential-shaped key names recognized in FREE TEXT. Longer alternatives
#: come first so ``access_token`` is not clipped to ``token`` and
#: ``secret_key`` is not clipped to ``secret``. The list is deliberately
#: scoped to credential field names so a benign number in shell output (a
#: price, a duration, a timestamp) is never mangled.
#:
#: All names are SINGULAR and ``\b``-anchored: a plural is a count or a
#: collection, never a credential, and matching it mangles routine output
#: (``tokens: 1204 in / 318 out`` from the LLM usage line, ``api_keys: 3``).
_TEXT_CREDENTIAL_KEYS = (
    r"api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token"
    r"|refresh[_-]?token|bearer[_-]?token|id[_-]?token|session[_-]?token"
    r"|client[_-]?secret|secret[_-]?key|private[_-]?key|app[_-]?secret"
    r"|passphrase|password|passwd|authorization|secret|token"
)

#: Value shapes: a double-quoted string, a single-quoted string, or a bare
#: token. The bare branch stops at whitespace, at list/dict/call punctuation
#: and at quotes, so it can neither swallow a following JSON key nor — since
#: ``[`` and ``]`` are excluded — re-match an inserted ``[redacted]``.
_TEXT_VALUE = r"\"[^\"\n]*\"|'[^'\n]*'|[^\s,;{}\[\]()\"']+"

#: ``key=value`` / ``key: value`` / ``"key": "value"`` credential pairs. The
#: key may be quoted (JSON) as long as the quoting is symmetric, matched with a
#: backreference. The negative lookahead keeps the substitution idempotent (an
#: already-redacted value is skipped) and defers ``Bearer <jwt>`` to
#: :data:`_TEXT_BEARER_PATTERN`, which would otherwise be consumed as the value
#: and leave the token body visible.
#:
#: Every quantifier applies to a bounded character class, with no nesting and
#: no overlapping alternatives, so matching stays linear (no ReDoS surface).
_TEXT_KV_PATTERN = re.compile(
    r"(?P<q>[\"']?)\b(?P<name>" + _TEXT_CREDENTIAL_KEYS + r")\b(?P=q)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?![\"']?" + re.escape(_REDACTED) + r"[\"']?|bearer\b)"
    r"(?P<value>" + _TEXT_VALUE + r")",
    re.IGNORECASE,
)

#: ``Authorization: Bearer <token>`` and bare ``bearer <token>`` header values.
#: Applied before :data:`_TEXT_KV_PATTERN`; the value class excludes ``[`` so a
#: second pass cannot match ``Bearer [redacted]``.
_TEXT_BEARER_PATTERN = re.compile(
    r"\b(?P<scheme>bearer)\s+(?P<value>[A-Za-z0-9._~+/-]+=*)",
    re.IGNORECASE,
)


def _sub_credential_pair(match: re.Match[str]) -> str:
    """Rebuild one ``key=value`` match with the value redacted.

    Key and value quoting are preserved, so a redacted JSON fragment stays
    parseable (``{"api_key": "[redacted]"}``) and a second pass produces the
    identical string.

    Args:
        match: Match produced by :data:`_TEXT_KV_PATTERN`.

    Returns:
        The rebuilt ``key``/separator/sentinel fragment.
    """
    value = match.group("value")
    quote = value[0] if value[:1] in ("'", '"') else ""
    key_quote = match.group("q")
    return (
        f"{key_quote}{match.group('name')}{key_quote}{match.group('sep')}"
        f"{quote}{_REDACTED}{quote}"
    )


#: Credential formats recognised WITHOUT a key label. Key-based and
#: ``key=value`` matching both miss a bare token pasted into shell output or an
#: error string, so the well-known issuer prefixes are matched on shape. Each
#: alternative is anchored and length-bounded so ordinary prose cannot match.
_TEXT_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])("
    r"sk-[A-Za-z0-9_-]{20,}"                 # OpenAI / Anthropic style
    r"|gh[pousr]_[A-Za-z0-9]{30,}"           # GitHub PAT family
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"         # Slack
    r"|AKIA[0-9A-Z]{16}"                     # AWS access key id
    r"|pypi-[A-Za-z0-9_-]{16,}"              # PyPI upload token
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"  # JWT
    r")(?![A-Za-z0-9_-])"
)


def redact_text(text: object) -> str:
    """Scrub credential-shaped values from a free-form string.

    Used for plain-text tool results, shell output, error messages and log
    lines where :func:`redact_payload` is a no-op (it only walks structured
    keys). Bearer header values and ``key=value`` / ``key: value`` /
    ``"key": "value"`` credential pairs are replaced with ``'[redacted]'``
    while the surrounding text — labels, paths, error context — stays
    readable.

    Args:
        text: Free-form string (or any object coerced via :func:`str`).
            ``None`` becomes the empty string to match
            :func:`redact_internal_paths`.

    Returns:
        The redacted string. Idempotent: redacting an already-redacted string
        returns it unchanged. Never raises on non-string input.
    """
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    if not s:
        return s
    s = _TEXT_BEARER_PATTERN.sub(r"\g<scheme> " + _REDACTED, s)
    s = _TEXT_KV_PATTERN.sub(_sub_credential_pair, s)
    # Bare tokens with no key label in front of them.
    return _TEXT_TOKEN_PATTERN.sub(_REDACTED, s)


def redact_tool_result(result: object) -> str:
    """Redact one tool result for trace persistence and event previews.

    The single choke point for a tool-result string: callers redact once and
    hand the same value to every subscriber (the persisted trace record, the
    SSE preview, the react trace) instead of redacting per subscriber.

    A JSON result goes through :func:`redact_payload` in the
    :data:`RESULT_SINK`: sensitive keys are replaced by name, ``content``
    envelopes stay readable, and the surviving free-text string leaves are
    pattern-scrubbed — the common shape is a JSON envelope whose ``stdout`` /
    ``error`` field holds raw output that no key-based rule can classify. A
    non-JSON result is pattern-scrubbed directly. Each byte is processed by
    exactly one of the two mechanisms; nothing is redacted twice.

    Args:
        result: Raw tool result (string, or any object coerced via
            :func:`str`). ``None`` becomes the empty string.

    Returns:
        The redacted result as a string. JSON input comes back re-serialized
        with ``ensure_ascii=False`` and default separators, so preview
        consumers that grep the JSON shape (``"audit_id": "la_…"``) keep
        matching.
    """
    if result is None:
        return ""
    text = result if isinstance(result, str) else str(result)
    if not text:
        return text
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return redact_text(text)
    return json.dumps(redact_payload(payload, sink=RESULT_SINK), ensure_ascii=False)
