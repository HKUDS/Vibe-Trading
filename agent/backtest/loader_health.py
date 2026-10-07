"""Public-source health lane: isolated processes, no keys/cache, safe reports.

Run ``python -m backtest.loader_health --output report.json`` from agent/.
Every non-healthy source fails the lane; connectivity is never a passing skip.
A row also carries the loader's own warnings as ``evidence``, so an empty frame
says whether the source refused this runner or the loader itself is broken.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
import logging
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

CANARY_SYMBOLS = {
    "akshare": "601398.SH",
    "baostock": "sh.601398",
    "binance": "BTC-USDT",
    "ccxt": "BTC-USDT",
    "eastmoney": "601398.SH",
    "mootdx": "601398.SH",
    "nobitex": "BTC-IRT",
    "okx": "BTC-USDT",
    "pykrx": "005930.KS",
    "sina": "AAPL.US",
    "stooq": "AAPL.US",
    "tencent": "601398.SH",
    "wallex": "BTC-TMN",
    # These loaders require the project's explicit US suffix; using bare
    # ``AAPL`` here made the canary report empty data while real ``AAPL.US``
    # requests were healthy.
    "yahoo": "AAPL.US",
    "yfinance": "AAPL.US",
}
EXCLUDED_PUBLIC_SOURCES = {"local": "operator files, not a public endpoint"}
DEPENDENCIES = {
    "akshare": "akshare",
    "baostock": "baostock",
    "ccxt": "ccxt",
    "mootdx": "mootdx",
    "pykrx": "pykrx",
    "yfinance": "yfinance",
}
FRESHNESS_DAYS = 14
WINDOW_DAYS = 21

#: A row carries at most this many loader warnings, each capped and sanitized.
MAX_EVIDENCE = 3
EVIDENCE_TEXT_LIMIT = 200

_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://\S+")
# Filesystem paths may contain spaces: partial replacement can expose names.
# Omit those warnings entirely; slashes inside market symbols remain sanitizable.
_FILESYSTEM_PATH_RE = re.compile(r"(?<![A-Za-z0-9])(?:/|[A-Za-z]:[\\/]|\\\\)")
_PATH_RE = re.compile(r"/[^\s]+")
_CREDENTIAL_RE = re.compile(
    r"[\"']?\b[\w-]*(?:token|secret|password|passwd|api[-_]?key|private[-_]?key)[\w-]*[\"']?"
    r"\s*[=:]\s*(?:\"(?:\\.|[^\"])*(?:\"|$)|'(?:\\.|[^'])*(?:'|$)|\S+)"
    # A scheme owns the rest of the warning: its value may be labelled
    # (``Bearer token: VALUE``), and stopping at the label left the value behind.
    r"|\b(?:bearer|basic)\s+\S+(?:\s+\S+)*"
    r"|\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-)[\w-]{8,}",
    re.IGNORECASE,
)


def sanitize_evidence(text: str) -> str | None:
    """Redact URLs, paths and credential-shaped tokens from a loader warning.

    Args:
        text: A log message emitted by a loader.

    Returns:
        The message with URLs and credential-shaped values redacted and
        whitespace collapsed, or ``None`` for filesystem paths or when the
        result still carries an unclassified URL or path separator. An
        unclassifiable message is dropped because this artifact is public.
    """
    cleaned = _CREDENTIAL_RE.sub("<redacted>", _URL_RE.sub("<url>", text or ""))
    if _FILESYSTEM_PATH_RE.search(cleaned):
        return None
    if "://" in cleaned:
        return None
    cleaned = " ".join(cleaned.split())
    cleaned = _PATH_RE.sub("<path>", cleaned)[:EVIDENCE_TEXT_LIMIT].strip()
    if not cleaned or any(marker in cleaned for marker in ("://", "/", "\\")):
        return None
    return cleaned


class _LoaderWarningCollector(logging.Handler):
    """Collect a loader's own warnings so an empty frame can explain itself.

    The child process suppresses the loader's log output (this lane exists to
    separate a blocked source from a broken one, and both reach the report as
    the same empty frame), so the reason is carried in the report instead.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if not (record.name == "backtest.loaders" or record.name.startswith("backtest.loaders.")):
            return
        if len(self.messages) >= MAX_EVIDENCE:
            return
        text = sanitize_evidence(record.getMessage())
        if text and text not in self.messages:
            self.messages.append(text)


def coverage_errors() -> list[str]:
    """Return catalog drift without probing network or credentials."""
    from backtest.loaders.registry import LOADER_REGISTRY, VALID_SOURCES, _ensure_registered

    _ensure_registered()
    missing = VALID_SOURCES - {"auto"} - LOADER_REGISTRY.keys()
    public = {name for name, cls in LOADER_REGISTRY.items() if not cls.requires_auth}
    mapped = CANARY_SYMBOLS.keys() | EXCLUDED_PUBLIC_SOURCES.keys()
    return [
        *[f"unregistered:{n}" for n in sorted(missing)],
        *[f"unmapped:{n}" for n in sorted(public - mapped)],
        *[f"unexpected:{n}" for n in sorted(mapped - public)],
    ]


