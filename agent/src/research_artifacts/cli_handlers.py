"""CLI handlers for ``vibe-trading research-artifact``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .store import ResearchArtifactStore


def _store(args: argparse.Namespace) -> ResearchArtifactStore:
    override = getattr(args, "path", None)
    return ResearchArtifactStore(Path(override).expanduser() if override else None)


def _emit(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _cmd_save(args: argparse.Namespace) -> int:
    evidence = json.loads(args.evidence) if args.evidence else None
    if evidence is not None and not isinstance(evidence, list):
        raise ValueError("evidence must be a JSON array")
    store = _store(args)
    try:
        result = store.save(
            artifact_id=args.artifact_id,
            subject=args.subject,
            universe=args.universe,
            content=args.content,
            data_as_of=args.data_as_of,
            evidence=evidence,
            verification_status=args.verification_status,
            completeness=args.completeness,
            hypothesis_id=args.hypothesis_id,
            goal_id=args.goal_id,
            session_id=args.session_id,
            run_id=args.run_id,
        )
        _emit(result.to_dict())
        return 0
    finally:
        store.close()


def _cmd_search(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        rows = store.search(
            query=args.query,
            subject=args.subject,
            universe=args.universe,
            hypothesis_id=args.hypothesis_id,
            goal_id=args.goal_id,
            session_id=args.session_id,
            run_id=args.run_id,
            limit=args.limit,
        )
        _emit({"count": len(rows), "artifacts": [row.to_dict() for row in rows]})
        return 0
    finally:
        store.close()


def _cmd_show(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        latest = store.get_latest(args.artifact_id)
        if latest is None:
            raise KeyError(f"research artifact not found: {args.artifact_id}")
        _emit(
            {
                "artifact": latest.to_dict(),
                "revisions": [row.to_dict() for row in store.list_revisions(args.artifact_id)],
            }
        )
        return 0
    finally:
        store.close()


def _cmd_revision(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        revision = store.get_revision(args.revision_id)
        if revision is None:
            raise KeyError(f"research revision not found: {args.revision_id}")
        _emit({"revision": revision.to_dict()})
        return 0
    finally:
        store.close()


_DISPATCH: dict[str, Callable[[argparse.Namespace], int]] = {
    "save": _cmd_save,
    "search": _cmd_search,
    "show": _cmd_show,
    "revision": _cmd_revision,
}
_PARSER: argparse.ArgumentParser | None = None


def _link_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hypothesis-id", default="")
    parser.add_argument("--goal-id", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--run-id", default="")


def add_subparser(subparsers: Any) -> argparse.ArgumentParser:
    """Register the research-artifact command tree."""
    global _PARSER
    parser = subparsers.add_parser(
        "research-artifact",
        help="Save, search, and revise evidence-backed research artifacts",
    )
    parser.add_argument("--path", default=None, help="Override research-artifact SQLite path")
    commands = parser.add_subparsers(dest="research_artifact_command")

    save = commands.add_parser("save", help="Save a new artifact or linked revision")
    save.add_argument("--artifact-id", default=None, help="Existing series ID to revise")
    save.add_argument("--subject", default=None)
    save.add_argument("--universe", default=None)
    save.add_argument("--content", required=True)
    save.add_argument("--data-as-of", required=True)
    save.add_argument("--evidence", default=None, help="JSON array of evidence objects")
    save.add_argument("--verification-status", default=None)
    save.add_argument("--completeness", default=None)
    _link_arguments(save)

    search = commands.add_parser("search", help="Search latest research revisions")
    search.add_argument("--query", default="")
    search.add_argument("--subject", default="")
    search.add_argument("--universe", default="")
    search.add_argument("--limit", type=int, default=50)
    _link_arguments(search)

    show = commands.add_parser("show", help="Show a series and its revision history")
    show.add_argument("artifact_id")

    revision = commands.add_parser("revision", help="Show one immutable revision")
    revision.add_argument("revision_id")

    _PARSER = parser
    return parser


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch a research-artifact subcommand."""
    command = getattr(args, "research_artifact_command", None)
    if command is None:
        if _PARSER is not None:
            _PARSER.print_help()
        return 1
    handler = _DISPATCH.get(command)
    if handler is None:
        print(f"unknown research-artifact subcommand: {command}", file=sys.stderr)
        return 1
    try:
        return handler(args)
    except Exception as exc:
        print(f"research-artifact {command} failed: {exc}", file=sys.stderr)
        return 1
