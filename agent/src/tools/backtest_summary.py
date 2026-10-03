"""Structured backtest summary for the tool result envelope (FE-1 R1 + R4).

The backtest tool envelope historically carried engine results only as raw
stdout, so consumers (e.g. the web frontend) had to ``JSON.parse`` a truncated
log tail to recover metrics.  This module builds a bounded, JSON-safe
``summary`` dict straight from the run directory's own artifacts —
``run_card.json``, ``artifacts/equity.csv`` and the per-symbol
``artifacts/ohlcv_*.csv`` files — and a code → path map of the OHLCV artifacts.

Everything here is best-effort by contract: :func:`try_build_backtest_summary`
never raises and returns ``None`` when a run cannot be summarised (missing or
corrupt ``run_card.json``, unreadable CSV), so the tool envelope stays ``ok``
and simply omits the ``summary`` key.  Payloads are bounded the same way other
tool results are (see :mod:`src.tools._result_paging`): the equity preview is
equal-stride sampled down to at most :data:`MAX_PREVIEW_POINTS` points with the
first and last row always kept, while ``metrics`` stays complete.
"""

from __future__ import annotations

import csv
import json
import logging
import math
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

#: Version of the summary contract consumed by the frontend.
SCHEMA_VERSION = "1.0"
#: Hard cap on ``equity_preview`` points; longer curves are equal-stride
#: sampled with the first and last row always included.
MAX_PREVIEW_POINTS = 50

_OHLCV_PREFIX = "ohlcv_"
_OHLCV_SUFFIX = ".csv"
_OHLCV_GLOB = f"{_OHLCV_PREFIX}*{_OHLCV_SUFFIX}"
# U+00B7 MIDDLE DOT, spelled as an escape so the separator is unambiguous.
_TITLE_SEPARATOR = " \u00b7 "
_PREVIEW_NUMERIC_FIELDS = ("equity", "drawdown", "benchmark_equity")


def collect_ohlcv_paths(run_dir: Path) -> dict[str, str]:
    """Map each symbol code to the absolute path of its OHLCV CSV.

    Globs ``<run_dir>/artifacts/ohlcv_*.csv``; the code is the filename minus
    the ``ohlcv_`` prefix and ``.csv`` suffix (``ohlcv_BTC-USDT.csv`` maps to
    ``BTC-USDT``).  Paths are absolute when ``run_dir`` is absolute, which the
    backtest tool guarantees via ``safe_run_dir``.

    Args:
        run_dir: Backtest run directory root.

    Returns:
        Code → path mapping, empty when there are no OHLCV artifacts or the
        directory cannot be scanned.  Never raises.
    """
    mapping: dict[str, str] = {}
    try:
        candidates = sorted((Path(run_dir) / "artifacts").glob(_OHLCV_GLOB))
        for path in candidates:
            code = path.name[len(_OHLCV_PREFIX) : -len(_OHLCV_SUFFIX)]
            if code:
                mapping[code] = str(path)
    except OSError as exc:  # pragma: no cover - defensive, glob rarely raises
        logger.debug("ohlcv glob failed for %s: %s", run_dir, exc)
    return mapping


