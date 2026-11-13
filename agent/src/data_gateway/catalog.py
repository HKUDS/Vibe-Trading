"""Capability discovery derives historical coverage from the existing registry."""


def capabilities(config):
    """Describe routing coverage, not a claim that every endpoint is reachable."""
    from backtest.loaders.registry import FALLBACK_CHAINS, refresh_source_order_overrides

    refresh_source_order_overrides()
    return {
        "ok": True,
        "historical_bars": {
            "markets": {market: list(sources) for market, sources in FALLBACK_CHAINS.items()},
            "routing": "existing compatible chains with local-network health",
            "credentials": "existing loader availability rules; no new paid subscription",
        },
        "history_datasets": {
            "source": "baostock",
            "markets": ["a_share"],
            "symbols": "canonical SH/SZ equities",
            "intervals": ["5m", "15m", "30m", "1H"],
            "adjustment": "raw",
            "coverage": "calendar, daily trading status and exact intraday grid",
            "storage_settings": "/data/history/storage",
            "job_api": "/data/history/jobs",
            "resumable": True,
            "sampled": False,
        },
        "options_chain": {
            "markets": ["us_equity"],
            "sources": list(config.sources),
            "quality": "delayed_or_unknown",
            "coverage": "all standard rows at requested expiration",
            "all_expirations": "discover dates, fetch each on demand",
        },
        "subscriptions": {
            "options": "shared periodic snapshots",
            "bars": "all existing public market routes; periodic bars, not real-time quotes",
            "crypto": "OKX spot WebSocket + REST fallback",
            "all_market_firehose": False,
            "lossless_tick_archive": False,
        },
        "network_policy": "learn from this machine's requests; no IP geolocation; no cross-venue quote substitution",
    }
