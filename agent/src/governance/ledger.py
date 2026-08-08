"""Hash-chained, fsynced, append-only JSONL ledger.

A generic, domain-agnostic primitive for governance/compliance records: each
record embeds ``seq`` (1-based position) and ``prev_record_hash`` (the
previous record's own hash, or :data:`GENESIS_PREV_HASH` for the first
record), then commits to both plus its own payload in ``record_hash``.
Because every record's hash folds in its predecessor's hash, editing or
deleting ANY earlier record breaks the hash of every record chained after
it — that propagation, not a per-line checksum, is what makes tampering
detectable (:func:`verify_chain`).

**Why this exists.** ``src/live/audit.py`` (SPEC.md Consent §5) is the
compliance-grade ledger of every live-money action, but its original write
path was a bare ``open(path, "a").write(line)`` — no fsync (a host crash
could lose the last record while the diagnostic per-run trace, which
already fsyncs every write, would not), no sequencing, no prior-record hash,
and nothing to detect if a line were edited or deleted after the fact. This
module supplies the missing piece; ``src/live/audit.py`` wires it in as an
opt-in ``chain=True`` mode on ``write_live_action`` (see that module for
why it is opt-in and why it writes to a *separate* file rather than
retrofitting the pre-existing plain ``audit.jsonl``).

**Durability.** :func:`append_record` fsyncs the ledger file after every
write by default (mirroring ``src.agent.trace.TraceWriter.write``), and
fsyncs the parent directory the first time the ledger file is created (same
reasoning as ``TraceWriter.__init__``: the directory ENTRY for a brand new
file is itself not durable until the directory is fsynced).

**Concurrency.** A POSIX ``flock`` (``msvcrt`` byte-range lock on Windows)
is held across the read-tail + append critical section so two writers
cannot compute conflicting ``seq``/``prev_record_hash`` values for the same
next slot. This is a liveness optimization against accidental forks, not
the source of the tamper-evidence guarantee — :func:`verify_chain` would
still catch a fork or a corrupted tail even if the lock were bypassed.

**Refuse-to-extend-a-broken-chain.** :func:`append_record` verifies the
ENTIRE existing chain (not just its last line) before appending, and raises
:class:`LedgerCorruptionError` rather than silently building a valid-looking
suffix on top of an already-tampered history. This is O(n) per append,
trading write latency for the strongest available guarantee; the live-action
ledger this backs is low-volume by construction (one record per
order/mandate/breach/halt event, not per market tick — the same volume
argument ``TraceWriter`` makes for "one fsync per record is acceptable"), so
this is judged an acceptable cost rather than a premature optimization
target. A future change under real volume pressure could memoize the tail
state in a small companion file; deliberately not built here without a
demonstrated need for it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Iterator, Mapping

try:  # POSIX advisory lock (Linux/macOS).
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:  # Windows advisory byte-range lock.
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

__all__ = [
    "GENESIS_PREV_HASH",
    "EXPORT_FORMAT",
    "ChainBreak",
    "ChainVerificationResult",
    "LedgerCorruptionError",
    "compute_record_hash",
    "append_record",
    "verify_chain",
    "build_export",
    "export_chain_to_file",
    "verify_export",
    "DEFAULT_ROTATE_BYTES",
    "archive_segments",
    "rotate_if_needed",
    "verify_chain_with_archives",
]

#: Sentinel ``prev_record_hash`` for the first record in a chain — there is
#: no predecessor to reference.
GENESIS_PREV_HASH = "sha256:genesis"

#: Reserved top-level keys written by :func:`append_record`. A caller
#: payload must not set any of these itself.
_CHAIN_FIELDS = frozenset({"seq", "prev_record_hash", "record_hash"})

#: Export envelope format tag (bump on any breaking export-shape change).
EXPORT_FORMAT = "vibe-trading-governance-ledger-export/v1"

_fsync_warned = False


def _warn_fsync_failure(exc: OSError, target: Any) -> None:
    """Log the first fsync failure for this process, then stay quiet.

    Mirrors ``src.agent.trace.TraceWriter._warn_fsync_failure``: on an
    unsupported filesystem, durability degrades to flush-only rather than
    failing the caller (the ledger write already succeeded at the OS-cache
    level; refusing to record a compliance event because fsync is
    unsupported would be worse than a degraded durability guarantee).
    """
    global _fsync_warned
    if _fsync_warned:
        return
    _fsync_warned = True
    logger.warning(
        "governance ledger fsync failed on %s (%s); durability degraded to flush-only",
        target,
        exc,
    )


def _canonical_json(obj: Any) -> str:
    """Serialize ``obj`` deterministically for hashing (sorted keys, compact)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_record_hash(seq: int, prev_record_hash: str, payload: Mapping[str, Any]) -> str:
    """Hash one ledger record so it commits to its position and predecessor.

    Args:
        seq: This record's 1-based position in the chain.
        prev_record_hash: The previous record's own ``record_hash``, or
            :data:`GENESIS_PREV_HASH` for the first record.
        payload: The record body (everything except the three chain fields).

    Returns:
        ``sha256:<hex>`` over the canonical JSON of ``{seq, prev_record_hash,
        payload}``.
    """
    body = _canonical_json(
        {"seq": seq, "prev_record_hash": prev_record_hash, "payload": payload}
    )
    return f"sha256:{_sha256_hex(body)}"