def build_backtest_summary(
    run_dir: Path,
    ohlcv_paths: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the structured summary dict for a finished backtest run.

    Reads ``run_card.json`` (schema 1.0: ``card["backtest"]`` carries
    codes/dates/interval/initial_cash, ``card["metrics"]`` the scalar metrics,
    ``card["warnings"]`` the warning list) and previews ``artifacts/equity.csv``.
    The full metrics object is carried — sanitized recursively so non-finite
    floats become ``None`` and ``json.dumps`` stays valid — while the equity
    curve is sampled down to at most :data:`MAX_PREVIEW_POINTS` points.

    Args:
        run_dir: Backtest run directory root containing ``run_card.json``.
        ohlcv_paths: Optional precomputed code → path mapping; gathered with
            :func:`collect_ohlcv_paths` when omitted.

    Returns:
        JSON-safe summary dict following the FE-1 contract.

    Raises:
        OSError: ``run_card.json`` or ``artifacts/equity.csv`` is unreadable.
        json.JSONDecodeError: ``run_card.json`` is not valid JSON.
        ValueError: ``run_card.json`` does not contain a JSON object.
    """
    run_dir = Path(run_dir)
    card = _load_run_card(run_dir)
    backtest = card.get("backtest")
    if not isinstance(backtest, dict):
        backtest = {}
    raw_codes = backtest.get("codes")
    codes = [str(code) for code in raw_codes] if isinstance(raw_codes, list) else []

    if ohlcv_paths is None:
        ohlcv_paths = collect_ohlcv_paths(run_dir)

    artifacts_dir = run_dir / "artifacts"
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_dir.name,
        "title": _TITLE_SEPARATOR.join(codes),
        "codes": codes,
        "start_date": backtest.get("start_date"),
        "end_date": backtest.get("end_date"),
        "interval": backtest.get("interval"),
        "initial_cash": backtest.get("initial_cash"),
        "metrics": _json_safe(_as_dict(card.get("metrics"))),
        "equity_preview": _equity_preview(artifacts_dir / "equity.csv"),
        "artifact_paths": {
            "equity": _existing_file(artifacts_dir / "equity.csv"),
            "trades": _existing_file(artifacts_dir / "trades.csv"),
            "metrics": _existing_file(artifacts_dir / "metrics.csv"),
            "run_card_json": str(run_dir / "run_card.json"),
            "ohlcv": dict(ohlcv_paths),
        },
        "warnings": _json_safe(
            card.get("warnings") if isinstance(card.get("warnings"), list) else []
        ),
    }


def try_build_backtest_summary(
    run_dir: Path,
    ohlcv_paths: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Best-effort :func:`build_backtest_summary` that never raises.

    Args:
        run_dir: Backtest run directory root.
        ohlcv_paths: Optional precomputed code → path mapping.

    Returns:
        The summary dict, or ``None`` when anything about the run directory
        prevents building one (missing/corrupt ``run_card.json``, unreadable
        CSV).  Callers omit the ``summary`` key on ``None``.
    """
    try:
        return build_backtest_summary(run_dir, ohlcv_paths)
    except Exception as exc:  # noqa: BLE001 — contract: never fail the envelope
        logger.debug("backtest summary omitted for %s: %s", run_dir, exc)
        return None


def _load_run_card(run_dir: Path) -> dict[str, Any]:
    """Read and validate ``run_card.json`` at the run directory root."""
    payload = json.loads((run_dir / "run_card.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(
            f"run_card.json must contain a JSON object, got {type(payload).__name__}"
        )
    return payload


def _as_dict(value: Any) -> dict[str, Any]:
    """Return ``value`` when it is a dict, else an empty dict."""
    return value if isinstance(value, dict) else {}


def _existing_file(path: Path) -> str | None:
    """Absolute-style path string when the file exists, else ``None``."""
    return str(path) if path.is_file() else None


def _json_safe(value: Any) -> Any:
    """Recursively replace non-finite floats with ``None``.

    Mirrors ``backtest.run_card._json_safe``: ``json.dumps(..., allow_nan=False)``
    and strict frontend parsers reject ``NaN``/``Infinity``, and Python's
    ``json.loads`` happily produces both from non-standard literals.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _parse_float(cell: str | None) -> float | None:
    """Parse one CSV cell into a finite float, else ``None``.

    Covers blank cells, non-numeric text and the ``NaN``/``inf`` spellings
    ``float()`` accepts, so a dirty equity row degrades to nulls instead of
    poisoning the preview.
    """
    if cell is None:
        return None
    try:
        value = float(cell)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _equity_preview(equity_path: Path) -> list[dict[str, Any]]:
    """Read ``equity.csv`` into bounded preview points.

    Columns follow the engine's artifact contract: ``timestamp,ret,equity,
    drawdown,benchmark_equity,active_ret``.  ``time`` keeps the raw timestamp
    string; numeric fields become finite floats or ``None``.  A missing or
    empty file yields ``[]`` — the summary is still built.

    Raises:
        OSError: The file exists but cannot be read.
        csv.Error: The file is not parseable CSV.
    """
    if not equity_path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with equity_path.open(encoding="utf-8", newline="") as stream:
        for record in csv.DictReader(stream):
            point: dict[str, Any] = {"time": record.get("timestamp")}
            for field in _PREVIEW_NUMERIC_FIELDS:
                point[field] = _parse_float(record.get(field))
            rows.append(point)
    return _sample_rows(rows, MAX_PREVIEW_POINTS)


def _sample_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Equal-stride sample of at most ``limit`` rows, endpoints always kept.

    Rows within the limit are returned unchanged.  Beyond it, the integer
    stride ``i * (n - 1) // (limit - 1)`` yields exactly ``limit`` distinct
    indices that include the first (``i = 0``) and last (``i = limit - 1``)
    row by construction.
    """
    total = len(rows)
    if limit < 2 or total <= limit:
        return list(rows)
    indices = (i * (total - 1) // (limit - 1) for i in range(limit))
    return [rows[index] for index in indices]
