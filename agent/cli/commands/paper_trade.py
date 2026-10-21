"""CLI for local paper accounts and caller-owned step payloads."""

import json
from pathlib import Path

from src.tools.paper_trade.accounts import PaperAccounts


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "paper", help="Forward paper accounts; never places real orders"
    )
    commands = parser.add_subparsers(dest="paper_command", required=True)
    create = commands.add_parser("create", help="Start today or next trading session")
    create.add_argument("--label", required=True)
    create.add_argument("--market", required=True, choices=["cn_a", "hk", "us"])
    create.add_argument(
        "--state", required=True, help="JSON file with cash and positions"
    )
    create.add_argument("--start", default="today", choices=["today", "next_session"])
    commands.add_parser("list")
    for name in ("show", "history", "advance"):
        cmd = commands.add_parser(name)
        cmd.add_argument("account_id")
        if name == "advance":
            cmd.add_argument("--revision", required=True, type=int)
            cmd.add_argument("--to-date", required=True)
            mode = cmd.add_mutually_exclusive_group(required=True)
            mode.add_argument(
                "--orders", help="JSON file containing an order array (or [])"
            )
            mode.add_argument("--strategy-path")
    step = commands.add_parser(
        "step", help="Run a pure step from a caller-owned JSON payload"
    )
    step.add_argument("payload")


def dispatch(args):
    try:
        if args.paper_command == "step":
            from src.tools.paper_trade.tool import run_paper_trade_step

            result = json.loads(
                run_paper_trade_step(json.loads(Path(args.payload).read_text()))
            )
        else:
            service = PaperAccounts()
            if args.paper_command == "create":
                result = service.create(
                    label=args.label,
                    market=args.market,
                    start=args.start,
                    account_state=json.loads(Path(args.state).read_text()),
                )
            elif args.paper_command == "advance":
                result = service.advance(
                    args.account_id,
                    expected_revision=args.revision,
                    to_date=args.to_date,
                    orders=(
                        json.loads(Path(args.orders).read_text())
                        if args.orders
                        else None
                    ),
                    strategy_path=args.strategy_path,
                )
            elif args.paper_command == "list":
                result = service.list()
            elif args.paper_command == "history":
                result = service.history(args.account_id)
            else:
                result = service.get(args.account_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(
            isinstance(result, dict)
            and ("code" in result or result.get("committed") is False)
        )
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
