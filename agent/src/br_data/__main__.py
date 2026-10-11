"""CLI: ``python -m src.br_data {sync,daemon,status}``."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from src.br_data.sync import SOURCES, run_daemon, run_sync


def _status() -> dict:
    from src.br_data.store import connect, db_path

    out: dict = {"db": str(db_path())}
    try:
        with connect() as conn:
            for table, col in (
                ("b3_quotes", "trade_date"), ("cvm_fund_daily", "trade_date"),
                ("cvm_statements", "period_end"), ("bcb_series", "obs_date"),
                ("tesouro_prices", "base_date"),
            ):
                row = conn.execute(f"SELECT COUNT(*), MIN({col}), MAX({col}) FROM {table}").fetchone()
                out[table] = {"rows": row[0], "from": row[1], "to": row[2]}
            for table in ("cvm_funds", "cvm_companies", "cvm_company_tickers"):
                out[table] = {"rows": conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]}
    except FileNotFoundError as exc:
        out["error"] = str(exc)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.br_data", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("sync", "daemon"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--only", nargs="+", choices=SOURCES, help="sources to sync (default: all)")
        if name == "sync":
            cmd.add_argument("--cotahist-from", type=int, help="first COTAHIST year (1986+)")
            cmd.add_argument("--cvm-from", type=int, help="first CVM year")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "status":
        print(json.dumps(_status(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "daemon":
        run_daemon(args.only)
        return 0
    report = run_sync(args.only, cotahist_from=args.cotahist_from, cvm_from=args.cvm_from)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if any(isinstance(v, dict) and "error" in v for v in report.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
