from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.alpha_foundry.reports.model import AlphaGenesisReport
from src.alpha_foundry.reports.render_markdown import render_markdown


def load_report(path: str | Path) -> AlphaGenesisReport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return AlphaGenesisReport(**payload)


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
    print(render_report_file(args.report, markdown=args.markdown))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
