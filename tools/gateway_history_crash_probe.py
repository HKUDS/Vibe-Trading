"""Kill a real routed history worker, corrupt one chunk, then verify bounded resume."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from src.data_gateway.history_store import HistoryStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--job")
    args = parser.parse_args()
    store = HistoryStore(args.root)
    if args.job:
        try:
            value = store.run(args.job)
            print(json.dumps({"state": value["state"], "rows": value["rows"]}), flush=True)
        finally:
            store.close()
        return
    started = time.monotonic()
    job = store.create(
        codes=["AAPL.US", "MSFT.US"], start_date="1995-11-14", end_date="2026-11-13", interval="1M", source="auto"
    )
    identity = job["id"]
    store.close()
    command = [sys.executable, __file__, "--root", str(args.root), "--output", str(args.output), "--job", identity]
    with args.output.with_suffix(".log").open("w") as log:
        child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            until = time.monotonic() + 120
            completed = []
            while time.monotonic() < until and child.poll() is None:
                with sqlite3.connect(args.root / "catalog.sqlite") as db:
                    completed = db.execute(
                        "SELECT idx,digest FROM chunks WHERE job=? AND state='complete' ORDER BY idx", (identity,)
                    ).fetchall()
                if len(completed) >= 3:
                    break
                time.sleep(0.1)
            if len(completed) < 3:
                raise RuntimeError("Real history worker did not acquire three chunks")
            child.kill()
            child.wait(10)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(10)
        # Alter only this probe's own isolated dataset; valid chunks must survive.
        corrupt = args.root / identity / f"{completed[0][0]}.jsonl.gz"
        corrupt.write_bytes(b"probe interrupted/corrupted gzip")
        resumed = HistoryStore(args.root)
        before = resumed.status(identity)
        assert before["state"] == "paused" and before["reserved"] == 0
        resumed.close()
        second = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            second.wait(timeout=240)
            assert second.returncode == 0
        finally:
            if second.poll() is None:
                second.terminate()
                second.wait(10)
    final_store = HistoryStore(args.root)
    try:
        final = final_store.status(identity)
        assert final["state"] in {"complete", "downloaded"}
        unchanged = all(
            hashlib.sha256((args.root / identity / f"{idx}.jsonl.gz").read_bytes()).hexdigest() == digest
            for idx, digest in completed[1:]
        )
        assert unchanged and corrupt.read_bytes()[:2] == b"\x1f\x8b"
        page = final_store.read(identity, 0, 1000)
        assert len(page["rows"]) == final["rows"] and page["next_offset"] is None and not page["sampled"]
        report = {
            "verified_recovery": True,
            "killed_pid": child.pid,
            "exit_code": child.returncode,
            "committed_before_kill": len(completed),
            "valid_chunks_unchanged": unchanged,
            "corrupt_chunk_repaired": True,
            "state": final["state"],
            "rows": final["rows"],
            "chunks": final["completed_chunks"],
            "sources": final["sources"],
            "reserved_bytes": final_store.settings()["reserved_bytes"],
            "wall_seconds": round(time.monotonic() - started, 3),
        }
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        final_store.close()


if __name__ == "__main__":
    main()
