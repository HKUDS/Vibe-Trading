"""Resolve saved observations into calculation inputs without executing code."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from src.tools.path_utils import FileRoots, allowed_file_roots, resolve_safe_path


def resolve_json_pointer(data: Any, pointer: str) -> tuple[Any, bool]:
    """Select an RFC 6901 JSON value and report whether its source was sampled.

    Args:
        data: Parsed JSON document.
        pointer: Empty for the whole document, otherwise a slash-prefixed pointer.

    Returns:
        The selected value and whether it or an ancestor declares ``truncated: true``.

    Raises:
        ValueError: If the pointer is malformed or names no value in the document.
    """
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("pointer must be an RFC 6901 JSON pointer, e.g. /data/0")
    sampled = False
    for token in pointer.split("/")[1:]:
        sampled |= isinstance(data, dict) and data.get("truncated") is True
        if re.search(r"~(?![01])", token):
            raise ValueError("Invalid JSON pointer escape; use ~0 for ~ and ~1 for /")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(data, list):
            if not (token == "0" or (token.isascii() and token.isdigit() and not token.startswith("0"))):
                raise ValueError("JSON pointer array indices must be non-negative integers without leading zeros")
            if int(token) >= len(data):
                raise ValueError(f"JSON pointer not found: {pointer}")
            data = data[int(token)]
        elif isinstance(data, dict):
            if token not in data:
                raise ValueError(f"JSON pointer not found: {pointer}")
            data = data[token]
        else:
            raise ValueError("JSON pointer cannot descend through a scalar")
    sampled |= isinstance(data, dict) and data.get("truncated") is True
    return data, sampled


def resolve_data_refs(value: Any, run_dir: str | None, sources: list[dict], *, roots: FileRoots) -> Any:
    """Resolve nested JSON/CSV references and record their calculation basis.

    Args:
        value: Argument tree; references use a sole ``__data_ref__`` key.
        run_dir: Current task workspace, subject to the ordinary read boundary.
        sources: Receives file hashes, projections and observation coverage.
        roots: File roots authorized by the host.

    Returns:
        Arguments containing ordinary values or indexed pandas Series.

    Raises:
        ValueError: If a reference escapes readable roots, has invalid data, or names a pointer
            that is malformed or absent from the document.
    """
    if isinstance(value, list):
        return [resolve_data_refs(item, run_dir, sources, roots=roots) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) != {"__data_ref__"}:
        return {key: resolve_data_refs(item, run_dir, sources, roots=roots) for key, item in value.items()}
    import pandas as pd

    ref = value["__data_ref__"]
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
        raise ValueError("__data_ref__ needs a path; use the data tool's _result_file.path")
    path = resolve_safe_path(ref["path"], run_dir, allowed_file_roots(roots=roots), purpose="file", roots=roots)
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if ref.get("sha256") and ref["sha256"] != digest:
        raise ValueError("Data file changed since the supplied sha256; read the current result")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
    elif path.suffix.lower() == ".csv":
        import io
        data = pd.read_csv(io.BytesIO(raw)).to_dict(orient="records")
    else:
        raise ValueError("Data references support JSON and CSV only")
    provenance = data.get("_provenance") if isinstance(data, dict) else None
    pointer = ref.get("pointer", "")
    data, sampled = resolve_json_pointer(data, pointer)
    if isinstance(data, dict) and sampled and isinstance(data.get("data"), list):
        data = data["data"]
    basis = {"path": str(path), "sha256": digest, "pointer": pointer,
             "column": ref.get("column"), "transform": ref.get("transform", "none"),
             "sampled": sampled}
    if provenance is not None:
        basis["provenance"] = provenance
    if ref.get("column"):
        frame = pd.DataFrame(data)
        column = ref["column"]
        index = ref.get("index")
        if frame.empty:
            raise ValueError("Selected data contains no observations")
        values = pd.to_numeric(frame[column], errors="raise")
        if index:
            labels = pd.to_datetime(frame[index], errors="raise", utc=True)
            if labels.duplicated().any() or not labels.is_monotonic_increasing:
                raise ValueError("Data dates must be unique and increasing; select the intended series")
            values.index = pd.DatetimeIndex(labels)
            basis.update(start=str(labels.iloc[0]), end=str(labels.iloc[-1]))
        data = values
        basis["input_rows"] = len(data)
    transform = ref.get("transform", "none")
    if transform == "pct_change":
        if sampled:
            raise ValueError("Sampled rows cannot produce consecutive-bar returns; fetch get_market_data max_rows=0")
        series = pd.Series(data, dtype=float)
        if (series.dropna() <= 0).any():
            raise ValueError("pct_change requires positive observed prices")
        # Missing observations break both adjacent returns; never fill or bridge.
        data = series.pct_change(fill_method=None).dropna()
        basis["output_rows"] = len(data)
        basis["missing_returns"] = max(0, len(series) - 1 - len(data))
    elif transform != "none":
        raise ValueError("Supported transforms: none, pct_change")
    select = ref.get("select")
    if select is not None:
        if select != "last":
            raise ValueError("Supported selection: last")
        if isinstance(data, pd.Series):
            basis["selected_index"] = str(data.index[-1])
            data = data.iloc[-1].item()
        else:
            data = data[-1]
        basis["select"] = select
    sources.append(basis)
    return data
