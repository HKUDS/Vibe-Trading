"""CLI handlers for research protocol and ledger commands."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from src.research_protocol.extractor import draft_protocol_from_hypothesis
from src.research_protocol.ledger import TrialLedger
from src.research_protocol.registry import ProtocolRegistry
from src.research_protocol.trial import TrialEventType


_RESEARCH_PARSER: argparse.ArgumentParser | None = None


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _registry(args: argparse.Namespace) -> ProtocolRegistry:
    root = Path(args.root).expanduser() if getattr(args, "root", None) else None
    artifact_root = Path(args.artifact_root).expanduser() if getattr(args, "artifact_root", None) else None
    return ProtocolRegistry(root=root, artifact_root=artifact_root)


def _cmd_protocol_draft(args: argparse.Namespace) -> int:
    hypothesis = " ".join(args.hypothesis).strip()
    if not hypothesis:
        _err("research protocol draft requires a hypothesis")
        return 1
    protocol = draft_protocol_from_hypothesis(
        hypothesis,
        protocol_id=args.protocol_id,
        created_by="cli",
    )
    saved = _registry(args).save_draft(protocol)
    payload = saved.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"draft {saved.protocol_id} {saved.protocol_hash}")
    return 0


def _cmd_protocol_register(args: argparse.Namespace) -> int:
    registry = _registry(args)
    protocol = registry.register(args.protocol_id, created_by="cli")
    TrialLedger(Path(args.ledger_path).expanduser() if args.ledger_path else None).append(
        protocol_hash=protocol.protocol_hash,
        event_type=TrialEventType.PROTOCOL_REGISTERED,
        payload={"protocol_id": protocol.protocol_id},
    )
    payload = protocol.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"registered {protocol.protocol_id} {protocol.protocol_hash}")
    return 0


def _cmd_ledger_verify(args: argparse.Namespace) -> int:
    result = TrialLedger(Path(args.ledger_path).expanduser() if args.ledger_path else None).verify()
    payload = result.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif result.valid:
        print(f"ledger ok ({result.event_count} events)")
    else:
        print("ledger invalid")
        for error in result.errors:
            print(f"  - {error}")
    return 0 if result.valid else 1


_DISPATCH: dict[tuple[str, str], Callable[[argparse.Namespace], int]] = {
    ("protocol", "draft"): _cmd_protocol_draft,
    ("protocol", "register"): _cmd_protocol_register,
    ("ledger", "verify"): _cmd_ledger_verify,
}


def add_subparser(subparsers: Any) -> argparse.ArgumentParser:
    """Register ``research`` CLI commands."""

    global _RESEARCH_PARSER
    parser = subparsers.add_parser("research", help="Research protocol and ledger commands")
    parser.add_argument("--verbose", action="store_true", help="Show full traceback on errors")
    parser.add_argument("--root", default=None, help="Override protocol registry directory")
    parser.add_argument("--artifact-root", default=None, help="Override artifact store root")
    parser.add_argument("--ledger-path", default=None, help="Override trial ledger SQLite path")
    research_sub = parser.add_subparsers(dest="research_command")

    protocol = research_sub.add_parser("protocol", help="Draft/register research protocols")
    protocol_sub = protocol.add_subparsers(dest="protocol_command")
    draft = protocol_sub.add_parser("draft", help="Create a draft protocol from a hypothesis")
    draft.add_argument("hypothesis", nargs="+", help="Hypothesis text")
    draft.add_argument("--protocol-id", default="proto_draft", help="Protocol id to write")
    draft.add_argument("--json", action="store_true", help="Emit JSON")

    register = protocol_sub.add_parser("register", help="Register an existing draft protocol")
    register.add_argument("protocol_id", help="Protocol id to register")
    register.add_argument("--json", action="store_true", help="Emit JSON")

    ledger = research_sub.add_parser("ledger", help="Trial ledger commands")
    ledger_sub = ledger.add_subparsers(dest="ledger_command")
    verify = ledger_sub.add_parser("verify", help="Verify the trial ledger hash chain")
    verify.add_argument("--json", action="store_true", help="Emit JSON")

    _RESEARCH_PARSER = parser
    return parser


def dispatch(args: argparse.Namespace) -> int:
    """Dispatch ``research`` subcommands."""

    command = getattr(args, "research_command", None)
    subcommand = getattr(args, f"{command}_command", None) if command else None
    handler = _DISPATCH.get((command, subcommand))
    if handler is None:
        if _RESEARCH_PARSER is not None:
            _RESEARCH_PARSER.print_help()
        else:
            _err("research requires a subcommand")
        return 1
    try:
        return int(handler(args))
    except Exception as exc:  # noqa: BLE001
        if getattr(args, "verbose", False):
            traceback.print_exc()
        else:
            _err(f"research {command} {subcommand} failed: {exc}")
        return 1
