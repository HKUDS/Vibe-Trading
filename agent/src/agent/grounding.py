"""Run-scoped identity and numeric evidence gates for the main agent loop.

The language model remains responsible for research and explanation, but three
facts are structural rather than advisory:

* a market-data consumer may only use an identity that was locked before the
  current assistant tool-call batch started;
* a final price claim may not contradict the full, untruncated tool result; and
* a figure may not be attached to an instrument that no tool call in this run
  ever passed in or returned.

Those are the mechanically decidable parts of the agent's output principles.
The rest of that contract — "state the as-of", "analysis, not advice", "refuse
out loud" — stays in the system prompt on purpose: see ``_validate_price_claims``
and the module tests for why a regex gate on them rejects correct answers.

This module deliberately contains no provider or tool-registry dependencies so
its state machine and final-answer checks remain deterministic and testable.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from src.agent.price_claims import (
    NumericClaim,
    extract_prose_price_claims,
    parse_numeric_cell,
)


GROUNDING_ARTIFACT = "grounding_evidence.json"

_RESOLVER_TOOL = "search_symbol"
_PRIVATE_COMPANY_SKILL_NAMES = {
    "private-company",
    "private-company-analysis",
    "private-company-research",
    "private_company",
    "private_company_analysis",
    "private_company_research",
}
_SYMBOL_ARGUMENT_KEYS = {
    "code",
    "codes",
    "symbol",
    "symbols",
    "ticker",
    "tickers",
    "underlying",
    "underlyings",
}
# Workflow selection must not race an in-flight resolution or proceed on
# contradicted identity. It may proceed once the resolver has answered — and
# ``ambiguous`` is an answer: a screening request ("推荐低价高增长股票") resolves to
# many candidates by design. Requiring a locked identity there stalls every
# discovery task before it can load a screening skill, which is #955.
_RESOLUTION_INCOMPLETE_STATUSES = {"unresolved", "conflicting", "invalidated"}
# Bounded read-only recovery (#1081): a missing instrument identity or price
# evidence is often recoverable deterministically, so the loop should keep
# driving the original task through `search_symbol` and `get_market_data`
# instead of handing the user a terminal "confirm and continue" fallback.
# These budgets are separate from the rejected-draft count so real recovery
# progress is never cut off at the three-draft retry cap.
MAX_GROUNDING_RECOVERY_ROUNDS = 6
MAX_SYMBOL_RESOLUTION_ATTEMPTS = 2
MAX_PRICE_EVIDENCE_ATTEMPTS = 3
_PRICE_FIELDS = {"open", "high", "low", "close", "adj_close", "price"}
_TIMESTAMP_FIELDS = ("trade_date", "date", "datetime", "timestamp", "time", "index")
_MAX_GENERIC_EVIDENCE = 2_000
_MAX_TRACKED_SYMBOLS = 5_000

# CSV columns (case-insensitive) accepted from OHLC files the run wrote via
# bash+yfinance, and their canonical price-field names. Everything else in the
# file (Volume, Adj Close, etc.) is deliberately ignored so the contradiction
# check does not gain values it would be willing to accept.
_CSV_PRICE_COLUMNS = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "price": "price",
}
_CSV_DATE_COLUMNS = {"date", "datetime", "trade_date", "timestamp", "index"}
# Filename -> symbol mapping for run-dir CSVs. The bash workaround writes each
# series with a filesystem-safe stem: ``BYN_V.csv`` for ``BYN.V``, ``PDI_TO.csv``
# for ``PDI.TO``, ``GC_F.csv`` for ``GC=F``.
_CSV_FILENAME_SUFFIX_MAP = (
    ("_V", ".V"),
    ("_TO", ".TO"),
    ("_F", "=F"),
    # A US name is written ``INTC_US.csv`` by the same workaround, and
    # ``.US`` is the venue suffix the rest of the project resolves on. Without
    # this row the CSV was ingested as no evidence at all, so every price the
    # run had actually fetched came back "numeric_claim_unavailable".
    ("_US", ".US"),
)

# Only ``get_market_data`` returns bars whose columns are already the canonical
# OHLC field names. Every other market-sensitive tool nests its quote somewhere,
# and ``_ingest_generic_numeric`` stores that JSON path verbatim — "data.last",
# "quote[0].close_price". Without this map those observations never reach the
# final-answer check, so a price the run genuinely retrieved is rejected as
# "no matching observed tool evidence": measured against the live validator, an
# answer quoting a ``get_stock_profile`` price failed with
# ``numeric_claim_unavailable`` while the identical claim backed by
# ``get_market_data`` passed. Only unambiguous quote fields are mapped; ratios,
# volumes, strikes, and analyst targets stay out so the contradiction check does
# not gain a wider set of values it is willing to accept.
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

# Project-style canonical symbols. A bare model-generated ticker is still
# checked when it appears under a symbol argument key, but it is not accepted
# as user-provided identity because it lacks venue information.
_CANONICAL_SYMBOL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"\d{3,6}\.(?:SH|SZ|BJ|SS|HK|KS|KQ)|"
    r"[A-Z][A-Z0-9&.-]{0,19}\.(?:US|NS|BO|FX|TO|V)|"
    r"[A-Z]{3}/[A-Z]{3}|"
    r"[A-Z0-9]{2,15}(?:-|/)(?:USDT|USDC|USD|BTC|ETH)|"
    r"[A-Z0-9]{2,15}=[FX]"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_ACTIONABLE_MARKET_RE = re.compile(
    r"(?:\bbuy\b|\bsell\b|\bentry\b|\btarget price\b|\bcurrent price\b|"
    r"\blatest price\b|\bprice of\b|\btrade\b|"
    r"\bvaluation of\b|\bwhat (?:is|are) .{1,80} worth\b|"
    r"\bis .{1,80} (?:listed|publicly traded)\b|"
    r"买入|卖出|入场|目标价|现价|最新价|股价|交易价格|估值|值多少钱|"
    r".{1,40}(?:是否|有没有|已经|已)(?:在.{0,20})?上市)",
    re.IGNORECASE,
)
_PRIVATE_ASSERTION_RE = re.compile(
    r"(?:\b(?:is|remains|still)\s+(?:an?\s+)?(?:private company|privately held)\b|"
    r"\bnot publicly traded\b|\bunlisted company\b|"
    r"(?:是|仍是|属于)(?:一家)?(?:私人|私营|非上市)公司|未上市|没有上市)",
    re.IGNORECASE,
)
_TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")

_TABLE_FIELD_ALIASES = {
    "open": "open",
    "opening": "open",
    "opening price": "open",
    "开盘": "open",
    "开盘价": "open",
    "high": "high",
    "highest": "high",
    "最高": "high",
    "最高价": "high",
    "low": "low",
    "lowest": "low",
    "最低": "low",
    "最低价": "low",
    "close": "close",
    "closing": "close",
    "closing price": "close",
    "收盘": "close",
    "收盘价": "close",
}
_DATE_HEADERS = {"date", "datetime", "trade date", "timestamp", "日期", "交易日", "时间"}

_SYMBOL_HEADERS = {"symbol", "ticker", "code", "标的", "代码", "证券代码"}


def _utc_now() -> str:
    """Return an audit-friendly UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Provider spellings that denote one instrument. Shanghai is quoted as ``.SH``
# by Eastmoney and ``.SS`` by Yahoo, A-share tools also accept an exchange
# prefix (``sh600519``), Hong Kong codes are zero-padded to five digits, and
# ccxt writes a crypto pair with a slash. Every one of these is a spelling, not
# an identity: ``_infer_venue`` and ``_infer_currency`` below already map ``.SS``
# and ``.SH`` to the same venue and the same currency. Treating them as
# different identities made ``search_symbol("600519")`` return two candidates
# for one listing, which no tie-break could resolve, so every Shanghai listing
# resolved ``ambiguous`` and no market tool could run for the rest of the run.
_EXCHANGE_PREFIXED_RE = re.compile(r"^(SH|SZ|BJ)(\d{6})$")


def _normalize_symbol(value: Any) -> str:
    """Normalize a symbol onto one canonical identity for exact comparison.

    Args:
        value: Any provider- or model-supplied symbol spelling.

    Returns:
        The canonical spelling — uppercased, with Shanghai's ``.SS`` alias
        folded onto ``.SH``, an exchange prefix rewritten as a suffix, a Hong
        Kong code zero-padded, and a crypto pair hyphenated. Text that is not a
        symbol is returned uppercased and otherwise untouched.
    """
    symbol = str(value or "").strip().upper().replace("/", "-")
    if not symbol:
        return ""
    prefixed = _EXCHANGE_PREFIXED_RE.match(symbol)
    if prefixed:
        return f"{prefixed.group(2)}.{prefixed.group(1)}"
    base, dot, suffix = symbol.rpartition(".")
    if not dot:
        return symbol
    if suffix == "SS":
        suffix = "SH"
    if suffix == "HK" and base.isdigit():
        base = base.zfill(5)
    return f"{base}.{suffix}"


