"""Hash-verified, network-free input snapshots for reproducible experiments."""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from backtest.loaders.base import validate_ohlc

BENCHMARK_PRICE_FILENAME = "benchmark_prices.csv"
BENCHMARK_PRICE_ARTIFACT = f"artifacts/{BENCHMARK_PRICE_FILENAME}"


@dataclass(frozen=True)
class FrozenBenchmarkInput:
    ticker: str
    prices: pd.DataFrame


def read_frozen_input(snapshot: Path, entry: dict, label: str) -> bytes:
    """Read the bytes described by a snapshot entry, or refuse changed input."""
    if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
        raise ValueError(f"invalid frozen input entry: {label}")
    root = snapshot.resolve()
    path = (root / entry["path"]).resolve()
    if not path.is_relative_to(root):
        raise ValueError("frozen frame escapes its snapshot")
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"frozen input is missing: {label}") from exc
    if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
        raise ValueError(f"frozen input changed: {label}")
    return raw


def write_benchmark_prices(path: Path, prices: pd.DataFrame) -> None:
    """Use one UTC offset on disk; the reference entry retains the source zone."""
    if prices.index.tz is not None:
        prices = prices.tz_convert("UTC")
    prices.to_csv(path, index_label="timestamp")


def read_benchmark_prices(raw: bytes, timezone: str | None) -> pd.DataFrame:
    prices = pd.read_csv(io.BytesIO(raw), index_col=0, parse_dates=True, float_precision="round_trip")
    if prices.empty:
        prices.index = pd.DatetimeIndex(prices.index, tz="UTC" if timezone else None)
    if not isinstance(prices.index, pd.DatetimeIndex) or not prices.index.is_unique or prices.index.hasnans:
        raise ValueError("frozen benchmark needs distinct dated bars")
    if (prices.index.tz is None) != (timezone is None):
        raise ValueError("frozen benchmark timezone does not match its input")
    if timezone is not None:
        prices = prices.tz_convert(timezone)
    if set(prices.columns) not in ({"close"}, {"open", "close"}):
        raise ValueError("frozen benchmark needs closing prices and optional opening prices")
    if not prices.empty and (
        any(not pd.api.types.is_numeric_dtype(dtype) for dtype in prices.dtypes) or prices["close"].isna().any()
    ):
        raise ValueError("frozen benchmark prices are invalid")
    return prices.sort_index()


def frozen_benchmark_entry(manifest: dict) -> dict | None:
    """Distinguish old manifests from a declared reference that cannot be used."""
    if "benchmark_input" not in manifest:
        return None
    entry = manifest["benchmark_input"]
    if not isinstance(entry, dict) or entry.get("path") != BENCHMARK_PRICE_FILENAME:
        raise ValueError("invalid frozen benchmark input entry")
    if not isinstance(entry.get("ticker"), str) or not entry["ticker"]:
        raise ValueError("frozen benchmark needs a ticker")
    return entry


def load_frozen_benchmark(manifest_path: str, manifest: dict, config: dict) -> FrozenBenchmarkInput | None:
    """Read a reference separately from the strategy's instruments and calendar."""
    entry = frozen_benchmark_entry(manifest)
    if entry is None:
        return None
    raw = read_frozen_input(Path(manifest_path).expanduser().resolve().parent, entry, "benchmark")
    ticker = entry["ticker"]
    requested = config.get("benchmark")
    if requested and requested not in ("auto", ticker):
        raise ValueError("frozen benchmark differs from the requested ticker")
    prices = read_benchmark_prices(raw, entry.get("timezone"))
    visible = prices.loc[config["start_date"] : config["end_date"]].copy()
    return FrozenBenchmarkInput(ticker, visible)


def load_frozen_frames(manifest_path: str, config: dict) -> tuple[dict, dict]:
    """Read sealed price inputs, filtering before a strategy sees any rows.

    Args:
        manifest_path: Manifest inside an allowed run root.
        config: Requested symbols, date range, and bar interval.

    Returns:
        Frames and the original snapshot metadata.

    Raises:
        ValueError: If a file changed, escapes the snapshot, or lacks coverage.
    """
    from src.tools.path_utils import safe_run_dir

    path = Path(manifest_path).expanduser().resolve()
    safe_run_dir(str(path.parent))
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported frozen-data manifest")
    if manifest.get("interval") != config.get("interval", "1D"):
        raise ValueError("frozen data interval differs from the requested interval")
    frames = {}
    for code in config["codes"]:
        code = code.removeprefix("local:")
        entry = manifest.get("frames", {}).get(code)
        if entry is None:
            raise ValueError(f"frozen snapshot has no data for {code}")
        raw = read_frozen_input(path.parent, entry, code)
        frame = pd.read_csv(
            io.BytesIO(raw), index_col=0, parse_dates=True, float_precision="round_trip"
        )
        if not isinstance(frame.index, pd.DatetimeIndex) or not frame.index.is_unique:
            raise ValueError(f"frozen input needs distinct dated bars: {code}")
        frame = frame.sort_index()
        frame = frame.loc[config["start_date"] : config["end_date"]].copy()
        if frame.empty:
            raise ValueError(f"frozen input has no bars in the requested window: {code}")
        if not {"open", "high", "low", "close"}.issubset(frame.columns):
            raise ValueError(f"frozen input lacks OHLC fields: {code}")
        validate_ohlc(frame, strategy="raise", allow_nonpositive_prices=config.get("allow_nonpositive_prices", False))
        frame.attrs.update(entry.get("attrs", {}))
        frames[code] = frame
    return frames, manifest