def check_frame(frame, today: date) -> dict:
    """Validate normalized OHLCV and return safe diagnostic metadata.

    Args:
        frame: A single source's candidate DataFrame.
        today: UTC date used to judge freshness.

    Returns:
        Fixed status/reason and, on success, row count and last bar date.
    """
    import numpy as np
    import pandas as pd

    def bad(reason):
        return {"status": "invalid", "reason": reason}

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return bad("empty_frame")
    columns = ["open", "high", "low", "close", "volume"]
    if not frame.columns.is_unique or not set(columns) <= set(frame.columns):
        return bad("schema")
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans:
        return bad("datetime_index")
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        return bad("index_order")
    if any(not pd.api.types.is_numeric_dtype(frame[c]) for c in columns):
        return bad("numeric_columns")
    values = frame[columns].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return bad("nonfinite_values")
    if (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
        return bad("invalid_prices_or_volume")
    if (frame.high < frame[["open", "close", "low"]].max(axis=1)).any() or (
        frame.low > frame[["open", "close"]].min(axis=1)
    ).any():
        return bad("ohlc_order")
    last_date = frame.index[-1].date()
    age = (today - last_date).days
    if age < 0:
        return bad("future_bar")
    if age > FRESHNESS_DAYS:
        return {"status": "stale", "reason": "last_bar_too_old", "age_days": age}
    return {"status": "healthy", "rows": len(frame), "last_bar": last_date.isoformat(), "age_days": age}


def probe(source: str, today: date) -> dict:
    """Fetch an explicit public loader; never fall back to another source."""
    import requests
    from backtest.loaders.registry import LOADER_REGISTRY, _ensure_registered

    dependency = DEPENDENCIES.get(source)
    if dependency and importlib.util.find_spec(dependency) is None:
        return {"status": "missing_dependency", "reason": "install_canary_dependencies"}
    _ensure_registered()
    cls = LOADER_REGISTRY.get(source)
    if cls is None:
        return {"status": "unavailable", "reason": "loader_not_registered"}
    if cls.requires_auth or source not in CANARY_SYMBOLS:
        return {"status": "invalid", "reason": "not_public_canary"}
    symbol = CANARY_SYMBOLS[source]
    result = {"status": "unavailable", "reason": "availability_probe_failed"}
    collector = _LoaderWarningCollector()
    loaders_logger = logging.getLogger("backtest.loaders")
    loaders_logger.addHandler(collector)
    try:
        for attempt in range(1, 3):
            try:
                loader = cls()
                if not loader.is_available():
                    result = {"status": "unavailable", "reason": "availability_probe_failed"}
                else:
                    frames = loader.fetch(
                        [symbol], (today - timedelta(days=WINDOW_DAYS)).isoformat(), today.isoformat(), interval="1D"
                    )
                    result = check_frame(frames.get(symbol) if isinstance(frames, dict) else None, today)
            except (ConnectionError, TimeoutError, requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                result = {"status": "unreachable", "reason": "network_error"}
            except ImportError:
                result = {"status": "missing_dependency", "reason": "loader_import_failed"}
            except Exception:
                # Exception messages can contain URLs, local paths or credentials.
                result = {"status": "error", "reason": "fetch_failed"}
            result["attempts"] = attempt
            if result["status"] == "healthy":
                break
    finally:
        loaders_logger.removeHandler(collector)
    if collector.messages and result["status"] != "healthy":
        result["evidence"] = collector.messages
    return result


def child_environment(home: str) -> dict[str, str]:
    """Allow process essentials only, excluding operator keys and settings."""
    essentials = {"PATH", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    env = {k: v for k, v in os.environ.items() if k.upper() in essentials}
    env.update(
        {
            "HOME": home,
            "USERPROFILE": home,
            "VIBE_TRADING_HOME": home,
            "VIBE_TRADING_DATA_CACHE": "0",
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return env


def run_source(source: str, today: date, timeout: float) -> dict:
    """Isolate one source and bound imports, availability probes and retries."""
    row = {"source": source, "symbol": CANARY_SYMBOLS[source]}
    with tempfile.TemporaryDirectory(prefix="vibe-loader-health-") as home:
        output = Path(home) / "result.json"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "backtest.loader_health",
                    "--source",
                    source,
                    "--today",
                    today.isoformat(),
                    "--output",
                    str(output),
                ],
                cwd=home,
                env=child_environment(home),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
            if completed.returncode != 0:
                return row | {"status": "error", "reason": "child_failed"}
            result = json.loads(output.read_text(encoding="utf-8"))
            if not isinstance(result, dict) or result.get("status") not in {
                "healthy",
                "invalid",
                "stale",
                "missing_dependency",
                "unavailable",
                "unreachable",
                "error",
            }:
                return row | {"status": "error", "reason": "child_report_failed"}
            return row | result
        except subprocess.TimeoutExpired:
            return row | {"status": "timeout", "reason": "source_deadline"}
        except (OSError, ValueError):
            return row | {"status": "error", "reason": "child_report_failed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--source", choices=sorted(CANARY_SYMBOLS), help=argparse.SUPPRESS)
    parser.add_argument("--today", type=date.fromisoformat, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0 or not 1 <= args.workers <= 4:
        parser.error("timeout must be finite and positive; workers must be 1..4")
    today = args.today or datetime.now(timezone.utc).date()
    if args.source:
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            report = probe(args.source, today)
        exit_code = 0
    else:
        errors = coverage_errors()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows = list(pool.map(lambda source: run_source(source, today, args.timeout), sorted(CANARY_SYMBOLS)))
        report = {
            "date": today.isoformat(),
            "coverage_errors": errors,
            "excluded": EXCLUDED_PUBLIC_SOURCES,
            "sources": rows,
        }
        exit_code = int(bool(errors) or any(row["status"] != "healthy" for row in rows))
        for row in rows:
            print(f"{row['source']}: {row['status']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
