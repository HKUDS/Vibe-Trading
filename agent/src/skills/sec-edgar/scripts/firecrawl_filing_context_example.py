#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reproducible example: SEC filings for one issuer plus optional Firecrawl context.

Runs the ``get_filing_context`` tool for one ticker and form and prints the
SEC paging block and every Firecrawl context item (filing URL, filing date,
form, accession number and the start of the excerpt).

``--offline`` replays the redacted fixture in
``tests/fixtures/firecrawl/aapl_filing_context.json`` (AAPL 8-K, accession
0001140361-26-042798) without any network call, so the output is the same on
every machine. Without ``--offline``, the call is live; without
``FIRECRAWL_API_KEY`` it makes no Firecrawl request and shows the disabled note.
Run from the ``agent/`` directory::

    python src/skills/sec-edgar/scripts/firecrawl_filing_context_example.py --offline
    python src/skills/sec-edgar/scripts/firecrawl_filing_context_example.py AAPL 8-K "Item 8.01"
"""

import json
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.config.accessor import reset_env_config
from src.tools import firecrawl_filing_context_tool, sec_filings_tool
from src.tools.firecrawl_filing_context_tool import FirecrawlFilingContextTool

_FIXTURE = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "firecrawl" / "aapl_filing_context.json"


def _offline(stack: ExitStack) -> None:
    """Serve the SEC index and the Firecrawl response from the redacted fixture."""
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    os.environ["FIRECRAWL_API_KEY"] = "offline-example"
    reset_env_config()
    stack.enter_context(patch.object(sec_filings_tool, "cik_for", lambda ticker: fixture["cik"]))
    stack.enter_context(patch.object(sec_filings_tool, "get_submissions", lambda cik: fixture["sec_submissions"]))
    stack.enter_context(
        patch.object(
            firecrawl_filing_context_tool, "throttled_post_json", lambda url, **kw: fixture["firecrawl_scrape"]
        )
    )


def main() -> None:
    """Fetch filing context for the ticker, form and query given on the command line."""
    args = [a for a in sys.argv[1:] if a != "--offline"]
    ticker = args[0] if len(args) > 0 else "AAPL"
    form = args[1] if len(args) > 1 else "8-K"
    query = args[2] if len(args) > 2 else "Item 8.01"

    with ExitStack() as stack:
        if "--offline" in sys.argv:
            _offline(stack)
        out = json.loads(FirecrawlFilingContextTool().execute(ticker=ticker, form=form, max_filings=1, query=query))
    if not out.get("ok") or "firecrawl_context" not in out:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return

    context = out["firecrawl_context"]
    for item in context["items"]:
        item["excerpt"] = item["excerpt"][:300]
    print(
        json.dumps(
            {"source": out["source"], "paging": out["paging"], "firecrawl_context": context},
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