def _symbol_from_csv_filename(stem: str) -> str | None:
    """Map a run-dir CSV stem back to a canonical project symbol.

    The bash workaround writes filesystem-safe stems: ``BYN_V.csv`` -> ``BYN.V``,
    ``PDI_TO.csv`` -> ``PDI.TO``, ``GC_F.csv`` -> ``GC=F``, ``INTC_US.csv`` ->
    ``INTC.US``. A stem without a recognized suffix (e.g. a bare US name
    ``AAPL``) maps to None because the project convention requires an explicit
    venue suffix.

    Args:
        stem: CSV filename without the ``.csv`` extension.

    Returns:
        The canonical symbol, or ``None`` when the stem has no recognizable
        venue suffix.
    """
    upper = (stem or "").strip().upper()
    if not upper:
        return None
    for raw, canonical in _CSV_FILENAME_SUFFIX_MAP:
        if upper.endswith(raw) and len(upper) > len(raw):
            return upper[: -len(raw)] + canonical
    return None


def _query_key(value: Any) -> str:
    """Normalize resolver queries into stable state-machine keys."""
    return " ".join(str(value or "").casefold().split())


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
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _coerce_csv_number(value: Any) -> int | float | None:
    """Coerce a CSV cell to a finite number, or return None.

    CSV readers return every cell as text (``"0.375"``), so a bare
    ``_is_number`` check would discard them all. Values that do not parse as a
    finite number (blank cells, ``-``, ``N/A``) return ``None``.
    """
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


# "." is deliberately not a separator: a decimal price such as 8.5 would parse
# as month 8 day 5 and match a real trading day.
# A report writes the day as a table cell -- "08-10(一)", "08-10(周一)盘中",
# "08-10盘中" -- and the weekday or session suffix made the cell match no
# evidence row at all, so every price in that row came back
# "numeric_claim_unavailable" even though the run had fetched the bar.
_TRADING_DAY_SUFFIX = (
    r"(?:\s*[(（]\s*(?:周|星期)?[一二三四五六日天]\s*[)）])?"
    r"\s*(?:盘中|盘后|盘前|收盘|开盘|早盘|尾盘)?"
)
_YEARLESS_CLAIM_DATE_RE = re.compile(
    r"^(0?[1-9]|1[0-2])\s*[-/月]\s*(0?[1-9]|[12]\d|3[01])\s*[日号]?" + _TRADING_DAY_SUFFIX + r"$"
)
# Two-digit day alternatives are tried before a bare digit so an
# unanchored prefix match consumes the full day ("10" of "08-10(一)")
# instead of stopping at "1".
_ISO_CLAIM_DATE_PREFIX_RE = re.compile(
    r"^\s*((?:19|20)\d{2})\s*[-/]\s*(0?[1-9]|1[0-2])\s*[-/]\s*([12]\d|3[01]|0?[1-9])"
)
_YEARLESS_CLAIM_DATE_PREFIX_RE = re.compile(r"^\s*(0?[1-9]|1[0-2])\s*[-/月]\s*([12]\d|3[01]|0?[1-9])")
_ISO_TIMESTAMP_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")
_COMPACT_TIMESTAMP_RE = re.compile(r"^((?:19|20)\d{2})(\d{2})(\d{2})$")


def _observation_day(timestamp: str | None) -> str | None:
    """Normalize common bar timestamps to an ISO trading-day key."""
    raw = str(timestamp or "").strip()
    if not raw:
        return None
    iso = _ISO_TIMESTAMP_RE.match(raw)
    if iso:
        return f"{int(iso.group(1)):04d}-{int(iso.group(2)):02d}-{int(iso.group(3)):02d}"
    compact = _COMPACT_TIMESTAMP_RE.match(raw)
    if compact:
        return f"{compact.group(1)}-{compact.group(2)}-{compact.group(3)}"
    try:
        epoch = float(raw)
    except ValueError:
        return None
    if not math.isfinite(epoch):
        return None
    if abs(epoch) >= 1_000_000_000_000:
        epoch /= 1000.0
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _claim_date_tuple(date_value: str) -> tuple[int, int] | None:
    """Extract the (month, day) named by a report-style date cell.

    Reports routinely annotate a trading day: the date column reads
    ``08-10(一)``, ``08-10(周一)盘中`` or ``08-10盘中`` rather than the bare
    ``08-10`` the strict full-cell matchers accept. Any leading month-day (or
    full ISO date) prefix is therefore accepted so such a claim still compares
    against the matching evidence row instead of being reported as
    unevidenced.

    Args:
        date_value: Date cell as written in the answer.

    Returns:
        The (month, day) tuple, or None when no date prefix is present.
    """
    claim = (date_value or "").strip()
    match = _YEARLESS_CLAIM_DATE_RE.match(claim)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    match = _ISO_CLAIM_DATE_PREFIX_RE.match(claim)
    if match:
        return (int(match.group(2)), int(match.group(3)))
    match = _YEARLESS_CLAIM_DATE_PREFIX_RE.match(claim)
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return None


