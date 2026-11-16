"""Hash-verified, network-free input snapshots for reproducible experiments."""

from __future__ import annotations

import hashlib
import json
import io
from pathlib import Path

import pandas as pd

from backtest.loaders.base import validate_ohlc


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
        file = (path.parent / entry["path"]).resolve()
        if not file.is_relative_to(path.parent):
            raise ValueError("frozen frame escapes its snapshot")
        raw = file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError(f"frozen input changed: {code}")
        frame = pd.read_csv(io.BytesIO(raw), index_col=0, parse_dates=True)
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
