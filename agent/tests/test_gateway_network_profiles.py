"""Simulated regional network restrictions, not evidence of geographic reachability."""

import pandas as pd
import pytest

from src.data_gateway.config import Config
from src.data_gateway.service import MarketDataGateway


@pytest.mark.parametrize("profile", ["dns_block", "tls_failure", "http_451", "http_429", "slow_primary", "offline"])
def test_network_profiles_fail_over_per_market_and_relearn_after_move(tmp_path, monkeypatch, profile):
    from backtest.loaders import registry
    from src import market_data
    from backtest.engines._market_hooks import _detect_market
    import requests

    registry._ensure_registered()
    codes = ["AAPL.US", "00700.HK", "TD.TO", "VOD.L", "601398.SH", "BTC-USDT"]
    currencies = dict(zip(codes, ["USD", "HKD", "CAD", "GBP", "CNY", "USDT"]))
    failures = {
        "dns_block": lambda: ConnectionError("controlled DNS refusal"),
        "tls_failure": lambda: requests.exceptions.SSLError("controlled TLS failure"),
        "http_451": lambda: requests.exceptions.HTTPError("controlled HTTP 451"),
        "http_429": lambda: requests.exceptions.HTTPError("controlled HTTP 429"),
        "slow_primary": lambda: TimeoutError("controlled source deadline exceeded"),
        "offline": lambda: ConnectionError("controlled all-source outage"),
    }
    restored, calls = [False], []

    class Loader:
        name = "primary"

        def is_available(self):
            return True

        def fetch(self, symbols, *args, **kwargs):
            calls.append((self.name, tuple(symbols)))
            if not restored[0] and (self.name == "primary" or profile == "offline"):
                raise failures[profile]()
            result = {}
            for symbol in symbols:
                frame = pd.DataFrame(
                    {k: [10.0, 10.0] for k in ("open", "high", "low", "close", "volume")},
                    index=pd.date_range("2026-11-02", periods=2),
                )
                frame.index.name = "trade_date"
                frame.attrs.update(quote_currency=currencies[symbol], timezone="UTC", timestamp_basis="session_date")
                result[symbol] = frame
            return result

    class Backup(Loader):
        name = "backup"

    monkeypatch.setattr(registry, "refresh_source_order_overrides", lambda: None)
    monkeypatch.setattr(registry, "get_source_order_override", lambda market: None)
    monkeypatch.setattr(registry, "LOADER_REGISTRY", {"primary": Loader, "backup": Backup})
    monkeypatch.setattr(registry, "FALLBACK_CHAINS", {_detect_market(code): ["primary", "backup"] for code in codes})
    monkeypatch.setattr(market_data, "detect_source", lambda code: "primary")
    gateway = MarketDataGateway(Config(tmp_path))
    clock = [100.0]
    gateway.router.clock = lambda: clock[0]
    request = dict(codes=codes, start_date="2026-11-02", end_date="2026-11-03", interval="1D")
    try:
        first = gateway.bars(**request, max_rows=100)
        if profile == "offline":
            assert first["ok"] is False and not first["data"]["_provenance"]
            assert gateway.cache.stats()["memory_entries"] == 0
        else:
            assert first["complete"] is True, first
            assert {v["source"] for v in first["data"]["_provenance"].values()} == {"backup"}
            assert {k: v["quote_currency"] for k, v in first["data"]["_provenance"].items()} == currencies
            before = sum(name == "primary" for name, _ in calls)
            again = gateway.bars(**request, max_rows=101)
            assert again["complete"] is True
            assert sum(name == "primary" for name, _ in calls) == before
        restored[0] = True
        clock[0] += gateway.config.health_ttl + 1
        moved = gateway.bars(**request, max_rows=102)
        assert moved["complete"] is True, moved
        assert {v["source"] for v in moved["data"]["_provenance"].values()} == {"primary"}
        assert gateway.config.memory_bytes == 8 * 1024**2
        assert gateway.config.disk_bytes == 64 * 1024**2
        assert gateway.config.request_timeout == 15
    finally:
        gateway.close()
