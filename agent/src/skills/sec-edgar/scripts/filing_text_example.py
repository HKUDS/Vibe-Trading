"""Print citable passages from Item 1A of a public 10-K through the agent tool."""

import argparse
import json

from src.tools.sec_filings_tool import SecFilingsTool


def main() -> None:
    """Read the latest 10-K or reproduce a particular recent accession."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--accession", help="Use this exact recent accession")
    args = parser.parse_args()
    tool = SecFilingsTool()
    accession = args.accession
    if accession is None:
        index = json.loads(tool.execute(ticker=args.ticker, form="10-K", limit=1))
        if not index["ok"]:
            raise SystemExit(index["error"])
        filings = index["data"]["filings"]
        if not filings:
            raise SystemExit(f"No recent 10-K for {args.ticker}")
        accession = filings[0]["accession_number"]
    result = json.loads(
        tool.execute(
            ticker=args.ticker, form="10-K", accession_number=accession, item="1A"
        )
    )
    if not result["ok"]:
        raise SystemExit(result["error"])
    print(json.dumps(result["data"], indent=2))


if __name__ == "__main__":
    main()
