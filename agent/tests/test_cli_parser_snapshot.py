"""Parser help snapshot for the modular CLI registry."""
from __future__ import annotations

import json
from pathlib import Path

from cli.commands.parser import build_parser


SNAPSHOT = Path(__file__).with_name("fixtures") / "cli_parser_help_snapshot.json"


def _collect(parser, path: str = "") -> dict[str, str]:
    parser.prog = "vibe-trading" + path.replace("/", " ")
    output = {path: parser.format_help()}
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if not hasattr(choices, "items"):
            continue
        for name, subparser in choices.items():
            output.update(_collect(subparser, f"{path}/{name}"))
    return output


def test_every_command_help_matches_the_pinned_snapshot() -> None:
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert _collect(build_parser()) == expected


def test_dev_defaults_use_the_repository_frontend_and_agent_directory() -> None:
    """Moving handlers must not move the dev server's working directory."""
    from cli.commands import common

    agent_dir = Path(__file__).resolve().parents[1]
    assert common.AGENT_DIR == agent_dir
    for command in ("dev", "setup"):
        args = build_parser().parse_args([command])
        assert Path(args.frontend_dir) == agent_dir.parent / "frontend"