def _timestamp_matches_claim_date(timestamp: str, date_value: str) -> bool:
    """Match an evidence timestamp against the date cell of a claim.

    The comparison used to be ``timestamp.startswith(date_value)``, which can
    only succeed when the answer repeats the year. A table whose date column
    reads ``08-05`` — the ordinary way a report writes a trading day — matched
    nothing, so every cell in the row was reported as having no supporting
    evidence while that evidence sat right there (#983: 79 such rejections in
    one run, every value inside the observed range).

    A year-less date is matched on month and day, and a date cell may carry
    weekday or intraday annotations (``08-10(一)``, ``08-10盘中``) whose
    leading month-day is still recognized. Matching the wrong year is a
    smaller failure than matching nothing, but it is a real one, so the
    caller still compares the value against every record that matched rather
    than trusting the date.

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
    day = _observation_day(stamp)
    iso = _ISO_TIMESTAMP_RE.match(day or "")
    if claim_tuple is None or not iso:
        return False
    return (int(iso.group(2)), int(iso.group(3))) == claim_tuple


def _price_field_for_path(path: str) -> str | None:
    """Map a generic evidence JSON path to a canonical price field.

    Args:
        path: Recorded evidence field, e.g. ``"data.quote[0].last_price"``.

    Returns:
        The matching member of ``_PRICE_FIELDS``, or ``None`` when the leaf is
        not an unambiguous quote field.
    """
    leaf = str(path or "").rsplit(".", 1)[-1]
    leaf = re.sub(r"\[\d+\]$", "", leaf).strip().casefold()
    return _GENERIC_PRICE_FIELD_ALIASES.get(leaf)


def _scan_symbols(text: str) -> set[str]:
    """Return the canonical symbols written anywhere in a blob of text."""
    return {_normalize_symbol(match.group(0)) for match in _CANONICAL_SYMBOL_RE.finditer(text or "")}


def _infer_venue(symbol: str) -> str | None:
    """Infer a coarse venue from a project symbol."""
    upper = _normalize_symbol(symbol)
    suffixes = {
        ".US": "us",
        ".SH": "shanghai",
        ".SZ": "shenzhen",
        ".BJ": "beijing",
        ".HK": "hong_kong",
        ".KS": "kospi",
        ".KQ": "kosdaq",
        ".NS": "nse",
        ".BO": "bse",
        ".FX": "forex",
        ".TO": "toronto",
        ".V": "tsx_venture",
    }
    for suffix, venue in suffixes.items():
        if upper.endswith(suffix):
            return venue
    if "-" in upper or "/" in upper:
        return "crypto_or_fx"
    if upper.endswith("=F"):
        return "futures"
    return None


def _infer_currency(symbol: str) -> str | None:
    """Infer quote currency without performing an implicit conversion."""
    upper = _normalize_symbol(symbol)
    suffixes = {
        ".US": "USD",
        ".SH": "CNY",
        ".SZ": "CNY",
        ".BJ": "CNY",
        ".HK": "HKD",
        ".KS": "KRW",
        ".KQ": "KRW",
        ".NS": "INR",
        ".BO": "INR",
        ".TO": "CAD",
        ".V": "CAD",
    }
    for suffix, currency in suffixes.items():
        if upper.endswith(suffix):
            return currency
    for separator in ("-", "/"):
        if separator in upper:
            quote = upper.rsplit(separator, 1)[-1]
            if 3 <= len(quote) <= 5:
                return quote
    return None


def _infer_instrument_type(symbol: str, candidate_type: Any = None) -> str:
    """Normalize provider types into the identity contract."""
    raw = str(candidate_type or "").strip().casefold()
    if "fund" in raw or "etf" in raw or "trust" in raw:
        return "fund"
    if "crypto" in raw:
        return "crypto"
    if "future" in raw:
        return "future"
    if "option" in raw:
        return "option"
    if "forex" in raw or raw == "currency":
        return "forex"
    upper = _normalize_symbol(symbol)
    if upper.endswith("=F"):
        return "future"
    if upper.endswith(".FX"):
        return "forex"
    if "-" in upper or "/" in upper:
        return "crypto"
    return "listed_security"


@dataclass(frozen=True)
class IdentityRecord:
    """One versioned entity-to-instrument resolution result."""

    query: str
    status: str
    symbol: str | None = None
    venue: str | None = None
    instrument_type: str | None = None
    currency: str | None = None
    source_tool_call_id: str | None = None
    source: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1
    updated_at: str = field(default_factory=_utc_now)
    inherited_from_attempt_id: str | None = None
    inherited_from_run_id: str | None = None
    inherited_at: str | None = None


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
    observed_at: str = field(default_factory=_utc_now)
    market_session: str | None = None
    adjustment: str | None = None
    unit: str | None = None
    inherited_from_attempt_id: str | None = None
    inherited_from_run_id: str | None = None
    inherited_at: str | None = None


@dataclass(frozen=True)
class ToolAuthorization:
    """Deterministic decision made before a tool starts."""

    allowed: bool
    error_code: str | None = None
    message: str | None = None
    symbols: tuple[str, ...] = ()

    def error_payload(self, tool_name: str, identity: Mapping[str, Any]) -> str:
        """Render a blocked tool call as a normal structured error result."""
        return json.dumps(
            {
                "status": "error",
                "error_code": self.error_code or "identity_gate_blocked",
                "tool": tool_name,
                "message": self.message or "Tool call blocked by identity gate",
                "symbols": list(self.symbols),
                "identity": dict(identity),
                "required_action": (
                    "Call search_symbol in a separate assistant tool turn, wait for "
                    "its result, then reuse the exact locked symbol and venue. If the "
                    "resolver answers with a shortlist rather than one instrument, "
                    "show the candidates and ask the user which one to use — narrowing "
                    "the query again will not turn a genuine dual listing into one."
                ),
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class ValidationResult:
    """Final-answer grounding decision."""

    valid: bool
    issues: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _observation_cohort(record: EvidenceRecord) -> tuple[str, str, str, str, str]:
    """Return the semantic identity required before two quotes are comparable."""
    return (
        _observation_day(record.timestamp) or "unknown-day",
        (record.market_session or "unknown-session").casefold(),
        (record.adjustment or "unknown-adjustment").casefold(),
        (record.currency or "unknown-currency").upper(),
        (record.unit or "unknown-unit").casefold(),
    )


def _price_tolerance(values: Sequence[float]) -> float:
    """Return the existing 0.5% quote tolerance for one comparable cohort."""
    scale = max((abs(value) for value in values), default=0.0)
    return max(scale * 0.005, 1e-9)


class GroundingLedger:
    """Run-scoped identity state machine and evidence ledger."""

    def __init__(
        self,
        *,
        run_dir: Path,
        user_message: str,
        history: Sequence[Mapping[str, Any]] | None = None,
        inherited_grounding: Mapping[str, Any] | None = None,
    ) -> None:
        """Create a ledger and seed only authoritative prior identities.

        Args:
            run_dir: Active run directory.
            user_message: Current user request.
            history: Optional prior message history. It remains available to
                the model, but is deliberately not an authorization source for
                this run: stale identities from an earlier user subject must
                not unlock a new subject's tools.
            inherited_grounding: Trusted artifact from the direct parent
                Attempt after SessionService has verified task continuity.
        """
        self.run_dir = Path(run_dir)
        self.user_message = user_message
        self._identities: dict[str, IdentityRecord] = {}
        self._evidence: list[EvidenceRecord] = []
        self._tool_failures: list[dict[str, Any]] = []
        self._validations: list[dict[str, Any]] = []
        self._recovery_rounds = 0
        self._symbol_resolution_attempts = 0
        self._price_evidence_attempts = 0
        self._ingested_csvs: set[str] = set()
        self._identity_required = bool(_ACTIONABLE_MARKET_RE.search(user_message))
        self._buffer_output = self._identity_required
        # Every instrument this run is entitled to write about: the ones the
        # user named, plus the ones a succeeding tool call passed in or returned.
        self._session_symbols: set[str] = _scan_symbols(user_message)
        # Bare tickers a succeeding call passed in, e.g. "AAPL" for the nine
        # tools whose contract is a bare US ticker. "AAPL.US" in the answer then
        # names an instrument the run really handled.
        self._session_symbol_roots: set[str] = set()

        self._hydrate_inherited_grounding(inherited_grounding)
        self._seed_symbols(user_message, source="user_message")
        self.persist()

    def _hydrate_inherited_grounding(
        self,
        payload: Mapping[str, Any] | None,
    ) -> None:
        """Import trusted locked identities and observed evidence from a parent run."""
        if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
            return
        inheritance = payload.get("_inheritance")
        if not isinstance(inheritance, Mapping):
            return
        attempt_id = str(inheritance.get("attempt_id") or "").strip()
        run_id = str(inheritance.get("run_id") or "").strip()
        if not attempt_id or not run_id:
            return
        inherited_at = _utc_now()

        identity = payload.get("identity")
        identity_rows = identity.get("records") if isinstance(identity, Mapping) else []
        if isinstance(identity_rows, list):
            for raw in identity_rows:
                if not isinstance(raw, Mapping) or raw.get("status") != "locked":
                    continue
                symbol_value = raw.get("symbol")
                symbol = _normalize_symbol(str(symbol_value)) if symbol_value else ""
                if not symbol:
                    continue
                query = str(raw.get("query") or symbol).strip()
                source_value = raw.get("source")
                sources = (
                    [str(item) for item in source_value if str(item).strip()] if isinstance(source_value, list) else []
                )
                raw_version = raw.get("version")
                version = (
                    max(1, raw_version) if isinstance(raw_version, int) and not isinstance(raw_version, bool) else 1
                )
                record = IdentityRecord(
                    query=query,
                    status="locked",
                    symbol=symbol,
                    venue=str(raw.get("venue") or "") or None,
                    instrument_type=str(raw.get("instrument_type") or "") or None,
                    currency=str(raw.get("currency") or "") or None,
                    source_tool_call_id=(str(raw.get("source_tool_call_id") or "") or None),
                    source=sources,
                    candidates=[],
                    version=version,
                    updated_at=str(raw.get("updated_at") or inherited_at),
                    inherited_from_attempt_id=attempt_id,
                    inherited_from_run_id=run_id,
                    inherited_at=inherited_at,
                )
                self._identities[f"inherited:{symbol}"] = record
                self._session_symbols.add(symbol)

        evidence_rows = payload.get("evidence")
        if isinstance(evidence_rows, list):
            for raw in evidence_rows:
                if not isinstance(raw, Mapping) or raw.get("status") != "observed":
                    continue
                symbol_value = raw.get("symbol")
                symbol = _normalize_symbol(str(symbol_value)) if symbol_value else ""
                source = str(raw.get("source") or "").strip()
                timestamp = str(raw.get("timestamp") or "").strip()
                value = raw.get("value")
                if (
                    not symbol
                    or not source
                    or source.casefold() in {"auto", "unknown"}
                    or not timestamp
                    or isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                ):
                    continue
                call_id = str(raw.get("call_id") or "").strip()
                tool = str(raw.get("tool") or "").strip()
                field_name = str(raw.get("field") or "").strip()
                if not call_id or not tool or not field_name:
                    continue
                self._evidence.append(
                    EvidenceRecord(
                        call_id=call_id,
                        tool=tool,
                        symbol=symbol,
                        source=source,
                        timestamp=timestamp,
                        field=field_name,
                        value=value,
                        status="observed",
                        currency=str(raw.get("currency") or "") or None,
                        venue=str(raw.get("venue") or "") or None,
                        currency_conversion=(str(raw.get("currency_conversion") or "") or None),
                        observed_at=str(raw.get("observed_at") or inherited_at),
                        market_session=(str(raw.get("market_session") or "") or None),
                        adjustment=str(raw.get("adjustment") or "") or None,
                        unit=str(raw.get("unit") or "") or None,
                        inherited_from_attempt_id=attempt_id,
                        inherited_from_run_id=run_id,
                        inherited_at=inherited_at,
                    )
                )
                self._session_symbols.add(symbol)

        if self._identities or self._evidence:
            self._identity_required = True
            self._buffer_output = True

    @property
    def authorized_symbols(self) -> set[str]:
        """Return exact symbols locked before the next tool batch."""
        return {record.symbol for record in self._identities.values() if record.status == "locked" and record.symbol}

    @property
    def identity_status(self) -> str:
        """Return the aggregate first-class identity state.

        ``conflicting`` is the only state that outranks a successful lock: two
        sources contradicting each other about one query is a fact about the
        data, not a gap in it. Every other blocking state means "not known
        yet", and a side query that failed, went unanswered, or returned a
        shortlist must not retract an identity the run did lock — one flaky
        resolver call otherwise poisons every remaining answer in the session,
        with no path back. Per-symbol safety does not depend on this aggregate:
        a consumer still has to match a locked symbol in
        :meth:`_match_authorized_symbol` before it may run.
        """
        records = list(self._identities.values())
        if not records:
            return "unresolved" if self._identity_required else "not_required"
        statuses = {record.status for record in records}
        if "conflicting" in statuses:
            return "conflicting"
        if "locked" in statuses:
            return "locked"
        for blocking in ("ambiguous", "invalidated", "unresolved"):
            if blocking in statuses:
                return blocking
        if "not_found" in statuses:
            return "not_found"
        return "unresolved"

    @property
    def should_buffer_output(self) -> bool:
        """Return whether unverified model prose must be hidden from live sinks."""
        return self._buffer_output or bool(self._evidence)

    @property
    def validation_count(self) -> int:
        """Return the number of final drafts checked so far."""
        return len(self._validations)

    def identity_summary(self) -> dict[str, Any]:
        """Return compact identity state for traces and tool errors."""
        return {
            "status": self.identity_status,
            "authorized_symbols": sorted(self.authorized_symbols),
            "records": [asdict(record) for record in self._identities.values()],
            "recovery": self.recovery_summary(),
        }

    def recovery_summary(self) -> dict[str, Any]:
        """Return bounded-recovery budget state for traces and the artifact."""
        return {
            "rounds": self._recovery_rounds,
            "max_rounds": MAX_GROUNDING_RECOVERY_ROUNDS,
            "symbol_resolution_attempts": self._symbol_resolution_attempts,
            "max_symbol_resolution_attempts": MAX_SYMBOL_RESOLUTION_ATTEMPTS,
            "price_evidence_attempts": self._price_evidence_attempts,
            "max_price_evidence_attempts": MAX_PRICE_EVIDENCE_ATTEMPTS,
        }

    def authorize_tool_call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        batch_authorized_symbols: Iterable[str],
        call_id: str,
        batch_identity_status: str | None = None,
    ) -> ToolAuthorization:
        """Authorize against identity state frozen before the whole LLM batch.

        Args:
            tool_name: Requested tool.
            arguments: Model-supplied arguments.
            batch_authorized_symbols: Snapshot taken before processing any call
                from this assistant response.
            call_id: Provider tool-call identity.
            batch_identity_status: Aggregate identity status from the same
                pre-batch snapshot. Defaults to the current state for direct
                callers outside the Agent loop.

        Returns:
            An allow/block decision. Resolver calls are allowed but their result
            cannot affect another call in this same batch.
        """
        if tool_name == _RESOLVER_TOOL:
            self._identity_required = True
            self._buffer_output = True
            self._begin_resolution(str(arguments.get("query") or ""), call_id)
            return ToolAuthorization(allowed=True)

        if self._is_private_company_skill(tool_name, arguments):
            return self._authorize_private_company_skill()

        if tool_name == "load_skill" and self._identity_required:
            frozen_status = batch_identity_status or self.identity_status
            if frozen_status in _RESOLUTION_INCOMPLETE_STATUSES:
                return ToolAuthorization(
                    allowed=False,
                    error_code="identity_required",
                    message=(
                        "Market-sensitive workflow selection is blocked while instrument "
                        "resolution is in flight or contradicted; a resolver result from "
                        "this same batch cannot be consumed."
                    ),
                )
            return ToolAuthorization(allowed=True)

        symbols = tuple(self._extract_symbol_arguments(arguments))
        if not symbols:
            return ToolAuthorization(allowed=True)

        self._identity_required = True
        self._buffer_output = True
        authorized = {_normalize_symbol(item) for item in batch_authorized_symbols}
        frozen_status = batch_identity_status or self.identity_status
        if frozen_status != "locked" or not authorized:
            return ToolAuthorization(
                allowed=False,
                error_code=(
                    "identity_conflict"
                    if frozen_status in {"ambiguous", "conflicting", "invalidated"}
                    else "identity_required"
                ),
                message=(
                    "A canonical, non-conflicting identity was not locked before this "
                    "assistant tool-call batch started. A resolver result from this same "
                    "batch cannot be consumed."
                ),
                symbols=symbols,
            )

        mismatched = tuple(symbol for symbol in symbols if self._match_authorized_symbol(symbol, authorized) is None)
        if mismatched:
            message = (
                "Consumer symbol/venue differs from the locked resolver identity; "
                "silent suffix or exchange rewrites are forbidden."
            )
            hints = [hint for symbol in mismatched for hint in self._venue_mismatch_hints(symbol, authorized)]
            if hints:
                message += " " + " ".join(hints)
            return ToolAuthorization(
                allowed=False,
                error_code="identity_mismatch",
                message=message,
                symbols=mismatched,
            )
        return ToolAuthorization(allowed=True, symbols=symbols)

    @staticmethod
    def _venue_mismatch_hints(
        requested_symbol: str,
        authorized_symbols: Iterable[str],
    ) -> list[str]:
        """Turn a same-issuer venue mismatch into an actionable resolver hint.

        ``BLDP.US`` against a locked ``BLDP.TO`` is not a typo of one identity;
        it is a second listing of the same company that was never resolved.
        Naming the exact ``search_symbol`` query keeps the model from retrying
        the identical unauthorized call. A bare ticker that collides with
        several locked venues gets a "use the full suffix" hint instead.
        """
        requested = _normalize_symbol(requested_symbol)
        authorized = {_normalize_symbol(item) for item in authorized_symbols}
        if "." in requested:
            base = requested.rsplit(".", 1)[0]
            same_issuer = sorted(item for item in authorized if "." in item and item.rsplit(".", 1)[0] == base)
            if same_issuer:
                return [
                    f"[{requested_symbol} is a second venue of {', '.join(same_issuer)}; "
                    f"call search_symbol('{requested_symbol}') in a separate turn "
                    f"before querying it.]"
                ]
            return []
        matches = sorted(item for item in authorized if "." in item and item.rsplit(".", 1)[0] == requested)
        if len(matches) > 1:
            return [
                f"[{requested_symbol} matches multiple locked identities "
                f"({', '.join(matches)}); use the full venue-suffixed symbol.]"
            ]
        return []

    @staticmethod
    def _match_authorized_symbol(
        requested_symbol: str,
        authorized_symbols: Iterable[str],
    ) -> str | None:
        """Map a consumer argument to one unique locked canonical symbol.

        Both sides are canonicalized first, so a provider alias (``600519.SS``),
        an exchange prefix (``sh600519``), an unpadded Hong Kong code
        (``700.HK``) or a slashed pair (``BTC/USDT``) addresses the instrument
        it names rather than being read as a silent venue rewrite.

        A bare code carries no venue, so it is accepted only when exactly one
        locked identity has it as its base. That uniqueness — not a list of
        which tools are allowed to use one — is what makes a bare ticker safe.
        The list this replaced named nine tools while eleven documented
        argument spellings across the registry were bare or prefixed, so the
        tools' own schema examples were being rejected.

        Args:
            requested_symbol: Model-supplied symbol argument.
            authorized_symbols: Symbols locked before the tool batch.

        Returns:
            The unique canonical identity consumed by the argument, or ``None``.
        """
        requested = _normalize_symbol(requested_symbol)
        authorized = {_normalize_symbol(item) for item in authorized_symbols}
        if requested in authorized:
            return requested
        if "." in requested:
            return None
        matches = [symbol for symbol in authorized if "." in symbol and symbol.rsplit(".", 1)[0] == requested]
        return matches[0] if len(matches) == 1 else None

    def ingest_tool_result(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        result: str,
        call_id: str,
        success: bool,
    ) -> None:
        """Consume the full untruncated tool result and persist its evidence.

        Args:
            tool_name: Executed tool name.
            arguments: Exact normalized tool arguments.
            result: Full raw result, before model-context truncation.
            call_id: Provider tool-call identity.
            success: Result-envelope success classification.
        """
        payload = _json_object(result)
        if not success:
            self._record_tool_failure(tool_name, call_id, result)
            if tool_name == _RESOLVER_TOOL:
                self._finish_failed_resolution(arguments, call_id)
            self.persist()
            return

        self._track_session_symbols(arguments, result)
        if tool_name == _RESOLVER_TOOL:
            self._ingest_resolution(arguments, payload, call_id)
        elif tool_name == "get_market_data":
            self._ingest_market_data(arguments, payload, call_id)
        elif payload is not None:
            self._ingest_generic_numeric(tool_name, arguments, payload, call_id)
        self.persist()

    def validate_final_answer(self, content: str) -> ValidationResult:
        """Validate identity assertions and numeric price claims.

        Args:
            content: Candidate assistant answer.

        Returns:
            A deterministic validation result. A record containing only the
            answer hash and structured issues is appended to the artifact.
        """
        self._ingest_run_dir_ohlc_csvs()
        issues: list[dict[str, Any]] = []
        issues.extend(self._validate_identity(content))
        issues.extend(self._validate_unsourced_symbols(content))
        price_issues, warnings = self._validate_price_claims(content)
        issues.extend(price_issues)
        result = ValidationResult(valid=not issues, issues=issues, warnings=warnings)
        self._validations.append(
            {
                "attempt": len(self._validations) + 1,
                "checked_at": _utc_now(),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "valid": result.valid,
                "issues": issues,
                "warnings": warnings,
            }
        )
        self.persist()
        return result

    def correction_prompt(self, validation: ValidationResult) -> str:
        """Build bounded feedback for one rejected model draft."""
        lines = [
            "[GROUNDING GATE] The previous draft was rejected and was not released to the user.",
            "Correct every issue using the existing structured identity and tool evidence:",
        ]
        for issue in validation.issues[:12]:
            lines.append(f"- {issue.get('message', issue.get('code', 'grounding error'))}")
        # Name the exact values that must be REMOVED, not rephrased. The model
        # tends to restate a rejected figure in a new format; the gate then
        # rejects it again and the run burns iterations until the fallback.
        banned: list[str] = []
        for issue in validation.issues:
            code = issue.get("code")
            value = issue.get("value")
            if (
                code in {"numeric_claim_conflict", "numeric_claim_unavailable", "unsourced_symbol_figures"}
                and value is not None
            ):
                symbol = issue.get("symbol") or ""
                label = f"{value:g}" if isinstance(value, (int, float)) else str(value)
                banned.append(f"{label} ({symbol})" if symbol else label)
        if banned:
            deduped = list(dict.fromkeys(banned))
            lines.append(
                "REMOVE these rejected value(s) entirely - do NOT restate, rephrase, "
                "or recompute them in any other format: " + ", ".join(deduped) + "."
            )
            repeated: list[str] = []
            for prior in self._validations:
                for prior_issue in prior.get("issues", []):
                    prior_value = prior_issue.get("value")
                    if isinstance(prior_value, (int, float)):
                        mark = f"{prior_value:g}"
                        if any(entry.startswith(mark) for entry in deduped):
                            repeated.append(mark)
            if repeated:
                lines.append(
                    "These value(s) have now been rejected repeatedly across drafts: "
                    + ", ".join(dict.fromkeys(repeated))
                    + ". Repeating them in any form keeps failing; drop them, or show "
                    "the full derivation from the observed inputs."
                )
        lines.extend(
            [
                "If a value is a derived or prospective level (stop, target, entry, etc.), "
                "you must EITHER show the full derivation with the observed inputs and the "
                "formula, OR omit it from the draft.",
                "Reuse the exact locked symbol and venue.",
                "Do not attach figures to a symbol no tool call in this session handled; "
                "report it as not retrieved instead.",
            ]
        )
        recovery = self.recovery_action(validation)
        if recovery == _RESOLVER_TOOL:
            lines.extend(
                [
                    "Instrument identity is unresolved. Call `search_symbol` for the "
                    "candidate name in a separate tool-call turn, lock the exact canonical "
                    "symbol and venue it returns, then call `get_market_data` before finalizing.",
                    "Do NOT ask the user to confirm or continue while this read-only recovery remains available.",
                ]
            )
        elif recovery == "get_market_data":
            lines.extend(
                [
                    "Identity is locked but price evidence is missing. Call `get_market_data` "
                    "for the locked canonical symbol and venue in a separate tool-call turn, "
                    "then regenerate and re-validate the final answer.",
                    "Do NOT ask the user to confirm or continue while this read-only recovery remains available.",
                ]
            )
        else:
            lines.append(
                "If evidence is genuinely unavailable or conflicting and recovery is "
                "exhausted, say so and ask for clarification; do not guess."
            )
        return "\n".join(lines)

    def recovery_action(self, validation: ValidationResult) -> str | None:
        """Decide the next safe read-only recovery step for a draft.

        Returns ``search_symbol`` when instrument identity is unresolved and
        resolution attempts remain; ``get_market_data`` when identity is locked
        but a price claim has no observed evidence and fetch attempts remain;
        otherwise ``None`` (genuinely ambiguous, conflicting, or exhausted —
        the loop must then ask the user or fail closed).

        This is the deterministic half of #1081: recoverable missing evidence is
        often obtainable through read-only tools, so a rejected draft should
        drive the original task forward instead of stopping.
        """
        if self._recovery_rounds >= MAX_GROUNDING_RECOVERY_ROUNDS:
            return None
        if self._identity_required and self.identity_status == "unresolved":
            if self._symbol_resolution_attempts < MAX_SYMBOL_RESOLUTION_ATTEMPTS:
                return _RESOLVER_TOOL
            return None
        findings = [*validation.issues, *validation.warnings]
        if self.identity_status == "locked" and any(
            finding.get("code") in {"numeric_claim_unavailable", "unsourced_symbol_figures", "evidence_unavailable"}
            for finding in findings
        ):
            if self._price_evidence_attempts < MAX_PRICE_EVIDENCE_ATTEMPTS:
                return "get_market_data"
        return None

    def record_recovery(self, action: str) -> None:
        """Account one bounded recovery attempt against its budget."""
        self._recovery_rounds += 1
        if action == _RESOLVER_TOOL:
            self._symbol_resolution_attempts += 1
        elif action == "get_market_data":
            self._price_evidence_attempts += 1

    def recovery_prompt(self, action: str, validation: ValidationResult) -> str:
        """Build an executable next-step message for one bounded recovery turn."""
        if action == _RESOLVER_TOOL:
            return (
                "[GROUNDING RECOVERY] Instrument identity is not yet locked and is "
                "recoverable with read-only tools. Call `search_symbol` for the candidate "
                "name in a separate assistant tool-call turn, lock and reuse the exact "
                "canonical symbol and venue it returns, then call `get_market_data`. "
                "Do NOT ask the user to confirm or continue while this read-only recovery "
                "remains available, and do NOT finalize yet."
            )
        if action == "get_market_data":
            return (
                "[GROUNDING RECOVERY] Identity is locked but price evidence is missing. "
                "Call `get_market_data` for the locked canonical symbol and venue in a "
                "separate tool-call turn and use its existing bounded provider fallback, "
                "then regenerate and re-validate the final answer. Do NOT ask the user to "
                "confirm or continue while this read-only recovery remains available, and "
                "do NOT finalize yet."
            )
        return self.correction_prompt(validation)

    def safe_fallback(self) -> str:
        """Return a deterministic fail-closed answer after repeated rejection."""
        is_zh = bool(re.search(r"[\u3400-\u9fff]", self.user_message))
        price_records = self._price_records()
        if price_records:
            by_symbol: dict[str, list[EvidenceRecord]] = {}
            for record in price_records:
                by_symbol.setdefault(record.symbol or "unknown", []).append(record)
            facts = []
            for symbol, records in sorted(by_symbol.items()):
                values = [float(record.value) for record in records if record.value is not None]
                currency = next((record.currency for record in records if record.currency), None)
                sources = sorted({record.source for record in records if record.source})
                source_label = "/".join(sources) if sources else "unknown"
                unit = f" {currency}" if currency else ""
                facts.append(
                    f"{symbol}: {min(values):g}–{max(values):g}{unit} "
                    f"(source: {source_label}; currency conversion: none)"
                )
            joined = "；".join(facts) if is_zh else "; ".join(facts)
            if is_zh:
                return (
                    "为避免输出与工具证据冲突的价格，我已拒绝上一版答案。"
                    f"当前可验证的已观测 OHLC 范围是：{joined}。"
                    "在重新核对标的或明确展示推导公式前，我不会生成买入价。"
                )
            return (
                "I rejected the previous draft because its prices conflicted with tool evidence. "
                f"The verified observed OHLC range is: {joined}. "
                "I will not invent an entry price without a visible derivation or refreshed evidence."
            )
        # No observed price evidence: distinguish "identity unresolved" from
        # "the draft cited prices this session never observed". Reporting the
        # identity message for the latter is misleading (the run may not even
        # have touched the market tools).
        issue_codes = {
            code
            for validation in self._validations
            for code in (issue.get("code") for issue in validation.get("issues", []))
        }
        if issue_codes & {"numeric_claim_unavailable", "numeric_claim_conflict", "unsourced_symbol_figures"}:
            if is_zh:
                return (
                    "我的回答被安全门槛拒绝:草稿引用了本会话未通过工具获取的价格数字,无法核验。"
                    "请重新发起任务,让模型先调用行情工具获取数据,或要求它去掉这些价格引用后重试。"
                )
            return (
                "My previous answer was rejected by the verification gate: it cited price "
                "figures that this session never obtained through a tool, so they could not "
                "be verified. Re-run the task and let the agent fetch the market data first, "
                "or ask it to answer without the unverified prices."
            )
        if is_zh:
            return "当前无法安全确认标的身份或价格证据，因此没有生成交易结论。请确认候选证券代码和交易所后再继续。"
        return (
            "I could not safely lock the instrument identity or price evidence, so I did not "
            "produce a trading conclusion. Please confirm the candidate symbol and venue."
        )

    def persist(self) -> None:
        """Atomically persist the current structured ledger."""
        artifact_dir = self.run_dir / "artifacts"
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = artifact_dir / GROUNDING_ARTIFACT
            temp = path.with_suffix(path.suffix + ".tmp")
            payload = {
                "schema_version": 1,
                "updated_at": _utc_now(),
                "identity": self.identity_summary(),
                "session_symbols": sorted(self._session_symbols),
                "session_symbol_roots": sorted(self._session_symbol_roots),
                "evidence": [asdict(record) for record in self._evidence],
                "tool_failures": list(self._tool_failures),
                "validations": list(self._validations),
            }
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)
        except OSError:
            # Grounding decisions remain in memory; a read-only/broken artifact
            # directory must not crash the agent's error path.
            return

    def _seed_symbols(self, text: str, *, source: str) -> None:
        """Lock exact symbols explicitly supplied by a user."""
        for match in _CANONICAL_SYMBOL_RE.finditer(text or ""):
            symbol = _normalize_symbol(match.group(0))
            key = f"explicit:{symbol}"
            existing = self._identities.get(key)
            version = existing.version + 1 if existing else 1
            self._identities[key] = IdentityRecord(
                query=symbol,
                status="locked",
                symbol=symbol,
                venue=_infer_venue(symbol),
                instrument_type=_infer_instrument_type(symbol),
                currency=_infer_currency(symbol),
                source_tool_call_id=source,
                source=[source],
                version=version,
            )
            self._identity_required = True
            self._buffer_output = True

    def _begin_resolution(self, query: str, call_id: str) -> None:
        """Enter unresolved state before the resolver executes."""
        key = _query_key(query) or f"call:{call_id}"
        existing = self._identities.get(key)
        self._identities[key] = IdentityRecord(
            query=query,
            status="unresolved",
            source_tool_call_id=call_id,
            version=(existing.version + 1) if existing else 1,
        )
        self.persist()

    def _finish_failed_resolution(
        self,
        arguments: Mapping[str, Any],
        call_id: str,
    ) -> None:
        """Mark transport/business failure as invalidated, never not-found."""
        query = str(arguments.get("query") or "")
        key = _query_key(query) or f"call:{call_id}"
        existing = self._identities.get(key)
        self._identities[key] = IdentityRecord(
            query=query,
            status="invalidated",
            source_tool_call_id=call_id,
            version=(existing.version + 1) if existing else 1,
        )

    def _ingest_resolution(
        self,
        arguments: Mapping[str, Any],
        payload: dict[str, Any] | None,
        call_id: str,
    ) -> None:
        """Advance unresolved identity from a structured resolver result."""
        data = payload.get("data") if isinstance(payload, dict) else None
        data = data if isinstance(data, dict) else {}
        query = str(data.get("query") or arguments.get("query") or "")
        key = _query_key(query) or f"call:{call_id}"
        existing = self._identities.get(key)
        version = (existing.version + 1) if existing else 1

        if not isinstance(payload, dict) or payload.get("ok") is False:
            self._identities[key] = IdentityRecord(
                query=query,
                status="invalidated",
                source_tool_call_id=call_id,
                version=version,
            )
            return

        raw_candidates = data.get("candidates")
        candidates = (
            [dict(item) for item in raw_candidates if isinstance(item, dict)]
            if isinstance(raw_candidates, list)
            else []
        )
        sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
        if not candidates:
            # "This entity does not exist" may only be concluded when every
            # source that could answer did answer. Counting two clean sources
            # instead was unreachable for a Chinese query — Yahoo cannot serve
            # one at all — so an entity that simply is not listed came back as
            # ``invalidated``, which blocks the run rather than answering it.
            # A source that skipped an unsupported query shape is not an outage.
            clean_sources = [str(name) for name, value in sources.items() if str(value).casefold() == "ok"]
            failed_sources = [
                str(name)
                for name, value in sources.items()
                if str(value).casefold() != "ok" and not str(value).casefold().startswith("skipped")
            ]
            self._identities[key] = IdentityRecord(
                query=query,
                status="not_found" if clean_sources and not failed_sources else "invalidated",
                source_tool_call_id=call_id,
                source=clean_sources,
                candidates=[],
                version=version,
            )
            return

        chosen = self._choose_candidate(query, candidates)
        if chosen is None:
            self._identities[key] = IdentityRecord(
                query=query,
                status="ambiguous",
                source_tool_call_id=call_id,
                candidates=candidates,
                version=version,
            )
            return

        symbol = _normalize_symbol(chosen.get("symbol"))
        if not symbol:
            self._identities[key] = IdentityRecord(
                query=query,
                status="invalidated",
                source_tool_call_id=call_id,
                candidates=candidates,
                version=version,
            )
            return

        # A query that already spells a canonical symbol is asserting one, so a
        # resolver answering with a different instrument contradicts it rather
        # than refining it. This generalizes the ``.SS``/``.SH`` alias check it
        # replaces: that one fired on one exchange's two spellings and stayed
        # silent on an actual cross-exchange swap, which is the case that
        # matters.
        asserted = _scan_symbols(query)
        if asserted and symbol not in asserted:
            conflicting = list(candidates)
            conflicting.extend({"symbol": item, "source": ["query"]} for item in sorted(asserted))
            self._identities[key] = IdentityRecord(
                query=query,
                status="conflicting",
                source_tool_call_id=call_id,
                candidates=conflicting,
                version=version,
            )
            return

        if existing and existing.status == "locked" and existing.symbol != symbol:
            conflicting = list(candidates)
            conflicting.insert(0, {"symbol": existing.symbol, "source": existing.source})
            self._identities[key] = IdentityRecord(
                query=query,
                status="conflicting",
                source_tool_call_id=call_id,
                candidates=conflicting,
                version=version,
            )
            return

        source_names = []
        for value in [chosen.get("source"), *(chosen.get("also_from") or [])]:
            name = str(value or "").strip()
            if name and name not in source_names:
                source_names.append(name)
        venue = str(chosen.get("exchange") or chosen.get("market") or "").strip() or _infer_venue(symbol)
        self._identities[key] = IdentityRecord(
            query=query,
            status="locked",
            symbol=symbol,
            venue=venue,
            instrument_type=_infer_instrument_type(symbol, chosen.get("type")),
            currency=_infer_currency(symbol),
            source_tool_call_id=call_id,
            source=source_names,
            candidates=candidates,
            version=version,
        )
        self._supersede_shortlists(symbol)

    def _supersede_shortlists(self, symbol: str) -> None:
        """Retire ambiguous shortlists that this lock has just answered.

        A screening query resolves to many candidates by design. Once one of
        them is locked by a later, narrower resolution, the earlier shortlist is
        answered rather than unresolved — leaving it ``ambiguous`` blocks every
        final answer in the run for the rest of the session (#955).

        Args:
            symbol: Canonical symbol locked by the current resolution.
        """
        for key, record in self._identities.items():
            if record.status != "ambiguous":
                continue
            offered = {_normalize_symbol(candidate.get("symbol")) for candidate in record.candidates}
            if symbol in offered:
                self._identities[key] = replace(record, status="superseded", updated_at=_utc_now())

    @staticmethod
    def _choose_candidate(
        query: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Choose only a unique or strongly corroborated resolver candidate.

        Candidates are collapsed onto their canonical symbol first. Two rows
        that differ only by a provider's suffix convention describe one listing,
        and counting them as rival candidates is what left every Shanghai query
        with two "exact" matches and therefore no choice at all.
        """
        by_symbol: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            by_symbol.setdefault(_normalize_symbol(candidate.get("symbol")), candidate)
        candidates = list(by_symbol.values())
        if len(candidates) == 1:
            return candidates[0]
        normalized_query = re.sub(r"[^a-z0-9\u3400-\u9fff]", "", query.casefold())
        exact: list[dict[str, Any]] = []
        strong: list[dict[str, Any]] = []
        for candidate in candidates:
            symbol = _normalize_symbol(candidate.get("symbol"))
            base = symbol.split(".", 1)[0].split("-", 1)[0].split("/", 1)[0]
            name = str(candidate.get("name") or "")
            comparable = {
                re.sub(r"[^a-z0-9\u3400-\u9fff]", "", base.casefold()),
                re.sub(r"[^a-z0-9\u3400-\u9fff]", "", name.casefold()),
                re.sub(r"[^a-z0-9\u3400-\u9fff]", "", symbol.casefold()),
            }
            if normalized_query and normalized_query in comparable:
                exact.append(candidate)
            if candidate.get("also_from") or candidate.get("cik"):
                strong.append(candidate)
        if len(exact) == 1:
            return exact[0]
        if len(strong) == 1:
            return strong[0]
        return None

    def _authorize_private_company_skill(self) -> ToolAuthorization:
        """Keep private-company routing symmetric with locked listing evidence."""
        locked_listings = [
            record
            for record in self._identities.values()
            if record.status == "locked" and record.instrument_type in {"listed_security", "fund"}
        ]
        if locked_listings:
            return ToolAuthorization(
                allowed=False,
                error_code="identity_conflict",
                message=(
                    "A resolver has locked this entity to a listed security. Model memory "
                    "cannot replace that evidence with a private-company workflow."
                ),
                symbols=tuple(record.symbol for record in locked_listings if record.symbol),
            )
        if self.identity_status == "not_found" or not self._identity_required:
            return ToolAuthorization(allowed=True)
        return ToolAuthorization(
            allowed=False,
            error_code="identity_required",
            message=(
                "Private-company routing requires a completed resolver result with clean "
                "not_found status; current identity is unresolved, ambiguous, or invalidated."
            ),
        )

    @staticmethod
    def _is_private_company_skill(
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> bool:
        """Return whether this call selects a private-company skill."""
        if tool_name != "load_skill":
            return False
        name = str(arguments.get("name") or "").strip().casefold()
        return name in _PRIVATE_COMPANY_SKILL_NAMES or ("private" in name and "company" in name)

    @staticmethod
    def _extract_symbol_arguments(arguments: Mapping[str, Any]) -> list[str]:
        """Extract model-selected identities from well-known argument keys."""
        symbols: list[str] = []
        for key, value in arguments.items():
            if str(key).casefold() not in _SYMBOL_ARGUMENT_KEYS:
                continue
            values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
            for item in values:
                if not isinstance(item, (str, int)):
                    continue
                symbol = _normalize_symbol(item)
                if symbol and symbol not in symbols:
                    symbols.append(symbol)
        return symbols

    def _track_session_symbols(
        self,
        arguments: Mapping[str, Any],
        result: str,
    ) -> None:
        """Widen the run's instrument surface from one succeeding tool call.

        Both sides of a successful call count. The result is the strong signal —
        a resolver shortlist, an OHLC panel, a filing index. The arguments are
        the weaker one, but a symbol the model handed to a tool that then
        succeeded has at least been exercised against a real system, whereas a
        symbol that surfaces for the first time in the final prose has been
        exercised against nothing. Failed calls are deliberately excluded, so a
        blocked or erroring call never launders an invented ticker.

        Bare symbol arguments are tracked separately as roots. Many tools take a
        bare ticker by contract, so a run that legitimately fetched ``AAPL``
        never writes ``AAPL.US`` into any argument or result. Without the root,
        the canonical spelling used in the answer would be rejected as an
        unhandled instrument.

        Args:
            arguments: Exact normalized tool arguments.
            result: Full raw result, before model-context truncation.
        """
        if len(self._session_symbols) >= _MAX_TRACKED_SYMBOLS:
            return
        try:
            rendered_arguments = json.dumps(arguments, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            rendered_arguments = ""
        found = _scan_symbols(rendered_arguments) | _scan_symbols(result)
        room = _MAX_TRACKED_SYMBOLS - len(self._session_symbols)
        self._session_symbols.update(sorted(found)[:room])
        self._session_symbol_roots.update(
            symbol for symbol in self._extract_symbol_arguments(arguments) if "." not in symbol
        )

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
        observed_at = _utc_now()
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
                if isinstance(symbol_provenance, dict) and symbol_provenance.get("currency_conversion")
                else None
            )
            market_session = (
                str(symbol_provenance.get("market_session"))
                if isinstance(symbol_provenance, dict) and symbol_provenance.get("market_session")
                else None
            )
            adjustment = (
                str(symbol_provenance.get("adjustment") or symbol_provenance.get("adjust"))
                if isinstance(symbol_provenance, dict)
                and (symbol_provenance.get("adjustment") or symbol_provenance.get("adjust"))
                else None
            )
            price_unit = (
                str(symbol_provenance.get("price_unit"))
                if isinstance(symbol_provenance, dict) and symbol_provenance.get("price_unit")
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
                            observed_at=observed_at,
                            market_session=(
                                str(row.get("market_session")) if row.get("market_session") else market_session
                            ),
                            adjustment=adjustment,
                            unit=price_unit,
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
            symbol = self._match_authorized_symbol(symbol, self.authorized_symbols) or symbol
        source = str(payload.get("source") or tool_name)
        timestamp = next(
            (str(payload[key]) for key in _TIMESTAMP_FIELDS if payload.get(key) is not None),
            None,
        )
        observed_at = _utc_now()
        market_session = str(payload.get("market_session") or "") or None
        adjustment = str(payload.get("adjustment") or payload.get("adjust") or "") or None
        unit = str(payload.get("price_unit") or "") or None
        remaining = _MAX_GENERIC_EVIDENCE

        def visit(value: Any, path: str) -> None:
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
                        observed_at=observed_at,
                        market_session=market_session,
                        adjustment=adjustment,
                        unit=unit,
                    )
                )
                remaining -= 1
                return
            if isinstance(value, dict):
                for key, item in value.items():
                    visit(item, f"{path}.{key}" if path else str(key))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, f"{path}[{index}]")

        visit(payload, "")

    def _ingest_run_dir_ohlc_csvs(self) -> None:
        """Register OHLC rows from CSVs the run wrote via the bash workaround.

        The bash+yfinance escape hatch writes per-symbol OHLC CSVs into the run
        directory (e.g. ``data/raw/BYN_V.csv``) instead of returning them through
        ``get_market_data``. Those prices were genuinely observed tool output,
        but they never entered the ledger, so the final-answer gate rejected
        every one of them as ``numeric_claim_unavailable``. Scan the run dir for
        such CSVs and register their open/high/low/close/price rows as observed
        evidence, keyed to the symbol derived from the filename.

        Only files whose filename maps to a symbol already tracked in this run
        are accepted, so a stray CSV cannot mint new identity. Rows are bounded
        by ``_MAX_GENERIC_EVIDENCE`` and each file is ingested at most once.
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
                        if str(key).strip().casefold() in _CSV_DATE_COLUMNS and row[key] not in (None, "")
                    ),
                    None,
                )
                for key, value in row.items():
                    field_name = _CSV_PRICE_COLUMNS.get(str(key).strip().casefold().replace(" ", "_"))
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

    def _validate_identity(self, content: str) -> list[dict[str, Any]]:
        """Validate aggregate state and listed/private contradictions."""
        issues: list[dict[str, Any]] = []
        status = self.identity_status
        # Two conditions, both load-bearing.
        #
        # ``self._identities`` — a run that never named an instrument has no
        # identity to get wrong. The trigger phrase is matched against the user
        # message, so "什么是市盈率估值法？" set identity_required and then failed
        # every draft it could ever produce, including the honest answer. This
        # relaxation invents no licence to guess: a figure still has to survive
        # ``_validate_price_claims``, and a figure attached to a symbol no tool
        # handled still has to survive ``_validate_unsourced_symbols``.
        #
        # ``ambiguous`` is deliberately absent. A shortlist is an answer, which
        # is why ``_RESOLUTION_INCOMPLETE_STATUSES`` already lets workflow
        # selection proceed on it (#955) — but the final answer stayed blocked,
        # so a screening run loaded its skill and was then refused a conclusion.
        # Consumers remain blocked on ambiguous in ``authorize_tool_call``, so
        # such a run still cannot fetch a quote to misattribute.
        if self._identity_required and self._identities and status in {"unresolved", "conflicting", "invalidated"}:
            issues.append(
                {
                    "code": "identity_not_locked",
                    "status": status,
                    "message": f"Instrument identity is {status}; a final market conclusion requires locked identity.",
                }
            )
        listed = [
            record
            for record in self._identities.values()
            if record.status == "locked" and record.instrument_type in {"listed_security", "fund"}
        ]
        if listed and _PRIVATE_ASSERTION_RE.search(content):
            symbols = sorted(record.symbol for record in listed if record.symbol)
            issues.append(
                {
                    "code": "listed_identity_relabelled_private",
                    "symbols": symbols,
                    "message": (
                        f"Locked listed identity {', '.join(symbols)} was relabelled as private/unlisted "
                        "without a conflicting resolver result."
                    ),
                }
            )
        return issues

    def _validate_unsourced_symbols(self, content: str) -> list[dict[str, Any]]:
        """Reject explicit price claims for an instrument no tool handled.

        Counts, dates and other arbitrary figures do not establish a price
        assertion.  Reusing the same positive parser as the numeric validator
        keeps this gate mechanically decidable without a second exclusion list.

        Args:
            content: Candidate assistant answer.

        Returns:
            One issue per distinct unsourced symbol carrying figures.
        """
        issues: list[dict[str, Any]] = []
        reported: set[str] = set()
        for claim in extract_prose_price_claims(content):
            unknown = sorted(
                symbol for symbol in _scan_symbols(claim.text) - reported if not self._symbol_was_sourced(symbol)
            )
            for symbol in unknown:
                reported.add(symbol)
                issues.append(
                    {
                        "code": "unsourced_symbol_figures",
                        "symbol": symbol,
                        "value": claim.value,
                        "field": claim.field,
                        "claim": claim.text[:200],
                        "message": (
                            f"No tool call in this session passed in or returned {symbol}, "
                            "yet the answer makes an explicit price claim for it. Retrieve "
                            "it, or report it as not retrieved."
                        ),
                    }
                )
        return issues

    def _symbol_was_sourced(self, symbol: str) -> bool:
        """Return whether this run was entitled to make claims for ``symbol``."""
        normalized = _normalize_symbol(symbol)
        return normalized in self._session_symbols or normalized.rsplit(".", 1)[0] in self._session_symbol_roots

    def _validate_price_claims(
        self,
        content: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Check only positively identified observed-price claims."""
        issues, warnings, _table_lines = self._validate_price_tables(content)
        records = self._comparable_price_records()
        document_symbol = self._symbol_for_claim(content, records)
        for claim in extract_prose_price_claims(content):
            symbol = self._symbol_for_claim(claim.text, records) or document_symbol
            issue, warning = self._compare_price_claim(
                claim=claim,
                records=records,
                symbol=symbol,
            )
            if issue:
                issues.append(issue)
            if warning:
                warnings.append(warning)
        return self._dedupe_issues(issues), self._dedupe_issues(warnings)

    @staticmethod
    def _symbol_for_claim(
        content: str,
        records: Sequence[EvidenceRecord],
    ) -> str | None:
        """Return one canonical evidence symbol explicitly named in a claim."""
        known = {record.symbol for record in records if record.symbol}
        matches = {
            _normalize_symbol(match.group(0))
            for match in _CANONICAL_SYMBOL_RE.finditer(content)
            if _normalize_symbol(match.group(0)) in known
        }
        return next(iter(matches)) if len(matches) == 1 else None

    def _validate_price_tables(
        self,
        content: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[int]]:
        """Validate field/date-specific claims in Markdown OHLC tables."""
        lines = content.splitlines()
        issues: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        consumed: set[int] = set()
        index = 0
        records = self._comparable_price_records()
        while index + 1 < len(lines):
            header = self._table_cells(lines[index])
            separator = self._table_cells(lines[index + 1])
            if not header or not separator or len(header) != len(separator):
                index += 1
                continue
            if not all(_TABLE_SEPARATOR_RE.match(cell.replace(" ", "")) for cell in separator):
                index += 1
                continue
            field_columns = {
                position: _TABLE_FIELD_ALIASES[cell.strip().casefold()]
                for position, cell in enumerate(header)
                if cell.strip().casefold() in _TABLE_FIELD_ALIASES
            }
            if not field_columns:
                index += 1
                continue
            date_column = next(
                (position for position, cell in enumerate(header) if cell.strip().casefold() in _DATE_HEADERS),
                None,
            )
            symbol_column = next(
                (position for position, cell in enumerate(header) if cell.strip().casefold() in _SYMBOL_HEADERS),
                None,
            )
            consumed.update({index, index + 1})
            row_index = index + 2
            while row_index < len(lines):
                row = self._table_cells(lines[row_index])
                if not row or len(row) != len(header):
                    break
                consumed.add(row_index)
                date_value = row[date_column].strip() if date_column is not None else None
                symbol = _normalize_symbol(row[symbol_column]) if symbol_column is not None else None
                for position, field_name in field_columns.items():
                    parsed = parse_numeric_cell(row[position])
                    if parsed is None:
                        continue
                    value, currency, unit = parsed
                    if symbol and not self._symbol_was_sourced(symbol):
                        issues.append(
                            {
                                "code": "unsourced_symbol_figures",
                                "symbol": symbol,
                                "value": value,
                                "field": field_name,
                                "claim": row[position].strip(),
                                "message": (
                                    f"No successful tool call in this session handled {symbol}, "
                                    "yet the answer makes an explicit table price claim for it."
                                ),
                            }
                        )
                        continue
                    issue, warning = self._compare_price_claim(
                        claim=NumericClaim(
                            value=value,
                            field=field_name,
                            text=row[position].strip(),
                            date=date_value,
                            currency=currency,
                            unit=unit,
                            temporal_scope="dated" if date_value else "latest",
                        ),
                        records=records,
                        symbol=symbol,
                    )
                    if issue:
                        issues.append(issue)
                    if warning:
                        warnings.append(warning)
                row_index += 1
            index = max(row_index, index + 1)
        return issues, warnings, consumed

    @staticmethod
    def _table_cells(line: str) -> list[str]:
        """Split one Markdown table row, or return an empty list."""
        if "|" not in line:
            return []
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [cell.strip() for cell in stripped.split("|")]

    def _compare_price_claim(
        self,
        *,
        claim: NumericClaim,
        records: list[EvidenceRecord],
        symbol: str | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Compare one explicit claim only when its evidence is comparable.

        A contradiction is blocking only when the ledger has one semantic
        observation cohort (same instrument, field, trading day, session,
        adjustment, currency and unit) and the sources in that cohort agree.
        Missing attribution, mixed cohorts and disagreeing providers are data
        quality facts, so they are returned as auditable warnings instead of
        suppressing the whole answer.
        """
        if not records:
            return {
                "code": "numeric_claim_unavailable",
                "claim": claim.text,
                "value": claim.value,
                "symbol": symbol,
                "field": claim.field,
                "date": claim.date,
                "message": "No observed tool evidence was available for this price claim.",
            }, None

        candidates = [record for record in records if record.field == claim.field]
        if symbol:
            normalized_symbol = _normalize_symbol(symbol)
            candidates = [
                record
                for record in candidates
                if record.symbol and _normalize_symbol(record.symbol) == normalized_symbol
            ]
            symbol = normalized_symbol
        symbols = sorted({record.symbol for record in candidates if record.symbol})
        if not symbol and len(symbols) == 1:
            symbol = symbols[0]
        elif not symbol and len(symbols) > 1:
            return None, {
                "code": "evidence_not_comparable",
                "reason": "ambiguous_symbol",
                "claim": claim.text,
                "value": claim.value,
                "field": claim.field,
                "symbols": symbols,
                "message": "Price claim could not be attributed to exactly one instrument.",
            }

        if claim.date:
            candidates = [
                record
                for record in candidates
                if record.timestamp and _timestamp_matches_claim_date(record.timestamp, claim.date)
            ]
        else:
            observed_days = [day for record in candidates if (day := _observation_day(record.timestamp)) is not None]
            if observed_days:
                latest_day = max(observed_days)
                candidates = [record for record in candidates if _observation_day(record.timestamp) == latest_day]

        if not candidates:
            return None, {
                "code": "evidence_unavailable",
                "claim": claim.text,
                "value": claim.value,
                "symbol": symbol,
                "field": claim.field,
                "date": claim.date,
                "message": "No matching observed evidence was available for this price claim.",
            }

        known_currencies = sorted({record.currency.upper() for record in candidates if record.currency})
        if claim.currency:
            if known_currencies and claim.currency not in known_currencies:
                return {
                    "code": "explicit_currency_conflict",
                    "claim": claim.text,
                    "value": claim.value,
                    "symbol": symbol,
                    "currency": claim.currency,
                    "observed_currencies": known_currencies,
                    "message": (
                        f"Price claim declares {claim.currency}, but matching evidence "
                        f"uses {', '.join(known_currencies)}."
                    ),
                }, None
            candidates = [
                record for record in candidates if not record.currency or record.currency.upper() == claim.currency
            ]

        if claim.unit:
            known_units = {record.unit.casefold() for record in candidates if record.unit}
            if known_units and claim.unit.casefold() not in known_units:
                return None, {
                    "code": "evidence_not_comparable",
                    "reason": "unit_mismatch",
                    "claim": claim.text,
                    "value": claim.value,
                    "unit": claim.unit,
                    "observed_units": sorted(known_units),
                    "message": "Claim and evidence use different units.",
                }
            candidates = [
                record for record in candidates if not record.unit or record.unit.casefold() == claim.unit.casefold()
            ]

        cohorts: dict[tuple[str, str, str, str, str], list[EvidenceRecord]] = {}
        for record in candidates:
            cohorts.setdefault(_observation_cohort(record), []).append(record)
        if len(cohorts) != 1:
            return None, {
                "code": "evidence_not_comparable",
                "reason": "mixed_observation_cohorts",
                "claim": claim.text,
                "value": claim.value,
                "symbol": symbol,
                "field": claim.field,
                "cohorts": [list(cohort) for cohort in sorted(cohorts)],
                "message": "Matching sources use different observation semantics.",
            }

        comparable = next(iter(cohorts.values()))
        observed = [float(record.value) for record in comparable if record.value is not None]
        tolerance = _price_tolerance(observed)
        if max(observed) - min(observed) > tolerance:
            return None, {
                "code": "source_divergence",
                "claim": claim.text,
                "value": claim.value,
                "symbol": symbol,
                "field": claim.field,
                "observed_min": min(observed),
                "observed_max": max(observed),
                "source_tool_call_ids": sorted({record.call_id for record in comparable}),
                "message": "Comparable sources disagree beyond the configured tolerance.",
            }
        if any(abs(claim.value - value) <= tolerance for value in observed):
            return None, None
        return {
            "code": "numeric_claim_conflict",
            "claim": claim.text,
            "value": claim.value,
            "symbol": symbol,
            "field": claim.field,
            "date": claim.date,
            "observed_min": min(observed),
            "observed_max": max(observed),
            "source_tool_call_ids": sorted({record.call_id for record in comparable}),
            "message": (
                f"Price claim {claim.value:g} conflicts with observed {claim.field} "
                f"evidence {min(observed):g}–{max(observed):g}."
            ),
        }, None

    def _price_records(self) -> list[EvidenceRecord]:
        """Return observed OHLC/price evidence only."""
        return [
            record
            for record in self._evidence
            if record.status == "observed" and record.field in _PRICE_FIELDS and record.value is not None
        ]

    def _comparable_price_records(self) -> list[EvidenceRecord]:
        """Return every observed quote a numeric claim may be checked against.

        ``_price_records`` only sees fields already named ``open``/``close``/…,
        which in practice means ``get_market_data``. Quotes returned by the
        other market-sensitive tools are re-keyed onto the same canonical field
        so the contradiction check compares like with like instead of reporting
        the claim as unevidenced.

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
                continue
            records.append(replace(record, field=field_name))
        return records

    @staticmethod
    def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicate validator findings while preserving order."""
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for issue in issues:
            key = json.dumps(issue, sort_keys=True, ensure_ascii=False, default=str)
            if key in seen:
                continue
            seen.add(key)
            unique.append(issue)
        return unique


__all__ = [
    "GROUNDING_ARTIFACT",
    "GroundingLedger",
    "IdentityRecord",
    "ToolAuthorization",
    "ValidationResult",
]
