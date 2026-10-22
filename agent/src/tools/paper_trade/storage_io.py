"""On-disk layout + byte-level durability for the paper-trade store (T5).

Everything that decides *where* and *how* bytes reach the disk lives here, so
``store.py`` can stay an account/step contract module and ``recovery.py`` can
reason about residue without importing either:

* :func:`dumps` — deterministic strict JSON (sorted keys, compact separators,
  ``ensure_ascii=False``, no NaN/Infinity).  Same spelling as ``wire.dumps_payload``
  so an on-disk document and a wire document are readable by the same tools.
* :func:`atomic_write` — temp file in the SAME directory, fsync, ``os.replace``,
  then fsync the directory.  Same-directory is load-bearing: ``os.replace`` is
  only atomic within one filesystem.
* :func:`write_step_directory` — assemble a step under ``.staging-<date>-*``,
  fsync every file (including the ``bars/`` directory entry itself), build the
  manifest over what was actually written, then rename the directory into
  place.  A rename of a directory is atomic, so a reader never sees a
  half-written step, and an existing target is refused rather than replaced.

``manifest.json`` lists every other file in the step; it cannot list itself (a
digest over a document that contains that digest is not computable), and the
document says so under ``excludes`` instead of leaving the gap implicit.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

__all__ = [
    "ACCOUNT_FILE",
    "ACCOUNTS_DIRNAME",
    "BARS_DIRNAME",
    "LOCK_FILE",
    "MANIFEST_FILE",
    "RECOVERY_FILE",
    "STEPS_DIRNAME",
    "STEP_FILE",
    "StoreError",
    "atomic_write",
    "dumps",
    "jsonl",
    "read_json",
    "row",
    "verify_files",
    "write_step_directory",
]

#: Layout constants (plan §11).  ``paper_trade`` is the store's base dirname,
#: appended to the resolved runtime root.
BASE_DIRNAME = "paper_trade"
ACCOUNTS_DIRNAME = "accounts"
STEPS_DIRNAME = "steps"
ACCOUNT_FILE = "account.json"
STEP_FILE = "step.json"
MANIFEST_FILE = "manifest.json"
RECOVERY_FILE = "recovery.json"
LOCK_FILE = ".lock"
BARS_DIRNAME = "bars"

STAGING_PREFIX = ".staging-"
TMP_PREFIX = ".tmp-"

_BAR_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class StoreError(RuntimeError):
    """A store refusal carrying a stable ``code`` (raised by any store layer)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ── serialization ──


def dumps(value: Any) -> str:
    """Deterministic strict JSON (sorted keys, compact, no NaN/Infinity)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def row(value: Any) -> Any:
    """Normalize one step row (dataclass or mapping) to a JSON-native value."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise StoreError(
        "invalid_step_row",
        f"step rows must be mappings or dataclasses, got {type(value).__name__}",
    )


def jsonl(rows: Sequence[Any] | Iterator[Any]) -> bytes:
    """One canonical JSON document per line; empty input is a 0-byte file."""
    return b"".join(dumps(row(item)).encode("utf-8") + b"\n" for item in rows)


def read_json(path: Path, code: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StoreError(code, f"cannot read {path.name}: {exc}") from exc


# ── durability ──


def _fsync_dir(directory: Path) -> None:
    """Persist a directory entry (POSIX only; Windows has no directory fsync)."""
    if os.name != "posix":
        return
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_durable(path: Path, data: bytes) -> None:
    """Create ``path`` with ``data`` and fsync it (staging-scope write)."""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def atomic_write(path: Path, data: bytes) -> None:
    """Replace ``path`` atomically: temp file in place, fsync, rename, fsync dir."""
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(prefix=f"{TMP_PREFIX}{path.name}-", dir=str(directory))
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    _fsync_dir(directory)


def _bar_filename(symbol: str) -> str:
    name = str(symbol)
    if not _BAR_NAME_RE.match(name) or len(name) > 64:
        raise StoreError(
            "invalid_bar_symbol",
            f"bar symbol {name!r} is not a safe single file name "
            "([A-Za-z0-9][A-Za-z0-9._-]*, at most 64 characters)",
        )
    return f"{name}.csv"


def _manifest(directory: Path, fields: Mapping[str, Any]) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        files[path.relative_to(directory).as_posix()] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "lines": data.count(b"\n"),
            "bytes": len(data),
        }
    return {
        **fields,
        "files": files,
        "excludes": [MANIFEST_FILE],
        "note": (
            "manifest.json cannot list itself (a digest over a document "
            "containing that digest is not computable); it is the only "
            "uncovered file in the step"
        ),
    }


