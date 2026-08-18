"""Run listing and detail HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_runs_routes(app, ...)``.
"""

from __future__ import annotations

import csv
import json
import math
import os
import statistics
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, Generator, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# Helper functions (module-level; host Pydantic models resolved via sys.modules)
# ---------------------------------------------------------------------------

_FACTOR_MAX_RESULTS = 20
_FACTOR_MAX_SCAN_ENTRIES = 4096
_FACTOR_MAX_SCAN_DEPTH = 8
_FACTOR_MAX_FILE_BYTES = 2 * 1024 * 1024
_FACTOR_MAX_SUMMARY_BYTES = 128 * 1024
_FACTOR_MAX_TOTAL_ARTIFACT_BYTES = 8 * 1024 * 1024
_FACTOR_MAX_ROWS_PER_CSV = 5000
_FACTOR_MAX_TOTAL_ROWS = 20_000
_FACTOR_MAX_GROUP_COLUMNS = 100


def _load_json_file(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON from disk if present."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _load_csv_to_dict(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Load CSV rows into a list of dictionaries."""
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
        if limit is not None:
            rows = rows[:limit]
        return rows
    except Exception:
        return []


def _finite_float(value: Any) -> Optional[float]:
    """Parse a finite float, returning ``None`` for invalid values.

    Args:
        value: Candidate numeric value.

    Returns:
        Parsed finite float, or ``None``.
    """
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _sanitize_finite_json(value: Any) -> Any:
    """Replace non-finite JSON numeric leaves with ``None`` recursively.

    Args:
        value: Parsed JSON value.

    Returns:
        JSON-compatible value without NaN or infinities.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _sanitize_finite_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_finite_json(item) for item in value]
    return value


def _claim_factor_artifact(
    path: Path,
    *,
    max_file_bytes: int,
    remaining_bytes: int,
) -> Tuple[bool, int, bool]:
    """Check whether an artifact can be read inside the response byte budget.

    Symlinks are rejected so companion files cannot escape the discovered
    bundle. The returned tuple is ``(readable, charged_bytes, degraded)``;
    missing optional files are not considered degraded.

    Args:
        path: Candidate artifact path.
        max_file_bytes: Per-file byte ceiling.
        remaining_bytes: Remaining aggregate byte budget.

    Returns:
        Tuple of readability, charged bytes, and degraded status.
    """
    try:
        if path.is_symlink():
            return False, 0, True
        if not path.is_file():
            return False, 0, False
        size = path.stat().st_size
    except OSError:
        return False, 0, True
    if size < 0 or size > max_file_bytes or size > remaining_bytes:
        return False, 0, True
    return True, size, False


def _load_ic_series_csv(path: Path, row_limit: int) -> Tuple[List[Dict[str, Any]], bool]:
    """Load an ``ic_series.csv`` file into ``{"date", "ic"}`` rows.

    The first CSV column is treated as the date column regardless of its
    header name (the factor tool writes it with an empty or varying index
    label). Rows whose IC value does not parse as a float are skipped.

    Args:
        path: Path to the ic_series.csv file.
        row_limit: Maximum source rows to parse.

    Returns:
        Tuple of rows with raw string dates and finite IC values plus a flag
        indicating that the source was truncated or could not be parsed.
    """
    if row_limit <= 0:
        return [], True
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames
            if not fieldnames or fieldnames[0] is None:
                return [], True
            date_col = fieldnames[0]
            rows: List[Dict[str, Any]] = []
            truncated = False
            for source_index, row in enumerate(reader):
                if source_index >= row_limit:
                    truncated = True
                    break
                date_value = row.get(date_col)
                if date_value is None:
                    continue
                ic_value = _finite_float(row.get("IC"))
                if ic_value is None:
                    continue
                rows.append({"date": date_value, "ic": ic_value})
            return rows, truncated
    except Exception:
        return [], True


def _load_group_equity_csv(
    path: Path,
    row_limit: int,
) -> Tuple[List[Dict[str, Any]], List[str], bool]:
    """Load a ``group_equity.csv`` file into dated rows of float group values.

    The first column is the date; every remaining column is kept in file
    order and parsed as float. Cells that fail to parse are dropped.

    Args:
        path: Path to the group_equity.csv file.
        row_limit: Maximum source rows to parse.

    Returns:
        Tuple of (rows, value column names in file order, truncated/degraded).
    """
    if row_limit <= 0:
        return [], [], True
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames
            if not fieldnames or fieldnames[0] is None or len(fieldnames) < 2:
                return [], [], True
            date_col = fieldnames[0]
            all_value_cols = [col for col in fieldnames[1:] if col]
            value_cols = all_value_cols[:_FACTOR_MAX_GROUP_COLUMNS]
            truncated = len(value_cols) < len(all_value_cols)
            rows: List[Dict[str, Any]] = []
            for source_index, row in enumerate(reader):
                if source_index >= row_limit:
                    truncated = True
                    break
                date_value = row.get(date_col)
                if date_value is None:
                    continue
                parsed: Dict[str, Any] = {"date": date_value}
                for col in value_cols:
                    numeric_value = _finite_float(row.get(col))
                    if numeric_value is not None:
                        parsed[col] = numeric_value
                rows.append(parsed)
            return rows, value_cols, truncated
    except Exception:
        return [], [], True


def _load_factor_summary(path: Path) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Load a factor summary while removing non-finite numeric leaves.

    Args:
        path: Path to ``ic_summary.json``.

    Returns:
        Sanitized summary and whether parsing degraded.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None, True
        return _sanitize_finite_json(payload), False
    except (OSError, UnicodeError, ValueError, RecursionError):
        return None, True


def _iter_factor_series_files(
    run_dir: Path,
    *,
    max_results: int,
) -> Generator[Path, None, None]:
    """Yield bounded, non-symlinked ``ic_series.csv`` paths.

    Directory entries, nesting depth, and result count are all capped. Unlike
    ``Path.rglob()``, this iterator never constructs the complete match list
    and never follows a symlinked directory.

    Args:
        run_dir: Root directory of the run.
        max_results: Maximum factor marker paths to yield.

    Yields:
        Safe paths to factor IC-series artifacts.
    """
    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.is_dir() or artifacts_dir.is_symlink() or max_results <= 0:
        return

    pending: Deque[Tuple[Path, int]] = deque([(artifacts_dir, 0)])
    entries_seen = 0
    yielded = 0
    while pending and entries_seen < _FACTOR_MAX_SCAN_ENTRIES and yielded < max_results:
        directory, depth = pending.popleft()
        child_directories: List[Path] = []
        try:
            with os.scandir(directory) as scan:
                iterator = iter(scan)
                while entries_seen < _FACTOR_MAX_SCAN_ENTRIES:
                    try:
                        entry = next(iterator)
                    except StopIteration:
                        break
                    entries_seen += 1
                    if entry.name.startswith("."):
                        continue
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.name == "ic_series.csv" and entry.is_file(follow_symlinks=False):
                            yield Path(entry.path)
                            yielded += 1
                            if yielded >= max_results:
                                return
                        elif depth < _FACTOR_MAX_SCAN_DEPTH and entry.is_dir(follow_symlinks=False):
                            child_directories.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
        child_directories.sort(key=lambda path: path.name)
        pending.extend((path, depth + 1) for path in child_directories)


def _has_factor_artifacts(run_dir: Path) -> bool:
    """Return whether a bounded directory-entry scan finds a factor bundle."""
    candidates = _iter_factor_series_files(run_dir, max_results=1)
    try:
        return next(candidates, None) is not None
    finally:
        candidates.close()


def _scan_factor_results(run_dir: Path) -> List[Dict[str, Any]]:
    """Scan a run directory for factor-analysis artifact bundles.

    A factor result is any directory under ``run_dir/artifacts`` (recursive)
    that contains an ``ic_series.csv`` file. Traversal, nesting, factor count,
    file sizes, source rows, columns, and aggregate response inputs are all
    bounded. Symlinked directories and files are ignored.

    Args:
        run_dir: Root directory of the run.
    Returns:
        Factor result dicts sorted by name ascending.
    """
    artifacts_dir = run_dir / "artifacts"
    results: List[Dict[str, Any]] = []
    remaining_bytes = _FACTOR_MAX_TOTAL_ARTIFACT_BYTES
    remaining_rows = _FACTOR_MAX_TOTAL_ROWS
    for csv_path in _iter_factor_series_files(run_dir, max_results=_FACTOR_MAX_RESULTS):
        try:
            relative_dir = csv_path.parent.relative_to(run_dir)
        except ValueError:
            continue
        directory = csv_path.parent
        name = "factor_analysis" if directory == artifacts_dir else directory.name

        truncated: Dict[str, bool] = {}
        ic_rows: List[Dict[str, Any]] = []
        ic_readable, ic_size, ic_degraded = _claim_factor_artifact(
            csv_path,
            max_file_bytes=_FACTOR_MAX_FILE_BYTES,
            remaining_bytes=remaining_bytes,
        )
        if ic_readable:
            remaining_bytes -= ic_size
            ic_rows, ic_rows_truncated = _load_ic_series_csv(
                csv_path,
                min(_FACTOR_MAX_ROWS_PER_CSV, remaining_rows),
            )
            remaining_rows -= len(ic_rows)
            if ic_rows_truncated:
                truncated["ic_series"] = True
        elif ic_degraded:
            truncated["ic_series"] = True

        summary: Optional[Dict[str, Any]] = None
        summary_path = directory / "ic_summary.json"
        summary_readable, summary_size, summary_degraded = _claim_factor_artifact(
            summary_path,
            max_file_bytes=_FACTOR_MAX_SUMMARY_BYTES,
            remaining_bytes=remaining_bytes,
        )
        if summary_readable:
            remaining_bytes -= summary_size
            summary, summary_parse_degraded = _load_factor_summary(summary_path)
            if summary_parse_degraded:
                truncated["ic_stats"] = True
        elif summary_degraded:
            truncated["ic_stats"] = True

        equity_rows: List[Dict[str, Any]] = []
        equity_cols: List[str] = []
        equity_path = directory / "group_equity.csv"
        equity_readable, equity_size, equity_degraded = _claim_factor_artifact(
            equity_path,
            max_file_bytes=_FACTOR_MAX_FILE_BYTES,
            remaining_bytes=remaining_bytes,
        )
        if equity_readable:
            remaining_bytes -= equity_size
            equity_rows, equity_cols, equity_rows_truncated = _load_group_equity_csv(
                equity_path,
                min(_FACTOR_MAX_ROWS_PER_CSV, remaining_rows),
            )
            remaining_rows -= len(equity_rows)
            if equity_rows_truncated:
                truncated["group_equity"] = True
        elif equity_degraded:
            truncated["group_equity"] = True

        group_cols = [col for col in equity_cols if col.startswith("Group_")]
        spread_cols = group_cols or equity_cols
        long_short_spread: Optional[float] = None
        group_final_equity: Dict[str, Any] = {}
        if equity_rows and spread_cols:
            last_row = equity_rows[-1]
            first_value = last_row.get(spread_cols[0])
            last_value = last_row.get(spread_cols[-1])
            if first_value is not None and last_value is not None:
                spread = last_value - first_value
                if math.isfinite(spread):
                    long_short_spread = round(spread, 6)
            group_final_equity = {col: last_row[col] for col in equity_cols if col in last_row}
        entry: Dict[str, Any] = {
            "name": name,
            "path": relative_dir.as_posix(),
            "ic_series": ic_rows,
        }
        if isinstance(summary, dict):
            entry["ic_stats"] = summary
        entry["group_equity"] = equity_rows
        entry["n_groups"] = len(group_cols)
        entry["long_short_spread"] = long_short_spread
        entry["group_final_equity"] = group_final_equity
        if truncated:
            entry["truncated"] = truncated
        results.append(entry)
    results.sort(key=lambda item: (str(item["name"]), str(item["path"])))
    return results


def _pearson_correlation(x_values: List[float], y_values: List[float]) -> float:
    """Compute Pearson correlation, degrading to 0.0 for degenerate input.

    Args:
        x_values: First series of values.
        y_values: Second series of values (same length).

    Returns:
        Pearson correlation in [-1, 1], or 0.0 when a variance is zero.
    """
    try:
        correlation = statistics.correlation(x_values, y_values)
    except (statistics.StatisticsError, ValueError, OverflowError, ZeroDivisionError):
        return 0.0
    if not math.isfinite(correlation):
        return 0.0
    return max(-1.0, min(1.0, correlation))


def _factor_ic_correlation(factors: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Build the pairwise IC correlation matrix across factor results.

    Args:
        factors: Factor result dicts from ``_scan_factor_results``.

    Returns:
        Labels plus a symmetric Pearson correlation matrix rounded to four
        decimals, or ``None`` when fewer than two factors exist or any pair
        shares fewer than 10 dates.
    """
    if len(factors) < 2:
        return None
    series: List[Dict[str, float]] = []
    for factor in factors:
        series.append({str(row["date"]): float(row["ic"]) for row in factor.get("ic_series") or []})
    for i in range(len(series)):
        for j in range(i + 1, len(series)):
            if len(series[i].keys() & series[j].keys()) < 10:
                return None
    size = len(series)
    matrix: List[List[float]] = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for i in range(size):
        for j in range(i + 1, size):
            common_dates = sorted(series[i].keys() & series[j].keys())
            x_values = [series[i][date] for date in common_dates]
            y_values = [series[j][date] for date in common_dates]
            correlation = round(_pearson_correlation(x_values, y_values), 4)
            matrix[i][j] = correlation
            matrix[j][i] = correlation
    return {"labels": [str(factor["name"]) for factor in factors], "matrix": matrix}


# Bounded contract for /runs/{run_id}/positions/sectors: at most
# _POSITIONS_SECTOR_MAX_SYMBOLS symbols get a network industry lookup (excess
# symbols degrade to asset-class-only grouping), lookups run on ONE shared
# module-level executor with _POSITIONS_SECTOR_WORKERS threads (created lazily
# on first use and never shut down — process-lifetime — so concurrent requests
# share a single bounded pool instead of spawning one per request), and each
# HTTP call carries the shared Eastmoney client's 15-second socket timeout.
_POSITIONS_SECTOR_MAX_SYMBOLS = 200
_POSITIONS_SECTOR_WORKERS = 4
_POSITIONS_SECTOR_EXECUTOR: Optional[ThreadPoolExecutor] = None
_POSITIONS_SECTOR_EXECUTOR_LOCK = threading.Lock()


def _get_positions_sector_executor() -> ThreadPoolExecutor:
    """Return the shared, process-lifetime industry-lookup executor.

    Created lazily on first use with ``_POSITIONS_SECTOR_WORKERS`` workers and
    never shut down, so every request fans out onto the same bounded pool.

    Returns:
        The shared executor instance.
    """
    global _POSITIONS_SECTOR_EXECUTOR
    if _POSITIONS_SECTOR_EXECUTOR is None:
        with _POSITIONS_SECTOR_EXECUTOR_LOCK:
            if _POSITIONS_SECTOR_EXECUTOR is None:
                _POSITIONS_SECTOR_EXECUTOR = ThreadPoolExecutor(
                    max_workers=_POSITIONS_SECTOR_WORKERS,
                    thread_name_prefix="positions-sector",
                )
    return _POSITIONS_SECTOR_EXECUTOR


def _read_positions_symbols(path: Path) -> List[str]:
    """Read the symbol column names from a wide-format ``positions.csv``.

    Args:
        path: Path to ``artifacts/positions.csv`` (header
            ``timestamp,<sym1>,<sym2>,...``).

    Returns:
        Symbol column names in file order; empty when the file is missing,
        a symlink, empty, or unreadable.
    """
    try:
        if not path.exists() or path.is_symlink():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            fieldnames = csv.DictReader(handle).fieldnames
    except Exception:
        return []
    if not fieldnames:
        return []
    return [name.strip() for name in fieldnames[1:] if name and name.strip()]


def _resolve_industries_concurrent(symbols: List[str]) -> Dict[str, Optional[str]]:
    """Resolve A-share industry boards with bounded concurrency.

    Args:
        symbols: A-share symbols to resolve (already capped by the caller).

    Returns:
        Mapping of symbol -> industry board name, or ``None`` when the lookup
        failed or found no board row. Never raises.
    """
    from src.tools.sector_tool import resolve_industry_board

    results: Dict[str, Optional[str]] = {}
    pool = _get_positions_sector_executor()
    futures = {pool.submit(resolve_industry_board, symbol): symbol for symbol in symbols}
    for future in as_completed(futures):
        symbol = futures[future]
        try:
            results[symbol] = future.result()
        except Exception:  # noqa: BLE001 - one failure must not abort the batch
            results[symbol] = None
    return results


def _build_positions_sector_map(run_dir: Path, run_id: str, *, refresh: bool) -> Dict[str, Any]:
    """Resolve asset class + A-share industry for a run's position symbols.

    Serves from the ``artifacts/sector_map.json`` cache when a valid cache
    exists and ``refresh`` is false; otherwise recomputes and rewrites the
    cache. A corrupt cache file is treated as a cache miss.

    Blocking work here (file reads plus throttled Eastmoney HTTP) is bounded
    by the module-level contract: at most ``_POSITIONS_SECTOR_MAX_SYMBOLS``
    network lookups, ``_POSITIONS_SECTOR_WORKERS`` concurrent workers, and the
    shared Eastmoney client's 15-second per-request socket timeout. Symbols
    beyond the cap keep their asset class but skip industry resolution. The
    caller must run this off the event loop (see ``run_in_threadpool``).

    Args:
        run_dir: Persisted run directory containing ``artifacts/``.
        run_id: Run identifier echoed back in the response envelope.
        refresh: True bypasses the disk cache.

    Returns:
        The envelope ``{"ok", "run_id", "resolved_at", "cached", "symbols",
        "unresolved", "total_symbols", "symbol_limit"}``, or the ``{"ok",
        "run_id", "symbols", "note"}`` form when no positions artifact exists.
    """
    from backtest.engines._market_hooks import _detect_market

    artifacts_dir = run_dir / "artifacts"
    cache_path = artifacts_dir / "sector_map.json"
    try:
        symlinked = artifacts_dir.is_symlink() or cache_path.is_symlink()
    except OSError:
        symlinked = False
    if symlinked:
        # Mirror the factor scan's symlink rejection: a symlinked artifacts dir
        # — or a symlinked sector_map.json cache file inside a real one — is
        # treated as having no positions artifact rather than followed, so
        # neither the cache read nor the cache rewrite can escape the run dir.
        return {"ok": True, "run_id": run_id, "symbols": {}, "note": "no positions artifact"}

    if not refresh:
        cached = _load_json_file(cache_path)
        if isinstance(cached, dict) and isinstance(cached.get("symbols"), dict):
            cached["cached"] = True
            cached["run_id"] = run_id
            return cached

    symbols = _read_positions_symbols(run_dir / "artifacts" / "positions.csv")
    if not symbols:
        return {"ok": True, "run_id": run_id, "symbols": {}, "note": "no positions artifact"}

    resolved: Dict[str, Any] = {}
    a_share_to_resolve: List[str] = []
    for symbol in symbols:
        asset_class = _detect_market(symbol)
        resolved[symbol] = {
            "asset_class": asset_class,
            "industry": None,
            "industry_source": None,
        }
        # The budget counts A-share network lookups only — non-A-share symbols
        # never consume it, so a mixed book with a long non-A-share prefix
        # still resolves its first _POSITIONS_SECTOR_MAX_SYMBOLS A-shares.
        if asset_class == "a_share" and len(a_share_to_resolve) < _POSITIONS_SECTOR_MAX_SYMBOLS:
            a_share_to_resolve.append(symbol)

    if a_share_to_resolve:
        for symbol, industry in _resolve_industries_concurrent(a_share_to_resolve).items():
            if industry is not None:
                resolved[symbol]["industry"] = industry
                resolved[symbol]["industry_source"] = "eastmoney"

    unresolved = [
        symbol
        for symbol in symbols
        if resolved[symbol]["asset_class"] == "a_share" and resolved[symbol]["industry"] is None
    ]

    payload: Dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "cached": False,
        "symbols": resolved,
        "unresolved": unresolved,
        "total_symbols": len(symbols),
        "symbol_limit": _POSITIONS_SECTOR_MAX_SYMBOLS,
    }
    tmp_path = cache_path.with_name(f".sector_map.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, cache_path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
    return payload


def _run_response_payload(response: Any) -> Dict[str, Any]:
    """Return a JSON-ready payload for opt-in run response variants."""
    return response.model_dump(mode="json")


def _build_response_from_run_dir(
    run_dir: Path,
    elapsed: float,
    *,
    include_analysis: bool = False,
    chart_symbol: Optional[str] = None,
    chart_payload: str = "full",
    chart_symbols_out: Optional[List[str]] = None,
):
    """Build a run response from a persisted run directory."""
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    RunResponse = host.RunResponse
    BacktestMetrics = host.BacktestMetrics
    RAGSelection = host.RAGSelection
    Artifact = host.Artifact

    run_id = run_dir.name

    response = RunResponse(
        status="unknown",
        run_id=run_id,
        elapsed_seconds=elapsed,
        run_directory=str(run_dir),
    )

    state_data = _load_json_file(run_dir / "state.json")
    if state_data:
        state_status = str(state_data.get("status") or "").lower()
        if state_status == "success":
            response.status = "success"
        elif state_status in {"failed", "cancelled"}:
            response.status = state_status
            response.reason = state_data.get("reason", "")
        else:
            response.status = state_status or "unknown"
    else:
        response.status = "unknown"

    request_data = _load_json_file(run_dir / "req.json") or {}
    response.prompt = request_data.get("prompt") or request_data.get("request")

    planner_path = run_dir / "planner_output.json"
    response.planner_output = _load_json_file(planner_path)

    design_path = run_dir / "design_spec.json"
    response.strategy_spec = _load_json_file(design_path)

    rag_path = run_dir / "rag_metadata.json"
    rag_data = _load_json_file(rag_path)
    if rag_data:
        response.rag_selection = RAGSelection(
            selected_api=rag_data.get("selected_api") or rag_data.get("api_code", ""),
            selected_name=rag_data.get("selected_name") or rag_data.get("api_name", ""),
            selected_score=float(rag_data.get("selected_score") or rag_data.get("score", 0.0)),
        )

    metrics_path = run_dir / "artifacts" / "metrics.csv"
    if metrics_path.exists():
        metrics_dict_list = _load_csv_to_dict(metrics_path, limit=1)
        if metrics_dict_list:
            row = metrics_dict_list[0]
            try:
                # Pass ALL CSV columns to BacktestMetrics (extra="allow")
                parsed: dict = {}
                for k, v in row.items():
                    if not k or not v:
                        continue
                    try:
                        parsed[k] = int(float(v)) if k == "trade_count" or k == "max_consecutive_loss" else float(v)
                    except (ValueError, TypeError):
                        continue
                if "final_value" in parsed:
                    response.metrics = BacktestMetrics(**parsed)
            except (ValueError, TypeError):
                pass

    artifacts_dir = run_dir / "artifacts"
    if artifacts_dir.exists():
        for file_path in artifacts_dir.iterdir():
            if file_path.is_file():
                file_type = file_path.suffix.lstrip(".")
                response.artifacts.append(
                    Artifact(
                        name=file_path.name,
                        path=str(file_path),
                        type=file_type if file_type else "unknown",
                        size=file_path.stat().st_size,
                        exists=True,
                    )
                )

    response.has_factor_artifacts = _has_factor_artifacts(run_dir)

    equity_path = run_dir / "artifacts" / "equity.csv"
    if equity_path.exists():
        response.artifacts_equity_csv = _load_csv_to_dict(equity_path)

    metrics_csv_path = run_dir / "artifacts" / "metrics.csv"
    if metrics_csv_path.exists():
        response.artifacts_metrics_csv = _load_csv_to_dict(metrics_csv_path)

    run_card_path = run_dir / "run_card.json"
    if run_card_path.exists():
        try:
            response.run_card = json.loads(run_card_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    risk_xray = _load_json_file(run_dir / "artifacts" / "risk_xray.json")
    if risk_xray is not None:
        response.risk_xray = risk_xray
    rebalance_notes = _load_json_file(run_dir / "artifacts" / "rebalance_notes.json")
    if rebalance_notes is not None:
        response.rebalance_notes = rebalance_notes

    llm_usage_path = run_dir / "llm_usage.json"
    if llm_usage_path.exists():
        try:
            response.llm_usage = json.loads(llm_usage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    trades_path = run_dir / "artifacts" / "trades.csv"
    if trades_path.exists():
        response.artifacts_trades_csv = _load_csv_to_dict(trades_path)

    positions_path = run_dir / "artifacts" / "positions.csv"
    if positions_path.exists():
        response.artifacts_positions_csv = _load_csv_to_dict(positions_path)

    target_positions_path = run_dir / "artifacts" / "target_positions.csv"
    if target_positions_path.exists():
        response.artifacts_target_positions_csv = _load_csv_to_dict(target_positions_path)

    validation_path = run_dir / "artifacts" / "validation.json"
    if validation_path.exists():
        try:
            response.validation = json.loads(validation_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    if response.artifacts_equity_csv:
        filtered_equity = []
        for row in response.artifacts_equity_csv[:1000]:
            filtered_row: Dict[str, Any] = {}
            if "timestamp" in row:
                filtered_row["time"] = row["timestamp"]
            if "equity" in row:
                filtered_row["equity"] = row["equity"]
            if "drawdown" in row:
                filtered_row["drawdown"] = row["drawdown"]
            filtered_equity.append(filtered_row)
        response.equity_curve = filtered_equity

    if response.artifacts_trades_csv:
        response.trade_log = response.artifacts_trades_csv[:500]

    if include_analysis:
        from src.ui_services import build_run_analysis

        analysis = build_run_analysis(
            run_dir,
            symbols=[chart_symbol] if chart_symbol else None,
            include_payload=chart_payload != "summary" or bool(chart_symbol),
            include_symbol_list=chart_symbols_out is not None,
        )
        if chart_symbols_out is not None:
            chart_symbols_out.extend(analysis.get("chart_symbols") or [])
        response.run_stage = analysis.get("run_stage")
        response.run_context = analysis.get("run_context")
        response.price_series = analysis.get("price_series")
        response.indicator_series = analysis.get("indicator_series")
        response.trade_markers = analysis.get("trade_markers")
        response.run_logs = analysis.get("run_logs")

    return response


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_runs_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the runs routes onto ``app``.

    Resolves ``require_auth`` from the host ``api_server`` module via
    ``sys.modules`` when not passed explicitly.
    """
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if host is None:
        raise RuntimeError(
            "register_runs_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    if require_auth is None:
        require_auth = host.require_auth

    # Late-access closures for shared host symbols (monkeypatch-safe)
    def _host_validate_path_param(value: str, kind: str) -> None:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._validate_path_param(value, kind)

    def _host_RUNS_DIR() -> Path:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h.RUNS_DIR

    # Pydantic models for response_model (resolved at registration time)
    RunResponse = host.RunResponse
    RunInfo = host.RunInfo

    # --- Routes ---

    @app.get("/runs/{run_id}/code", dependencies=[Depends(require_auth)])
    async def get_run_code(run_id: str):
        """Return strategy source files for a run.

        Args:
            run_id: Run identifier.

        Returns:
            Map filename -> source text.
        """
        _host_validate_path_param(run_id, "run_id")
        run_dir = _host_RUNS_DIR() / run_id / "code"
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail=f"Code directory for run {run_id} not found")
        result = {}
        for f in ["signal_engine.py"]:
            p = run_dir / f
            if p.exists():
                result[f] = p.read_text(encoding="utf-8")
        return result

    @app.get("/runs/{run_id}/pine", dependencies=[Depends(require_auth)])
    async def get_run_pine(run_id: str):
        """Return Pine Script file for a run.

        Args:
            run_id: Run identifier.

        Returns:
            Object with pine script content and exists flag.
        """
        _host_validate_path_param(run_id, "run_id")
        pine_path = _host_RUNS_DIR() / run_id / "artifacts" / "strategy.pine"
        if not pine_path.exists():
            return {"exists": False, "content": None}
        return {
            "exists": True,
            "content": pine_path.read_text(encoding="utf-8"),
        }

    @app.get("/runs/{run_id}/factor", dependencies=[Depends(require_auth)])
    async def get_run_factor(run_id: str):
        """Return factor-analysis artifacts for a run.

        Args:
            run_id: Run identifier.

        Returns:
            Object with exists flag, factor results sorted by name, and the
            pairwise IC correlation matrix (null when not computable).
        """
        _host_validate_path_param(run_id, "run_id")
        run_dir = _host_RUNS_DIR() / run_id
        if not run_dir.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found"
            )
        factors = await run_in_threadpool(_scan_factor_results, run_dir)
        if not factors:
            return {"exists": False, "factors": [], "ic_correlation": None}
        return {
            "exists": True,
            "factors": factors,
            "ic_correlation": _factor_ic_correlation(factors),
        }

    @app.get("/runs/{run_id}", response_model=RunResponse, dependencies=[Depends(require_auth)])
    async def get_run_result(
        run_id: str,
        chart_symbol: Optional[str] = Query(None, description="Opt in to chart payloads for a single symbol"),
        chart_payload: Optional[str] = Query(
            None,
            description="Optional chart payload mode. Use 'summary' to omit chart rows and trade markers.",
        ),
    ):
        """Fetch details for a historical run by ``run_id``.

        The default response stays unchanged for existing consumers. Chart-heavy
        optimizations are opt-in via query parameters.
        """
        _host_validate_path_param(run_id, "run_id")
        if chart_payload not in (None, "summary"):
            raise HTTPException(status_code=400, detail="invalid chart_payload")
        run_dir = _host_RUNS_DIR() / run_id

        if not run_dir.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found"
            )

        wants_chart_meta = bool(chart_payload or chart_symbol)
        chart_symbols: List[str] = []
        response = _build_response_from_run_dir(
            run_dir,
            elapsed=0.0,
            include_analysis=True,
            chart_symbol=chart_symbol,
            chart_payload=chart_payload or "full",
            chart_symbols_out=chart_symbols if wants_chart_meta else None,
        )

        if wants_chart_meta:
            payload = _run_response_payload(response)
            payload["chart_symbols"] = chart_symbols
            return JSONResponse(payload)

        return response

    @app.get("/runs/{run_id}/positions/sectors", dependencies=[Depends(require_auth)])
    async def get_run_positions_sectors(
        run_id: str,
        refresh: int = Query(0, description="Set to 1 to bypass the disk cache and recompute."),
    ):
        """Resolve asset class + A-share industry for a run's position symbols.

        Read-only classification over ``artifacts/positions.csv``, cached in
        ``artifacts/sector_map.json``. The blocking classification (file reads
        plus throttled Eastmoney lookups) runs in the FastAPI threadpool so it
        never stalls the event loop, and is bounded by
        ``_POSITIONS_SECTOR_MAX_SYMBOLS`` / ``_POSITIONS_SECTOR_WORKERS`` /
        the shared client's 15-second per-request timeout.

        Args:
            run_id: Run identifier.
            refresh: ``1`` bypasses the disk cache, ``0`` (default) serves it.

        Returns:
            The sector-map envelope built by ``_build_positions_sector_map``.

        Raises:
            HTTPException: 404 when the run directory does not exist.
        """
        _host_validate_path_param(run_id, "run_id")
        run_dir = _host_RUNS_DIR() / run_id

        if not run_dir.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found"
            )

        return await run_in_threadpool(
            _build_positions_sector_map, run_dir, run_id, refresh=bool(refresh)
        )

    @app.get("/runs", response_model=List[RunInfo], dependencies=[Depends(require_auth)])
    async def list_runs(limit: int = 20):
        """List recent runs with summary fields."""
        from src.ui_services import load_run_context

        limit = min(max(1, limit), 100)
        runs_dir = _host_RUNS_DIR()

        if not runs_dir.exists():
            return []

        run_dirs = sorted(
            [d for d in runs_dir.iterdir() if d.is_dir()],
            key=lambda x: x.name,
            reverse=True
        )

        results = []
        for d in run_dirs[:limit]:
            run_id = d.name

            # Status from state.json or artifacts
            status_val = "unknown"
            state_file = _load_json_file(d / "state.json")
            if state_file:
                status_val = str(state_file.get("status") or "unknown").lower()
            elif (d / "artifacts" / "equity.csv").exists():
                status_val = "success"
            elif (d / "review_report.json").exists():
                status_val = "success"

            # Parse created_at from run_id (YYYYMMDD_HHMMSS or run_YYYYMMDD_HHMMSS)
            created_at = "Unknown"
            if run_id.startswith("run_"):
                parts = run_id.split('_')
                if len(parts) >= 3:
                    d_str, t_str = parts[1], parts[2]
                    if len(d_str) == 8 and len(t_str) == 6:
                        created_at = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]} {t_str[:2]}:{t_str[2:4]}:{t_str[4:6]}"
            elif "_" in run_id:
                parts = run_id.split('_')
                if len(parts) >= 2:
                    d_str, t_str = parts[0], parts[1]
                    if len(d_str) == 8 and len(t_str) == 6:
                        created_at = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]} {t_str[:2]}:{t_str[2:4]}:{t_str[4:6]}"

            if created_at == "Unknown":
                mtime = datetime.fromtimestamp(d.stat().st_mtime)
                created_at = mtime.strftime("%Y-%m-%d %H:%M:%S")

            prompt = None
            req_file = d / "req.json"
            planner_file = d / "planner_output.json"
            if req_file.exists():
                try:
                    req_data = json.loads(req_file.read_text(encoding="utf-8"))
                    prompt = req_data.get("prompt")
                except (json.JSONDecodeError, OSError):
                    pass

            if not prompt and planner_file.exists():
                try:
                    planner_data = json.loads(planner_file.read_text(encoding="utf-8"))
                    prompt = planner_data.get("user_goal") or planner_data.get("goal")
                except (json.JSONDecodeError, OSError):
                    pass

            if not prompt:
                prompt_file = d / "user_prompt.txt"
                if prompt_file.exists():
                    prompt = prompt_file.read_text(encoding="utf-8").strip()

            total_return = None
            sharpe = None
            metrics_file = d / "artifacts" / "metrics.csv"
            if metrics_file.exists():
                try:
                    with open(metrics_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            total_return = float(row.get('total_return', 0) or 0)
                            sharpe = float(row.get('sharpe', 0) or 0)
                            break
                except (OSError, ValueError):
                    pass

            run_context = load_run_context(d)
            results.append(RunInfo(
                run_id=run_id,
                status=status_val,
                created_at=created_at,
                prompt=prompt or "Manual Analysis",
                total_return=total_return,
                sharpe=sharpe,
                codes=run_context.get("codes") or [],
                start_date=run_context.get("start_date"),
                end_date=run_context.get("end_date"),
            ))

        return results
