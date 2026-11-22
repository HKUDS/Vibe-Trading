"""`list --limit` and `memory search --limit` must be positive counts."""

from __future__ import annotations

import cli.commands.parser as _cmd_parser

import pytest



@pytest.mark.parametrize(
    "argv",
    [
        ["list", "--limit", "-1"],
        ["list", "--limit", "0"],
        ["memory", "search", "runbook", "--limit", "-1"],
        ["memory", "search", "runbook", "--limit", "0"],
    ],
)
def test_non_positive_limit_is_a_usage_error(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        _cmd_parser.build_parser().parse_args(argv)
    assert exc.value.code == 2
    assert "positive integer" in capsys.readouterr().err


def test_positive_limit_is_accepted() -> None:
    parser = _cmd_parser.build_parser()
    assert parser.parse_args(["list", "--limit", "3"]).list_limit == 3
    assert parser.parse_args(["memory", "search", "q", "--limit", "2"]).memory_limit == 2