@dataclass(frozen=True)
class ChainBreak:
    """Where and why :func:`verify_chain` / :func:`verify_export` stopped trusting the chain.

    Attributes:
        index: 0-based line index (within the source lines/records) where
            the break was detected.
        seq: The record's claimed ``seq`` value, when parseable (``None``
            for a line that failed to parse as JSON at all).
        reason: One of ``"malformed_json"``, ``"missing_chain_fields"``,
            ``"seq_gap"``, ``"prev_hash_mismatch"``, ``"record_hash_mismatch"``,
            ``"export_hash_mismatch"``.
        detail: Human-readable detail (expected vs. found).
    """

    index: int
    seq: int | None
    reason: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {"index": self.index, "seq": self.seq, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class ChainVerificationResult:
    """Outcome of walking a chain end to end.

    Attributes:
        ok: ``True`` iff every record from the first to the last verified
            cleanly.
        record_count: Number of records verified before ``first_break`` (or
            the total record count when ``ok`` is ``True``).
        first_break: The first (earliest) :class:`ChainBreak` encountered, or
            ``None`` when ``ok`` is ``True``.
    """

    ok: bool
    record_count: int
    first_break: ChainBreak | None

    @property
    def broken(self) -> bool:
        """Convenience negation of :attr:`ok`."""
        return not self.ok

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "ok": self.ok,
            "record_count": self.record_count,
            "first_break": None if self.first_break is None else self.first_break.to_dict(),
        }


class LedgerCorruptionError(RuntimeError):
    """Raised when :func:`append_record` finds the existing chain already broken.

    Refusing to extend a corrupted chain — rather than silently building a
    valid-looking suffix on top of it — is the point: a chain that "heals"
    itself after a break would defeat the entire tamper-evidence guarantee.
    """

    def __init__(self, chain_break: ChainBreak) -> None:
        super().__init__(
            f"ledger chain already broken at index={chain_break.index} "
            f"seq={chain_break.seq} reason={chain_break.reason}: {chain_break.detail}"
        )
        self.chain_break = chain_break


def _iter_parsed_lines(lines: Iterable[str]) -> Iterator[tuple[int, dict[str, Any] | None, str | None]]:
    """Yield ``(index, parsed_record_or_None, parse_error_or_None)`` for non-blank lines.

    Stops (does not yield further lines) after the first unparsable line —
    content past a corrupted line is not trustworthy context for chain
    verification.
    """
    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        try:
            yield index, json.loads(line), None
        except json.JSONDecodeError as exc:
            yield index, None, str(exc)
            return


