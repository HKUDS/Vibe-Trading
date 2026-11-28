"""Parser help snapshot for the modular CLI registry."""
from __future__ import annotations

import json
from pathlib import Path

from cli.commands.parser import build_parser


SNAPSHOT = Path(__file__).with_name("fixtures") / "cli_parser_help_snapshot.json"
REPO_ROOT = str(Path(__file__).resolve().parents[2])


def _describe(action) -> dict:
    """One argument as data, so the pin does not depend on argparse's layout.

    Python 3.14 renders ``-p PROMPT, --prompt PROMPT`` as ``-p, --prompt PROMPT``
    and wraps usage lines differently, while 3.11 still renders the old form;
    the arguments themselves are unchanged.
    """
    choices = getattr(action, "choices", None)
    return {
        "kind": type(action).__name__,
        "option_strings": list(action.option_strings),
        "dest": action.dest,
        "metavar": action.metavar if action.metavar is None or isinstance(action.metavar, str) else list(action.metavar),
        "nargs": action.nargs,
        "const": repr(action.const),
        # dev/setup default to the checkout's frontend; pin it relative to the repo.
        "default": repr(action.default).replace(REPO_ROOT, "<repo>"),
        "type": getattr(action.type, "__name__", repr(action.type)) if action.type is not None else None,
        "choices": list(choices) if choices is not None else None,
        # A positional's requiredness follows from nargs; 3.13 changed what argparse
        # stores for ``*`` / ``...``, so only an option's flag is pinned.
        "required": action.required if action.option_strings else None,
        "help": action.help,
    }


def _collect(parser, path: str = "") -> dict[str, dict]:
    output = {
        path: {
            "description": parser.description,
            "epilog": parser.epilog,
            "groups": [
                {"title": group.title, "description": group.description, "dests": [a.dest for a in group._group_actions]}
                for group in parser._action_groups
            ],
            "exclusive": [[a.dest for a in group._group_actions] for group in parser._mutually_exclusive_groups],
            "arguments": [_describe(action) for action in parser._actions],
        }
    }
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if not hasattr(choices, "items"):
            continue
        helps = {sub.dest: sub.help for sub in getattr(action, "_choices_actions", [])}
        for name, subparser in choices.items():
            output.update(_collect(subparser, f"{path}/{name}"))
            output[f"{path}/{name}"]["help"] = helps.get(name)
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
