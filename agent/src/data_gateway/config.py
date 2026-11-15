"""Resource limits for the local data gateway, independent of runtime repo paths."""

from dataclasses import dataclass
from pathlib import Path

from src.config.accessor import get_env_value


def number(name: str, default: float, minimum: float, maximum: float) -> float:
    """Read a bounded numeric environment setting, refusing invalid values."""
    value = float(get_env_value("VIBE_GATEWAY_" + name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"VIBE_GATEWAY_{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Config:
    """Limits are per process; the disk budget is shared by cache-directory users."""

    cache_dir: Path
    memory_bytes: int = 8 * 1024 * 1024
    disk_bytes: int = 64 * 1024 * 1024
    entry_bytes: int = 2 * 1024 * 1024
    entries: int = 256
    workers: int = 4
    pending: int = 16
    scan_symbols: int = 10000
    scan_attempts: int = 6
    scan_spacing: float = 0.25
    source_spacing: float = 0.25
    http_batch_symbols: int = 4
    source_timeout: float = 6
    request_timeout: float = 15
    ttl: float = 60
    stale_ttl: float = 900
    cooldown: float = 30
    sources: tuple[str, ...] = ("cboe", "yahoo")

    stream_topics: int = 16
    stream_clients: int = 16
    stream_interval: float = 1
    stream_poll: float = 60
    stream_snapshot_interval: float = 15
    health_ttl: float = 300
    stream_quote_age: float = 30
    memory_idle: float = 120
    cleanup_interval: float = 30

    @classmethod
    def from_env(cls) -> "Config":
        """Resolve explicit limits. Cache never follows VIBE_TRADING_HOME."""
        directory = (
            Path(get_env_value("VIBE_GATEWAY_CACHE_DIR", str(Path.home() / ".vibe-trading/cache/gateway")))
            .expanduser()
            .resolve()
        )
        # A cache override must not place quotes under this checkout either.
        repo = Path(__file__).resolve().parents[3]
        if directory == repo or repo in directory.parents:
            raise ValueError("Gateway cache must be outside the repository")
        sources = tuple(
            x.strip() for x in get_env_value("VIBE_GATEWAY_OPTIONS_SOURCES", "cboe,yahoo").split(",") if x.strip()
        )
        if not sources or any(s not in {"yahoo", "cboe"} for s in sources):
            raise ValueError("Gateway options sources must contain yahoo and/or cboe")
        return cls(
            cache_dir=directory,
            memory_bytes=int(number("MEMORY_MB", 8, 0, 128) * 1024**2),
            disk_bytes=int(number("DISK_MB", 64, 0, 1024) * 1024**2),
            entry_bytes=int(number("ENTRY_MB", 2, 0.01, 8) * 1024**2),
            entries=int(number("CACHE_ENTRIES", 256, 1, 2048)),
            workers=int(number("WORKERS", 4, 1, 8)),
            pending=int(number("PENDING", 16, 1, 64)),
            scan_symbols=int(number("SCAN_SYMBOLS", 10000, 1, 10000)),
            scan_attempts=int(number("SCAN_ATTEMPTS", 6, 1, 10)),
            scan_spacing=number("SCAN_SPACING", 0.25, 0.1, 30),
            source_spacing=number("SOURCE_SPACING", 0.25, 0.05, 10),
            http_batch_symbols=int(number("HTTP_BATCH_SYMBOLS", 4, 1, 8)),
            source_timeout=number("SOURCE_TIMEOUT", 6, 0.1, 30),
            request_timeout=number("REQUEST_TIMEOUT", 15, 0.2, 60),
            ttl=number("TTL", 60, 1, 3600),
            stale_ttl=number("STALE_TTL", 900, 1, 86400),
            cooldown=number("COOLDOWN", 30, 1, 300),
            sources=sources,
            stream_topics=int(number("STREAM_TOPICS", 16, 1, 64)),
            stream_clients=int(number("STREAM_CLIENTS", 16, 1, 64)),
            stream_interval=number("STREAM_INTERVAL", 1, 0.25, 60),
            stream_poll=number("STREAM_POLL", 60, 15, 3600),
            stream_snapshot_interval=number("STREAM_SNAPSHOT_INTERVAL", 15, 5, 300),
            health_ttl=number("HEALTH_TTL", 300, 30, 3600),
            stream_quote_age=number("STREAM_QUOTE_AGE", 30, 5, 300),
            memory_idle=number("MEMORY_IDLE", 120, 1, 3600),
            cleanup_interval=number("CLEANUP_INTERVAL", 30, 1, 60),
        )
