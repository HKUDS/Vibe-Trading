"""Replay v22 catalog observations in separate processes to attribute memory.

Uses an existing stopped test catalog read-only, never market-price files or a
running server. Compare legacy connection lifetime, closed full reads, and the
fixed narrow reads. No explicit collection or allocator trimming is performed.
"""

import argparse
from contextlib import closing
import gc
import json
import os
from pathlib import Path
import sqlite3
import time

from gateway_full_scan_probe import memory_tree


def replay(root, mode, iterations):
    """Measure catalog observer overhead without gateway/network variability.

    Args:
        root: Stopped probe directory with history/catalog.sqlite.
        mode: Legacy, closed full-snapshot, or narrow query implementation.
        iterations: Number of independent reads; no gateway limits are changed.

    Returns:
        OS memory samples and open SQLite connection count before process exit.
    """
    samples = []
    started = time.monotonic()
    uri = (root / "history/catalog.sqlite").resolve().as_uri() + "?mode=ro"
    if mode == "gateway-catalog":
        from src.data_gateway.history_store import HistoryStore

        # Exercise the real read methods without starting workers, recovery,
        # schema changes or cleanup against the stopped evidence catalog.
        reader = HistoryStore.__new__(HistoryStore)
        reader.db_path = (root / "history/catalog.sqlite").resolve()
        reader.lock_timeout = 2
        identities = [job["id"] for job in reader.status()]
    for index in range(iterations):
        if mode == "gateway-catalog":
            reader.status()
            reader.status(identities[index % len(identities)])
        elif mode in ("legacy", "closed"):
            db = sqlite3.connect(uri, uri=True)
            db.row_factory = sqlite3.Row
            with db:
                jobs = [dict(row) for row in db.execute("SELECT * FROM jobs")]
                chunks = [dict(row) for row in db.execute("SELECT * FROM chunks ORDER BY job,idx")]
            if mode == "closed":
                db.close()
            del db, jobs, chunks
        else:
            with closing(sqlite3.connect(uri, uri=True)) as db:
                db.execute(
                    "SELECT 1 FROM chunks WHERE symbol=? AND start=? AND end=? AND state='complete' LIMIT 1",
                    ("601398.SH", "2021-11-14", "2021-11-30"),
                ).fetchone()
                db.execute("SELECT COUNT(*) FROM chunks WHERE state='complete'").fetchone()
        if index % 20 == 0 or index == iterations - 1:
            samples.append({"iteration": index, **memory_tree(os.getpid())})
    # Inspect only after the memory series; do not hold connections while replaying.
    connections = [obj for obj in gc.get_objects() if isinstance(obj, sqlite3.Connection)]
    opened = 0
    for connection in connections:
        try:
            connection.execute("SELECT 1")
            opened += 1
        except sqlite3.ProgrammingError:
            pass
    return {"mode": mode, "seconds": time.monotonic() - started, "open_connections": opened, "samples": samples}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["legacy", "closed", "narrow", "gateway-catalog"], required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=401)
    args = parser.parse_args()
    print(json.dumps(replay(args.root, args.mode, args.iterations)))
