"""Capability discovery derives historical coverage from the existing registry."""


def capabilities(config):
    """Describe routing coverage, not a claim that every endpoint is reachable."""
    from backtest.loaders.registry import FALLBACK_CHAINS, refresh_source_order_overrides

    from .history_router import inventory, INTERVALS

    refresh_source_order_overrides()
    return {
        "ok": True,
        "consumers": {
            "snapshots": "shared by page REST routes, agent tools, MCP and CLI",
            "research": "financial statements, fundamentals, news, flows, screening, holdings, filings, macro and discovery tools",
            "analysis": "registered loaders for backtests, paper simulation, chart reconstruction and indicators",
            "public_http": "shared public HTTP clients and bundled skill examples",
            "cache_policy": "successful public JSON only; incomplete/error results, depth, credential-scoped reads and mutable files are not reused",
            "frames": "full caller-owned DataFrames, unchanged index/dtypes/attrs; not retained in snapshot cache",
            "private_accounts": "separate authorized broker channels; never public snapshot cache",
        },
        "historical_bars": {
            "markets": {market: list(sources) for market, sources in FALLBACK_CHAINS.items()},
            "routing": "existing compatible chains with local-network health",
            "credentials": "existing loader availability rules; no new paid subscription",
        },
        "history_datasets": {
            "source": "auto",
            "markets": list(FALLBACK_CHAINS),
            "sources": inventory(),
            "intervals": list(INTERVALS),
            "adjustment": "source-declared; incompatible chunks are never mixed",
            "coverage": "complete only with coverage verification; otherwise downloaded with explicit warning",
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
