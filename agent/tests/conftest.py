"""Shared fixtures and sys.path setup for all tests."""

from __future__ import annotations

import atexit
import os
import shutil
import site
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure agent/ is on sys.path so imports like `backtest.*` and `src.*` work.
AGENT_DIR = Path(__file__).resolve().parent.parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# --------------------------------------------------------------------------- #
# Sandbox the config runtime root BEFORE any test module is imported (#1116).
# --------------------------------------------------------------------------- #
# The suite must never resolve its config root against the real ~/.vibe-trading
# (live mandate + audit-ledger state). Modules in BOTH categories must resolve
# to a temp sandbox:
#
#   * Import-time-baked constants (bound when the module is first imported,
#     i.e. during collection): loop.RUNS_DIR/SESSIONS_DIR, goal/session
#     _DB_PATH, helpers.ENV_PATH, memory MEMORY_BASE, skills USER_SKILLS_DIR,
#     strategy_store _DEFAULT_DB_PATH, swarm presets USER_PRESETS_DIR,
#   * Runtime Path.home() call sites: redaction's internal-root anchors
#     (_internal_roots_for_cwd), alpha_bench report output (_default_output_dir),
#     autopilot run dirs, uploads shadow_reports.
#
# Because the import-time constants are baked during test-module collection, the
# sandbox cannot be a pytest fixture (fixtures run AFTER collection); it has to
# be installed at conftest import time, before pytest imports any test module.
#
# The sandbox owns exactly ONE knob: the home directory. ``get_runtime_root()``
# consults ``VIBE_TRADING_HOME`` first and only falls back to
# ``Path.home()/".vibe-trading"`` (src/config/paths.py:27-34), so the override is
# DELETED rather than pointed at the sandbox. Two reasons, both load-bearing:
#
#   * A developer with ``VIBE_TRADING_HOME`` exported in their shell would
#     otherwise keep resolving to it — the leak this sandbox exists to close.
#   * Setting it would outrank every per-test ``monkeypatch.setenv("HOME")`` /
#     ``monkeypatch.setattr(Path, "home", ...)``, silently collapsing per-test
#     roots into one shared directory. That is not hypothetical: it made
#     test_shadow_account's "returns latest" read a profile another test in the
#     same file had saved.
#
# With the override gone, ``Path.home()`` is the single point of control, so a
# test redirecting home gets its own root on every platform and needs no
# knowledge of this sandbox. On Windows ``Path.home()`` ignores $HOME and reads
# %USERPROFILE%, so both spellings are set.
_PRIOR_SANDBOX_ENV = {
    key: os.environ.get(key)
    for key in ("VIBE_TRADING_HOME", "HOME", "USERPROFILE", "PYTHONPATH")
}

# Outcome guard, armed BEFORE the redirect so it reuses the app's own resolution
# rather than restating it. The assertions in _sandbox_runtime_root check that
# the redirect is INSTALLED, which is a proxy; this checks what #1116 is actually
# about — that nothing reached the user's own state — so a path the redirect does
# not cover fails the run with the artefact named, instead of quietly appending to
# a live audit ledger for another release. The ledgers are the headline harm
# (fabricated order_rejected records in an append-only, tamper-evident chain) and
# they move only on a real live action, so they cannot produce noise.
from src.config.paths import get_runtime_root  # noqa: E402 — needs AGENT_DIR above

_REAL_LEDGERS = tuple(
    get_runtime_root() / "live" / name for name in ("audit.jsonl", "audit_chain.jsonl")
)
# The sandbox root is RESOLVED. On macOS ``tempfile.mkdtemp()`` returns a path
# under ``/var/folders/...``, which is a symlink to ``/private/var/folders/...``.
# Handing the unresolved form to HOME breaks every guard that compares a
# ``Path.resolve()``d path against a ``Path.home()``-derived prefix: the two
# spellings of the same directory do not compare equal, the guard reads it as an
# escape attempt and refuses. Resolving here keeps one spelling everywhere.
_SANDBOX_HOME = Path(tempfile.mkdtemp(prefix="vibe-trading-test-home-")).resolve()
os.environ.pop("VIBE_TRADING_HOME", None)
os.environ["HOME"] = str(_SANDBOX_HOME)
os.environ["USERPROFILE"] = str(_SANDBOX_HOME)
(_SANDBOX_HOME / ".vibe-trading").mkdir(parents=True, exist_ok=True)