def write_step_directory(
    target: Path,
    *,
    files: Mapping[str, bytes],
    bars: Mapping[str, str] | None = None,
    manifest_fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble ``target`` under a staging name and rename it into place.

    The caller has already refused an existing target; a race that lands one
    anyway surfaces as the ``OSError`` from ``os.replace`` rather than a silent
    overwrite.  The staging directory is removed on every failure path.
    """
    staging = Path(tempfile.mkdtemp(prefix=f"{STAGING_PREFIX}{target.name}-", dir=str(target.parent)))
    try:
        for name, data in files.items():
            _write_durable(staging / name, data)
        if bars:
            bars_dir = staging / BARS_DIRNAME
            bars_dir.mkdir(mode=0o700)
            for symbol in sorted(bars):
                text = bars[symbol]
                if text and not text.endswith("\n"):
                    text += "\n"
                _write_durable(bars_dir / _bar_filename(symbol), text.encode("utf-8"))
            # The files' own dirents live in ``bars/``; fsyncing only ``staging``
            # would persist the tree but not the bar entries inside it.
            _fsync_dir(bars_dir)
        manifest = _manifest(staging, manifest_fields)
        _write_durable(staging / MANIFEST_FILE, (dumps(manifest) + "\n").encode("utf-8"))
        _fsync_dir(staging)
        # ``Path.exists()`` follows a link, so the caller's pre-check cannot see
        # a dangling symlink sitting at the target name, and ``os.replace``
        # would replace that link instead of refusing.  A step directory is
        # evidence, never a link, so refuse the target before the rename.
        if target.is_symlink():
            raise StoreError(
                "step_corrupt",
                f"refusing to replace symbolic link {target.name!r} with a step directory",
            )
        os.replace(staging, target)
        _fsync_dir(target.parent)
        return manifest
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _resolve_manifest_path(directory: Path, relative: Any) -> Path | None:
    """Resolve one manifest key inside ``directory`` or return ``None``.

    The manifest is written by this process but read back from disk, so a
    locally edited key must not make the verifier read outside the step:
    absolute paths, any ``..`` segment and a resolved path outside the step are
    all refused before the file is touched.
    """
    if not isinstance(relative, str) or not relative:
        return None
    candidate = Path(relative)
    if candidate.anchor or ".." in candidate.parts:
        return None
    try:
        root = directory.resolve()
        resolved = (directory / candidate).resolve()
    except (OSError, RuntimeError):
        return None
    if resolved == root or root not in resolved.parents:
        return None
    return resolved


def verify_files(directory: Path, manifest: Mapping[str, Any]) -> tuple[str, ...]:
    """Return ``missing:`` / ``sha256:`` / ``lines:`` / ``path:`` mismatches."""
    files = manifest.get("files") or {}
    if not isinstance(files, Mapping):
        return ("manifest:<files>",)
    problems: list[str] = []
    for relative, entry in sorted(files.items()):
        path = _resolve_manifest_path(directory, relative)
        if path is None:
            problems.append(f"path:{relative}")
            continue
        if not path.is_file():
            problems.append(f"missing:{relative}")
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"sha256:{relative}")
        if data.count(b"\n") != entry.get("lines"):
            problems.append(f"lines:{relative}")
    return tuple(problems)
