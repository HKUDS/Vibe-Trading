"""Export already acquired bars without another fetch or a second in-memory table."""

import csv
import hashlib
import io
import os
from pathlib import Path
import tempfile

from src.config.limits import TOOL_RESULT_LIMIT


_BAR_FIELDS = ("trade_date", "open", "high", "low", "close", "volume")
_PROVENANCE_FIELDS = {
    "currency": "quote_currency", "source": "source", "adjustment": "adjustment",
    "volume_unit": "volume_unit", "timezone": "timezone", "timestamp_basis": "timestamp_basis",
}
_COLUMNS = ("symbol", *_BAR_FIELDS, *_PROVENANCE_FIELDS, "sampled")


def export_bars_csv(payload: dict, folder: Path, root: Path) -> dict:
    """Stream returned bars to an immutable, content-linked task artifact.

    Args:
        payload: Original market result, including sampling and source metadata.
        folder: Existing content-addressed JSON artifact directory.
        root: Authorized task workspace.

    Returns:
        CSV receipt with actual rows, bytes, checksum and fixed column schema.
        Only returned rows are exported; empty values stay empty, prices are
        never rounded, and sampled series remain marked as sampled.

    Raises:
        ValueError: Escaping/modified artifact or malformed bar records.
        OSError: File creation or storage failure.
    """
    path = folder / "bars.csv"
    if not path.resolve().is_relative_to(root):
        raise ValueError("CSV artifact escapes workspace")
    row_count = 0
    sampled = False
    preview = io.StringIO(newline="")
    preview_writer = csv.DictWriter(preview, fieldnames=_COLUMNS)
    preview_writer.writeheader()
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=folder,
                                         prefix=".bars-", delete=False) as stream:
            temp = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=_COLUMNS)
            writer.writeheader()
            for symbol, value in payload.items():
                if symbol.startswith("_"):
                    continue
                rows = value.get("data") if isinstance(value, dict) else value
                if not isinstance(rows, list):
                    continue
                is_sampled = isinstance(value, dict) and value.get("truncated") is True
                sampled |= is_sampled
                provenance = payload.get("_provenance", {}).get(symbol, {})
                for bar in rows:
                    if not isinstance(bar, dict) or "trade_date" not in bar:
                        raise ValueError("CSV requires normalized bar records with trade_date")
                    record = {
                        "symbol": symbol, **{k: bar.get(k) for k in _BAR_FIELDS},
                        **{k: provenance.get(v) for k, v in _PROVENANCE_FIELDS.items()},
                        "sampled": is_sampled,
                    }
                    writer.writerow(record)
                    if row_count < 2:
                        preview_writer.writerow(record)
                    row_count += 1
        with temp.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        size = temp.stat().st_size
        # Atomic publication, without replacing a previous user's edit.
        try:
            os.link(temp, path)
        except FileExistsError:
            with path.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").hexdigest() != digest:
                    raise ValueError("Existing CSV artifact was modified") from None
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    receipt = {
        "path": str(path), "relative_path": str(path.relative_to(root)),
        "format": "csv", "encoding": "utf-8", "sha256": digest, "bytes": size,
        "rows": row_count, "columns": list(_COLUMNS), "sampled": sampled,
        "basis": "returned_rows_only; no_rounding_or_currency_conversion; null_fields_are_empty",
    }
    # The exact header/first records answer format inspection without a head/cat
    # round. This is an output preview budget, never a data/cache memory limit.
    if len(preview.getvalue()) <= TOOL_RESULT_LIMIT // 8:
        receipt["preview_csv"] = preview.getvalue()
        receipt["preview_rows"] = min(row_count, 2)
    return receipt
