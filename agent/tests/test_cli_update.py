"""Tests for the ``vibe-trading update`` self-upgrade command."""

from __future__ import annotations

import json

import pytest
import requests

from cli import _legacy
from cli.commands import update as update_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakePyPIResponse:
    """Minimal stand-in for ``requests.Response`` carrying a PyPI payload."""

    def __init__(self, latest: str, *, status_error: str | None = None):
        self._latest = latest
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error:
            raise requests.HTTPError(self._status_error)

    def json(self) -> dict:
        return {"info": {"version": self._latest}}


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


def _fake_subprocess(pip_rc: int = 0, verify_stdout: str = "99.0.0") -> tuple[list[list[str]], object]:
    """Install a fake ``subprocess.run`` and return (calls, original_run).

    The pip call is identified by the ``-m pip`` marker, the verification call
    by the ``-c`` marker.
    """
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):  # noqa: ANN001, ANN002
        calls.append(cmd)
        if "-c" in cmd:
            return _FakeProc(0, verify_stdout)
        return _FakeProc(pip_rc)

    return calls, fake_run


def _monkeypatch_upgrade_env(monkeypatch, *, latest: str = "99.0.0", kind: str = update_mod.KIND_WHEEL):
    """Point PyPI + install-kind detection at deterministic fakes."""
    monkeypatch.setattr(update_mod.requests, "get", lambda *a, **k: _FakePyPIResponse(latest))
    monkeypatch.setattr(update_mod, "detect_install_kind", lambda: kind)


# ---------------------------------------------------------------------------
# CLI registration
# ---------------------------------------------------------------------------


def test_parser_accepts_update_subcommand() -> None:
    parser = _legacy._build_parser()

    args = parser.parse_args(["update"])
    assert args.command == "update"


def test_help_lists_update(capsys: pytest.CaptureFixture[str]) -> None:
    parser = _legacy._build_parser()

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--help"])
    assert excinfo.value.code == 0
    assert "update" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Install-kind detection
# ---------------------------------------------------------------------------


class _FakeDist:
    """Stand-in for importlib.metadata.Distribution."""

    def __init__(self, direct_url: dict | None = None, files=None):
        self._direct_url = direct_url
        self.files = files or []

    def read_text(self, filename: str) -> str | None:
        if filename == "direct_url.json" and self._direct_url is not None:
            return json.dumps(self._direct_url)
        return None


def test_detect_install_kind_checkout(monkeypatch) -> None:
    def _raise(*a, **k):  # noqa: ANN001, ANN002
        raise update_mod.PackageNotFoundError

    monkeypatch.setattr(update_mod, "distribution", _raise)
    assert update_mod.detect_install_kind() == update_mod.KIND_CHECKOUT


def test_detect_install_kind_editable_modern_marker(monkeypatch) -> None:
    """direct_url.json with dir_info.editable => editable (modern pip style)."""
    dist = _FakeDist(direct_url={"url": "file:///repo", "dir_info": {"editable": True}})
    monkeypatch.setattr(update_mod, "distribution", lambda *a, **k: dist)
    assert update_mod.detect_install_kind() == update_mod.KIND_EDITABLE


def test_detect_install_kind_wheel(monkeypatch) -> None:
    """direct_url.json WITHOUT editable (a wheel's index URL) => wheel."""
    dist = _FakeDist(direct_url={"url": "https://pypi.org/simple/...", "dir_info": {}})
    monkeypatch.setattr(update_mod, "distribution", lambda *a, **k: dist)
    assert update_mod.detect_install_kind() == update_mod.KIND_WHEEL


def test_detect_install_kind_wheel_without_any_marker(monkeypatch) -> None:
    """No direct_url.json and no egg-info on sys.path => wheel."""
    dist = _FakeDist(direct_url=None)
    monkeypatch.setattr(update_mod, "distribution", lambda *a, **k: dist)
    monkeypatch.setattr(update_mod, "_has_source_tree_egg_info", lambda: False)
    assert update_mod.detect_install_kind() == update_mod.KIND_WHEEL


def test_detect_install_kind_legacy_editable_egg_info(monkeypatch) -> None:
    """Metadata without direct_url.json but an egg-info in the source tree.

    Covers the case that bit us live: running ``python -m cli`` from ``agent/``
    resolves the distribution to ``agent/vibe_trading_ai.egg-info`` (left by
    ``pip install -e .``), which has no ``direct_url.json``.
    """
    dist = _FakeDist(direct_url=None)
    monkeypatch.setattr(update_mod, "distribution", lambda *a, **k: dist)
    monkeypatch.setattr(update_mod, "_has_source_tree_egg_info", lambda: True)
    assert update_mod.detect_install_kind() == update_mod.KIND_EDITABLE


def test_detect_install_kind_corrupt_direct_url_is_wheel(monkeypatch) -> None:
    """Unparseable direct_url.json defaults to the pip path, never crashes."""
    class _CorruptDist:
        def read_text(self, filename: str) -> str:
            return "not-json{"

    monkeypatch.setattr(update_mod, "distribution", lambda *a, **k: _CorruptDist())
    assert update_mod.detect_install_kind() == update_mod.KIND_WHEEL


