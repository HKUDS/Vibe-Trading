"""Run-artifact reader: chunked, downsampled, structured JSON over run files.

A backtest run writes CSV artifacts (``equity.csv``, ``trades.csv``, ...) plus
a ``run_card.json`` sidecar whose ``artifacts`` manifest lists every file the
run produced with its sha256 and size.  The generic ``read_file`` tool returns
raw text, burning LLM tokens on comma-separated noise and truncating mid-file.
This tool scans artifacts without retaining the full table and serves structured JSON pages:

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
from src.config.limits import TOOL_RESULT_LIMIT
from src.tools.path_utils import safe_run_dir

# Match the cap applied by both the agent and swarm consumers.
_BYTE_BUDGET = TOOL_RESULT_LIMIT

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
        card_path = _safe_relative_resolve(run_root, _RUN_CARD_PATH)
        if card_path is None:
            return {}
        card = json.loads(card_path.read_text(encoding="utf-8"))
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
    if re.fullmatch(r"[+-]?0[0-9]+", text):
        return raw
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


def _csv_shape(path: Path) -> tuple[list[str], int]:
    """Count records without retaining the source table in memory."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader, [])
        return header, sum(1 for row in reader if row)


def _read_csv(path: Path, indices: set[int], width: int) -> list[list[Any]]:
    """Read only selected records, retaining at most the requested page."""
    rows: list[list[Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        next(reader, None)
        index = 0
        for record in reader:
            if not record:
                continue
            if index in indices:
                aligned = record[:width] + [""] * max(0, width - len(record))
                rows.append([_coerce_value(cell) for cell in aligned])
            index += 1
    return rows


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
    never dropped silently. A record too large to fit returns an actionable
    error instead of an oversized payload.
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
        if len(payload) <= budget:
            return payload
        if count <= 1:
            return _error("A single record exceeds the result budget",
                          "Project fewer columns, or use read_file for this record.")
        count = max(1, min(count - 1, int(count * budget / len(payload))))


def _fit_downsample_payload(
    base: dict[str, Any], path: Path, header: list[str],
    requested: list[str] | None, max_points: int, budget: int
) -> str:
    """Serialize a downsample envelope, re-striding to fewer points if needed.

    ``base`` is the envelope skeleton without ``rows`` / ``downsample``
    fields. Each pass reads only selected rows from ``path``; the first
    and last source row stay pinned at every sample size.
    """
    total = base["total_rows"]
    target = max(2, max_points)
    while True:
        indices, stride = _downsample_indices(total, target)
        sample = _read_csv(path, set(indices), len(header))
        if requested is not None:
            _, sample = _project(header, sample, requested)
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
        if len(payload) <= budget:
            return payload
        if target <= 2:
            return _error("The sample endpoints exceed the result budget",
                          "Project fewer columns, or request individual rows.")
        target = max(2, min(target - 1, int(target * budget / len(payload))))


def _read_json_artifact(path: Path, artifact: str, run_dir: str, *, meta: bool = False) -> str:
    """Parse and envelope a small JSON artifact (run_card or manifest-listed).

    Returns the ``{"artifact", "run_dir", "json", "size_bytes"}`` envelope, or
    the error envelope when the file is corrupt — never partial JSON.
    """
    try:
        with path.open(encoding="utf-8") as stream:
            content = stream.read(_BYTE_BUDGET + 1)
        if len(content) > _BYTE_BUDGET:
            if meta:
                return _serialize({"artifact": artifact, "run_dir": run_dir,
                                   "size_bytes": path.stat().st_size, "format": "json",
                                   "content_omitted": True,
                                   "hint": "JSON exceeds the result budget; inspect it locally."})
            return _error("JSON artifact exceeds the result budget",
                          "Inspect the artifact locally or regenerate a smaller JSON artifact.")
        parsed = json.loads(content, parse_constant=lambda value: None)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _error(
            f"{artifact} is not valid JSON: {exc}",
            f"Delete or regenerate {path.name}; this tool never returns partial JSON.",
        )
    payload = _serialize(
        {
            "artifact": artifact,
            "run_dir": run_dir,
            "json": parsed,
            "size_bytes": path.stat().st_size,
        }
    )

    if len(payload) > _BYTE_BUDGET:
        return _error("JSON artifact exceeds the result budget", "Inspect the artifact locally or regenerate a smaller JSON artifact.")
    return payload


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
    payload = _serialize(envelope)
    if len(payload) > _BYTE_BUDGET:
        return _error("Artifact metadata exceeds the result budget", "Project fewer columns.")
    return payload


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
            JSON artifacts return their parsed object when it fits; oversized
            JSON returns size metadata only in meta mode, otherwise an error.
        offset: First row index for ``rows`` mode; negative values refused.
        max_rows: Page size clamped to ``[1, 5000]``; samples need at least two endpoints.
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

    manifest = {} if artifact == _RUN_CARD_ALIAS else _load_artifact_manifest(run_root)
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
        return _read_json_artifact(path, artifact, run_dir, meta=format == "meta")

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
        header, total_rows = _csv_shape(path)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return _error(
            f"failed to read {artifact}: {exc}",
            "The file may be corrupt or not a UTF-8 CSV artifact.",
        )
    if columns is not None:
        try:
            _project(header, [], list(columns))
        except ValueError as exc:
            return _error(
                str(exc),
                "Pass only column names from the artifact header, or omit 'columns'.",
            )

    source_header = header
    if columns is not None:
        header = list(columns)
    base: dict[str, Any] = {"artifact": artifact, "run_dir": run_dir, "path": str(path), "columns": header}
    budget = _BYTE_BUDGET

    if format == "meta":
        return _meta_envelope(base, total_rows, path, entry)

    if format == "downsample":
        return _fit_downsample_payload(
            {**base, "total_rows": total_rows, "offset": 0},
            path, source_header, columns, max_rows, budget
        )

    # rows mode
    page = _read_csv(path, set(range(offset, min(total_rows, offset + max_rows))), len(source_header))
    if columns is not None:
        _, page = _project(source_header, page, columns)
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
                "description": "Page size [1, 5000]; samples keep at least two endpoints (default 1000)",
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
