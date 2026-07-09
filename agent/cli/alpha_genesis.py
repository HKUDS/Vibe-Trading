from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.alpha_foundry.reports.model import AlphaGenesisReport
from src.alpha_foundry.reports.render_markdown import render_markdown


class AlphaGenesisCliError(RuntimeError):
    """Raised for operator-facing CLI report read/render failures."""


def load_report(path: str | Path) -> AlphaGenesisReport:
    try:
        payload: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AlphaGenesisCliError("invalid Alpha Genesis report") from exc
    if not isinstance(payload, dict):
        raise AlphaGenesisCliError("invalid Alpha Genesis report")
    try:
        return AlphaGenesisReport(**payload)
    except TypeError as exc:
        raise AlphaGenesisCliError("invalid Alpha Genesis report") from exc


def render_report_file(path: str | Path, *, markdown: bool = False) -> str:
    report = load_report(path)
    if markdown:
        return render_markdown(report)
    return report.to_json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read Alpha Genesis research artifacts")
    parser.add_argument("report", help="Path to an Alpha Genesis report JSON file")
    parser.add_argument("--markdown", action="store_true", help="Render Markdown instead of JSON")
    args = parser.parse_args(argv)
    try:
        print(render_report_file(args.report, markdown=args.markdown))
    except AlphaGenesisCliError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
