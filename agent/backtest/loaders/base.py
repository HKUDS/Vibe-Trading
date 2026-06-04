"""DataLoader Protocol, shared exceptions, retry helpers, and loader cache.

The retry/budget helpers are the canonical pattern for any loader that calls
a flaky external API: a wall-clock deadline plus a small backoff schedule
applied only to a declared transient exception class. New loaders should
import :func:`check_budget` and :func:`retry_with_budget` rather than
re-implementing the loop.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Protocol, TypeVar, runtime_checkable

import pandas as pd

logger = logging.getLogger(__name__)


class NoAvailableSourceError(Exception):
    """Raised when no data source is available for a given market."""


def validate_date_range(start_date: str, end_date: str) -> None:
    """Validate that start_date <= end_date.

    Args:
        start_date: Start date string (YYYY-MM-DD).
        end_date: End date string (YYYY-MM-DD).

    Raises:
        ValueError: If dates are invalid or start > end.
    """
    try:
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
    except Exception as exc:
        raise ValueError(f"Invalid date format: start={start_date!r}, end={end_date!r}") from exc
    if start > end:
        raise ValueError(f"start_date ({start_date}) > end_date ({end_date})")


# ---------------------------------------------------------------------------
# Bounded retry / budget helpers (shared by ccxt_loader, okx, and any future
# loader calling a flaky external API).
# ---------------------------------------------------------------------------

DEFAULT_BACKOFF: tuple[float, ...] = (0.5, 1.5, 4.0)
DEFAULT_MAX_RETRIES = 3


def check_budget(deadline: float, label: str, budget_s: float | None = None) -> None:
    """Raise :class:`TimeoutError` if the monotonic clock has crossed ``deadline``.

    Use this between pages of a paginated fetch to fail fast instead of
    grinding through more requests once the wall-clock budget is gone.

    Args:
        deadline: ``time.monotonic()`` instant past which we abort.
        label: Free-form label used in the exception message
            (e.g. ``"ccxt fetch for BTC/USDT"``).
        budget_s: Original budget in seconds, included verbatim in the
            message when present.
    """
    if time.monotonic() > deadline:
        suffix = f" exceeded {budget_s:.0f}s budget" if budget_s is not None else " exceeded budget"
        raise TimeoutError(f"{label}{suffix}")


_T = TypeVar("_T")


def retry_with_budget(
    fn: Callable[[], _T],
    *,
    transient: type[BaseException] | tuple[type[BaseException], ...],
    deadline: float,
    label: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff: tuple[float, ...] = DEFAULT_BACKOFF,
) -> _T:
    """Call ``fn`` with a bounded retry budget on declared transient errors.

    Between attempts sleeps ``min(backoff[attempt], remaining_budget)`` so a
    short remaining budget never spends the full backoff. The terminal
    transient failure — whether ``max_retries`` is exhausted OR the deadline
    has passed — is wrapped in :class:`TimeoutError`, preserving the original
    exception as ``__cause__``. Anything not in ``transient`` propagates
    unchanged on the first occurrence (we never retry an exception class
    the caller didn't opt in to).

    Args:
        fn: Zero-arg callable producing the result.
        transient: Exception class(es) considered transient and retryable.
        deadline: ``time.monotonic()`` instant past which retries are aborted.
        label: Free-form label used in the TimeoutError message
            (e.g. ``"OKX fetch for BTC-USDT"``).
        max_retries: Additional attempts after the first call. Total
            attempts = ``max_retries + 1``.
        backoff: Per-retry sleep seconds. Must have at least
            ``max_retries`` entries.

    Returns:
        Whatever ``fn`` returns.

    Raises:
        ValueError: ``backoff`` is shorter than ``max_retries``.
        TimeoutError: All retries exhausted or the deadline crossed.
        Any non-transient exception: Propagated unchanged from ``fn``.
    """
    if len(backoff) < max_retries:
        raise ValueError(
            f"backoff has {len(backoff)} entries; need >= max_retries ({max_retries})"
        )
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except transient as exc:
            remaining = deadline - time.monotonic()
            if attempt == max_retries or remaining <= 0:
                raise TimeoutError(
                    f"{label} failed after {attempt + 1} attempt(s): {exc}"
                ) from exc
            time.sleep(min(backoff[attempt], max(0.0, remaining)))
    raise AssertionError("unreachable: retry loop must return or raise")  # pragma: no cover


# ---------------------------------------------------------------------------
# Opt-in local loader cache.
# ---------------------------------------------------------------------------

LOADER_CACHE_ENV = "VIBE_TRADING_DATA_CACHE"
_LOADER_CACHE_TRUE_VALUES = {"1", "true", "yes", "on"}
_LOADER_CACHE_VERSION = 1


def loader_cache_enabled() -> bool:
    """Return whether the local market-data cache is explicitly enabled."""
    return os.getenv(LOADER_CACHE_ENV, "").strip().lower() in _LOADER_CACHE_TRUE_VALUES


def make_loader_cache_key(
    *,
    source: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    fields: list[str] | tuple[str, ...] | None = None,
    as_of_date: str | None = None,
) -> str:
    """Build a stable content-addressed key for one loader payload."""
    payload = _loader_cache_payload(
        source=source,
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        fields=fields,
        as_of_date=as_of_date,
    )
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def loader_cache_path(
    *,
    source: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    fields: list[str] | tuple[str, ...] | None = None,
    as_of_date: str | None = None,
) -> Path:
    """Return the parquet cache path for one loader payload."""
    key = make_loader_cache_key(
        source=source,
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        fields=fields,
        as_of_date=as_of_date,
    )
    source_dir = _sanitize_cache_segment(source)
    return Path.home() / ".vibe-trading" / "cache" / "loaders" / source_dir / f"{key}.parquet"


def cached_loader_fetch(
    *,
    source: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    fields: list[str] | tuple[str, ...] | None,
    fetch: Callable[[], pd.DataFrame | None],
    as_of_date: str | None = None,
) -> pd.DataFrame | None:
    """Fetch one DataFrame through the opt-in local cache.

    Cache read/write failures are intentionally non-fatal: a bad local entry
    falls back to the provider, and write failures simply leave the run
    uncached.
    """
    if not loader_cache_enabled():
        return fetch()

    cache_path = loader_cache_path(
        source=source,
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        fields=fields,
        as_of_date=as_of_date,
    )
    cached = _read_loader_cache_frame(cache_path)
    if cached is not None:
        return cached

    frame = fetch()
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        _write_loader_cache_frame(cache_path, frame)
    return frame


def _loader_cache_payload(
    *,
    source: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    fields: list[str] | tuple[str, ...] | None,
    as_of_date: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": _LOADER_CACHE_VERSION,
        "source": str(source),
        "symbol": str(symbol),
        "timeframe": str(timeframe),
        "start_date": _normalize_cache_date(start_date),
        "end_date": _normalize_cache_date(end_date),
        "fields": [str(field) for field in (fields or ())],
    }
    if as_of_date is not None:
        payload["as_of_date"] = _normalize_cache_date(as_of_date)
    return payload


def _normalize_cache_date(value: str) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _sanitize_cache_segment(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip().lower())
    return cleaned or "unknown"


def _loader_cache_metadata_path(cache_path: Path) -> Path:
    return cache_path.with_suffix(cache_path.suffix + ".json")


def _read_loader_cache_frame(cache_path: Path) -> pd.DataFrame | None:
    if not cache_path.is_file():
        return None

    metadata_path = _loader_cache_metadata_path(cache_path)
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - local cache miss is non-fatal
        logger.warning("loader cache metadata read failed for %s: %s", cache_path.name, exc)
        return None

    con = None
    try:
        import duckdb

        con = duckdb.connect(database=":memory:")
        frame = con.execute(
            f"SELECT * FROM read_parquet({_duckdb_sql_string(cache_path)})"
        ).fetchdf()
    except Exception as exc:  # noqa: BLE001 - corrupt cache falls back to provider
        logger.warning("loader cache read failed for %s: %s", cache_path.name, exc)
        return None
    finally:
        if con is not None:
            con.close()

    index_columns = metadata.get("index_columns") or []
    if index_columns:
        missing = [column for column in index_columns if column not in frame.columns]
        if missing:
            logger.warning("loader cache %s missing index column(s): %s", cache_path.name, missing)
            return None
        frame = frame.set_index(index_columns)
        frame.index.names = metadata.get("index_names") or index_columns
    return frame


def _write_loader_cache_frame(cache_path: Path, frame: pd.DataFrame) -> None:
    metadata_path = _loader_cache_metadata_path(cache_path)
    tmp_path = cache_path.with_name(f"{cache_path.name}.{os.getpid()}.tmp")
    tmp_metadata_path = metadata_path.with_name(f"{metadata_path.name}.{os.getpid()}.tmp")

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_frame, metadata = _frame_for_loader_cache(frame)

        import duckdb

        con = duckdb.connect(database=":memory:")
        try:
            con.register("cache_frame", cache_frame)
            con.execute(f"COPY cache_frame TO {_duckdb_sql_string(tmp_path)} (FORMAT PARQUET)")
        finally:
            con.close()

        tmp_metadata_path.write_text(
            json.dumps(metadata, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(tmp_path, cache_path)
        os.replace(tmp_metadata_path, metadata_path)
    except Exception as exc:  # noqa: BLE001 - cache write failures should not fail fetches
        logger.warning("loader cache write failed for %s: %s", cache_path.name, exc)
        for path in (tmp_path, tmp_metadata_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _frame_for_loader_cache(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    cache_frame = frame.copy()
    original_index_names = list(cache_frame.index.names)
    index_columns = _cache_index_columns(cache_frame)
    cache_frame.index = cache_frame.index.set_names(index_columns)
    metadata: dict[str, object] = {
        "version": _LOADER_CACHE_VERSION,
        "index_columns": index_columns,
        "index_names": original_index_names,
    }
    return cache_frame.reset_index(), metadata


def _cache_index_columns(frame: pd.DataFrame) -> list[str]:
    columns = {str(column) for column in frame.columns}
    used: set[str] = set()
    index_columns: list[str] = []
    for pos, name in enumerate(frame.index.names):
        base = str(name) if name is not None else f"__vibe_loader_index_{pos}__"
        candidate = base
        suffix = 1
        while candidate in columns or candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        index_columns.append(candidate)
        used.add(candidate)
    return index_columns


def _duckdb_sql_string(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


@runtime_checkable
class DataLoaderProtocol(Protocol):
    """Interface that every data source loader must satisfy."""

    name: str
    markets: set[str]
    requires_auth: bool

    def is_available(self) -> bool:
        """Check whether this data source is usable (token present, network ok, etc.)."""
        ...

    def fetch(
        self,
        codes: list[str],
        start_date: str,
        end_date: str,
        *,
        interval: str = "1D",
        fields: list[str] | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch OHLCV data.

        Returns:
            Mapping ``{symbol: DataFrame(trade_date, open, high, low, close, volume)}``.
        """
        ...
