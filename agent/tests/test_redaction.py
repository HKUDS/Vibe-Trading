"""G1 evidence: anchored redaction — no over-redaction, idempotent, None-safe."""

from __future__ import annotations

import os
from pathlib import Path

from src.tools.redaction import _internal_roots, redact_internal_paths


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


def test_no_over_redaction_when_root_is_substring_of_unrelated_path():
    """Regression for Issue #5: ``/Users/alice`` must NOT redact
    ``/Users/alicetest/foo`` (substrings that share a prefix but are not
    ancestor paths). The path-aware redaction should leave the unrelated
    path intact."""
    roots = _internal_roots()
    # Inject a synthetic short root so we can test the boundary directly
    # without depending on the actual machine's home layout.
    synthetic = "/data/internal_users"
    candidate_unrelated = "/data/internal_users_test/data.csv"
    candidate_descendant = "/data/internal_users/x.csv"

    # Build a temporary roots list by piggy-backing on _internal_roots():
    # the function is uncached so this monkeypatch is per-call.
    import src.tools.redaction as red_mod

    original_roots = red_mod._internal_roots

    def patched_roots():
        return sorted(
            set(original_roots()) | {synthetic, synthetic.replace("/", os.sep)},
            key=len,
            reverse=True,
        )

    red_mod._internal_roots = patched_roots
    try:
        out_unrelated = red_mod.redact_internal_paths(candidate_unrelated)
        out_descendant = red_mod.redact_internal_paths(candidate_descendant)
    finally:
        red_mod._internal_roots = original_roots

    # The unrelated path keeps ``internal_users_test`` unchanged — the old
    # substring match would have clobbered the prefix.
    assert "internal_users_test" in out_unrelated
    assert "<redacted>" not in out_unrelated or "internal_users_test" in out_unrelated
    # The legitimate descendant IS redacted.
    assert "<redacted>" in out_descendant
    assert synthetic not in out_descendant


def test_internal_roots_is_not_cached_across_chdir():
    """Regression for Issue #6: ``_internal_roots`` must reflect the current
    working directory, not the one captured at import time."""
    import os as _os
    import tempfile

    from src.tools import redaction as red_mod

    first_cwd = _os.getcwd()
    with tempfile.TemporaryDirectory() as d:
        d_real = _os.path.realpath(d)
        _os.chdir(d)
        try:
            with_cwd = red_mod._internal_roots()
        finally:
            _os.chdir(first_cwd)
        without_cwd = red_mod._internal_roots()

    # The roots list uses both the symlink and realpath forms (see the
    # s.replace("\\", "/") / s.replace("/", "\\") permutations in
    # _internal_roots), so check either spelling.
    assert (
        d_real in with_cwd or d in with_cwd
    ), "cwd must be reflected when not cached"
    assert (
        d_real not in without_cwd and d not in without_cwd
    ), "cwd should not linger after chdir back"