def test_detect_install_kind_non_dict_direct_url_is_wheel(monkeypatch) -> None:
    """Valid JSON that is not a dict must not crash (AttributeError guard)."""
    class _WeirdDist:
        def read_text(self, filename: str) -> str:
            return "[1, 2, 3]"

    monkeypatch.setattr(update_mod, "distribution", lambda *a, **k: _WeirdDist())
    assert update_mod.detect_install_kind() == update_mod.KIND_WHEEL


def test_has_source_tree_egg_info_finds_egg_info_on_sys_path(monkeypatch, tmp_path) -> None:
    egg_dir = tmp_path / f"{update_mod.PACKAGE_NAME.replace('-', '_')}.egg-info"
    egg_dir.mkdir()
    monkeypatch.setattr(update_mod.sys, "path", [str(tmp_path), "/nonexistent"])
    assert update_mod._has_source_tree_egg_info() is True


def test_has_source_tree_egg_info_absent(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(update_mod.sys, "path", [str(tmp_path)])
    assert update_mod._has_source_tree_egg_info() is False


# ---------------------------------------------------------------------------
# Update flow
# ---------------------------------------------------------------------------


def test_already_up_to_date_no_pip(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Latest PyPI version <= installed version: exit 0, no pip call at all."""
    calls, fake_run = _fake_subprocess()
    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)
    # "0.0.1" is below the repo's dev version (0.1.13), and also below any real release.
    _monkeypatch_upgrade_env(monkeypatch, latest="0.0.1")

    assert update_mod.cmd_update() == update_mod.EXIT_OK
    assert calls == []
    assert "Already up to date" in capsys.readouterr().out


def test_downgrade_protection_no_pip(monkeypatch) -> None:
    """A lower PyPI version must never trigger an install (covers downgrade guard)."""
    calls, fake_run = _fake_subprocess()
    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)
    _monkeypatch_upgrade_env(monkeypatch, latest="0.0.1")

    update_mod.cmd_update()
    assert calls == []


def test_newer_wheel_upgrades(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Newer version + wheel install: exactly one pip upgrade call, exit 0."""
    calls, fake_run = _fake_subprocess(pip_rc=0, verify_stdout="99.0.0")
    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)
    _monkeypatch_upgrade_env(monkeypatch, latest="99.0.0")

    assert update_mod.cmd_update() == update_mod.EXIT_OK
    assert len(calls) == 2
    pip_cmd = calls[0]
    assert pip_cmd[:3] == [update_mod.sys.executable, "-m", "pip"]
    assert "install" in pip_cmd and "--upgrade" in pip_cmd
    assert update_mod.PACKAGE_NAME in pip_cmd
    assert "Updated to 99.0.0" in capsys.readouterr().out


def test_pip_failure_surfaces(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """pip exits non-zero: report failure, exit 1, no verification run."""
    calls, fake_run = _fake_subprocess(pip_rc=1, verify_stdout="99.0.0")
    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)
    _monkeypatch_upgrade_env(monkeypatch, latest="99.0.0")

    assert update_mod.cmd_update() == update_mod.EXIT_FAILED
    assert len(calls) == 1  # pip call only; verification must not run
    assert "Upgrade failed" in capsys.readouterr().out


def test_verification_mismatch(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """pip succeeded but the fresh process reports an older version: exit 1."""
    calls, fake_run = _fake_subprocess(pip_rc=0, verify_stdout="0.0.1")
    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)
    _monkeypatch_upgrade_env(monkeypatch, latest="99.0.0")

    assert update_mod.cmd_update() == update_mod.EXIT_FAILED
    assert len(calls) == 2
    assert "verification mismatch" in capsys.readouterr().out


def test_editable_install_prints_hint_no_pip(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls, fake_run = _fake_subprocess()
    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)
    _monkeypatch_upgrade_env(monkeypatch, latest="99.0.0", kind=update_mod.KIND_EDITABLE)

    assert update_mod.cmd_update() == update_mod.EXIT_OK
    assert calls == []
    assert "git pull" in capsys.readouterr().out


def test_checkout_install_prints_hint_no_pip(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls, fake_run = _fake_subprocess()
    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)
    _monkeypatch_upgrade_env(monkeypatch, latest="99.0.0", kind=update_mod.KIND_CHECKOUT)

    assert update_mod.cmd_update() == update_mod.EXIT_OK
    assert calls == []
    assert "git pull" in capsys.readouterr().out


def test_pypi_fetch_failure_no_pip(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Network/HTTP failure on the version check: clear error, install untouched."""
    def _boom(*a, **k):  # noqa: ANN001, ANN002
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(update_mod.requests, "get", _boom)
    calls, fake_run = _fake_subprocess()
    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)

    assert update_mod.cmd_update() == update_mod.EXIT_FAILED
    assert calls == []
    assert "Could not check for updates" in capsys.readouterr().out


def test_unparseable_installed_version_errors(monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A garbage installed version cannot be compared: exit 1, nothing touched."""
    calls, fake_run = _fake_subprocess()
    monkeypatch.setattr(update_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(update_mod, "CURRENT_VERSION", "not-a-version")
    _monkeypatch_upgrade_env(monkeypatch, latest="99.0.0")

    assert update_mod.cmd_update() == update_mod.EXIT_FAILED
    assert calls == []
    assert "Could not compare versions" in capsys.readouterr().out