def _walk_chain(
    record_source: Iterable[tuple[int, dict[str, Any] | None, str | None]],
    start_seq: int = 1,
    start_prev_hash: str = GENESIS_PREV_HASH,
) -> tuple[ChainVerificationResult, int, str]:
    """Walk parsed records once, verifying the chain invariant at each step.

    Args:
        record_source: Parsed records to walk.
        start_seq: Sequence number the first record must carry. Defaults to 1
            (a chain that starts at genesis). A ledger whose earlier segments
            have been sealed by :func:`rotate_if_needed` starts partway through
            the chain instead, and passing the continuation here is what stops
            a rotated file from looking like a corrupt one.
        start_prev_hash: ``prev_record_hash`` the first record must carry.

    Returns:
        ``(result, last_valid_seq, last_valid_record_hash)``. When the
        source is empty, these are ``start_seq - 1`` and ``start_prev_hash``.
    """
    expected_prev = start_prev_hash
    expected_seq = start_seq
    count = 0

    def _break(index: int, seq: int | None, reason: str, detail: str) -> ChainVerificationResult:
        return ChainVerificationResult(
            ok=False, record_count=count, first_break=ChainBreak(index, seq, reason, detail)
        )

    for index, record, parse_error in record_source:
        if parse_error is not None:
            return _break(index, None, "malformed_json", parse_error), expected_seq - 1, expected_prev

        assert record is not None  # parse_error is None iff record is not None
        missing = sorted(_CHAIN_FIELDS - record.keys())
        if missing:
            return (
                _break(index, record.get("seq"), "missing_chain_fields", f"missing {missing}"),
                expected_seq - 1,
                expected_prev,
            )

        seq = record["seq"]
        prev_hash = record["prev_record_hash"]
        record_hash = record["record_hash"]

        if seq != expected_seq:
            detail = f"expected seq={expected_seq}, found {seq!r}"
            return _break(index, seq, "seq_gap", detail), expected_seq - 1, expected_prev

        if prev_hash != expected_prev:
            detail = f"expected prev_record_hash={expected_prev}, found {prev_hash!r}"
            return _break(index, seq, "prev_hash_mismatch", detail), expected_seq - 1, expected_prev

        payload = {k: v for k, v in record.items() if k not in _CHAIN_FIELDS}
        recomputed = compute_record_hash(seq, prev_hash, payload)
        if recomputed != record_hash:
            detail = f"stored record_hash={record_hash!r}, recomputed={recomputed!r}"
            return _break(index, seq, "record_hash_mismatch", detail), expected_seq - 1, expected_prev

        expected_prev = record_hash
        expected_seq += 1
        count += 1

    return ChainVerificationResult(ok=True, record_count=count, first_break=None), expected_seq - 1, expected_prev


def verify_chain(path: Path) -> ChainVerificationResult:
    """Walk an on-disk ledger end to end, returning where (if anywhere) it broke.

    Args:
        path: Ledger JSONL file path. A missing file verifies as an empty,
            intact (``ok=True``, ``record_count=0``) chain.

    Returns:
        A :class:`ChainVerificationResult` pinpointing the first break, if any.
    """
    if not path.exists():
        result, _, _ = _walk_chain(iter(()))
        return result
    with path.open("r", encoding="utf-8") as handle:
        result, _, _ = _walk_chain(_iter_parsed_lines(handle))
    return result


def _lock_exclusive(handle: BinaryIO) -> None:
    """Acquire a blocking, cross-process exclusive advisory lock on ``handle``."""
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    if msvcrt is not None:  # pragma: no cover - exercised on Windows CI
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    # No supported lock backend: proceed unlocked (single-writer assumption).
    # verify_chain still catches a corrupted/forked chain either way.


