"""Isolated Longbridge reader for the portfolio dashboard.

The official macOS SDK owns a native runtime which can terminate the Python
process while its contexts are being destroyed.  Emit the read-only payload
and exit without running native destructors so a connector issue cannot take
down the portfolio API server.
"""

from __future__ import annotations

import json
import os
import sys

MARKER = "VIBE_PORTFOLIO_JSON="


def main() -> None:
    """Print the read-only Longbridge payload and exit without native teardown.

    The payload is emitted on stdout behind :data:`MARKER` as JSON. On failure
    only the exception type is reported, so a connector error can never leak
    credentials or account identifiers into the parent process's logs.
    """
    try:
        from src.trading.connectors.longbridge.sdk import get_account_and_positions, get_quotes
        from src.trading.profiles import profile_by_id
        from src.trading.service import _sdk_config, _sdk_module

        profile = profile_by_id("longbridge-live-sdk-readonly")
        module = _sdk_module(profile.connector)
        connection_id = str(sys.argv[1] if len(sys.argv) > 1 else "").strip()
        overrides = {"connection_id": connection_id} if connection_id else {}
        config = _sdk_config(profile, module, overrides)
        payload = get_account_and_positions(config)
        symbols = [
            str(item.get("symbol") or "")
            for item in payload.get("positions", {}).get("positions", [])
            if item.get("symbol")
        ]
        try:
            payload["quotes"] = get_quotes(symbols, config=config)
        except Exception as exc:  # account totals remain usable if quote permission/network fails
            payload["quotes"] = {
                "status": "error",
                "error": type(exc).__name__,
                "quotes": [],
            }
        print(MARKER + json.dumps(payload, ensure_ascii=False), flush=True)
        os._exit(0)
    except Exception as exc:  # noqa: BLE001 - worker returns a redaction-safe code
        print(
            MARKER
            + json.dumps(
                {"error": type(exc).__name__},
                ensure_ascii=False,
            ),
            flush=True,
        )
        os._exit(1)


if __name__ == "__main__":
    main()
