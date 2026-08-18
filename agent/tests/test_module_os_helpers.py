"""The module-scoped ``os`` patch must stay inside the module it targets."""

from __future__ import annotations

import os
import types
from pathlib import Path

import pytest

from tests.module_os_helpers import patch_module_os


def test_patch_module_os_confines_the_replacement(monkeypatch, tmp_path: Path) -> None:
    """A raising replacement must not reach the interpreter-wide ``os`` (#1123).

    Patching ``module.os`` attributes directly reaches every importer, and
    pytest's own teardown calls ``os.replace`` / ``os.scandir`` while this
    test's fixture finalizers are still pending -- so a raiser installed that
    way aborts the teardown chain and the undo never runs.
    """
    victim = types.ModuleType("victim")
    victim.os = os

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("must never be reachable outside `victim`")

    patch_module_os(monkeypatch, victim, replace=_boom)

    with pytest.raises(RuntimeError):
        victim.os.replace("a", "b")

    source = tmp_path / "source"
    source.write_text("x", encoding="utf-8")
    os.replace(source, tmp_path / "target")
    assert (tmp_path / "target").read_text(encoding="utf-8") == "x"


def test_patch_module_os_forwards_everything_it_does_not_override(monkeypatch) -> None:
    """The stand-in is an ``os``, not a stub of the one call under test."""
    victim = types.ModuleType("victim")
    victim.os = os

    patch_module_os(monkeypatch, victim, fsync=lambda fd: None)

    assert victim.os.path is os.path
    assert victim.os.sep == os.sep
    assert victim.os.fsync(0) is None


def test_patch_module_os_rejects_a_name_os_does_not_have(monkeypatch) -> None:
    """A typo'd override would otherwise stub a function nobody calls."""
    victim = types.ModuleType("victim")
    victim.os = os

    with pytest.raises(AttributeError):
        patch_module_os(monkeypatch, victim, raplace=lambda *_: None)
