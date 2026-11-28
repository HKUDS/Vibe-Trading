"""Regression tests for the ``show`` subcommand dispatch.

The subcommand parser defines a positional ``run_id``, but the dispatch
previously read the ``--show`` flag instead — so ``vibe-trading show <id>``
always crashed with ``TypeError: unsupported operand type(s) for /:
'PosixPath' and 'NoneType'``. The flag form kept working, hiding the bug.
"""

from __future__ import annotations

import cli.commands.dispatch as _cmd_dispatch
import cli.commands.inspection as _cmd_inspection



def test_show_subcommand_passes_run_id_to_cmd_show(monkeypatch) -> None:
    """``show <run_id>`` must dispatch the positional run_id, not the flag."""
    captured: list[str | None] = []
    monkeypatch.setattr(
        _cmd_inspection, "cmd_show", lambda run_id: captured.append(run_id)
    )
    assert _cmd_dispatch.main(["show", "some_run_123"]) == 0
    assert captured == ["some_run_123"], f"cmd_show got {captured!r}"


def test_show_flag_still_passes_run_id(monkeypatch) -> None:
    """``--show <run_id>`` (legacy flag form) must keep working."""
    captured: list[str | None] = []
    monkeypatch.setattr(
        _cmd_inspection, "cmd_show", lambda run_id: captured.append(run_id)
    )
    assert _cmd_dispatch.main(["--show", "flag_run_456"]) == 0
    assert captured == ["flag_run_456"], f"cmd_show got {captured!r}"


def test_show_missing_run_id_is_usage_error(monkeypatch) -> None:
    """``show`` without a run_id is a parse error, not a crash."""
    captured: list[str | None] = []
    monkeypatch.setattr(
        _cmd_inspection, "cmd_show", lambda run_id: captured.append(run_id)
    )
    assert _cmd_dispatch.main(["show"]) != 0
    assert captured == []
