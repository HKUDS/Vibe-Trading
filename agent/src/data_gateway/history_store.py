"""Quota-controlled, resumable historical minute datasets outside the checkout."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time
import uuid

from .config import number


class HistoryCapacityError(ValueError):
    """A resumable job cannot safely reserve more local disk space."""


class HistoryStore:
    """One bounded worker per service; OS job leases protect cross-process resume.

    Only one month of one symbol is materialized. Each compressed chunk is
    atomically committed with a digest. Readers stream rows, never a full dataset.
    """

    def __init__(self, directory: Path, *, quota_bytes=256 * 1024**2, retention_days=30, fetcher=None):
        from .history_source import fetch_chunk

        self.directory = Path(directory).expanduser().resolve()
        if any((parent / ".git").exists() for parent in (self.directory, *self.directory.parents)):
            raise ValueError("History data must be outside all git checkouts")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.directory / "catalog.sqlite"
        self.lock = threading.RLock()
        self.lock_timeout = number("HISTORY_LOCK_TIMEOUT", 2, 0.05, 30)
        self.fetcher = fetcher or fetch_chunk
        self.chunk_limit = 2 * 1024**2
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-download")
        self.futures = {}
        self.stop = threading.Event()
        with self.transaction() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),quota INTEGER,retention INTEGER);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,spec TEXT,state TEXT,created REAL,accessed REAL,pinned INTEGER DEFAULT 0,cancel INTEGER DEFAULT 0,reserved INTEGER DEFAULT 0,error TEXT);
            CREATE TABLE IF NOT EXISTS chunks(job TEXT,idx INTEGER,symbol TEXT,start TEXT,end TEXT,state TEXT DEFAULT 'pending',rows INTEGER DEFAULT 0,bytes INTEGER DEFAULT 0,digest TEXT,meta TEXT,error TEXT,PRIMARY KEY(job,idx));
            """)
            if "owner" not in {row[1] for row in db.execute("PRAGMA table_info(jobs)")}:
                db.execute("ALTER TABLE jobs ADD COLUMN owner INTEGER")
            db.execute("INSERT OR IGNORE INTO settings VALUES(1,?,?)", (quota_bytes, retention_days))
        self._recover_interrupted()
        self.cleaner = threading.Thread(target=self._clean, daemon=True, name="history-cleanup")
        self.cleaner.start()

    def _recover_interrupted(self):
        with self.transaction() as db:
            for row in db.execute(
                "SELECT id,state,owner FROM jobs WHERE state IN ('running','queued') OR reserved>0"
            ).fetchall():
                try:
                    if row["state"] == "queued" and row["owner"]:
                        try:
                            os.kill(row["owner"], 0)
                            continue
                        except ProcessLookupError:
                            pass
                        except PermissionError:
                            continue
                    with self.lease(row["id"]):
                        db.execute(
                            "UPDATE jobs SET state='paused',reserved=0,error='Interrupted; resume verified chunks' WHERE id=?",
                            (row["id"],),
                        )
                        directory = self.directory / row["id"]
                        if directory.exists() and not directory.is_symlink():
                            for path in directory.glob("*.tmp"):
                                path.unlink(missing_ok=True)
                except ValueError:
                    pass

    @contextmanager
    def transaction(self):
        with self._metadata_guard():
            db = sqlite3.connect(self.db_path, timeout=10)
            db.row_factory = sqlite3.Row
            if self.db_path.stat().st_size == 0:
                db.execute("PRAGMA auto_vacuum=FULL")
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    @contextmanager
    def _metadata_guard(self):
        if not self.lock.acquire(timeout=self.lock_timeout):
            raise ValueError("History storage busy; retry shortly")
        try:
            with self._file_lock(".lock", self.lock_timeout):
                yield
        finally:
            self.lock.release()

    @contextmanager
    def _file_lock(self, name, timeout=0):
        with (self.directory / name).open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()

                def acquire():
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

                def release():
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                def acquire():
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

                def release():
                    fcntl.flock(handle, fcntl.LOCK_UN)

            deadline = time.monotonic() + timeout
            while True:
                try:
                    acquire()
                    break
                except (BlockingIOError, PermissionError):
                    if time.monotonic() >= deadline:
                        raise ValueError(
                            "History storage busy; retry shortly" if timeout else "History job is already running"
                        ) from None
                    time.sleep(min(0.02, max(0, deadline - time.monotonic())))
            try:
                yield
            finally:
                release()

    @contextmanager
    def lease(self, job):
        """Hold a nonblocking process lease; stale jobs are resumable after exit."""
        self._id(job)
        with self._file_lock(f"lease-{int(job[:8], 16) % 64}.lock"):
            yield

    def _id(self, value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
            raise ValueError("Invalid history job id")

    def _path(self, job, index, temporary=False):
        self._id(job)
        path = self.directory / job / (str(index) + (".tmp" if temporary else ".jsonl.gz"))
        if self.directory not in path.resolve().parents:
            raise ValueError("History path escapes storage")
        return path

    def _usage(self):
        return sum(p.stat().st_size for p in self.directory.rglob("*") if p.is_file() and not p.is_symlink())

    def _remove(self, db, job):
        self._id(job)
        path = self.directory / job
        if path.is_symlink():
            raise ValueError("Invalid history directory")
        if path.exists():
            shutil.rmtree(path)
        db.execute("DELETE FROM chunks WHERE job=?", (job,))
        db.execute("DELETE FROM jobs WHERE id=?", (job,))
        # Lease files persist to avoid unlink/recreate races with other processes.

    def _prune(self, db, required=0, exclude=None):
        settings = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
        reserved = db.execute("SELECT COALESCE(SUM(reserved),0) FROM jobs").fetchone()[0]
        usage = self._usage()
        cutoff = time.time() - settings["retention"] * 86400
        for row in db.execute(
            "SELECT * FROM jobs WHERE pinned=0 AND state NOT IN ('running','queued') ORDER BY accessed"
        ).fetchall():
            if row["id"] == exclude:
                continue
            if row["accessed"] >= cutoff and usage + reserved + required <= settings["quota"]:
                continue
            try:
                with self.lease(row["id"]):
                    self._remove(db, row["id"])
                    # Filesystem eviction cannot be rolled back. Commit its
                    # catalog removal before any later admission can fail.
                    db.commit()
                    db.execute("BEGIN IMMEDIATE")
            except ValueError:
                continue
            usage = self._usage()
        if usage + reserved + required > settings["quota"]:
            raise HistoryCapacityError("History storage quota exhausted; increase quota or unpin/delete datasets")
        if required and shutil.disk_usage(self.directory).free < required + 16 * 1024**2:
            raise HistoryCapacityError("Insufficient free disk space")

    def prune(self):
        with self.transaction() as db:
            self._prune(db)
        return self.settings()

    def _clean(self):
        while not self.stop.wait(30):
            try:
                self._recover_interrupted()
                self.prune()
            except (OSError, ValueError, sqlite3.Error):
                pass

    def settings(self, *, quota_bytes=None, retention_days=None):
        """Read/update global quota; shrinking never evicts pinned/running jobs."""
        with self.transaction() as db:
            old = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
            quota = old["quota"] if quota_bytes is None else quota_bytes
            retention = old["retention"] if retention_days is None else retention_days
            if isinstance(quota, bool) or not isinstance(quota, int) or not 4 * 1024**2 <= quota <= 10 * 1024**3:
                raise ValueError("Quota must be 4 MiB..10 GiB")
            if isinstance(retention, bool) or not isinstance(retention, int) or not 1 <= retention <= 365:
                raise ValueError("Retention must be 1..365 days")
            if (
                quota_bytes is not None
                and quota < self._usage() + db.execute("SELECT COALESCE(SUM(reserved),0) FROM jobs").fetchone()[0]
            ):
                raise ValueError("New quota is below current usage/reservations; delete or finish jobs first")
            db.execute("UPDATE settings SET quota=?,retention=? WHERE id=1", (quota, retention))
            return {
                "quota_bytes": quota,
                "retention_days": retention,
                "used_bytes": self._usage(),
                "reserved_bytes": db.execute("SELECT COALESCE(SUM(reserved),0) FROM jobs").fetchone()[0],
                "path": str(self.directory),
            }

    def plan(self, codes, start_date, end_date, interval="5m", source="baostock"):
        """Validate exact supported identity before allocating any download work."""
        if not isinstance(codes, list) or not 1 <= len(codes) <= 100:
            raise ValueError("Supply 1..100 distinct symbols")
        if any(not isinstance(code, str) or not re.fullmatch(r"\d{6}\.(SH|SZ)", code) for code in codes):
            raise ValueError("Verified long-minute history currently supports SH/SZ equities via BaoStock")
        if len(set(codes)) != len(codes):
            raise ValueError("Supply distinct symbols")
        if interval not in {"5m", "15m", "30m", "1H"} or source != "baostock":
            raise ValueError("Supported history: BaoStock 5m/15m/30m/1H")
        if not isinstance(start_date, str) or not isinstance(end_date, str):
            raise ValueError("start_date and end_date are required ISO dates")
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        from zoneinfo import ZoneInfo
        from datetime import datetime

        if start > end or (end - start).days > 3660 or end >= datetime.now(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("Request settled dates in an ordered range of at most ten years")
        chunks = []
        for code in codes:
            cursor = start
            while cursor <= end:
                next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
                last = min(end, next_month - timedelta(days=1))
                chunks.append((code, str(cursor), str(last)))
                cursor = last + timedelta(days=1)
        if len(chunks) > 4096:
            raise ValueError("Request exceeds 4096 chunks; split into multiple jobs")
        frequency = {"5m": 5, "15m": 15, "30m": 30, "1H": 60}[interval]
        upper_rows = (
            len(codes)
            * sum((start + timedelta(days=i)).weekday() < 5 for i in range((end - start).days + 1))
            * (240 // frequency)
        )
        return {
            "spec": {
                "codes": codes,
                "start_date": start_date,
                "end_date": end_date,
                "interval": interval,
                "source": source,
            },
            "chunks": len(chunks),
            "estimated_max_rows": upper_rows,
            "estimated_uncompressed_bytes": upper_rows * 256,
            "estimate_basis": "weekday upper estimate, 240 minutes/session, 256 JSON bytes/row; exact calendar/source grid validated per chunk",
            "storage": self.settings(),
            "parts": chunks,
        }

    def create(self, **spec):
        plan = self.plan(**spec)
        job = uuid.uuid4().hex
        with self.transaction() as db:
            self._prune(db, required=self.chunk_limit + len(plan["parts"]) * 1024)
            if db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= 32:
                raise ValueError("At most 32 datasets; delete unused datasets first")
            now = time.time()
            db.execute(
                "INSERT INTO jobs(id,spec,state,created,accessed) VALUES(?,?,?,?,?)",
                (job, json.dumps(plan["spec"]), "paused", now, now),
            )
            db.executemany(
                "INSERT INTO chunks(job,idx,symbol,start,end) VALUES(?,?,?,?,?)",
                [(job, i, *row) for i, row in enumerate(plan["parts"])],
            )
        return self.status(job)

    def status(self, job=None):
        with self.transaction() as db:
            if job is None:
                jobs = [
                    dict(row)
                    for row in db.execute(
                        "SELECT id,spec,state,created,accessed,pinned,error FROM jobs ORDER BY created DESC"
                    )
                ]
                for item in jobs:
                    item["spec"] = json.loads(item["spec"])
                    counts = db.execute(
                        "SELECT COUNT(*),SUM(state='complete'),SUM(rows) FROM chunks WHERE job=?", (item["id"],)
                    ).fetchone()
                    item.update(total_chunks=counts[0], completed_chunks=counts[1] or 0, rows=counts[2] or 0)
                return jobs
            self._id(job)
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if row is None:
                raise ValueError("History dataset not found or expired")
            summary = dict(row)
            summary["spec"] = json.loads(summary["spec"])
            summary["chunks"] = [
                dict(c)
                for c in db.execute(
                    "SELECT idx,symbol,start,end,state,rows,bytes,meta,error FROM chunks WHERE job=? ORDER BY idx",
                    (job,),
                )
            ]
            for chunk in summary["chunks"]:
                chunk["meta"] = json.loads(chunk["meta"]) if chunk["meta"] else None
            summary["rows"] = sum(c["rows"] for c in summary["chunks"])
            summary["completed_chunks"] = sum(c["state"] == "complete" for c in summary["chunks"])
            summary["total_chunks"] = len(summary["chunks"])
            return summary

    def start(self, job):
        with self.lock:
            self.futures = {key: value for key, value in self.futures.items() if not value.done()}
            if job in self.futures:
                return self.status(job)
            if len(self.futures) >= 4:
                raise ValueError("History worker queue is full")
            self.status(job)
            with self.lease(job), self.transaction() as db:
                state = db.execute("SELECT state FROM jobs WHERE id=?", (job,)).fetchone()[0]
                if state in {"running", "queued"}:
                    raise ValueError("History job is already running or queued")
                db.execute("UPDATE jobs SET state='queued',cancel=0,owner=? WHERE id=?", (os.getpid(), job))
            self.futures[job] = self.executor.submit(self.run, job)
            self.futures[job].add_done_callback(lambda future: self._finished(job, future))
        return self.status(job)

    def _finished(self, job, future):
        with self.lock:
            self.futures.pop(job, None)
            if future.cancelled() or future.exception():
                with self.transaction() as db:
                    db.execute(
                        "UPDATE jobs SET state='paused',reserved=0,owner=NULL WHERE id=? AND state IN ('queued','running') AND owner=?",
                        (job, os.getpid()),
                    )

    def cancel(self, job):
        self.status(job)
        with self.transaction() as db:
            db.execute("UPDATE jobs SET cancel=1 WHERE id=?", (job,))
        return self.status(job)

    def pin(self, job, pinned):
        if not isinstance(pinned, bool):
            raise ValueError("pinned must be a boolean")
        self.status(job)
        with self.transaction() as db:
            db.execute("UPDATE jobs SET pinned=?,accessed=? WHERE id=?", (bool(pinned), time.time(), job))
        return self.status(job)

    def delete(self, job):
        self.status(job)
        with self.lease(job), self.transaction() as db:
            self._remove(db, job)
        return {"deleted": job}

    def run(self, job):
        """Resume verified chunks; bounded retries preserve all completed work."""
        self.status(job)
        with self.lease(job):
            state = self.status(job)
            if state["state"] == "queued" and state["cancel"]:
                with self.transaction() as db:
                    db.execute("UPDATE jobs SET state='paused' WHERE id=?", (job,))
                return self.status(job)
            with self.transaction() as db:
                db.execute("UPDATE jobs SET state='running',cancel=0,reserved=0,error=NULL WHERE id=?", (job,))
            try:
                for chunk in state["chunks"]:
                    if self.stop.is_set():
                        break
                    with self.transaction() as db:
                        if db.execute("SELECT cancel FROM jobs WHERE id=?", (job,)).fetchone()[0]:
                            break
                    path = self._path(job, chunk["idx"])
                    if chunk["state"] == "complete" and path.exists():
                        with self.transaction() as db:
                            digest = db.execute(
                                "SELECT digest FROM chunks WHERE job=? AND idx=?", (job, chunk["idx"])
                            ).fetchone()[0]
                        if hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                            continue
                    with self.transaction() as db:
                        if path.exists():
                            path.unlink()
                        temporary = self._path(job, chunk["idx"], True)
                        temporary.unlink(missing_ok=True)
                        db.execute(
                            "UPDATE chunks SET state='pending',rows=0,bytes=0 WHERE job=? AND idx=?",
                            (job, chunk["idx"]),
                        )
                        # A removed/corrupt file must never roll back to a
                        # catalog entry claiming it is still complete.
                        db.commit()
                        db.execute("BEGIN IMMEDIATE")
                        self._prune(db, required=self.chunk_limit + 65536, exclude=job)
                        db.execute("UPDATE jobs SET reserved=? WHERE id=?", (self.chunk_limit + 65536, job))
                    error = None
                    for attempt in range(3):
                        try:
                            rows, meta = self.fetcher(
                                chunk["symbol"], chunk["start"], chunk["end"], state["spec"]["interval"]
                            )
                            error = None
                            break
                        except (ConnectionError, TimeoutError, OSError) as exc:
                            error = exc
                            if self.stop.wait(min(8, 2**attempt)):
                                break
                    if error is not None:
                        raise error
                    path.parent.mkdir(exist_ok=True)
                    try:
                        if len(rows) > 10000 or len(json.dumps(meta)) > 16384:
                            raise ValueError("Chunk row count or metadata exceeds limit")
                        with temporary.open("wb") as raw:
                            with gzip.GzipFile(
                                fileobj=_LimitedWriter(raw, self.chunk_limit), mode="wb", mtime=0
                            ) as handle:
                                for row in rows:
                                    encoded = (json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n").encode()
                                    if len(encoded) > 4096:
                                        raise ValueError("Chunk row exceeds limit")
                                    handle.write(encoded)
                        size = temporary.stat().st_size
                        if size > self.chunk_limit:
                            raise ValueError("Compressed chunk exceeds reserved limit")
                        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
                        with self.transaction() as db:
                            os.replace(temporary, path)
                            db.execute(
                                "UPDATE chunks SET state='complete',rows=?,bytes=?,digest=?,meta=?,error=NULL WHERE job=? AND idx=?",
                                (len(rows), size, digest, json.dumps(meta), job, chunk["idx"]),
                            )
                            db.execute("UPDATE jobs SET reserved=0,accessed=? WHERE id=?", (time.time(), job))
                        del rows
                    finally:
                        temporary.unlink(missing_ok=True)
                with self.transaction() as db:
                    pending = db.execute(
                        "SELECT COUNT(*) FROM chunks WHERE job=? AND state!='complete'", (job,)
                    ).fetchone()[0]
                    db.execute(
                        "UPDATE jobs SET state=?,reserved=0 WHERE id=?", ("paused" if pending else "complete", job)
                    )
            except Exception as exc:
                with self.transaction() as db:
                    db.execute(
                        "UPDATE jobs SET state=?,reserved=0,error=? WHERE id=?",
                        (
                            "paused" if isinstance(exc, HistoryCapacityError) else "failed",
                            type(exc).__name__ + ": " + str(exc)[:240],
                            job,
                        ),
                    )
            return self.status(job)

    def read(self, job, offset=0, limit=1000):
        """Read a bounded page of complete, hash-verified chunks without sampling."""
        if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Rows require offset>=0 and limit=1..1000")
        with self.lease(job):
            state = self.status(job)
            if state["state"] != "complete":
                raise ValueError("Dataset is not complete; inspect chunk errors or resume")
            with self.transaction() as db:
                db.execute("UPDATE jobs SET accessed=? WHERE id=?", (time.time(), job))
                chunks = db.execute("SELECT idx,rows,digest FROM chunks WHERE job=? ORDER BY idx", (job,)).fetchall()
            output = []
            skip = offset
            for chunk in chunks:
                if skip >= chunk["rows"]:
                    skip -= chunk["rows"]
                    continue
                path = self._path(job, chunk["idx"])
                if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != chunk["digest"]:
                    raise ValueError("Chunk integrity failed; resume to repair")
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        if skip:
                            skip -= 1
                            continue
                        output.append(json.loads(line))
                        if len(output) >= limit:
                            break
                if len(output) >= limit:
                    break
            return {
                "job": job,
                "offset": offset,
                "rows": output,
                "total_rows": state["rows"],
                "next_offset": offset + len(output) if offset + len(output) < state["rows"] else None,
                "sampled": False,
            }

    def close(self):
        self.stop.set()
        self.cleaner.join(timeout=1)
        self.executor.shutdown(wait=False, cancel_futures=True)


class _LimitedWriter:
    """Enforce the disk reservation before gzip writes any bytes."""

    def __init__(self, raw, limit):
        self.raw, self.limit = raw, limit

    def write(self, data):
        if self.raw.tell() + len(data) > self.limit:
            raise ValueError("Compressed chunk exceeds reserved limit")
        return self.raw.write(data)

    def flush(self):
        self.raw.flush()


_instance = None
_instance_lock = threading.Lock()


def history_directory():
    """Resolve the shared on-disk store independently of the application's cwd."""
    return Path(os.getenv("VIBE_GATEWAY_HISTORY_DIR", str(Path.home() / ".vibe-trading/history")))


def get_history_store():
    """Lazy shared history store; never follows VIBE_TRADING_HOME into a repo."""
    global _instance
    with _instance_lock:
        if _instance is None:
            import atexit

            _instance = HistoryStore(history_directory())
            atexit.register(_instance.close)
        return _instance