def _unlock(handle: BinaryIO) -> None:
    """Release the lock acquired by :func:`_lock_exclusive`."""
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if msvcrt is not None:  # pragma: no cover - exercised on Windows CI
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _fsync_dir(directory: Path) -> None:
    """Fsync a directory so a new file's directory entry survives a crash."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError as exc:
        _warn_fsync_failure(exc, directory)
    finally:
        os.close(dir_fd)


def append_record(
    path: Path,
    payload: Mapping[str, Any],
    *,
    fsync: bool = True,
    dir_mode: int = 0o700,
) -> dict[str, Any]:
    """Append one hash-chained record to a JSONL ledger, durably.

    Reads and verifies the ledger's ENTIRE existing chain under an exclusive
    advisory lock (see module docstring for the O(n)-per-append rationale),
    computes this record's ``seq``/``prev_record_hash``/``record_hash``,
    appends it as one JSON line, flushes, and (by default) fsyncs before
    releasing the lock.

    Args:
        path: Ledger JSONL file path. Parent directory is created (mode
            ``dir_mode``) on first write; the directory entry is itself
            fsynced the first time the file is created, unless ``fsync`` is
            ``False``.
        payload: This record's body. Must NOT contain the reserved keys
            ``seq`` / ``prev_record_hash`` / ``record_hash`` — those are
            chain metadata computed here, not caller-supplied.
        fsync: Fsync the ledger file after this write, AND fsync the parent
            directory the first time the file is created (default ``True``,
            matching ``TraceWriter``'s per-record durability guarantee — see
            module docstring for why the compliance ledger did not have this
            before). ``False`` issues no fsync syscalls at all.
        dir_mode: Permission bits for the parent directory when created.

    Returns:
        The full record as written: ``payload`` merged with ``seq``,
        ``prev_record_hash``, ``record_hash``.

    Raises:
        ValueError: ``payload`` sets a reserved chain-field key.
        LedgerCorruptionError: The ledger's existing chain is already broken
            (a prior record was edited or deleted) — the append is refused
            rather than silently extended on top of unknown history.
    """
    reserved_used = _CHAIN_FIELDS & payload.keys()
    if reserved_used:
        raise ValueError(f"payload must not set reserved chain fields: {sorted(reserved_used)}")

    path.parent.mkdir(parents=True, exist_ok=True, mode=dir_mode)
    created = not path.exists()

    handle = open(path, "a+b")
    try:
        _lock_exclusive(handle)
        try:
            handle.seek(0)
            existing_text = handle.read().decode("utf-8")
            # Sealed segments come first: after rotate_if_needed the active
            # file starts partway through the chain, and walking it as if it
            # began at genesis would report every rotated ledger as corrupt.
            # Continuing from the newest segment is also what makes deleting a
            # whole segment leave a detectable seam.
            start_seq, start_prev = 1, GENESIS_PREV_HASH
            segments = archive_segments(path)
            if segments:
                tail = _read_raw_records(segments[-1])
                if tail:
                    start_seq = int(tail[-1]["seq"]) + 1
                    start_prev = str(tail[-1]["record_hash"])

            verification, last_seq, last_hash = _walk_chain(
                _iter_parsed_lines(existing_text.splitlines()),
                start_seq=start_seq,
                start_prev_hash=start_prev,
            )
            if not verification.ok:
                assert verification.first_break is not None
                raise LedgerCorruptionError(verification.first_break)

            seq = last_seq + 1
            record_hash = compute_record_hash(seq, last_hash, payload)
            full_record: dict[str, Any] = {
                **payload,
                "seq": seq,
                "prev_record_hash": last_hash,
                "record_hash": record_hash,
            }
            line = (json.dumps(full_record, ensure_ascii=False) + "\n").encode("utf-8")

            handle.seek(0, os.SEEK_END)
            handle.write(line)
            handle.flush()
            if fsync:
                try:
                    os.fsync(handle.fileno())
                except OSError as exc:
                    _warn_fsync_failure(exc, path)
        finally:
            _unlock(handle)
    finally:
        handle.close()

    if created and fsync:
        _fsync_dir(path.parent)

    return full_record


def _read_raw_records(path: Path) -> list[dict[str, Any]]:
    """Read every parseable JSON line from ``path`` in order.

    Used by :func:`build_export` after :func:`verify_chain` has already
    established (or reported) chain integrity — this is a plain re-read, not
    itself a second verification pass.
    """
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(json.loads(stripped))
        except json.JSONDecodeError:
            # A malformed line is already surfaced by verify_chain's
            # "malformed_json" break; stop collecting records past it so the
            # export does not silently paper over the corruption.
            break
    return records


def build_export(path: Path) -> dict[str, Any]:
    """Build a self-contained, offline-verifiable export of a chained ledger.

    The export embeds every parsed record plus the verification outcome
    computed while building it, and a hash over the envelope itself
    (``export_hash``) so a COPY of this dict — with no access to the
    original ledger file or path — can be independently re-verified end to
    end via :func:`verify_export`.

    Args:
        path: Ledger JSONL file path.

    Returns:
        A JSON-serializable export dict.
    """
    verification = verify_chain(path)
    records = _read_raw_records(path)
    envelope = {"format": EXPORT_FORMAT, "source_path": str(path), "records": records}
    export_hash = f"sha256:{_sha256_hex(_canonical_json(envelope))}"
    return {
        "format": EXPORT_FORMAT,
        "source_path": str(path),
        "record_count": len(records),
        "records": records,
        "verification": verification.to_dict(),
        "export_hash": export_hash,
    }


def export_chain_to_file(path: Path, dest: Path) -> Path:
    """Write :func:`build_export`'s output to ``dest`` as pretty JSON.

    Args:
        path: Source ledger JSONL file path.
        dest: Destination file path for the export. Parent directory is
            created if needed.

    Returns:
        ``dest``, for chaining.
    """
    export = build_export(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(export, sort_keys=True, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return dest


def verify_export(export: Mapping[str, Any] | str | Path) -> ChainVerificationResult:
    """Re-verify a chain purely from an export — no source ledger file needed.

    First checks the export envelope itself (``export_hash``, recomputed the
    same way :func:`build_export` computed it) so a tampered EXPORT is
    caught even if the embedded records happen to still chain cleanly among
    themselves; only then walks the embedded records with the same
    verification routine :func:`verify_chain` uses.

    Args:
        export: A dict from :func:`build_export`, or a JSON string / file
            path to one.

    Returns:
        A :class:`ChainVerificationResult`. An envelope-level tamper reports
        ``first_break.reason == "export_hash_mismatch"`` at ``index=-1``.
    """
    if isinstance(export, Path):
        data: Mapping[str, Any] = json.loads(export.read_text(encoding="utf-8"))
    elif isinstance(export, str):
        data = json.loads(export)
    else:
        data = export

    records = list(data["records"])
    envelope = {
        "format": data.get("format", EXPORT_FORMAT),
        "source_path": data.get("source_path", ""),
        "records": records,
    }
    expected_export_hash = f"sha256:{_sha256_hex(_canonical_json(envelope))}"
    if expected_export_hash != data.get("export_hash"):
        detail = f"expected export_hash={expected_export_hash!r}, found {data.get('export_hash')!r}"
        return ChainVerificationResult(
            ok=False,
            record_count=0,
            first_break=ChainBreak(index=-1, seq=None, reason="export_hash_mismatch", detail=detail),
        )

    source = ((index, record, None) for index, record in enumerate(records))
    result, _, _ = _walk_chain(source)
    return result


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

#: Size at which :func:`rotate_if_needed` seals the active ledger. 64 MiB keeps
#: the O(n) verify-before-append (see the module docstring) bounded without
#: producing a directory full of tiny segments.
DEFAULT_ROTATE_BYTES: int = 64 * 1024 * 1024

#: Suffix given to a sealed segment: ``audit_chain.0001.jsonl``.
ARCHIVE_SUFFIX_WIDTH: int = 4


def archive_segments(path: Path) -> list[Path]:
    """Sealed segments for a ledger, oldest first.

    Args:
        path: Active ledger path, e.g. ``.../audit_chain.jsonl``.

    Returns:
        Sorted archive paths. Sorting is lexicographic over a zero-padded
        counter, which is why the counter is padded.
    """
    return sorted(path.parent.glob(f"{path.stem}.[0-9]" + "[0-9]" * (ARCHIVE_SUFFIX_WIDTH - 1) + path.suffix))


def rotate_if_needed(
    path: Path,
    max_bytes: int = DEFAULT_ROTATE_BYTES,
    *,
    fsync: bool = True,
) -> Path | None:
    """Seal the active ledger into an archive segment when it grows too large.

    **Nothing is ever deleted.** This project is not a regulated entity and has
    no statutory retention period to satisfy, and for an audit log the safe
    default in the absence of a policy is to keep everything: deleting an audit
    record is itself an auditable event, and a retention window invented by a
    library would silently destroy evidence nobody chose to destroy. Rotation
    here bounds the *active file*, not the history.

    The chain survives rotation. The sealed segment keeps its records unchanged,
    and the next record appended to the fresh active file continues from the
    sealed segment's final ``record_hash`` -- so a deletion of an entire segment
    is as detectable as an edit within one. Use
    :func:`verify_chain_with_archives` to check the whole history.

    Args:
        path: Active ledger path.
        max_bytes: Size at or above which the active file is sealed.
        fsync: Whether to fsync the directory after the rename.

    Returns:
        The archive path when a rotation happened, else None.

    Raises:
        ValueError: If ``max_bytes`` is not positive.
        LedgerCorruptionError: If the active chain is broken -- a corrupt
            ledger is sealed by nobody; fix or quarantine it deliberately.
    """
    if max_bytes <= 0:
        raise ValueError(f"max_bytes must be positive, got {max_bytes}")
    if not path.exists() or path.stat().st_size < max_bytes:
        return None

    result = verify_chain(path)
    if not result.ok:
        raise LedgerCorruptionError(result.first_break)

    counter = len(archive_segments(path)) + 1
    archive = path.with_name(f"{path.stem}.{counter:0{ARCHIVE_SUFFIX_WIDTH}d}{path.suffix}")
    path.rename(archive)
    if fsync:
        _fsync_dir(path.parent)
    return archive


def verify_chain_with_archives(path: Path) -> ChainVerificationResult:
    """Verify a ledger's whole history, sealed segments included.

    Walks the archives oldest-first and then the active file, checking that each
    segment's first record continues from the previous segment's last
    ``record_hash``. A segment deleted wholesale therefore shows up as a break
    at the seam, which is exactly what plain per-file verification would miss.

    Args:
        path: Active ledger path.

    Returns:
        A :class:`ChainVerificationResult` over the concatenated history. The
        ``index`` of a break is its position in that concatenation, not in any
        one file.
    """
    records: list[dict[str, Any]] = []
    for segment in [*archive_segments(path), path]:
        if not segment.exists():
            continue
        for line in segment.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))

    if not records:
        return ChainVerificationResult(ok=True, record_count=0, first_break=None)

    prev_hash = GENESIS_PREV_HASH
    for index, record in enumerate(records):
        expected_seq = index + 1
        if record.get("seq") != expected_seq:
            return ChainVerificationResult(
                ok=False,
                record_count=len(records),
                first_break=ChainBreak(
                    index=index,
                    seq=record.get("seq"),
                    reason="seq_gap",
                    detail=f"expected seq={expected_seq}, found {record.get('seq')!r}",
                ),
            )
        if record.get("prev_record_hash") != prev_hash:
            return ChainVerificationResult(
                ok=False,
                record_count=len(records),
                first_break=ChainBreak(
                    index=index,
                    seq=record.get("seq"),
                    reason="prev_hash_mismatch",
                    detail=(
                        f"expected prev_record_hash={prev_hash!r}, "
                        f"found {record.get('prev_record_hash')!r}"
                    ),
                ),
            )
        payload = {
            k: v for k, v in record.items()
            if k not in ("seq", "prev_record_hash", "record_hash")
        }
        recomputed = compute_record_hash(record["seq"], record["prev_record_hash"], payload)
        if recomputed != record.get("record_hash"):
            return ChainVerificationResult(
                ok=False,
                record_count=len(records),
                first_break=ChainBreak(
                    index=index,
                    seq=record.get("seq"),
                    reason="record_hash_mismatch",
                    detail=f"stored {record.get('record_hash')!r}, recomputed {recomputed!r}",
                ),
            )
        prev_hash = record["record_hash"]

    return ChainVerificationResult(ok=True, record_count=len(records), first_break=None)
