"""Quota-controlled, resumable historical datasets outside the checkout."""

from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
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

from src.config.accessor import get_env_value

from .config import number


class HistoryCapacityError(ValueError):
    """A resumable job cannot safely reserve more local disk space."""


class HistoryStore:
    """One bounded worker per service; OS job leases protect cross-process resume.

    Only one bounded chunk of one symbol is materialized. Each compressed chunk is
    atomically committed with a digest. Readers stream rows, never a full dataset.
    """

    def __init__(self, directory: Path, *, quota_bytes=256 * 1024**2, retention_days=30, fetcher=None):
        from .history_router import fetch_chunk

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
        self.retry_base = number("HISTORY_RETRY_BASE", 30, 1, 300)
        self.retry_max = number("HISTORY_RETRY_MAX", 300, self.retry_base, 3600)
        with self.transaction() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),quota INTEGER,retention INTEGER);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,spec TEXT,state TEXT,created REAL,accessed REAL,pinned INTEGER DEFAULT 0,cancel INTEGER DEFAULT 0,reserved INTEGER DEFAULT 0,error TEXT);
            CREATE TABLE IF NOT EXISTS chunks(job TEXT,idx INTEGER,symbol TEXT,start TEXT,end TEXT,state TEXT DEFAULT 'pending',rows INTEGER DEFAULT 0,bytes INTEGER DEFAULT 0,digest TEXT,meta TEXT,error TEXT,PRIMARY KEY(job,idx));
            """)
            if "owner" not in {row[1] for row in db.execute("PRAGMA table_info(jobs)")}:
                db.execute("ALTER TABLE jobs ADD COLUMN owner INTEGER")
            if "lease_slot" not in {row[1] for row in db.execute("PRAGMA table_info(jobs)")}:
                db.execute("ALTER TABLE jobs ADD COLUMN lease_slot INTEGER")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            for name, declaration in {
                "auto_resume": "INTEGER DEFAULT 0",
                "retry_at": "REAL DEFAULT 0",
                "retry_count": "INTEGER DEFAULT 0",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")
            used = {row[0] for row in db.execute("SELECT lease_slot FROM jobs WHERE lease_slot IS NOT NULL")}
            for row in db.execute("SELECT id FROM jobs WHERE lease_slot IS NULL").fetchall():
                preferred = int(row["id"][:8], 16) % 64
                slot = next(i for i in [preferred, *range(64)] if i not in used)
                db.execute("UPDATE jobs SET lease_slot=? WHERE id=?", (slot, row["id"]))
                used.add(slot)
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS jobs_lease_slot ON jobs(lease_slot)")
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
                        self._interrupted(db, row["id"])
                        directory = self.directory / row["id"]
                        if directory.exists() and not directory.is_symlink():
                            for path in directory.glob("*.tmp"):
                                path.unlink(missing_ok=True)
                except ValueError:
                    pass

    @staticmethod
    def _interrupted(db, job):
        """Preserve download intent across shutdown; explicit cancellation wins."""
        db.execute(
            "UPDATE jobs SET state=CASE WHEN auto_resume=1 AND cancel=0 THEN 'failed' ELSE 'paused' END,"
            "retry_at=CASE WHEN auto_resume=1 AND cancel=0 THEN ? ELSE 0 END,"
            "reserved=0,owner=NULL,error='Interrupted; resume verified chunks' WHERE id=?",
            (time.time(), job),
        )

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
    def snapshot(self):
        """Read a committed catalog snapshot without taking the mutation lock."""
        db = sqlite3.connect(self.db_path.as_uri() + "?mode=ro", uri=True, timeout=self.lock_timeout)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN")
            yield db
        finally:
            db.rollback()
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
    def lease(self, job, timeout=0):
        """Hold a nonblocking process lease; stale jobs are resumable after exit."""
        self._id(job)
        # Read only: callers may already hold the metadata write transaction.
        # Slots are allocated uniquely under that transaction, never UUID-hashed.
        db = sqlite3.connect(self.db_path, timeout=self.lock_timeout)
        try:
            row = db.execute("SELECT lease_slot FROM jobs WHERE id=?", (job,)).fetchone()
        finally:
            # sqlite's transaction context does not close its connection. This
            # lookup must release native pages/fds before the long-lived lease.
            db.close()
        if row is None:
            raise ValueError("Unknown history job")
        with self._file_lock(f"lease-{row[0]}.lock", timeout):
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
        total = 0
        for path in self.directory.rglob("*"):
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except FileNotFoundError:
                # Read-only status can race an atomic replacement or eviction.
                continue
        return total

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
            if (row["retry_at"] or row["state"] == "waiting") and row["accessed"] >= cutoff:
                continue  # Waiting downloads release reservations, not their committed prefix.
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
        next_cleanup = time.monotonic() + 30
        while not self.stop.wait(1):
            try:
                if time.monotonic() >= next_cleanup:
                    self._recover_interrupted()
                    self.prune()
                    next_cleanup = time.monotonic() + 30
                self._resume_due()
            except (OSError, ValueError, sqlite3.Error):
                pass

    def _resume_due(self):
        """Dispatch due durable retries through the existing bounded worker queue."""
        with self.snapshot() as db:
            jobs = [
                row[0]
                for row in db.execute(
                    "SELECT id FROM jobs WHERE auto_resume=1 AND cancel=0 AND "
                    "(state='waiting' OR (state='failed' AND retry_at>0 AND retry_at<=?)) "
                    "ORDER BY CASE WHEN state='waiting' THEN accessed ELSE retry_at END,created LIMIT 4",
                    (time.time(),),
                )
            ]
        for job in jobs:
            if self.stop.is_set():
                return
            try:
                self.start(job, _automatic=True)
            except ValueError:
                continue  # Another process, pause/delete, or bounded queue won the race.

    def settings(self, *, quota_bytes=None, retention_days=None):
        """Read/update global quota; shrinking never evicts pinned/running jobs."""
        if quota_bytes is None and retention_days is None:
            with self.snapshot() as db:
                row = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
                reserved = db.execute("SELECT COALESCE(SUM(reserved),0) FROM jobs").fetchone()[0]
            return {
                "quota_bytes": row["quota"],
                "retention_days": row["retention"],
                "used_bytes": self._usage(),
                "reserved_bytes": reserved,
                "path": str(self.directory),
            }
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

    def plan(self, codes, start_date, end_date, interval="5m", source="auto"):
        """Plan bounded acquisition through all compatible registered routes."""
        from .history_router import plan

        return {**plan(codes, start_date, end_date, interval, source), "storage": self.settings()}

    def create(self, **spec):
        plan = self.plan(**spec)
        job = uuid.uuid4().hex
        with self.transaction() as db:
            self._prune(db, required=self.chunk_limit + len(plan["parts"]) * 1024)
            if db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= 32:
                raise ValueError("At most 32 datasets; delete unused datasets first")
            now = time.time()
            used = {row[0] for row in db.execute("SELECT lease_slot FROM jobs")}
            slot = next(i for i in range(64) if i not in used)
            db.execute(
                "INSERT INTO jobs(id,spec,state,created,accessed,lease_slot) VALUES(?,?,?,?,?,?)",
                (job, json.dumps(plan["spec"]), "paused", now, now, slot),
            )
            db.executemany(
                "INSERT INTO chunks(job,idx,symbol,start,end) VALUES(?,?,?,?,?)",
                [(job, i, *row) for i, row in enumerate(plan["parts"])],
            )
        return self.status(job)

    def status(self, job=None):
        with self.snapshot() as db:
            if job is None:
                jobs = [
                    dict(row)
                    for row in db.execute(
                        "SELECT id,spec,state,created,accessed,pinned,error,auto_resume,retry_at,retry_count FROM jobs ORDER BY created DESC"
                    )
                ]
                for item in jobs:
                    item["spec"] = json.loads(item["spec"])
                    counts = db.execute(
                        "SELECT COUNT(*),SUM(state='complete'),SUM(rows) FROM chunks WHERE job=?", (item["id"],)
                    ).fetchone()
                    item["sources"] = [
                        row[0]
                        for row in db.execute(
                            "SELECT DISTINCT json_extract(meta, '$.source') FROM chunks WHERE job=? AND state='complete' AND meta IS NOT NULL",
                            (item["id"],),
                        )
                        if row[0]
                    ]
                    item.update(
                        total_chunks=counts[0],
                        completed_chunks=counts[1] or 0,
                        rows=counts[2] or 0,
                        coverage_verified=item["state"] == "complete",
                    )
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
            summary["failure"] = next(
                (
                    {
                        "symbol": c["symbol"],
                        "start": c["start"],
                        "end": c["end"],
                        "error": c["error"],
                        "routes": (c["meta"] or {}).get("route_attempts", []),
                    }
                    for c in summary["chunks"]
                    if c["error"] and c["state"] != "complete"
                ),
                None,
            )
            summary["sources"] = sorted(
                {c["meta"]["source"] for c in summary["chunks"] if c["meta"] and c["meta"].get("source")}
            )
            summary["coverage_verified"] = summary["state"] == "complete"
            return summary

    def start(self, job, *, _automatic=False):
        with self.lock:
            if self.stop.is_set():
                raise ValueError("History service is closed")
            self.futures = {key: value for key, value in self.futures.items() if not value.done()}
            if job in self.futures:
                return self.status(job)
            full = len(self.futures) >= 4
            if full and _automatic:
                raise ValueError("History worker queue is full")
            self.status(job)
            with self.transaction() as db:
                row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
                if _automatic and not (
                    row["auto_resume"]
                    and not row["cancel"]
                    and (row["state"] == "waiting" or (row["state"] == "failed" and 0 < row["retry_at"] <= time.time()))
                ):
                    return self.status(job)
                if row["state"] in {"running", "queued"}:
                    raise ValueError("History job is already running or queued")
                # Ineligible dispatchers must not briefly take a queued
                # worker's lease: its nonblocking acquisition would fail.
                # Keep the eligibility check and claim in one transaction.
                with self.lease(job):
                    db.execute(
                        "UPDATE jobs SET state=?,cancel=0,owner=?,auto_resume=1,retry_at=0,retry_count=? WHERE id=?",
                        (
                            "waiting" if full else "queued",
                            None if full else os.getpid(),
                            row["retry_count"] if _automatic else 0,
                            job,
                        ),
                    )
            if full:
                return self.status(job)
            self.futures[job] = self.executor.submit(self.run, job, max_chunks=1)
            self.futures[job].add_done_callback(lambda future: self._finished(job, future))
        return self.status(job)

    def _finished(self, job, future):
        with self.lock:
            self.futures.pop(job, None)
            if future.cancelled() or future.exception():
                with self.transaction() as db:
                    owned = db.execute(
                        "SELECT id FROM jobs WHERE id=? AND state IN ('queued','running') AND owner=?",
                        (job, os.getpid()),
                    ).fetchone()
                    if owned:
                        if self.stop.is_set():
                            self._interrupted(db, job)
                        else:
                            db.execute(
                                "UPDATE jobs SET state='paused',reserved=0,owner=NULL,auto_resume=0,retry_at=0 WHERE id=?",
                                (job,),
                            )

    def cancel(self, job):
        self.status(job)
        with self.transaction() as db:
            db.execute(
                "UPDATE jobs SET cancel=1,auto_resume=0,retry_at=0,state=CASE WHEN retry_at>0 OR state='waiting' THEN 'paused' ELSE state END WHERE id=?",
                (job,),
            )
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

    def _stop_requested(self, job):
        if self.stop.is_set():
            return True
        with self.transaction() as db:
            return bool(db.execute("SELECT cancel FROM jobs WHERE id=?", (job,)).fetchone()[0])

    def run(self, job, *, max_chunks=None):
        """Resume verified chunks; bounded retries preserve all completed work."""
        self.status(job)
        with self.lease(job):
            state = self.status(job)
            with self.transaction() as db:
                current = db.execute("SELECT state,cancel FROM jobs WHERE id=?", (job,)).fetchone()
                cancelled = current["cancel"] and (current["state"] == "queued" or not state["cancel"])
                if cancelled:
                    db.execute("UPDATE jobs SET state='paused',reserved=0 WHERE id=?", (job,))
                else:
                    db.execute("UPDATE jobs SET state='running',cancel=0,reserved=0,error=NULL WHERE id=?", (job,))
            if cancelled:
                return self.status(job)
            failed_index = None
            retryable = False
            downloaded = 0
            try:
                for chunk in state["chunks"]:
                    failed_index = chunk["idx"]
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
                            from .history_router import history_context

                            with self.transaction() as db:
                                prior = db.execute(
                                    "SELECT meta FROM chunks WHERE job=? AND symbol=? AND state='complete' AND rows>0 AND idx!=? ORDER BY idx LIMIT 1",
                                    (job, chunk["symbol"], chunk["idx"]),
                                ).fetchone()
                            token = history_context.set(
                                {
                                    "source": state["spec"].get("source", "baostock"),
                                    "stop_requested": lambda: self._stop_requested(job),
                                    "expected": json.loads(prior["meta"]) if prior and prior["meta"] else None,
                                }
                            )
                            try:
                                rows, meta = self.fetcher(
                                    chunk["symbol"], chunk["start"], chunk["end"], state["spec"]["interval"]
                                )
                            finally:
                                history_context.reset(token)
                            error = None
                            break
                        except (ConnectionError, TimeoutError, OSError) as exc:
                            retryable = getattr(exc, "retryable", isinstance(exc, (ConnectionError, TimeoutError)))
                            if error is None:
                                error = exc
                            if self._stop_requested(job):
                                from .history_router import HistoryPaused

                                raise HistoryPaused() from exc
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
                            db.execute(
                                "UPDATE jobs SET reserved=0,accessed=?,retry_count=0,retry_at=0 WHERE id=?",
                                (time.time(), job),
                            )
                        del rows
                    finally:
                        temporary.unlink(missing_ok=True)
                    downloaded += 1
                    if max_chunks is not None and downloaded >= max_chunks:
                        break
                with self.transaction() as db:
                    pending = db.execute(
                        "SELECT COUNT(*) FROM chunks WHERE job=? AND state!='complete'", (job,)
                    ).fetchone()[0]
                    verified = all(
                        self._coverage_verified(json.loads(row["meta"]))
                        for row in db.execute("SELECT meta FROM chunks WHERE job=? AND state='complete'", (job,))
                    )
                    final = "paused" if pending else "complete" if verified else "downloaded"
                    if pending and self.stop.is_set():
                        self._interrupted(db, job)
                    elif pending and max_chunks is not None:
                        # Yield one completed chunk, preserving the user's intent.
                        # The existing accessed timestamp puts this job after
                        # older waiting jobs without growing the in-memory queue.
                        db.execute(
                            "UPDATE jobs SET state=CASE WHEN auto_resume=1 AND cancel=0 THEN 'waiting' ELSE 'paused' END,"
                            "reserved=0,owner=NULL,retry_at=0 WHERE id=?",
                            (job,),
                        )
                    else:
                        db.execute(
                            "UPDATE jobs SET state=?,reserved=0,retry_at=0,auto_resume=0 WHERE id=?", (final, job)
                        )
            except Exception as exc:
                from .history_router import HistoryPaused

                paused = isinstance(exc, HistoryPaused)
                with self.transaction() as db:
                    current = db.execute(
                        "SELECT auto_resume,cancel,retry_count FROM jobs WHERE id=?", (job,)
                    ).fetchone()
                    paused = paused or bool(current["cancel"])
                    retry = (
                        retryable
                        and isinstance(exc, (ConnectionError, TimeoutError))
                        and current["auto_resume"]
                        and not paused
                    )
                    count = current["retry_count"] + 1 if retry else current["retry_count"]
                    retry_at = (
                        time.time() + min(self.retry_max, self.retry_base * 2 ** min(count - 1, 12)) if retry else 0
                    )
                    if failed_index is not None and not paused:
                        db.execute(
                            "UPDATE chunks SET error=? WHERE job=? AND idx=?", (str(exc)[:800], job, failed_index)
                        )
                        if hasattr(exc, "attempts"):
                            db.execute(
                                "UPDATE chunks SET meta=? WHERE job=? AND idx=?",
                                (
                                    json.dumps({"route_attempts": exc.attempts, "coverage_verified": False}),
                                    job,
                                    failed_index,
                                ),
                            )
                    db.execute(
                        "UPDATE jobs SET state=?,reserved=0,error=?,retry_at=?,retry_count=?,auto_resume=? WHERE id=?",
                        (
                            "paused" if paused or isinstance(exc, HistoryCapacityError) else "failed",
                            None if paused else type(exc).__name__ + ": " + str(exc)[:240],
                            retry_at,
                            count,
                            int(bool(retry)),
                            job,
                        ),
                    )
                    if self.stop.is_set() and (paused or retry) and not current["cancel"] and current["auto_resume"]:
                        db.execute("UPDATE jobs SET auto_resume=1 WHERE id=?", (job,))
                        self._interrupted(db, job)
            return self.status(job)

    @staticmethod
    def _coverage_verified(meta):
        return meta.get("coverage_verified", meta.get("coverage") == "calendar_daily_status_and_exact_intraday_grid")

    def read(self, job, offset=0, limit=1000):
        """Read a bounded page of complete, hash-verified chunks without sampling."""
        if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("Rows require offset>=0 and limit=1..1000")
        with self.lease(job, timeout=self.lock_timeout):
            state = self.status(job)
            if state["state"] not in {"complete", "downloaded"}:
                raise ValueError("Dataset is not complete; inspect chunk errors or resume")
            with self.transaction() as db:
                db.execute("UPDATE jobs SET accessed=? WHERE id=?", (time.time(), job))
                chunks = db.execute("SELECT idx,rows,digest FROM chunks WHERE job=? ORDER BY idx", (job,)).fetchall()
            manifest = {chunk["idx"]: chunk for chunk in state["chunks"]}
            provenance = {}
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
                info = manifest[chunk["idx"]]
                meta = info["meta"] or {}
                provenance.setdefault(info["symbol"], []).append(
                    {
                        "start_date": info["start"],
                        "end_date": info["end"],
                        **{
                            key: meta.get(key)
                            for key in (
                                "source",
                                "quote_currency",
                                "adjustment",
                                "volume_unit",
                                "timezone",
                                "timestamp_basis",
                                "calendar",
                                "calendar_version",
                                "coverage",
                                "coverage_verified",
                                "excluded_source_points",
                            )
                        },
                    }
                )
                if len(output) >= limit:
                    break
            return {
                "job": job,
                "interval": state["spec"]["interval"],
                "provenance": provenance,
                "coverage_verified": state["state"] == "complete",
                "coverage_warning": None
                if state["state"] == "complete"
                else "Acquired source rows; exchange-calendar completeness is unverified",
                "offset": offset,
                "rows": output,
                "total_rows": state["rows"],
                "next_offset": offset + len(output) if offset + len(output) < state["rows"] else None,
                "sampled": False,
            }

    def close(self):
        until = time.monotonic() + 1
        self.stop.set()
        self.cleaner.join(timeout=max(0, until - time.monotonic()))
        self.executor.shutdown(wait=False, cancel_futures=True)
        # Give cooperative fetches time to persist interruption before the host
        # re-raises its termination signal. Reuse, rather than extend, the old
        # one-second shutdown wait. Slow calls retain their lease for recovery.
        wait(tuple(self.futures.values()), timeout=max(0, until - time.monotonic()))


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
    override = get_env_value("VIBE_GATEWAY_HISTORY_DIR")
    if override:
        return Path(override)
    root = Path.home() / ".vibe-trading"
    legacy = root / "history"
    # The CLI already uses `history` as a text file. Preserve earlier dataset
    # installations only when this really is a dataset directory.
    if legacy.is_dir() and (legacy / "catalog.sqlite").is_file():
        return legacy
    return root / "datasets" / "history"


def get_history_store():
    """Lazy shared history store; never follows VIBE_TRADING_HOME into a repo."""
    global _instance
    with _instance_lock:
        if _instance is None:
            import atexit

            _instance = HistoryStore(history_directory())
            atexit.unregister(close_history_store)
            atexit.register(close_history_store)
        return _instance


def start_history_recovery():
    """Reopen an existing catalog at host startup, without creating idle stores."""
    if (history_directory() / "catalog.sqlite").is_file():
        get_history_store()


def close_history_store():
    """Stop the initialized service while retaining unfinished download intent."""
    global _instance
    with _instance_lock:
        instance, _instance = _instance, None
    if instance is not None:
        instance.close()
