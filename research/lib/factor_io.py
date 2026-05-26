"""
factor_io.py — Persist and reload factor time series as Parquet files.

Public API:
    dump_factor_values(symbol, factor_series_dict, manifests_dir) -> Path
    load_factor_values(symbol) -> pd.DataFrame
    load_factor_meta(symbol) -> dict
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    pass

SCHEMA_VERSION = 1

# Resolve manifests dir relative to this file's location:
# factor_io.py lives at research/lib/factor_io.py
# research/ is two parents up from this file when resolved as:
#   factor_io.py -> lib/ -> research/
_LIB_DIR = Path(__file__).resolve().parent       # research/lib/
_RESEARCH_DIR = _LIB_DIR.parent                  # research/
_DEFAULT_MANIFESTS_DIR = _RESEARCH_DIR / "manifests"


def _symbol_short(symbol: str) -> str:
    """Normalize symbol to short lowercase form.

    Accepts either short form ("eth") or full ticker ("ETH-USDT-SWAP").
    Returns lowercase short base, e.g. "eth".
    """
    s = symbol.strip()
    if "-" in s:
        # e.g. "ETH-USDT-SWAP" → "eth"
        return s.split("-")[0].lower()
    return s.lower()


def dump_factor_values(
    symbol: str,
    factor_series_dict: dict[str, pd.Series],
    manifests_dir: Path,
) -> Path:
    """Write factor time series to parquet + sidecar meta.json.

    Parameters
    ----------
    symbol:
        Symbol name, e.g. "eth" or "ETH-USDT-SWAP".
    factor_series_dict:
        Mapping from factor name → aligned pd.Series (DatetimeIndex, UTC).
    manifests_dir:
        Directory to write output into.  Tests pass tmp_path here.

    Returns
    -------
    Path to the written parquet file.
    """
    try:
        import pyarrow  # noqa: F401  # imported to trigger helpful error early
    except ImportError as exc:
        raise ImportError(
            "pyarrow is required to write factor parquet files.  "
            "Install it with:  pip install pyarrow"
        ) from exc

    sym_short = _symbol_short(symbol)

    # Build DataFrame — one column per factor, DatetimeIndex.
    if not factor_series_dict:
        raise ValueError(f"factor_series_dict is empty for symbol '{symbol}'")

    df = pd.DataFrame(factor_series_dict)
    # Ensure index is UTC tz-aware (coerce if naive).
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    # Cast all columns to float64.
    df = df.astype("float64")

    manifests_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = manifests_dir / f"factor_values_{sym_short}.parquet"
    meta_path = manifests_dir / f"factor_values_{sym_short}.meta.json"

    df.to_parquet(parquet_path, engine="pyarrow", compression="snappy")

    factor_names = list(factor_series_dict.keys())
    n_rows = len(df)
    generated_at = datetime.now(timezone.utc).isoformat()
    index_start = df.index.min().isoformat() if n_rows > 0 else ""
    index_end = df.index.max().isoformat() if n_rows > 0 else ""

    meta = {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "generated_at": generated_at,
        "factor_names": factor_names,
        "index_start": index_start,
        "index_end": index_end,
        "n_rows": n_rows,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    n_factors = len(factor_names)
    print(f"[stage1] {sym_short}: wrote factor_values parquet ({n_factors} factors, {n_rows} rows)")

    return parquet_path


def load_factor_values(symbol: str, manifests_dir: Path | None = None) -> pd.DataFrame:
    """Load factor parquet for the given symbol.

    Parameters
    ----------
    symbol:
        Short ("eth") or full ticker ("ETH-USDT-SWAP").
    manifests_dir:
        Override the default manifests directory (useful for tests).

    Raises
    ------
    FileNotFoundError
        If the parquet file does not exist.  Message includes
        "run stage1_factors first" as a hint.
    """
    sym_short = _symbol_short(symbol)
    mdir = manifests_dir if manifests_dir is not None else _DEFAULT_MANIFESTS_DIR
    parquet_path = mdir / f"factor_values_{sym_short}.parquet"

    if not parquet_path.exists():
        raise FileNotFoundError(
            f"Factor values parquet not found at '{parquet_path}'. "
            "run stage1_factors first to generate factor parquet files."
        )

    return pd.read_parquet(parquet_path, engine="pyarrow")


def load_factor_meta(symbol: str, manifests_dir: Path | None = None) -> dict:
    """Load sidecar meta.json for the given symbol.

    Parameters
    ----------
    symbol:
        Short ("eth") or full ticker ("ETH-USDT-SWAP").
    manifests_dir:
        Override the default manifests directory (useful for tests).

    Raises
    ------
    FileNotFoundError
        If the meta.json does not exist.
    ValueError
        If schema_version != SCHEMA_VERSION.
    """
    sym_short = _symbol_short(symbol)
    mdir = manifests_dir if manifests_dir is not None else _DEFAULT_MANIFESTS_DIR
    meta_path = mdir / f"factor_values_{sym_short}.meta.json"

    if not meta_path.exists():
        raise FileNotFoundError(
            f"Factor meta.json not found at '{meta_path}'. "
            "run stage1_factors first to generate factor parquet files."
        )

    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    version = meta.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"factor_values meta.json has schema_version={version!r}, "
            f"expected {SCHEMA_VERSION}.  Re-run stage1_factors to regenerate."
        )

    return meta
