"""Bounded quote-only Futu worker; invoked by the provider service."""

from __future__ import annotations

import contextlib
import io
import json
import sys

from src.hk_data.service import normalize_symbols


def main() -> int:
    """Fetch snapshots without opening any trade context or changing accounts."""
    try:
        symbols = normalize_symbols(json.load(sys.stdin))
        rows = []
        # Keep third-party SDK logging out of the machine-readable response.
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            import futu

            context = futu.OpenQuoteContext(host="127.0.0.1", port=11111)
            try:
                for offset in range(0, len(symbols), 20):
                    batch = symbols[offset : offset + 20]
                    result, frame = context.get_market_snapshot(
                        ["HK." + symbol[:-3] for symbol in batch]
                    )
                    if result != futu.RET_OK:
                        continue
                    for row in frame.to_dict("records"):
                        rows.append(
                            {
                                key: str(row[key])
                                for key in (
                                    "code",
                                    "last_price",
                                    "update_time",
                                    "volume",
                                )
                                if key in row
                            }
                        )
            finally:
                context.close()
        print(json.dumps({"rows": rows}, allow_nan=False))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "error": "Futu snapshot unavailable; verify SDK, OpenD and quote rights."
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
