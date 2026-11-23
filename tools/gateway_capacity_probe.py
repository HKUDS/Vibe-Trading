"""Synthetic historical-storage capacity experiment, NOT an implemented gateway path.

Generate a declared row count in DuckDB's streaming pipeline, write temporary
Parquet, scan it, and report OS process memory. No market access or real prices.
"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import resource
import sys
import tempfile
import time


def memory():
    if sys.platform == "darwin":

        class Usage(ctypes.Structure):
            _fields_ = [("uuid", ctypes.c_uint8 * 16), ("values", ctypes.c_uint64 * 35)]

        data = Usage()
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        if lib.proc_pid_rusage(os.getpid(), 4, ctypes.byref(data)):
            raise OSError(ctypes.get_errno())
        return {
            "rss_bytes": data.values[6],
            "footprint_bytes": data.values[7],
            "peak_footprint_bytes": data.values[28],
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    return {"peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=982800)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.rows <= 2000000:
        parser.error("This local experiment is limited to two million rows")
    import duckdb

    started = time.monotonic()
    before = memory()
    with tempfile.TemporaryDirectory(prefix="vibe-history-capacity-") as directory:
        connection = duckdb.connect()
        connection.execute("SET memory_limit='64MB'")
        connection.execute("SET threads=1")
        connection.execute("SET max_temp_directory_size='64MB'")
        connection.execute("SET temp_directory=?", [directory])
        target = str(Path(directory) / "synthetic.parquet")
        # Numeric fields have varying values so this is not a constant-column
        # compression best case. Rows are synthetic, not an exchange calendar.
        sql = f"""COPY (
            SELECT (i % 10)::USMALLINT AS symbol_id,
                TIMESTAMP '2000-01-01' + (i // 10) * INTERVAL '5 minutes' AS ts,
                100.0 + hash(i) % 1000000 / 10000.0 AS open,
                200.0 + hash(i + 1) % 1000000 / 10000.0 AS high,
                50.0 + hash(i + 2) % 100000 / 10000.0 AS low,
                100.0 + hash(i + 3) % 1000000 / 10000.0 AS close,
                (hash(i + 4) % 10000000)::BIGINT AS volume
            FROM range({args.rows}) AS data(i)
        ) TO ? (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 8192)"""
        connection.execute(sql, [target])
        after_write = memory()
        stored_bytes = Path(target).stat().st_size
        scanned_rows = connection.execute("SELECT count(*), sum(volume) FROM read_parquet(?)", [target]).fetchone()[0]
        after_scan = memory()
        connection.close()
        after_close = memory()
    result = {
        "synthetic": True,
        "integrated_with_gateway": False,
        "rows": args.rows,
        "scanned_rows": scanned_rows,
        "storage_bytes": stored_bytes,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "duckdb_memory_limit": "64MB",
        "row_group_size": 8192,
        "before": before,
        "after_write": after_write,
        "after_scan": after_scan,
        "after_close": after_close,
        "temporary_data_removed": not Path(directory).exists(),
        "limitations": "Synthetic columnar capacity only. Compression differs by real dataset. Does not establish free-provider history coverage or complete gateway task/quota support.",
    }
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