# A developer shell that exports MARKET_DATA_ORDER_* would silently reorder
# the default fallback chains (registry.refresh_source_order_overrides reads
# them at import time), breaking every default-order assertion in the suite.
# Scrub them for the session; override tests set them explicitly and restore
# defaults themselves. Must run before any test module imports the registry.
_PRIOR_SOURCE_ORDER_ENV = {
    key: os.environ.pop(key)
    for key in [k for k in list(os.environ) if k.startswith("MARKET_DATA_ORDER_")]
}

# Tests that spawn a subprocess hand it this environment, HOME included. On a
# machine whose dependencies live in the per-user site directory -- what
# ``pip install --user`` does, and the default when no virtualenv is active --
# that directory is derived FROM HOME, so redirecting HOME hides numpy, pandas
# and pytest itself from every child. The child then comes up with a partial
# tool registry rather than an error (tool auto-discovery logs an import failure
# and moves on), which surfaces as a baffling "Tool 'x' not found" far from the
# cause. ``site.USER_SITE`` was computed at interpreter startup, before this
# redirect, so it still names the real directory: pin it for children.
if site.ENABLE_USER_SITE and site.USER_SITE and Path(site.USER_SITE).is_dir():
    _prior_path = os.environ.get("PYTHONPATH", "")
    if site.USER_SITE not in _prior_path.split(os.pathsep):
        os.environ["PYTHONPATH"] = os.pathsep.join(
            part for part in (site.USER_SITE, _prior_path) if part
        )


def _ledger_state() -> dict[str, tuple[int, int] | None]:
    """Return (size, mtime_ns) per real live ledger; None where absent."""
    state: dict[str, tuple[int, int] | None] = {}
    for path in _REAL_LEDGERS:
        try:
            stat = path.stat()
        except OSError:
            state[str(path)] = None
        else:
            state[str(path)] = (stat.st_size, stat.st_mtime_ns)
    return state


_REAL_LEDGER_BASELINE = _ledger_state()


def _assert_real_root_untouched() -> None:
    """Raise if the user's own live ledgers moved during the run."""
    if changed := [p for p, now in _ledger_state().items() if _REAL_LEDGER_BASELINE[p] != now]:
        raise AssertionError(
            f"The suite wrote into the REAL config root (#1116): {changed}. "
            f"Something resolved outside the sandbox at {_SANDBOX_HOME}. Route "
            "the write through get_runtime_root(); do not widen this guard."
        )


def _teardown_sandbox() -> None:
    shutil.rmtree(_SANDBOX_HOME, ignore_errors=True)
    for key, prior in _PRIOR_SANDBOX_ENV.items():
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior
    os.environ.update(_PRIOR_SOURCE_ORDER_ENV)


# Safety net for e.g. `--collect-only` (no fixtures run) and abnormal exits.
atexit.register(_teardown_sandbox)


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001 - pytest hook
    """Fail the run if anything escaped the sandbox into the user's own state."""
    _assert_real_root_untouched()


@pytest.fixture(autouse=True, scope="session")
def _sandbox_runtime_root():
    """Guard the import-time sandbox and tear it down at session end.

    Home is redirected at conftest import time above — before collection, so
    constants baked at module import resolve there too. This fixture only asserts
    the invariant is still active and removes the temp dir at session end. The
    function-scoped ``_reset_env_config`` fixture snapshots the environment each
    test, so the sandbox survives every test while per-test monkeypatches keep
    working.
    """
    assert os.environ["HOME"] == str(_SANDBOX_HOME)
    assert os.environ["USERPROFILE"] == str(_SANDBOX_HOME)
    yield _SANDBOX_HOME / ".vibe-trading"
    _teardown_sandbox()


@pytest.fixture(autouse=True)
def _reset_env_config():
    """Isolate each test from the process environment and the config cache.

    Two things leak between tests otherwise, and the second one bit us:

    1. The cached ``EnvConfig`` singleton, so ``monkeypatch.setenv`` would have
       no effect on anything already holding the cached instance.
    2. ``os.environ`` itself. The settings write path deliberately applies a
       written ``.env`` to the running process, which is correct in production
       (settings take effect without a restart) but means a settings TEST
       writing ``TUSHARE_TOKEN=ts-secret-token`` into a temp file leaks that
       value into the process for every test that follows. That is exactly how
       four live-data tests came to fail with "token is wrong" while passing in
       isolation -- and monkeypatch cannot undo it, because the test never went
       through monkeypatch to set it.

    Snapshotting and restoring the whole environment closes the class of bug
    rather than the one instance of it.
    """
    from src.config.accessor import reset_env_config

    saved_environ = dict(os.environ)
    reset_env_config()
    yield
    os.environ.clear()
    os.environ.update(saved_environ)
    reset_env_config()
