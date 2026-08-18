"""Confine an ``os`` patch to the module under test.

``some_module.os`` is not a per-module copy -- it is the one shared ``os``
module object, so ``monkeypatch.setattr(some_module.os, "replace", boom)``
installs ``boom`` for every importer in the process for the duration of the
test. That is survivable only because monkeypatch undoes it at teardown, and
teardown ordering is not something a test controls: any ``pytest_runtest_``
hook that touches the filesystem runs BEFORE fixture finalizers, so it meets
the replacement, and a replacement that raises takes the teardown chain with
it -- after which the undo never happens and every later test sees the patched
function (#1123: ~3000 cascading errors from one such test).

Replacing the module's *reference* to ``os`` instead keeps the substitution
inside the module being tested, where it was always meant to be.
"""

from __future__ import annotations

import os
from types import ModuleType
from typing import Any


class _ModuleOs:
    """An ``os`` stand-in: overridden names first, the real module behind."""

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)


def patch_module_os(monkeypatch: Any, module: ModuleType, **overrides: Any) -> _ModuleOs:
    """Point ``module.os`` at a stand-in carrying ``overrides``.

    Args:
        monkeypatch: The test's ``monkeypatch`` fixture.
        module: The module whose ``os`` reference should be replaced.
        **overrides: ``os`` attribute names mapped to their replacements.

    Returns:
        The stand-in, so a test can add or swap an attribute mid-run.

    Raises:
        AttributeError: If an override names something ``os`` does not have,
            which would otherwise silently test a function nobody calls.
    """
    for name in overrides:
        getattr(os, name)
    stand_in = _ModuleOs()
    for name, value in overrides.items():
        setattr(stand_in, name, value)
    monkeypatch.setattr(module, "os", stand_in)
    return stand_in
