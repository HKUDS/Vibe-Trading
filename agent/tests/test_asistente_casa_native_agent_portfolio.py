"""Regression gates for the native Portfolio agent cutover (ported patch 004).

Note: the legacy `asistente_casa_portfolio` direct-HTTP tool module itself was
NOT ported into this experimental worktree (out of scope: it is not a target
of any of patches 002-016, and production keeps it only as a rollback
artifact). The `_DISABLED_LOCAL_TOOL_NAMES` guard is still ported so that, if
that module is ever added back to this tree, it stays excluded from the
conversational agent by policy rather than by mere absence.
"""

from src.tools import _DISABLED_LOCAL_TOOL_NAMES, build_registry


def test_legacy_direct_portfolio_tool_name_is_on_the_disabled_list():
    assert "asistente_casa_portfolio" in _DISABLED_LOCAL_TOOL_NAMES


def test_legacy_direct_portfolio_tool_is_not_registered():
    registry = build_registry()
    assert registry.get("asistente_casa_portfolio") is None


def test_native_portfolio_summary_remains_available():
    registry = build_registry()
    assert registry.get("portfolio_summary") is not None
