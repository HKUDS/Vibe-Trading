"""Run-artifact reader: chunked, downsampled, structured JSON over run files.

A backtest run writes CSV artifacts (``equity.csv``, ``trades.csv``, ...) plus
a ``run_card.json`` sidecar whose ``artifacts`` manifest lists every file the
run produced with its sha256 and size.  The generic ``read_file`` tool returns
raw text, burning LLM tokens on comma-separated noise and truncating mid-file.
This tool parses the artifact once and serves structured JSON pages:

* ``rows`` — offset paging over whole records with an honest ``truncated`` /
  ``next_offset`` contract, so a walk reassembles the file losslessly.
* ``downsample`` — equal-stride sampling to at most ``max_rows`` points, first
  and last row always pinned; ``offset`` is ignored (the sample spans all).
* ``meta`` — columns / total_rows / size_bytes, plus the manifest's ``sha256``
  and ``manifest_size_bytes`` for a manifest-listed artifact.

Resolution is manifest-driven: friendly aliases (``equity``, ``ohlcv:<CODE>``,
``run_card``) resolve by a fixed mapping, and any other value is treated as a
run_dir-relative path accepted ONLY when the run_card manifest lists it — a
new artifact kind becomes readable with zero code change, while a tampered
card can never point the reader outside the run directory (every entry is
validated, every resolution re-checked inside ``run_root``).  Serialized
envelopes stay under :data:`_BYTE_BUDGET` by shrinking whole records (never
mid-record, never broken JSON), following ``src/tools/_result_paging.py``.
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path
from typing import Any

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_run_dir

# Serialized-envelope budget in characters. MCP clients truncate large tool
# results (50KB is a common default; raised harness limits reach 256KB); 120K
# keeps a full page intact under the raised limit while leaving framing room.
_BYTE_BUDGET = 120_000

# Friendly CSV aliases: name -> path relative to run_dir.
_CSV_ARTIFACTS: dict[str, str] = {
    "equity": "artifacts/equity.csv",
    "trades": "artifacts/trades.csv",
    "metrics": "artifacts/metrics.csv",
    "positions": "artifacts/positions.csv",
    "target_positions": "artifacts/target_positions.csv",
}
_RUN_CARD_ALIAS = "run_card"
_RUN_CARD_PATH = "run_card.json"
_OHLCV_PREFIX = "ohlcv:"

_VALID_FORMATS = ("rows", "downsample", "meta")
_MAX_ROWS_CEILING = 5000
_SERVED_SUFFIXES = (".csv", ".json")

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")

_ALIAS_HINT = (
    "artifact must be one of: "
    + ", ".join([*_CSV_ARTIFACTS, f"{_OHLCV_PREFIX}<CODE>", _RUN_CARD_ALIAS])
    + ", or a run_dir-relative .csv/.json path listed in the run_card.json "
    "artifacts manifest (e.g. artifacts/validation.json)."
)
_MANIFEST_HINT = (
    "Pass a friendly alias, or a run_dir-relative path the run's run_card.json "
    "artifacts manifest lists; a run without a readable card only serves aliases."
)


class _ArtifactError(ValueError):
    """Artifact-resolution failure carrying its own user-facing hint."""

    def __init__(self, error: str, hint: str) -> None:
        super().__init__(error)
        self.hint = hint


def _error(error: str, hint: str) -> str:
    """Serialize the error envelope: ``{"ok": false, "error", "hint"}``."""
    return json.dumps({"ok": False, "error": error, "hint": hint}, ensure_ascii=False)


def _validate_ohlcv_code(code: str) -> None:
    """Reject an ``ohlcv:<CODE>`` suffix that could escape the artifacts dir.

    Raises:
        ValueError: If the code is empty or carries path separators, parent
            references, a leading dot, or a null byte.
    """
    if not code or not code.strip():
        raise ValueError("ohlcv: requires a non-empty symbol code")
    if "/" in code or "\\" in code or "\x00" in code:
        raise ValueError(f"ohlcv code {code!r} must not contain path separators")
    if code.startswith("."):
        raise ValueError(f"ohlcv code {code!r} must not start with a dot")
    if ".." in code:
        raise ValueError(f"ohlcv code {code!r} must not contain '..'")


def _safe_relative_resolve(run_root: Path, relative: str) -> Path | None:
    """Resolve a manifest-relative path, or return ``None`` if it is unsafe.

    Rejects empty paths, null bytes, absolute paths (POSIX or Windows
    shaped), any ``..`` segment under either separator style, and anything
    whose resolution leaves ``run_root`` (e.g. through a symlink) — so a
    tampered manifest entry is never followed.
    """
    if not relative or "\x00" in relative:
        return None
    if relative.startswith(("/", "\\")) or _WINDOWS_DRIVE.match(relative):
        return None
    if any(segment == ".." for segment in relative.replace("\\", "/").split("/")):
        return None
    if Path(relative).is_absolute():
        return None
    resolved = (run_root / relative).resolve()
    return resolved if resolved.is_relative_to(run_root) else None


def _load_artifact_manifest(run_root: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Load and validate the ``run_card.json`` artifacts manifest.

    The manifest is the trust anchor for non-alias artifact paths: an entry is
    followed only after its own validation (see :func:`_safe_relative_resolve`),
    so a missing, corrupt, or tampered card degrades to "no manifest" — aliases
    keep working against the disk, and relative paths are refused.

    Returns:
        Mapping of manifest path string to ``(resolved_path, entry)``; empty
        when the card carries no well-formed ``artifacts`` list.
    """
    try:
        card = json.loads((run_root / _RUN_CARD_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    entries = card.get("artifacts") if isinstance(card, dict) else None
    if not isinstance(entries, list):
        return {}
    manifest: dict[str, tuple[Path, dict[str, Any]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        relative = entry.get("path")
        if not isinstance(relative, str):
            continue
        resolved = _safe_relative_resolve(run_root, relative)
        if resolved is not None:
            manifest[relative] = (resolved, entry)
    return manifest


def _resolve_artifact(
    run_root: Path,
    artifact: str,
    manifest: dict[str, tuple[Path, dict[str, Any]]],
) -> tuple[Path, dict[str, Any] | None]:
    """Map an alias or manifest-listed path to a file inside ``run_root``.

    Friendly aliases resolve by a fixed mapping and need no card; any other
    value is accepted only when the validated manifest lists it and it is a
    ``.csv``/``.json`` file. Every branch re-verifies containment.

    Returns:
        ``(resolved_path, manifest_entry)``; the entry is ``None`` when the
        artifact is not manifest-listed.

    Raises:
        _ArtifactError: If the name is neither a valid alias nor a
            manifest-listed served-suffix path, or it escapes ``run_root``.
    """
    if artifact in _CSV_ARTIFACTS:
        relative = _CSV_ARTIFACTS[artifact]
    elif artifact == _RUN_CARD_ALIAS:
        relative = _RUN_CARD_PATH
    elif artifact.startswith(_OHLCV_PREFIX):
        code = artifact[len(_OHLCV_PREFIX) :]
        try:
            _validate_ohlcv_code(code)
        except ValueError as exc:
            raise _ArtifactError(str(exc), _ALIAS_HINT) from exc
        relative = f"artifacts/ohlcv_{code}.csv"
    else:
        listed = manifest.get(artifact)
        if listed is None:
            raise _ArtifactError(
                f"artifact {artifact!r} is not a known alias and is not "
                "listed in the run_card.json artifacts manifest",
                _MANIFEST_HINT,
            )
        path, entry = listed
        if path.suffix.lower() not in _SERVED_SUFFIXES:
            raise _ArtifactError(
                f"manifest artifact {artifact!r} is not a .csv or .json file",
                "read_run_artifact serves CSV and JSON artifacts; use "
                "read_file for other files.",
            )
        return path, entry

    resolved = (run_root / relative).resolve()
    if not resolved.is_relative_to(run_root):
        raise _ArtifactError(
            f"artifact {artifact!r} resolves outside run_dir", _ALIAS_HINT
        )
    listed = manifest.get(relative)
    return resolved, listed[1] if listed else None


def _coerce_value(raw: str) -> Any:
    """Coerce one CSV cell to int / float / None / str.

    Integer-looking text becomes ``int``, finite float-looking text becomes
    ``float``, empty or non-finite values (``nan``/``inf`` in any spelling
    ``float()`` accepts) become ``None``, anything else stays a string.
    Underscored numerics (``1_000``) stay strings because ``int()``/``float()``
    would silently accept them.
    """
    text = raw.strip()
    if not text:
        return None
    if "_" not in text:
        try:
            return int(text)
        except ValueError:
            pass
        try:
            value = float(text)
        except ValueError:
            return raw
        return value if math.isfinite(value) else None
    return raw


def _read_csv(path: Path) -> tuple[list[str], list[list[Any]]]:
    """Parse a CSV artifact into columns plus coerced, header-aligned rows.

    Each row has exactly ``len(columns)`` cells (short rows padded with
    ``None``, extra trailing cells dropped); an empty file yields ``([], [])``.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return [], []
        width = len(header)
        rows: list[list[Any]] = []
        for record in reader:
            if not record:
                continue
            aligned = record[:width] + [""] * (width - len(record))
            rows.append([_coerce_value(cell) for cell in aligned])
    return header, rows


def _project(
    columns: list[str], rows: list[list[Any]], requested: list[str]
) -> tuple[list[str], list[list[Any]]]:
    """Project rows onto the requested columns, preserving request order.

    Raises:
        ValueError: If a requested name is not in ``columns``; the message
            lists the valid columns.
    """
    unknown = [name for name in requested if name not in columns]
    if unknown:
        raise ValueError(f"unknown column(s) {unknown}; valid columns: {columns}")
    indices = [columns.index(name) for name in requested]
    return list(requested), [[row[i] for i in indices] for row in rows]


def _downsample_indices(total: int, max_points: int) -> tuple[list[int], int]:
    """Pick equal-stride sample indices with the first and last row pinned.

    When ``total <= max_points`` every index is returned with stride 1.
    """
    if total <= 0:
        return [], 1
    if max_points >= total:
        return list(range(total)), 1
    if max_points < 2:
        # Both endpoints outrank the point cap: a one-point "sample" could
        # never pin first AND last, so the floor is two.
        return [0, total - 1], max(1, total - 1)
    stride = -(-(total - 1) // (max_points - 1))  # ceil division
    indices = list(range(0, total, stride))
    if indices[-1] != total - 1:
        indices.append(total - 1)
    return indices, stride


def _serialize(envelope: dict[str, Any]) -> str:
    """Serialize an envelope the way every response in this tool does."""
    return json.dumps(envelope, ensure_ascii=False)


def _fit_rows_payload(
    base: dict[str, Any],
    page: list[list[Any]],
    offset: int,
    total_rows: int,
    budget: int,
) -> str:
    """Serialize a rows-mode page, shrinking whole rows until it fits budget.

    Mirrors ``_result_paging.fit_records``: shrink proportionally to the
    overflow (then one further) so wide records still converge, keeping
    ``returned_rows`` / ``truncated`` / ``next_offset`` honest — a shrunk page
    always reports ``truncated: true`` with the resume offset, so the tail is
    never dropped silently. The payload stays valid JSON even when a single
    row alone exceeds the budget.
    """
    count = len(page)
    while True:
        rows = page[:count]
        returned = len(rows)
        truncated = offset + returned < total_rows
        envelope = {
            **base,
            "rows": rows,
            "returned_rows": returned,
            "truncated": truncated,
            "next_offset": offset + returned if truncated else None,
        }
        payload = _serialize(envelope)
        if len(payload) <= budget or count <= 1:
            return payload
        count = max(1, min(count - 1, int(count * budget / len(payload))))


def _fit_downsample_payload(
    base: dict[str, Any], rows: list[list[Any]], max_points: int, budget: int
) -> str:
    """Serialize a downsample envelope, re-striding to fewer points if needed.

    ``base`` is the envelope skeleton without ``rows`` / ``downsample``
    fields; ``rows`` are the parsed (and projected) source rows. The first
    and last source row stay pinned at every sample size.
    """
    total = len(rows)
    target = max_points
    while True:
        indices, stride = _downsample_indices(total, target)
        sample = [rows[i] for i in indices]
        envelope = {
            **base,
            "rows": sample,
            "returned_rows": len(sample),
            "truncated": False,
            "next_offset": None,
            "downsample": {
                "stride": stride,
                "pinned_last": True,
                "algorithm": "every-nth",
                "total_rows": total,
            },
        }
        payload = _serialize(envelope)
        if len(payload) <= budget or target <= 2:
            return payload
        target = max(2, min(target - 1, int(target * budget / len(payload))))


def _read_json_artifact(path: Path, artifact: str, run_dir: str) -> str:
    """Parse and envelope a small JSON artifact (run_card or manifest-listed).

    Returns the ``{"artifact", "run_dir", "json", "size_bytes"}`` envelope, or
    the error envelope when the file is corrupt — never partial JSON.
    """
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _error(
            f"{artifact} is not valid JSON: {exc}",
            f"Delete or regenerate {path.name}; this tool never returns partial JSON.",
        )
    return _serialize(
        {
            "artifact": artifact,
            "run_dir": run_dir,
            "json": parsed,
            "size_bytes": path.stat().st_size,
        }
    )


def _meta_envelope(
    base: dict[str, Any],
    total_rows: int,
    path: Path,
    entry: dict[str, Any] | None,
) -> str:
    """Serialize a ``meta`` envelope, enriched from the manifest when listed.

    A manifest-listed artifact additionally carries the card's claims when it
    was written — ``sha256`` and ``manifest_size_bytes`` — beside the real
    ``size_bytes`` stat, so a caller can compare the run's verified-evidence
    record against the file on disk.
    """
    envelope: dict[str, Any] = {
        **base,
        "total_rows": total_rows,
        "size_bytes": path.stat().st_size,
    }
    if entry is not None:
        digest = entry.get("sha256")
        if isinstance(digest, str):
            envelope["sha256"] = digest
        declared = entry.get("size_bytes")
        if isinstance(declared, int) and not isinstance(declared, bool):
            envelope["manifest_size_bytes"] = declared
    return _serialize(envelope)


def read_run_artifact(
    run_dir: str,
    artifact: str,
    format: str = "rows",
    offset: int = 0,
    max_rows: int = 1000,
    columns: list[str] | None = None,
) -> str:
    """Read one run artifact as structured, budget-bounded JSON.

    Args:
        run_dir: Run directory; must sit inside an allowed run root.
        artifact: Friendly alias — ``equity``/``trades``/``metrics``/
            ``positions``/``target_positions`` (CSVs under ``artifacts/``),
            ``ohlcv:<CODE>``, ``run_card`` — or any run_dir-relative
            ``.csv``/``.json`` path listed in the run's ``run_card.json``
            artifacts manifest (e.g. ``artifacts/validation.json``).
        format: ``rows`` (offset paging), ``downsample`` (equal-stride sample,
            first+last pinned; ``offset`` ignored) or ``meta`` (shape only).
            JSON artifacts return their parsed object regardless of format.
        offset: First row index for ``rows`` mode; negative values refused.
        max_rows: Page/sample size, clamped to ``[1, 5000]``.
        columns: Optional projection applied before budget fitting; an unknown
            name is refused with the valid column list.

    Returns:
        JSON string.  Success envelopes carry no ``ok``/``status`` field;
        failures are ``{"ok": false, "error": ..., "hint": ...}``.  ``meta``
        on a manifest-listed artifact additionally carries the manifest's
        ``sha256`` and ``manifest_size_bytes`` beside the real ``size_bytes``.
    """
    if format not in _VALID_FORMATS:
        return _error(
            f"unknown format {format!r}",
            f"format must be one of: {', '.join(_VALID_FORMATS)}.",
        )

    try:
        run_root = safe_run_dir(run_dir)
    except ValueError as exc:
        return _error(str(exc), "Pass the run_dir a backtest/tool call returned.")

    manifest = _load_artifact_manifest(run_root)
    try:
        path, entry = _resolve_artifact(run_root, artifact, manifest)
    except _ArtifactError as exc:
        return _error(str(exc), exc.hint)

    if not path.is_file():
        return _error(
            f"artifact {artifact!r} not found at {path}",
            "The run may not have produced it yet — check the backtest result's "
            "'artifacts' map, or use format='meta' on an artifact that exists.",
        )

    if path.suffix.lower() == ".json":
        return _read_json_artifact(path, artifact, run_dir)

    try:
        offset = int(offset)
        max_rows = int(max_rows)
    except (TypeError, ValueError):
        return _error(
            "offset and max_rows must be integers",
            "Omit them for the defaults (offset=0, max_rows=1000).",
        )
    if offset < 0:
        return _error(
            f"offset must be >= 0, got {offset}",
            "Start at offset=0 and follow next_offset.",
        )
    max_rows = max(1, min(max_rows, _MAX_ROWS_CEILING))

    try:
        header, rows = _read_csv(path)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return _error(
            f"failed to read {artifact}: {exc}",
            "The file may be corrupt or not a UTF-8 CSV artifact.",
        )
    if columns is not None:
        try:
            header, rows = _project(header, rows, list(columns))
        except ValueError as exc:
            return _error(
                str(exc),
                "Pass only column names from the artifact header, or omit 'columns'.",
            )

    total_rows = len(rows)
    base: dict[str, Any] = {"artifact": artifact, "run_dir": run_dir, "columns": header}
    budget = _BYTE_BUDGET

    if format == "meta":
        return _meta_envelope(base, total_rows, path, entry)

    if format == "downsample":
        return _fit_downsample_payload(
            {**base, "total_rows": total_rows, "offset": 0}, rows, max_rows, budget
        )

    # rows mode
    page = rows[offset : offset + max_rows] if offset < total_rows else []
    envelope_base = {
        **base,
        "total_rows": total_rows,
        "offset": offset,
        "downsample": None,
    }
    return _fit_rows_payload(envelope_base, page, offset, total_rows, budget)


class RunArtifactTool(BaseTool):
    """Chunked/downsampled reader for backtest run artifacts."""

    name = "read_run_artifact"
    description = (
        "Read a backtest run artifact as structured JSON: paged rows "
        "(format='rows', follow next_offset), an equal-stride chart sample "
        "with first+last pinned (format='downsample', offset ignored), or "
        "shape only (format='meta', plus the manifest sha256 when listed). "
        "Artifacts: equity, trades, metrics, positions, target_positions, "
        "ohlcv:<CODE>, run_card, or any run_dir-relative .csv/.json path "
        "listed in the run_card.json artifacts manifest. Values arrive typed "
        "(int/float/null/string), never as raw CSV text, and every page stays "
        "within a bounded byte budget."
    )
    parameters = {
        "type": "object",
        "properties": {
            "run_dir": {"type": "string", "description": "Path to the run directory"},
            "artifact": {
                "type": "string",
                "description": (
                    "Artifact alias: equity | trades | metrics | positions | "
                    "target_positions | ohlcv:<CODE> (e.g. ohlcv:600519.SH) | "
                    "run_card — or a run_dir-relative path listed in the "
                    "run_card.json artifacts manifest (e.g. "
                    "artifacts/validation.json)"
                ),
            },
            "format": {
                "type": "string",
                "enum": list(_VALID_FORMATS),
                "description": (
                    "rows: offset paging over whole records; downsample: "
                    "equal-stride sample with first+last row pinned (offset "
                    "ignored); meta: columns/total_rows/size_bytes only"
                ),
            },
            "offset": {
                "type": "integer",
                "description": "First row index (rows mode only, default 0)",
            },
            "max_rows": {
                "type": "integer",
                "description": "Page/sample size, clamped to [1, 5000] (default 1000)",
            },
            "columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional column projection; unknown names are refused "
                    "with the valid list"
                ),
            },
        },
        "required": ["run_dir", "artifact"],
    }
    repeatable = True
    is_readonly = True

    def execute(self, **kwargs: Any) -> str:
        """Execute the artifact read (see :func:`read_run_artifact`)."""
        return read_run_artifact(
            run_dir=kwargs["run_dir"],
            artifact=kwargs["artifact"],
            format=kwargs.get("format", "rows"),
            offset=kwargs.get("offset", 0),
            max_rows=kwargs.get("max_rows", 1000),
            columns=kwargs.get("columns"),
        )
