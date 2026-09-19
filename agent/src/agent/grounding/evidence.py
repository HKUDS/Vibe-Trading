"""Evidence intake: what a tool result is allowed to ground.

Every observed number the gate validates against enters here. Kind maps are
keyed on tool field names, never on natural language.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from src.agent.grounding.identity import (
    _infer_currency,
    _infer_venue,
    _normalize_symbol,
    _utc_now,
)

_PRICE_FIELDS = {"open", "high", "low", "close", "adj_close", "price"}

_TIMESTAMP_FIELDS = ("trade_date", "date", "datetime", "timestamp", "time", "index")

_MAX_GENERIC_EVIDENCE = 2_000

# Only these CSV columns count; Volume, Adj Close etc. are ignored so the
# contradiction check gains no values it would be willing to accept.
_CSV_PRICE_COLUMNS = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "price": "price",
}

_CSV_DATE_COLUMNS = {"date", "datetime", "trade_date", "timestamp", "index"}

_CSV_FILENAME_SUFFIX_MAP = (
    ("_V", ".V"),
    ("_TO", ".TO"),
    ("_F", "=F"),
    ("_US", ".US"),
)

# Nested quote leaves of non-OHLC tools ("data.last", "quote[0].close_price")
# mapped to canonical price fields. Only unambiguous quote fields: ratios,
# volumes, strikes and analyst targets stay out so the check accepts no more.
_GENERIC_PRICE_FIELD_ALIASES = {
    "open": "open",
    "open_price": "open",
    "openprice": "open",
    "开盘": "open",
    "开盘价": "open",
    "high": "high",
    "high_price": "high",
    "最高": "high",
    "最高价": "high",
    "low": "low",
    "low_price": "low",
    "最低": "low",
    "最低价": "low",
    "close": "close",
    "close_price": "close",
    "closeprice": "close",
    "prev_close": "close",
    "pre_close": "close",
    "preclose": "close",
    "previous_close": "close",
    "收盘": "close",
    "收盘价": "close",
    "昨收": "close",
    "adj_close": "adj_close",
    "adjclose": "adj_close",
    "adjusted_close": "adj_close",
    "price": "price",
    "last": "price",
    "last_price": "price",
    "lastprice": "price",
    "latest_price": "price",
    "current_price": "price",
    "market_price": "price",
    "settle": "price",
    "settlement": "price",
    "settle_price": "price",
    "vwap": "price",
    "现价": "price",
    "最新价": "price",
}

# Metric family per field name: a figure is grounded only by evidence of its
# own kind, so an observed price never stands in for a volatility (#1336).
_ANALYSIS_KIND_ALIASES = {
    "annualized_vol": "vol",
    "annualized_volatility": "vol",
    "volatility": "vol",
    "return_vol": "vol",
    "return_volatility": "vol",
    "vol": "vol",
    "max_drawdown": "drawdown",
    "maxdd": "drawdown",
    "drawdown": "drawdown",
    "sharpe": "sharpe",
    "sharpe_ratio": "sharpe",
    "win_rate": "win_rate",
    "hit_rate": "win_rate",
    "hitrate": "win_rate",
    "probability": "probability",
    "prob": "probability",
    "total_return": "return",
    "annual_return": "return",
    "cumulative_return": "return",
    "benchmark_return": "return",
    "excess_return": "return",
    "annualized_return": "return",
    "return": "return",
    "returns": "return",
    "ic_positive_ratio": "win_rate",
    "var": "tail_risk",
    "var_95": "tail_risk",
    "var_99": "tail_risk",
    # quantlib_call records a scalar result under the function name, and "var"
    # alone matches only a whole leaf (_EXACT_ONLY_ALIASES), so these two need
    # their own entries or a real VaR result grounds nothing (#1464).
    "historical_var": "tail_risk",
    "parametric_var": "tail_risk",
    "cvar": "tail_risk",
    "es": "tail_risk",
    "expected_shortfall": "tail_risk",
    # Chinese TOOL FIELD NAMES from A-share tools, not answer prose.
    "最大回撤": "drawdown",
    "回撤": "drawdown",
    "夏普": "sharpe",
    "夏普比率": "sharpe",
    "年化波动率": "vol",
    "波动率": "vol",
    "胜率": "win_rate",
    "命中率": "win_rate",
    "概率": "probability",
    "年化收益率": "return",
    "累计收益率": "return",
    "收益率": "return",
}

# Sample-size, window and duration leaves share a metric's token but hold a
# count: ``return_observations = 81`` is 81 observations, never an 81% return
# (#1420/#1426). Matched on the leaf's first and last field-name token.
_METADATA_COUNT_HEADS = frozenset({"n"})

_METADATA_COUNT_TAILS = frozenset(
    {"obs", "observations", "window", "lookback", "count", "days", "duration"}
)

# Money-denominated row fields a currency-marked figure may quote besides a price.
_AMOUNT_FIELDS = frozenset({"amount", "turnover", "成交额"})


def _symbol_from_csv_filename(stem: str) -> str | None:
    """Map a run-dir CSV stem (``BYN_V`` -> ``BYN.V``) to a canonical symbol.

    A stem without a known venue suffix (a bare ``AAPL``) maps to None, because
    the project requires an explicit venue suffix.

    Args:
        stem: CSV filename without the ``.csv`` extension.

    Returns:
        The canonical symbol, or None.
    """
    upper = (stem or "").strip().upper()
    if not upper:
        return None
    for raw, canonical in _CSV_FILENAME_SUFFIX_MAP:
        if upper.endswith(raw) and len(upper) > len(raw):
            return upper[: -len(raw)] + canonical
    return None


def _json_object(value: Any) -> dict[str, Any] | None:
    """Parse a JSON object from a tool result when possible."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_number(value: Any) -> bool:
    """Return whether a value is a finite JSON-style number, excluding bool."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _coerce_csv_number(value: Any) -> int | float | None:
    """Coerce a CSV text cell (``"0.375"``) to a finite number, or None."""
    if _is_number(value):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value.strip().replace(",", ""))
        except (TypeError, ValueError):
            return None
        if math.isfinite(parsed):
            return parsed
    return None


# "." is not a separator: a decimal price such as 8.5 would parse as a date.
# Only the leading month-day (optional year) matters; annotations after the
# day ("08-10(一)", "08-10盘中") are ignored.
_CLAIM_DATE_RE = re.compile(
    r"^\s*(?:((?:19|20)\d{2})\s*[-/年]\s*)?"
    r"(0?[1-9]|1[0-2])\s*[-/月]\s*([12]\d|3[01]|0?[1-9])"
)


def _claim_date_tuple(date_value: str) -> tuple[int, int] | None:
    """Extract the (month, day) a report-style date cell names.

    Args:
        date_value: Date cell as written in the answer, e.g. ``08-10(周一)``.

    Returns:
        The (month, day) tuple, or None when no date prefix is present.
    """
    match = _CLAIM_DATE_RE.match((date_value or "").strip())
    if match is None:
        return None
    return (int(match.group(2)), int(match.group(3)))


def _timestamp_matches_claim_date(timestamp: str, date_value: str) -> bool:
    """Match an evidence timestamp against the date cell of a claim.

    A year-less cell (``08-05``) matches on month and day. That can match the
    wrong year, so callers still compare the value against every matched record
    rather than trusting the date.

    Args:
        timestamp: Evidence timestamp, normally ISO ``YYYY-MM-DD``.
        date_value: Date cell as written in the answer.

    Returns:
        True when the timestamp denotes the day the claim names.
    """
    stamp = (timestamp or "").strip()
    claim = (date_value or "").strip()
    if not stamp or not claim:
        return False
    if stamp.startswith(claim):
        return True
    claim_tuple = _claim_date_tuple(claim)
    parts = stamp[:10].split("-")
    if claim_tuple is None or len(parts) != 3:
        return False
    try:
        stamp_tuple = (int(parts[1]), int(parts[2]))
    except ValueError:
        return False
    return stamp_tuple == claim_tuple


def _leaf_name(path: str) -> str:
    """The last field name of an evidence path, without its list index."""
    leaf = str(path or "").rsplit(".", 1)[-1]
    return re.sub(r"\[\d+\]$", "", leaf).strip().casefold()


def _price_field_for_path(path: str) -> str | None:
    """Map a generic evidence JSON path to a canonical price field.

    Args:
        path: Recorded evidence field, e.g. ``"data.quote[0].last_price"``.

    Returns:
        The matching member of ``_PRICE_FIELDS``, or ``None`` when the leaf is
        not an unambiguous quote field.
    """
    return _GENERIC_PRICE_FIELD_ALIASES.get(_leaf_name(path))


def _is_metadata_count_leaf(path: str) -> bool:
    """Whether an evidence leaf is a sample size, window or duration.

    Args:
        path: Recorded evidence field, e.g. ``"stats.return_observations"``.

    Returns:
        True for ``n_*`` and ``*_obs`` / ``*_observations`` / ``*_window`` /
        ``*_lookback`` / ``*_count`` / ``*_days`` / ``*_duration`` leaves.
    """
    tokens = [token for token in _leaf_name(path).split("_") if token]
    if not tokens:
        return False
    return tokens[-1] in _METADATA_COUNT_TAILS or (
        len(tokens) > 1 and tokens[0] in _METADATA_COUNT_HEADS
    )


# Price-denominated indicator leaves, registered per tool and matched by path
# prefix (spec §5). An unregistered leaf is still evidence but cannot ground a
# price: inferring price-ness from leaf names admitted ``sma_cross`` as a price.
_REGISTERED_PRICE_INDICATORS: dict[str, tuple[str, ...]] = {
    "technical_indicators": (
        "latest_close",
        "indicators.sma_",
        "indicators.ema_",
        "indicators.bollinger.upper",
        "indicators.bollinger.middle",
        "indicators.bollinger.lower",
    ),
}


def _is_registered_price_indicator(tool: str, path: str) -> bool:
    """Whether a tool registered this leaf as a price-denominated level.

    Args:
        tool: The tool whose result produced the evidence record.
        path: Recorded evidence field, e.g. ``"indicators.bollinger.lower"``.

    Returns:
        True when the tool has a registration whose prefix the path matches.
    """
    prefixes = _REGISTERED_PRICE_INDICATORS.get(str(tool or ""))
    if not prefixes:
        return False
    leaf = str(path or "").strip()
    for prefix in prefixes:
        if leaf == prefix:
            return True
        if not leaf.startswith(prefix):
            continue
        # A prefix ending in "_" names a parametrised family (``sma_20``): only a
        # numeric parameter may follow, so ``sma_cross`` is not a price.
        rest = leaf[len(prefix):]
        if not prefix.endswith("_"):
            return True
        if rest.isdigit():
            return True
    return False


# Tail-risk names short enough to be a fragment of an unrelated leaf count only
# as the whole leaf: "var_explained" and "sales_es" are not a VaR.
_EXACT_ONLY_ALIASES = frozenset({"var", "es"})

# Field-name qualifiers that follow a metric's head and do not change what it
# measures ("hit_rate_daily", "vol_annualized"), like a numeric parameter.
_QUALIFIER_SUFFIXES = frozenset(
    {"daily", "weekly", "monthly", "annual", "annualized", "yearly", "pct", "percent", "bps"}
)


def _metric_kind_for_path(path: str) -> str | None:
    """Map an evidence JSON path to an analysis metric kind.

    A metadata count leaf (:func:`_is_metadata_count_leaf`) has no kind.
    """
    if _is_metadata_count_leaf(path):
        return None
    leaf = _leaf_name(path)
    kind = _ANALYSIS_KIND_ALIASES.get(leaf)
    if kind is not None:
        return kind
    # Compound leaves ("strategy_max_drawdown"): scan tokens from the right,
    # where English puts the head noun, so "return_vol" is vol, not return.
    # Only the head of a compound leaf says what it measures (#1426):
    # "strategy_max_drawdown" is a drawdown, while "sharpe_sample_size" and
    # "drawdown_threshold" are a size and a threshold. A trailing numeric
    # parameter or period qualifies the head ("cvar_95", "hit_rate_daily").
    tokens = [token for token in re.split(r"[_.]", leaf) if token]
    stripped = list(tokens)
    while stripped and (stripped[-1].isdigit() or stripped[-1] in _QUALIFIER_SUFFIXES):
        stripped.pop()
    for candidate in (tokens, stripped):
        for size in (2, 1):
            if len(candidate) < size:
                continue
            key = "_".join(candidate[-size:])
            kind = None if key in _EXACT_ONLY_ALIASES else _ANALYSIS_KIND_ALIASES.get(key)
            if kind is not None:
                return kind
    return None


@dataclass(frozen=True)
class EvidenceRecord:
    """One observed, unavailable, or derived numeric evidence item."""

    call_id: str
    tool: str
    symbol: str | None
    source: str
    timestamp: str | None
    field: str
    value: int | float | None
    status: str
    currency: str | None = None
    venue: str | None = None
    currency_conversion: str | None = None


def _is_price_kind(record: EvidenceRecord) -> bool:
    """Whether a record is money-denominated: a quote, a registered level or an amount.

    Args:
        record: One evidence record, with its raw or canonical field.

    Returns:
        True for OHLC/quote fields, registered price indicators and
        amount/turnover leaves.
    """
    return (
        record.field in _PRICE_FIELDS
        or _price_field_for_path(record.field) is not None
        or _is_registered_price_indicator(record.tool, record.field)
        or _leaf_name(record.field) in _AMOUNT_FIELDS
    )


class _EvidenceMixin:
    """Evidence behaviour of :class:`GroundingLedger`."""

    def _ingest_analysis_result(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        payload: dict[str, Any] | None,
        call_id: str,
    ) -> None:
        """Record metric figures a completed analysis result actually produced.

        An ok envelope is not enough: ``backtest`` reports ok for any runner exit
        and a skipped call carries no result (#1336). Only a result yielding at
        least one recognisable metric counts as completed analysis.
        """
        if payload is None or payload.get("skipped"):
            return
        if tool_name == "backtest":
            if str(payload.get("status") or "").casefold() != "ok" and payload.get(
                "exit_code"
            ) not in (0, "0"):
                return
            recorded = self._record_backtest_metrics(arguments, payload, call_id)
        elif tool_name == "factor_analysis":
            if str(payload.get("status") or "").casefold() != "ok":
                return
            recorded = self._record_leaf_metrics(payload, call_id, tool_name, "")
        elif tool_name == "run_shadow_backtest":
            if str(payload.get("status") or "").casefold() != "ok":
                return
            combined = payload.get("combined")
            if not isinstance(combined, dict):
                # A combined dict containing only {"error": ...} is no analysis.
                return
            recorded = self._record_leaf_metrics(combined, call_id, tool_name, "combined")
        elif tool_name == "quantlib_call":
            if payload.get("ok") is not True or str(
                arguments.get("action") or ""
            ).casefold() != "call":
                return
            function = str(arguments.get("function") or "")
            recorded = self._record_leaf_metrics(
                payload.get("result"), call_id, tool_name, function
            )
        else:
            return
        if recorded:
            self._analysis_completed.append(
                {"call_id": call_id, "tool": tool_name, "recorded_at": _utc_now()}
            )

    def _record_leaf_metrics(
        self,
        value: Any,
        call_id: str,
        tool_name: str,
        field_prefix: str,
    ) -> int:
        """Record nested numeric leaves whose key names a metric kind."""
        recorded = 0

        def visit(item: Any, path: str) -> None:
            nonlocal recorded
            if _is_number(item):
                kind = _metric_kind_for_path(path)
                if kind is None:
                    return
                self._analysis_metrics.append(
                    {
                        "metric": kind,
                        "value": float(item),
                        "tool": tool_name,
                        "call_id": call_id,
                        "field": path,
                    }
                )
                recorded += 1
                return
            if isinstance(item, dict):
                for key, child in item.items():
                    visit(child, f"{path}.{key}" if path else str(key))
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    visit(child, f"{path}[{index}]")

        visit(value, field_prefix or "")
        return recorded

    def _record_backtest_metrics(
        self,
        arguments: Mapping[str, Any],
        payload: dict[str, Any],
        call_id: str,
    ) -> int:
        """Parse metric figures from a successful backtest's run-dir artifacts."""
        root = self.run_dir.resolve()
        candidates: list[Path] = []
        raw_dir = arguments.get("run_dir") or payload.get("run_dir")
        if raw_dir:
            candidate = Path(str(raw_dir))
            if not candidate.is_absolute():
                candidate = self.run_dir / candidate
            try:
                resolved = candidate.resolve()
                if resolved == root or resolved.is_relative_to(root):
                    candidates.append(resolved)
            except OSError:
                pass
        # The loop archives a detached backtest's artifacts into the active run
        # dir right after it succeeds, so that copy is the second candidate.
        candidates.append(root)
        artifacts = payload.get("artifacts")
        if isinstance(artifacts, dict):
            for path_value in artifacts.values():
                if not isinstance(path_value, str):
                    continue
                try:
                    resolved = Path(path_value).resolve()
                    if resolved.is_relative_to(root):
                        candidates.append(resolved)
                except OSError:
                    continue
        files: list[Path] = []
        seen_dirs: set[Path] = set()
        for candidate in candidates:
            if candidate.is_file():
                files.append(candidate)
                continue
            if candidate in seen_dirs:
                continue
            seen_dirs.add(candidate)
            for dir_path in (candidate, candidate / "artifacts"):
                for name in ("metrics.csv", "metrics.json"):
                    target = dir_path / name
                    if target.is_file():
                        files.append(target)
        recorded = 0
        seen_files: set[Path] = set()
        for file_path in files:
            if file_path in seen_files:
                continue
            seen_files.add(file_path)
            recorded += self._record_metrics_file(file_path, call_id)
        return recorded

    def _record_metrics_file(self, path: Path, call_id: str) -> int:
        """Record metric figures from one metrics.csv/metrics.json artifact."""
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return 0
        if path.suffix == ".json":
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return 0
            if not isinstance(data, dict):
                return 0
            return self._record_leaf_metrics(data, call_id, "backtest", "")
        try:
            rows = list(csv.reader(text.splitlines()))
        except csv.Error:
            return 0
        if len(rows) < 2:
            return 0
        header = [cell.strip().casefold() for cell in rows[0]]
        recorded = 0
        for index, raw in enumerate(rows[1]):
            if index >= len(header):
                break
            kind = _ANALYSIS_KIND_ALIASES.get(header[index])
            value = _coerce_csv_number(raw)
            if kind is not None and value is not None:
                self._analysis_metrics.append(
                    {
                        "metric": kind,
                        "value": float(value),
                        "tool": "backtest",
                        "call_id": call_id,
                        "field": header[index],
                    }
                )
                recorded += 1
        return recorded

    def _record_tool_failure(self, tool_name: str, call_id: str, result: str) -> None:
        """Store structured unavailable evidence for failed business envelopes."""
        payload = _json_object(result) or {}
        self._tool_failures.append(
            {
                "call_id": call_id,
                "tool": tool_name,
                "status": "unavailable",
                "error_code": payload.get("error_code"),
                "message": str(payload.get("error") or payload.get("message") or "tool failed")[:500],
                "recorded_at": _utc_now(),
            }
        )

    def _ingest_market_data(
        self,
        arguments: Mapping[str, Any],
        payload: dict[str, Any] | None,
        call_id: str,
    ) -> None:
        """Convert full OHLCV payloads into source-linked evidence rows."""
        if payload is None:
            self._record_tool_failure("get_market_data", call_id, "malformed JSON result")
            return
        requested_source = str(arguments.get("source") or "auto")
        provenance = payload.get("_provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        for raw_symbol, raw_rows in payload.items():
            if str(raw_symbol).startswith("_"):
                continue
            symbol = _normalize_symbol(raw_symbol)
            rows = raw_rows.get("data") if isinstance(raw_rows, dict) else raw_rows
            if not isinstance(rows, list):
                continue
            symbol_provenance = provenance.get(raw_symbol)
            actual_source = (
                str(symbol_provenance.get("source"))
                if isinstance(symbol_provenance, dict) and symbol_provenance.get("source")
                else requested_source
            )
            currency_conversion = (
                str(symbol_provenance.get("currency_conversion"))
                if isinstance(symbol_provenance, dict)
                and symbol_provenance.get("currency_conversion")
                else None
            )
            for row in rows:
                if not isinstance(row, dict):
                    continue
                timestamp = next(
                    (str(row[key]) for key in _TIMESTAMP_FIELDS if row.get(key) is not None),
                    None,
                )
                for field_name, value in row.items():
                    normalized_field = str(field_name).casefold()
                    if normalized_field in _TIMESTAMP_FIELDS or not _is_number(value):
                        continue
                    self._evidence.append(
                        EvidenceRecord(
                            call_id=call_id,
                            tool="get_market_data",
                            symbol=symbol,
                            source=actual_source,
                            timestamp=timestamp,
                            field=normalized_field,
                            value=value,
                            status="observed",
                            currency=_infer_currency(symbol),
                            venue=_infer_venue(symbol),
                            currency_conversion=currency_conversion,
                        )
                    )
        unresolved = payload.get("_unresolved")
        if isinstance(unresolved, list):
            for raw_symbol in unresolved:
                symbol = _normalize_symbol(raw_symbol)
                self._evidence.append(
                    EvidenceRecord(
                        call_id=call_id,
                        tool="get_market_data",
                        symbol=symbol,
                        source=requested_source,
                        timestamp=None,
                        field="availability",
                        value=None,
                        status="unavailable",
                        currency=_infer_currency(symbol),
                        venue=_infer_venue(symbol),
                    )
                )

    def _ingest_generic_numeric(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        payload: dict[str, Any],
        call_id: str,
    ) -> None:
        """Flatten bounded numeric leaves from other market-sensitive tools."""
        symbols = self._extract_symbol_arguments(arguments)
        symbol = symbols[0] if len(symbols) == 1 else None
        if symbol:
            symbol = (
                self._match_authorized_symbol(symbol, self.authorized_symbols) or symbol
            )
        source = str(payload.get("source") or tool_name)
        remaining = _MAX_GENERIC_EVIDENCE
        timestamp_fields = (*_TIMESTAMP_FIELDS, "as_of")

        def visit(value: Any, path: str, timestamp: str | None = None) -> None:
            nonlocal remaining
            if remaining <= 0:
                return
            if _is_number(value):
                self._evidence.append(
                    EvidenceRecord(
                        call_id=call_id,
                        tool=tool_name,
                        symbol=symbol,
                        source=source,
                        timestamp=timestamp,
                        field=path or "value",
                        value=value,
                        status="observed",
                        currency=_infer_currency(symbol or ""),
                        venue=_infer_venue(symbol or ""),
                    )
                )
                remaining -= 1
                return
            if isinstance(value, dict):
                local_timestamp = next(
                    (
                        str(value[key])
                        for key in timestamp_fields
                        if value.get(key) is not None
                    ),
                    timestamp,
                )
                for key, item in value.items():
                    if str(key).casefold() in timestamp_fields:
                        continue
                    visit(
                        item,
                        f"{path}.{key}" if path else str(key),
                        local_timestamp,
                    )
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, f"{path}[{index}]", timestamp)

        visit(payload, "")

    def _ingest_run_dir_ohlc_csvs(self) -> None:
        """Register OHLC rows from per-symbol CSVs the run wrote via bash+yfinance.

        Those prices were observed but bypassed ``get_market_data``. Only a file
        whose name maps to a symbol already tracked in this run is accepted, so a
        stray CSV cannot mint identity; rows are bounded by
        ``_MAX_GENERIC_EVIDENCE`` and each file is ingested once.
        """
        if not self.run_dir.is_dir():
            return
        entitled = self._session_symbols | self.authorized_symbols
        if not entitled:
            return
        room = _MAX_GENERIC_EVIDENCE
        for path in sorted(self.run_dir.rglob("*.csv")):
            if room <= 0:
                return
            try:
                identity_key = f"{path.resolve()}:{path.stat().st_mtime_ns}"
            except (OSError, ValueError):
                continue
            if identity_key in self._ingested_csvs:
                continue
            self._ingested_csvs.add(identity_key)
            symbol = _symbol_from_csv_filename(path.stem)
            if not symbol or symbol not in entitled:
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                    rows = list(csv.DictReader(handle))
            except (OSError, UnicodeDecodeError, csv.Error):
                continue
            for row in rows:
                if room <= 0:
                    return
                if not isinstance(row, dict):
                    continue
                timestamp = next(
                    (
                        str(row[key]).strip()
                        for key in row
                        if str(key).strip().casefold() in _CSV_DATE_COLUMNS
                        and row[key] not in (None, "")
                    ),
                    None,
                )
                for key, value in row.items():
                    field_name = _CSV_PRICE_COLUMNS.get(
                        str(key).strip().casefold().replace(" ", "_")
                    )
                    if field_name is None:
                        continue
                    numeric = _coerce_csv_number(value)
                    if numeric is None:
                        continue
                    self._evidence.append(
                        EvidenceRecord(
                            call_id=f"csv:{path.name}",
                            tool="bash",
                            symbol=symbol,
                            source="yfinance",
                            timestamp=timestamp,
                            field=field_name,
                            value=numeric,
                            status="observed",
                            currency=_infer_currency(symbol),
                            venue=_infer_venue(symbol),
                        )
                    )
                    room -= 1

    def _price_records(self) -> list[EvidenceRecord]:
        """Return observed OHLC/price evidence only."""
        return [
            record
            for record in self._evidence
            if record.status == "observed"
            and record.field in _PRICE_FIELDS
            and record.value is not None
        ]

    def _comparable_price_records(self) -> list[EvidenceRecord]:
        """Return every observed quote a numeric claim may be checked against.

        Quotes from non-OHLC tools are re-keyed onto canonical price fields and
        registered indicator leaves onto ``indicator``.

        Returns:
            Observed price evidence with canonical ``field`` values.
        """
        records = self._price_records()
        already_counted = {id(record) for record in records}
        for record in self._evidence:
            if id(record) in already_counted:
                continue
            if record.status != "observed" or record.value is None:
                continue
            field_name = _price_field_for_path(record.field)
            if field_name is None:
                if _is_registered_price_indicator(record.tool, record.field):
                    records.append(replace(record, field="indicator"))
                continue
            records.append(replace(record, field=field_name))
        return records
