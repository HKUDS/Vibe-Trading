"""Regression tests for the sandboxed runtime root (issue #1116).

The suite must never resolve its config root against the real home directory.
It used to: tests isolated themselves by monkeypatching ``HOME``, which
``Path.home()`` ignores on Windows in favour of ``%USERPROFILE%``, so on Windows
the redirect was inert and runs appended fabricated ``order_rejected`` records to
the real, tamper-evident live audit ledger. ``conftest.py`` now redirects home at
import time — before collection, so constants baked at module import resolve
there too — and these tests pin that contract.

The sandbox controls ``Path.home()`` only, and deliberately DELETES
``VIBE_TRADING_HOME`` rather than setting it, so a single knob decides the root
and per-test home redirection still wins. Both halves are asserted below.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from src.config.paths import get_runtime_root
from src.live.audit import audit_ledger_path
from tests import conftest

AGENT_DIR = Path(__file__).resolve().parent.parent


def test_runtime_root_resolves_into_a_temp_sandbox() -> None:
    """The default root must be a temp sandbox, never the user's own."""
    root = get_runtime_root()

    assert root.is_absolute()
    # Resolve gettempdir() too: on macOS it reports /var/folders/... while the
    # sandbox root is the resolved /private/var/folders/... spelling, and the
    # unresolved form is not a prefix of the resolved one.
    assert root.is_relative_to(Path(tempfile.gettempdir()).resolve()), (
        f"the runtime root is {root}, outside the temp sandbox — the conftest "
        "redirect is not active and tests are writing to a real home (#1116)"
    )
    # The headline harm: the live audit ledger must resolve here too.
    assert audit_ledger_path() == root / "live" / "audit.jsonl"


def test_sandbox_sets_both_home_spellings_and_no_root_override() -> None:
    """One knob, two spellings — and the override must stay unset.

    ``USERPROFILE`` is what ``Path.home()`` reads on Windows, so setting only the
    POSIX ``HOME`` is the original bug. ``VIBE_TRADING_HOME`` must be absent: it
    outranks ``Path.home()``, so setting it would both preserve a developer's
    exported value and override every per-test home redirect.
    """
    sandbox = str(conftest._SANDBOX_HOME)

    assert os.environ["HOME"] == sandbox
    assert os.environ["USERPROFILE"] == sandbox
    assert "VIBE_TRADING_HOME" not in os.environ


def test_per_test_home_redirect_still_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A test redirecting home must get its OWN root, not the shared sandbox.

    This is the property a ``VIBE_TRADING_HOME``-based sandbox silently broke:
    every test that redirected home kept resolving to the one session directory,
    so state saved by one test was visible to the next. It is what made
    test_shadow_account's "returns latest" read another test's saved profile.
    """
    own_home = tmp_path / "own-home"
    monkeypatch.setenv("HOME", str(own_home))
    monkeypatch.setenv("USERPROFILE", str(own_home))  # Windows Path.home()

    assert get_runtime_root() == own_home / ".vibe-trading"
    assert get_runtime_root() != conftest._SANDBOX_HOME / ".vibe-trading"


def test_real_ledger_guard_fires_when_the_ledger_changes() -> None:
    """The outcome guard must reject a changed real ledger, not just a bad env.

    Mutating the baseline is the only way to exercise the positive branch without
    writing to the user's own ledger, which is the thing under guard.
    """
    conftest._assert_real_root_untouched()  # clean state: silent

    guarded = str(conftest._REAL_LEDGERS[0])
    original = conftest._REAL_LEDGER_BASELINE[guarded]
    conftest._REAL_LEDGER_BASELINE[guarded] = (1, 1)
    try:
        with pytest.raises(AssertionError, match="REAL config root"):
            conftest._assert_real_root_untouched()
    finally:
        conftest._REAL_LEDGER_BASELINE[guarded] = original

    conftest._assert_real_root_untouched()  # tracks state, does not latch


def test_guarded_ledgers_are_outside_the_sandbox() -> None:
    """The guard must watch the user's root, not the sandbox it created.

    Closes the mutation "resolve the guarded paths after the redirect": that
    guard would pass unconditionally.
    """
    for ledger in conftest._REAL_LEDGERS:
        assert not ledger.is_relative_to(conftest._SANDBOX_HOME)


def test_sandbox_home_keeps_child_processes_importable() -> None:
    """A subprocess spawned under the sandbox must still import its deps.

    The suite hands its own environment, home included, to every subprocess it
    spawns. Where dependencies live in the per-user site directory — what
    ``pip install --user`` does, and the default outside a virtualenv — that
    directory is derived from home, so redirecting home hides numpy/pandas from
    the child. Tool auto-discovery logs the import failure and continues, so the
    child comes up with a PARTIAL registry and the symptom surfaces later as an
    unrelated "Tool 'x' not found".
    """
    code = (
        "import json, pandas, numpy;"
        "from src.tools import build_registry;"
        "from src.config.accessor import get_env_config;"
        "from src.product.tool_policy import ToolPolicy;"
        "names = build_registry(policy=ToolPolicy.from_config(get_env_config())).tool_names;"
        "print(json.dumps({'count': len(names), 'has': 'options_pricing' in names}))"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(AGENT_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        cwd=str(AGENT_DIR),
        env=env,
        timeout=600,
    )

    assert result.returncode == 0, (
        "a child process could not import its dependencies under the sandbox "
        f"home: {result.stderr.decode()[-2000:]}"
    )
    payload = json.loads(result.stdout.decode().strip().splitlines()[-1])
    assert payload["has"], (
        f"the child built a partial tool registry ({payload['count']} tools, "
        "options_pricing missing) — the sandbox home hid the per-user site "
        "directory from it"
    )
