"""G1 evidence: anchored redaction — no over-redaction, idempotent, None-safe.

Covers ``redact_internal_paths`` (path-boundary aware root scrubbing) and
``redact_text`` (pattern scrubbing for free-form text surfaces).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

import src.tools.redaction as red_mod
from src.tools.redaction import _internal_roots, redact_internal_paths, redact_text

#: Short synthetic root used to test boundary behaviour deterministically,
#: independent of the machine's home / venv layout.
_SYNTHETIC_ROOT = "/data/internal_users"


def _install_synthetic_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Add :data:`_SYNTHETIC_ROOT` to the internal root set for one test.

    Args:
        monkeypatch: pytest patcher (reverted automatically at teardown).
    """
    real_roots = _internal_roots()
    monkeypatch.setattr(
        red_mod,
        "_internal_roots",
        lambda: sorted({*real_roots, _SYNTHETIC_ROOT}, key=len, reverse=True),
    )


def test_none_and_empty_and_nonstr_safe():
    assert redact_internal_paths(None) == ""
    assert redact_internal_paths("") == ""
    assert redact_internal_paths(42) == "42"


def test_internal_leak_is_redacted_but_tail_kept():
    leak = str(Path.cwd() / "agent" / "runs" / "RUN42" / "run.json")
    out = redact_internal_paths(leak)
    assert "<redacted>" in out
    assert str(Path.cwd()) not in out
    assert "RUN42" in out and "run.json" in out


def test_no_over_redaction_of_external_or_caller_paths():
    roots = _internal_roots()
    for keep in ("/etc/passwd", "/api/v1/orders", "../../etc/shadow", "D:\\external\\report.csv"):
        assert not any(rt in keep for rt in roots)
        assert redact_internal_paths(f"err: {keep}") == f"err: {keep}"


def test_idempotent():
    leak = str(Path.home() / "agent" / "x" / "run.json")
    once = redact_internal_paths(leak)
    assert redact_internal_paths(once) == once
    assert "<redacted>" in once


