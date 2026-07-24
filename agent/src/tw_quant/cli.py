"""Offline ``tw-data`` command for the Phase 01 data foundation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.tw_quant.config import db_path as default_db_path, snapshot_root as default_snapshot_root
from src.tw_quant.data.importers import import_dataset
from src.tw_quant.data.snapshots import create_snapshot
from src.tw_quant.data.verifier import verify_snapshot
from src.tw_quant.db.migrations import migrate


def _path(value: str | None, fallback: Path) -> Path:
    return Path(value).expanduser() if value else fallback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tw-data", description="Offline Taiwan research data foundation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    migrate_parser = subparsers.add_parser("migrate", help="apply DuckDB schema migrations")
    migrate_parser.add_argument("--db-path")

    import_parser = subparsers.add_parser("import", help="validate or append CSV/Parquet data")
    import_parser.add_argument("--dataset", required=True)
    import_parser.add_argument("--input", required=True)
    import_parser.add_argument("--source", required=True)
    import_parser.add_argument("--source-dataset", required=True)
    import_parser.add_argument("--schema-version", type=int, default=1)
    import_parser.add_argument("--revision-id")
    import_parser.add_argument("--mode", choices=("validate_only", "append"), default="validate_only")
    import_parser.add_argument("--db-path")

    snapshot_parser = subparsers.add_parser("snapshot", help="create or verify immutable snapshots")
    snapshot_subparsers = snapshot_parser.add_subparsers(dest="snapshot_command", required=True)

    create_parser = snapshot_subparsers.add_parser("create", help="build and seal a snapshot")
    create_parser.add_argument("--db-path")
    create_parser.add_argument("--snapshot-root")
    create_parser.add_argument("--snapshot-id")
    create_parser.add_argument("--start")
    create_parser.add_argument("--end")
    create_parser.add_argument("--repo-root")

    verify_parser = snapshot_subparsers.add_parser("verify", help="verify a snapshot")
    verify_parser.add_argument("snapshot_id")
    verify_parser.add_argument("--snapshot-root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "migrate":
            result: Any = migrate(_path(args.db_path, default_db_path()))
        elif args.command == "import":
            result = import_dataset(
                args.input,
                args.dataset,
                source=args.source,
                source_dataset=args.source_dataset,
                schema_version=args.schema_version,
                revision_id=args.revision_id,
                mode=args.mode,
                db_path=_path(args.db_path, default_db_path()) if args.mode == "append" else None,
            ).to_dict()
        elif args.snapshot_command == "create":
            result = create_snapshot(
                _path(args.db_path, default_db_path()),
                snapshot_root=_path(args.snapshot_root, default_snapshot_root()),
                snapshot_id=args.snapshot_id,
                start=args.start,
                end=args.end,
                repo_root=args.repo_root,
            )
        else:
            result = verify_snapshot(
                args.snapshot_id,
                _path(args.snapshot_root, default_snapshot_root()),
            ).to_dict()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ok", True) else 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
