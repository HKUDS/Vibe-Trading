"""Short fault-injected routing probe with real Yahoo data and default budgets.

Simulates the observed Tencent rejection, slow Eastmoney transport failure and
occupied BaoStock SDK session. Prices are fetched from the real fallback route;
this is deliberately separate from the all-real ten-job mixed restart probe.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
import urllib.error
from unittest.mock import patch


def run(root):
    """Verify timed fallback without persisting price rows.

    Args:
        root: Outside-checkout directory for the cache and diagnostic report.
    """
    import requests
    from backtest.loaders import baostock_loader, eastmoney_loader, tencent_loader
    from src.data_gateway.config import Config
    from src.data_gateway.scheduling import background
    from src.data_gateway.service import MarketDataGateway

    codes = ["000001.SZ", "000002.SZ", "000006.SZ", "000007.SZ"]
    config = Config(root / "cache")
    gateway = MarketDataGateway(config)
    attempts = []
    fetch = baostock_loader.DataLoader.fetch

    def occupied(self, *args, **kwargs):
        started = time.monotonic()
        value = fetch(self, *args, **kwargs)
        attempts.append({"elapsed": time.monotonic() - started, "errors": dict(self.fetch_errors)})
        return value

    def rejected(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test", 501, "injected WAF rejection", {}, None)

    def disconnected(*args, **kwargs):
        # Observed v21a batch duration: 5.1315 seconds. Keep source/request
        # budgets untouched; consume time in a failed adapter, never a retry.
        time.sleep(5.13)
        raise requests.exceptions.ProxyError("injected proxy disconnect")

    token = background.set(True)
    try:
        with (
            baostock_loader._session_admission(config.source_timeout) as owner,
            patch.object(tencent_loader.DataLoader, "_request_page", rejected),
            patch.object(eastmoney_loader.DataLoader, "fetch", disconnected),
            patch.object(baostock_loader.DataLoader, "fetch", occupied),
        ):
            assert owner is not None
            started = time.monotonic()
            result = gateway.bars(codes=codes, start_date="2026-11-02", end_date="2026-11-13")
            elapsed = time.monotonic() - started
        data = result.get("data", {})
        report = {
            "scope": "injected failures and SDK occupancy; real Yahoo bars; one request, no driver retry",
            "limits": asdict(config),
            "elapsed_seconds": elapsed,
            "ok": result.get("ok"),
            "complete": result.get("complete"),
            "error": result.get("error"),
            "returned": list(data.get("_provenance", {})),
            "provenance": data.get("_provenance", {}),
            "coverage": data.get("_coverage", {}),
            "diagnostics": data.get("_diagnostics", {}),
            "sdk_attempts": attempts,
        }
        root.mkdir(parents=True, exist_ok=True)
        (root / "report.json").write_text(json.dumps(report, indent=2, default=str))
        assert result["ok"] and set(report["returned"]) == set(codes), report
        assert elapsed < config.request_timeout and attempts and all(a["elapsed"] < 0.25 for a in attempts)
        assert all(p["source"] == "yahoo" for p in report["provenance"].values())
        print(json.dumps({"passed": True, "elapsed_seconds": elapsed, "sdk_attempts": attempts}))
    finally:
        background.reset(token)
        gateway.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    run(parser.parse_args().root)