def test_no_over_redaction_when_root_is_name_prefix_of_unrelated_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/data/internal_users`` must not redact ``/data/internal_users_test``.

    A root that is only a *name* prefix of a longer path component is not an
    ancestor, so the naive substring match over-redacted it.
    """
    unrelated = f"{_SYNTHETIC_ROOT}_test/data.csv"
    assert not any(rt in unrelated for rt in _internal_roots())
    _install_synthetic_root(monkeypatch)

    assert redact_internal_paths(unrelated) == unrelated
    # A real descendant of the same root still redacts.
    assert redact_internal_paths(f"{_SYNTHETIC_ROOT}/x.csv") == "<redacted>/x.csv"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_SYNTHETIC_ROOT, "<redacted>"),  # exact match: the whole string
        (f"cwd={_SYNTHETIC_ROOT}", "cwd=<redacted>"),  # root ends the string
        (f'"{_SYNTHETIC_ROOT}"', '"<redacted>"'),  # quoted
        (f"{_SYNTHETIC_ROOT}, next", "<redacted>, next"),  # comma-terminated
        (f"{_SYNTHETIC_ROOT}.", "<redacted>."),  # sentence-final period
        (f"{_SYNTHETIC_ROOT}/x.csv", "<redacted>/x.csv"),  # descendant
        (f"{_SYNTHETIC_ROOT}\\x.csv", "<redacted>\\x.csv"),  # windows separator
        (
            f"a {_SYNTHETIC_ROOT}/x and {_SYNTHETIC_ROOT}/y",
            "a <redacted>/x and <redacted>/y",
        ),  # every occurrence
    ],
)
def test_root_is_redacted_at_every_real_boundary(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    expected: str,
) -> None:
    """Regression: a root followed by a separator is NOT the only leak.

    An exact root (a bare cwd/home path), a root at end of string, and a root
    followed by punctuation all disclose internal topology and must redact —
    matching only ``root + separator`` silently stopped redacting them.
    """
    _install_synthetic_root(monkeypatch)
    assert redact_internal_paths(text) == expected


def test_internal_roots_tracks_cwd_changes() -> None:
    """``_internal_roots`` must reflect the live cwd, not the first one seen.

    The root set is memoized per working directory; a globally cached set went
    stale after ``os.chdir`` and silently stopped redacting the new cwd.
    """
    first_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp_dir:
        real_tmp = os.path.realpath(tmp_dir)
        os.chdir(tmp_dir)
        try:
            with_cwd = _internal_roots()
        finally:
            os.chdir(first_cwd)
        without_cwd = _internal_roots()

    # ``Path.cwd()`` resolves symlinks (macOS /tmp → /private/tmp), so accept
    # either spelling of the temporary directory.
    assert real_tmp in with_cwd or tmp_dir in with_cwd
    assert real_tmp not in without_cwd and tmp_dir not in without_cwd


#: ``(raw, expected)`` credential shapes for :func:`redact_text`. Quoted
#: values, quoted JSON keys and bearer tokens all bypassed the first pattern
#: revision, so each shape is asserted exactly and re-checked for idempotence.
_CREDENTIAL_SHAPES = (
    ("api_key=abc123", "api_key=[redacted]"),
    ('api_key="abc123"', 'api_key="[redacted]"'),
    ("api_key='abc123'", "api_key='[redacted]'"),
    ('{"api_key": "abc123"}', '{"api_key": "[redacted]"}'),
    ("{'api_key': 'abc123'}", "{'api_key': '[redacted]'}"),
    ("API_KEY = abc123", "API_KEY = [redacted]"),
    ("access_token: abc.123-x", "access_token: [redacted]"),
    ("client_secret=abc123", "client_secret=[redacted]"),
    ("SECRET_KEY=deadbeef", "SECRET_KEY=[redacted]"),
    ("passphrase: 'open sesame'", "passphrase: '[redacted]'"),
    ("password: hunter2, user: bob", "password: [redacted], user: bob"),
    ("authorization=raw-token-value", "authorization=[redacted]"),
    ("Authorization: Bearer eyJhbGciOi.J9-_x==", "Authorization: Bearer [redacted]"),
    ("bearer abc123", "bearer [redacted]"),
)


@pytest.mark.parametrize(("raw", "expected"), _CREDENTIAL_SHAPES)
def test_redact_text_scrubs_credential_shapes(raw: str, expected: str) -> None:
    assert redact_text(raw) == expected


@pytest.mark.parametrize("raw", [shape[0] for shape in _CREDENTIAL_SHAPES])
def test_redact_text_is_idempotent(raw: str) -> None:
    """Redacting twice must equal redacting once (previews are re-rendered)."""
    once = redact_text(raw)
    assert redact_text(once) == once
    assert "[redacted]" in once


@pytest.mark.parametrize(
    "raw",
    [
        "Backtest finished: sharpe=1.82, max_drawdown=-0.12",
        "fetched 250 bars, timestamp=1699999999",
        "GET /api/v1/orders 200 in 42ms",
        "content=Quarterly revenue rose 12%",
        "no separator after this token",
        "tokens: 1204 in / 318 out",  # plural = a count, not a credential
        "api_keys: 3 configured",
    ],
)
def test_redact_text_leaves_benign_output_readable(raw: str) -> None:
    """Only credential-shaped ``key=value`` pairs are touched."""
    assert redact_text(raw) == raw


def test_redact_text_scrubs_every_line_of_multiline_output() -> None:
    raw = "line1 api_key=one\nline2 clean\nline3 password: two"
    assert redact_text(raw) == (
        "line1 api_key=[redacted]\nline2 clean\nline3 password: [redacted]"
    )


def test_redact_text_none_and_empty_and_nonstr_safe() -> None:
    assert redact_text(None) == ""
    assert redact_text("") == ""
    assert redact_text(42) == "42"
