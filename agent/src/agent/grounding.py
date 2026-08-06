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

import ast
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


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
_BARE_US_TICKER_TOOLS = {
    "cancel_equity_order",
    "get_equity_quotes",
    "get_options_chain",
    "get_sec_filings",
    "get_stock_profile",
    "place_equity_order",
    "trading_cancel_order",
    "trading_place_order",
    "trading_quote",
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
_PRICE_FIELDS = {"open", "high", "low", "close", "adj_close", "price"}
_TIMESTAMP_FIELDS = ("trade_date", "date", "datetime", "timestamp", "time", "index")
_MAX_GENERIC_EVIDENCE = 2_000
_MAX_TRACKED_SYMBOLS = 5_000

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
    r"[A-Z][A-Z0-9&.-]{0,19}\.(?:US|NS|BO|FX)|"
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
_PRICE_CONTEXT_RE = re.compile(
    r"(?:\b(?:opening|open|high|low|closing|close|price|quote)\b|"
    r"\b(?:entry|buy|target|support|resistance)\s+(?:price|level)\b|"
    r"开盘价?|最高价?|最低价?|收盘价?|买入价|入场价|目标价|支撑位?|阻力位?|"
    r"现价|报价|价格|价位)",
    re.IGNORECASE,
)
_DERIVATION_RE = re.compile(
    r"(?:\bderived\b|\bcalculated\b|\bformula\b|\bbased on\b|计算|推导|公式|基于)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?![A-Za-z0-9_])"
)
_DATE_RE = re.compile(r"\b(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")
# Localized calendar text carries digits that the ISO pattern above leaves
# behind: "8 月 3 日" otherwise contributes 8 and 3 as candidate prices.
_LOCALIZED_DATE_RE = re.compile(
    r"(?:(?:19|20)\d{2}\s*年\s*)?\d{1,2}\s*月(?:\s*\d{1,2}\s*[日号])?|(?:19|20)\d{2}\s*年"
)
# An aggregate amount is not a quoted price. "100 股成本 820 CNY" states a
# position cost; comparing 820 against a per-share OHLC range is a category
# error. The tradeoff is that a per-share figure written only as "成本 8.20"
# goes unchecked — provenance still requires symbol, source, and currency.
_AGGREGATE_AMOUNT_RE = re.compile(
    r"(?:成本|总额|总价|总市值|市值|合计|金额|cost|total|notional|market value)"
    r"\s*(?:为|是|约)?\s*[:：]?\s*[-+]?\d[\d,]*(?:\.\d+)?",
    re.IGNORECASE,
)
# Quantities, horizons, and lot sizes are unit-bearing: "100 股", "1–4 周",
# "3 个月". None of them are prices.
_QUANTITY_WITH_UNIT_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?(?:\s*[-–—~至]\s*\d[\d,]*(?:\.\d+)?)?\s*"
    r"(?:股|手|张|份|口|笔|倍|个月|周|天|日|年|次|"
    r"shares?|contracts?|lots?|units?|weeks?|months?|days?|years?)",
    re.IGNORECASE,
)
# Full-width brackets and enumeration commas delimit prose clauses. ASCII
# parentheses are deliberately not separators: an explicit derivation such as
# "(8.5 - 7.9) / 2" must stay in one segment for the formula check.
_CLAUSE_SEPARATOR_RE = re.compile(r"[,，;；。、\n（）【】]")
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


def _normalize_symbol(value: Any) -> str:
    """Normalize a symbol for exact identity comparison."""
    return str(value or "").strip().upper()


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
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


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
    return {
        _normalize_symbol(match.group(0))
        for match in _CANONICAL_SYMBOL_RE.finditer(text or "")
    }


def _infer_venue(symbol: str) -> str | None:
    """Infer a coarse venue from a project symbol."""
    upper = _normalize_symbol(symbol)
    suffixes = {
        ".US": "us",
        ".SH": "shanghai",
        ".SS": "shanghai",
        ".SZ": "shenzhen",
        ".BJ": "beijing",
        ".HK": "hong_kong",
        ".KS": "kospi",
        ".KQ": "kosdaq",
        ".NS": "nse",
        ".BO": "bse",
        ".FX": "forex",
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
        ".SS": "CNY",
        ".SZ": "CNY",
        ".BJ": "CNY",
        ".HK": "HKD",
        ".KS": "KRW",
        ".KQ": "KRW",
        ".NS": "INR",
        ".BO": "INR",
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


def _is_exchange_alias_conflict(left: str, right: str) -> bool:
    """Return whether two symbols silently switch Shanghai suffix conventions."""
    left_symbol = _normalize_symbol(left)
    right_symbol = _normalize_symbol(right)
    if left_symbol == right_symbol:
        return False
    left_base, _, left_suffix = left_symbol.rpartition(".")
    right_base, _, right_suffix = right_symbol.rpartition(".")
    return (
        bool(left_base)
        and left_base == right_base
        and {left_suffix, right_suffix} == {"SH", "SS"}
    )


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
                    "its result, then reuse the exact locked symbol and venue."
                ),
            },
            ensure_ascii=False,
        )


@dataclass(frozen=True)
class ValidationResult:
    """Final-answer grounding decision."""

    valid: bool
    issues: list[dict[str, Any]] = field(default_factory=list)


class GroundingLedger:
    """Run-scoped identity state machine and evidence ledger."""

    def __init__(
        self,
        *,
        run_dir: Path,
        user_message: str,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Create a ledger and seed only authoritative prior identities.

        Args:
            run_dir: Active run directory.
            user_message: Current user request.
            history: Optional prior message history. It remains available to
                the model, but is deliberately not an authorization source for
                this run: stale identities from an earlier user subject must
                not unlock a new subject's tools.
        """
        self.run_dir = Path(run_dir)
        self.user_message = user_message
        self._identities: dict[str, IdentityRecord] = {}
        self._evidence: list[EvidenceRecord] = []
        self._tool_failures: list[dict[str, Any]] = []
        self._validations: list[dict[str, Any]] = []
        self._identity_required = bool(_ACTIONABLE_MARKET_RE.search(user_message))
        self._buffer_output = self._identity_required
        # Every instrument this run is entitled to write about: the ones the
        # user named, plus the ones a succeeding tool call passed in or returned.
        self._session_symbols: set[str] = _scan_symbols(user_message)
        # Bare tickers a succeeding call passed in, e.g. "AAPL" for the nine
        # tools whose contract is a bare US ticker. "AAPL.US" in the answer then
        # names an instrument the run really handled.
        self._session_symbol_roots: set[str] = set()

        self._seed_symbols(user_message, source="user_message")
        self.persist()

    @property
    def authorized_symbols(self) -> set[str]:
        """Return exact symbols locked before the next tool batch."""
        return {
            record.symbol
            for record in self._identities.values()
            if record.status == "locked" and record.symbol
        }

    @property
    def identity_status(self) -> str:
        """Return the aggregate first-class identity state."""
        records = list(self._identities.values())
        if not records:
            return "unresolved" if self._identity_required else "not_required"
        statuses = {record.status for record in records}
        for blocking in ("conflicting", "ambiguous", "invalidated", "unresolved"):
            if blocking in statuses:
                return blocking
        if "locked" in statuses:
            return "locked"
        if statuses == {"not_found"}:
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

        mismatched = tuple(
            symbol
            for symbol in symbols
            if self._match_authorized_symbol(tool_name, symbol, authorized) is None
        )
        if mismatched:
            return ToolAuthorization(
                allowed=False,
                error_code="identity_mismatch",
                message=(
                    "Consumer symbol/venue differs from the locked resolver identity; "
                    "silent suffix or exchange rewrites are forbidden."
                ),
                symbols=mismatched,
            )
        return ToolAuthorization(allowed=True, symbols=symbols)

    @staticmethod
    def _match_authorized_symbol(
        tool_name: str,
        requested_symbol: str,
        authorized_symbols: Iterable[str],
    ) -> str | None:
        """Map a consumer argument to one unique locked canonical symbol.

        Most repository tools accept the canonical symbol verbatim. A small
        explicit set of U.S.-only APIs and broker transports require a bare
        ticker; for those tools only, ``AAPL`` may consume ``AAPL.US``. Venue
        aliases such as ``.SS`` and ``.SH`` are never treated as equivalent.

        Args:
            tool_name: Requested consumer tool.
            requested_symbol: Model-supplied symbol argument.
            authorized_symbols: Symbols locked before the tool batch.

        Returns:
            The unique canonical identity consumed by the argument, or ``None``.
        """
        requested = _normalize_symbol(requested_symbol)
        authorized = {_normalize_symbol(item) for item in authorized_symbols}
        if requested in authorized:
            return requested
        if tool_name not in _BARE_US_TICKER_TOOLS or "." in requested:
            return None
        matches = [
            symbol
            for symbol in authorized
            if symbol.endswith(".US") and symbol.rsplit(".", 1)[0] == requested
        ]
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
        issues: list[dict[str, Any]] = []
        issues.extend(self._validate_identity(content))
        issues.extend(self._validate_unsourced_symbols(content))
        issues.extend(self._validate_price_claims(content))
        result = ValidationResult(valid=not issues, issues=issues)
        self._validations.append(
            {
                "attempt": len(self._validations) + 1,
                "checked_at": _utc_now(),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "valid": result.valid,
                "issues": issues,
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
        lines.extend(
            [
                "Reuse the exact locked symbol and venue.",
                "For every derived number, label it as derived and show the source inputs and formula.",
                "Do not attach figures to a symbol no tool call in this session handled; "
                "report it as not retrieved instead.",
                "If evidence is unavailable or conflicting, say so and ask for clarification; do not guess.",
            ]
        )
        return "\n".join(lines)

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
        if is_zh:
            return (
                "当前无法安全确认标的身份或价格证据，因此没有生成交易结论。"
                "请确认候选证券代码和交易所后再继续。"
            )
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
        candidates = [dict(item) for item in raw_candidates if isinstance(item, dict)] if isinstance(raw_candidates, list) else []
        sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
        if not candidates:
            clean_sources = [
                str(name)
                for name, value in sources.items()
                if str(value).casefold() == "ok"
            ]
            self._identities[key] = IdentityRecord(
                query=query,
                status="not_found" if len(clean_sources) >= 2 else "invalidated",
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

        alias_conflicts = [
            record
            for record in self._identities.values()
            if record.status == "locked"
            and record.symbol
            and _is_exchange_alias_conflict(record.symbol, symbol)
        ]
        if alias_conflicts:
            conflicting = list(candidates)
            conflicting.extend(
                {"symbol": record.symbol, "source": record.source}
                for record in alias_conflicts
            )
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
            offered = {
                _normalize_symbol(candidate.get("symbol")) for candidate in record.candidates
            }
            if symbol in offered:
                self._identities[key] = replace(
                    record, status="superseded", updated_at=_utc_now()
                )

    @staticmethod
    def _choose_candidate(
        query: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Choose only a unique or strongly corroborated resolver candidate."""
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
            if record.status == "locked"
            and record.instrument_type in {"listed_security", "fund"}
        ]
        if locked_listings:
            return ToolAuthorization(
                allowed=False,
                error_code="identity_conflict",
                message=(
                    "A resolver has locked this entity to a listed security. Model memory "
                    "cannot replace that evidence with a private-company workflow."
                ),
                symbols=tuple(
                    record.symbol for record in locked_listings if record.symbol
                ),
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
        return name in _PRIVATE_COMPANY_SKILL_NAMES or (
            "private" in name and "company" in name
        )

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

        Bare symbol arguments are tracked separately as roots. Nine tools take a
        bare US ticker by contract (``_BARE_US_TICKER_TOOLS``), so a run that
        legitimately fetched ``AAPL`` never writes ``AAPL.US`` into any argument
        or result. Without the root, the canonical spelling the rest of this
        module demands — see ``canonical_symbol_not_surfaced`` — would be the one
        spelling this gate rejects.

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
            symbol
            for symbol in self._extract_symbol_arguments(arguments)
            if "." not in symbol
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
            symbol = self._match_authorized_symbol(
                tool_name,
                symbol,
                self.authorized_symbols,
            ) or symbol
        source = str(payload.get("source") or tool_name)
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
                        timestamp=None,
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
                for key, item in value.items():
                    visit(item, f"{path}.{key}" if path else str(key))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, f"{path}[{index}]")

        visit(payload, "")

    def _validate_identity(self, content: str) -> list[dict[str, Any]]:
        """Validate aggregate state and listed/private contradictions."""
        issues: list[dict[str, Any]] = []
        status = self.identity_status
        if self._identity_required and status in {
            "unresolved",
            "ambiguous",
            "conflicting",
            "invalidated",
        }:
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
            if record.status == "locked"
            and record.instrument_type in {"listed_security", "fund"}
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
        """Reject figures attached to an instrument no tool in this run handled.

        This is the mechanically decidable half of "what the tools did not
        return, you do not supply" (#886/#887). Naming a symbol is left alone —
        prose may legitimately mention an index or a peer — but the moment a
        clause pairs an unhandled canonical symbol with a figure, the figure has
        no possible origin other than model memory.

        Args:
            content: Candidate assistant answer.

        Returns:
            One issue per distinct unsourced symbol carrying figures.
        """
        issues: list[dict[str, Any]] = []
        reported: set[str] = set()
        for line in content.splitlines():
            for segment in _CLAUSE_SEPARATOR_RE.split(line):
                unknown = sorted(
                    symbol
                    for symbol in _scan_symbols(segment) - self._session_symbols - reported
                    if symbol.rsplit(".", 1)[0] not in self._session_symbol_roots
                )
                if not unknown or not self._numbers_without_dates_or_percent(segment):
                    continue
                for symbol in unknown:
                    reported.add(symbol)
                    issues.append(
                        {
                            "code": "unsourced_symbol_figures",
                            "symbol": symbol,
                            "claim": segment.strip()[:200],
                            "message": (
                                f"No tool call in this session passed in or returned {symbol}, "
                                "yet the answer attaches figures to it. Retrieve it, or report "
                                "it as not retrieved."
                            ),
                        }
                    )
        return issues

    def _validate_price_claims(self, content: str) -> list[dict[str, Any]]:
        """Check Markdown OHLC tables and price prose against observed records.

        Comparison runs against every observed quote in the run, whichever tool
        produced it. The provenance demands below stay keyed on ``get_market_data``
        evidence, whose ``source``/``currency``/venue fields are authoritative;
        a generic tool's fallback source is its own name, and requiring the
        answer to spell that out would reject correct prose.
        """
        issues, table_lines = self._validate_price_tables(content)
        records = self._comparable_price_records()
        has_price_claim = any(
            self._numbers_without_dates_or_percent(line)
            for index, line in enumerate(content.splitlines())
            if index in table_lines
        )
        for index, line in enumerate(content.splitlines()):
            if index in table_lines or "|" in line:
                continue
            line_symbol = self._symbol_for_claim(line, records)
            for segment in _CLAUSE_SEPARATOR_RE.split(line):
                if not _PRICE_CONTEXT_RE.search(segment):
                    continue
                values = self._numbers_without_dates_or_percent(segment)
                if not values:
                    continue
                has_price_claim = True
                symbol = self._symbol_for_claim(segment, records) or line_symbol
                if self._is_explicit_derivation(segment, records, symbol):
                    continue
                for value in values:
                    issue = self._compare_price_claim(
                        value=value,
                        records=records,
                        field_name=None,
                        date_value=None,
                        symbol=symbol,
                        claim=segment.strip(),
                    )
                    if issue:
                        issues.append(issue)
        market_records = self._price_records()
        if has_price_claim and market_records:
            issues.extend(self._validate_price_provenance(content, market_records))
        return self._dedupe_issues(issues)

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

    def _validate_price_provenance(
        self,
        content: str,
        records: Sequence[EvidenceRecord],
    ) -> list[dict[str, Any]]:
        """Require canonical symbol, actual source, and quote currency in output."""
        issues: list[dict[str, Any]] = []
        folded = content.casefold()
        symbols = sorted({record.symbol for record in records if record.symbol})
        mentioned = [symbol for symbol in symbols if symbol.casefold() in folded]
        if not mentioned:
            issues.append(
                {
                    "code": "canonical_symbol_not_surfaced",
                    "symbols": symbols,
                    "message": (
                        "A price claim must surface its locked canonical symbol and venue suffix."
                    ),
                }
            )
        target_symbols = set(mentioned or (symbols if len(symbols) == 1 else []))
        target_records = [
            record
            for record in records
            if not target_symbols or record.symbol in target_symbols
        ]

        sources = sorted(
            {
                record.source
                for record in target_records
                if record.source and record.source.casefold() not in {"auto", "unknown"}
            }
        )
        missing_sources = [source for source in sources if source.casefold() not in folded]
        if missing_sources:
            issues.append(
                {
                    "code": "data_source_not_surfaced",
                    "sources": missing_sources,
                    "message": (
                        "Price claims must name the actual data source: "
                        + ", ".join(missing_sources)
                        + "."
                    ),
                }
            )

        currencies = sorted(
            {record.currency for record in target_records if record.currency}
        )
        missing_currencies = [
            currency
            for currency in currencies
            if not self._currency_is_surfaced(currency, content)
        ]
        if missing_currencies:
            issues.append(
                {
                    "code": "currency_not_surfaced",
                    "currencies": missing_currencies,
                    "message": (
                        "Price claims must name their quote currency: "
                        + ", ".join(missing_currencies)
                        + "."
                    ),
                }
            )
        return issues

    @staticmethod
    def _currency_is_surfaced(currency: str, content: str) -> bool:
        """Return whether a quote currency or an unambiguous alias is visible."""
        aliases = {
            "USD": ("usd", "us$", "美元"),
            "CNY": ("cny", "rmb", "人民币"),
            "HKD": ("hkd", "hk$", "港元"),
            "KRW": ("krw", "韩元"),
            "INR": ("inr", "印度卢比"),
        }
        folded = content.casefold()
        tokens = aliases.get(currency.upper(), (currency.casefold(),))
        return any(token.casefold() in folded for token in tokens)

    def _validate_price_tables(
        self,
        content: str,
    ) -> tuple[list[dict[str, Any]], set[int]]:
        """Validate field/date-specific claims in Markdown OHLC tables."""
        lines = content.splitlines()
        issues: list[dict[str, Any]] = []
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
                    values = self._numbers_without_dates_or_percent(row[position])
                    if len(values) != 1:
                        continue
                    issue = self._compare_price_claim(
                        value=values[0],
                        records=records,
                        field_name=field_name,
                        date_value=date_value,
                        symbol=symbol,
                        claim=row[position].strip(),
                    )
                    if issue:
                        issues.append(issue)
                row_index += 1
            index = max(row_index, index + 1)
        return issues, consumed

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
        value: float,
        records: list[EvidenceRecord],
        field_name: str | None,
        date_value: str | None,
        symbol: str | None,
        claim: str,
    ) -> dict[str, Any] | None:
        """Compare one unlabelled observed claim to the closest evidence value."""
        candidates = records
        if symbol:
            candidates = [record for record in candidates if record.symbol == symbol]
        symbols = sorted({record.symbol for record in candidates if record.symbol})
        if not symbol and len(symbols) == 1:
            symbol = symbols[0]
        elif not symbol and len(symbols) > 1:
            return {
                "code": "numeric_claim_ambiguous_symbol",
                "claim": claim,
                "value": value,
                "symbols": symbols,
                "message": (
                    f"Price claim {value:g} is ambiguous across multiple evidence symbols; "
                    "name the canonical symbol explicitly."
                ),
            }
        if field_name:
            candidates = [record for record in candidates if record.field == field_name]
        if date_value:
            candidates = [
                record
                for record in candidates
                if record.timestamp and record.timestamp.startswith(date_value)
            ]
        if not candidates:
            return {
                "code": "numeric_claim_unavailable",
                "claim": claim,
                "value": value,
                "symbol": symbol,
                "field": field_name,
                "date": date_value,
                "message": f"Price claim {value:g} has no matching observed tool evidence.",
            }
        observed = [float(record.value) for record in candidates if record.value is not None]
        if any(abs(value - item) <= max(abs(item) * 0.005, 1e-9) for item in observed):
            return None
        return {
            "code": "numeric_claim_conflict",
            "claim": claim,
            "value": value,
            "symbol": symbol,
            "field": field_name,
            "date": date_value,
            "observed_min": min(observed),
            "observed_max": max(observed),
            "source_tool_call_ids": sorted({record.call_id for record in candidates}),
            "message": (
                f"Price claim {value:g} conflicts with observed {field_name or 'OHLC'} "
                f"evidence {min(observed):g}–{max(observed):g}."
            ),
        }

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
    def _numbers_without_dates_or_percent(text: str) -> list[float]:
        """Extract the numbers in a claim that could plausibly be prices.

        Digits that belong to a canonical symbol, a calendar date, an aggregate
        amount, a unit-bearing quantity, or a percentage are masked first. Left
        unmasked they are compared against observed OHLC ranges and reject a
        correct draft: ``000543.SZ`` alone contributes 543.

        Args:
            text: One claim segment or table cell.

        Returns:
            Candidate price values, in order of appearance.
        """
        masked = _CANONICAL_SYMBOL_RE.sub(" ", text)
        masked = _LOCALIZED_DATE_RE.sub(" ", masked)
        masked = _DATE_RE.sub(" ", masked)
        masked = _AGGREGATE_AMOUNT_RE.sub(" ", masked)
        without_dates = _QUANTITY_WITH_UNIT_RE.sub(" ", masked)
        values: list[float] = []
        for match in _NUMBER_RE.finditer(without_dates):
            tail = without_dates[match.end() :].lstrip()
            if tail.startswith(("%", "％")):
                continue
            try:
                values.append(float(match.group(0).replace(",", "")))
            except ValueError:
                continue
        return values

    def _is_explicit_derivation(
        self,
        text: str,
        records: Sequence[EvidenceRecord],
        symbol: str | None,
    ) -> bool:
        """Allow only an arithmetically valid formula anchored to observed input."""
        if not _DERIVATION_RE.search(text):
            return False
        candidates = list(records)
        if symbol:
            candidates = [record for record in candidates if record.symbol == symbol]
        candidate_symbols = {record.symbol for record in candidates if record.symbol}
        if not symbol and len(candidate_symbols) > 1:
            return False
        observed = [
            float(record.value) for record in candidates if record.value is not None
        ]
        if not observed:
            return False

        for equals in re.finditer(r"=", text):
            left = re.search(r"([0-9.,+\-*/×÷()\s]+)$", text[: equals.start()])
            right = re.match(
                r"\s*([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)",
                text[equals.end() :],
            )
            if not left or not right:
                continue
            evaluated = self._evaluate_formula(left.group(1))
            if evaluated is None:
                continue
            computed, inputs = evaluated
            try:
                claimed = float(right.group(1).replace(",", ""))
            except ValueError:
                continue
            if not any(
                abs(item - value) <= max(abs(value) * 0.005, 1e-9)
                for item in inputs
                for value in observed
            ):
                continue
            if abs(computed - claimed) <= max(abs(computed) * 0.005, 1e-9):
                return True
        return False

    @staticmethod
    def _evaluate_formula(expression: str) -> tuple[float, list[float]] | None:
        """Evaluate a numeric ``+ - * /`` expression without executing code."""
        normalized = expression.replace("×", "*").replace("÷", "/").replace(",", "").strip()
        try:
            tree = ast.parse(normalized, mode="eval")
        except (SyntaxError, ValueError):
            return None
        inputs: list[float] = []

        def visit(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant) and _is_number(node.value):
                value = float(node.value)
                inputs.append(value)
                return value
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand)
                return value if isinstance(node.op, ast.UAdd) else -value
            if isinstance(node, ast.BinOp) and isinstance(
                node.op,
                (ast.Add, ast.Sub, ast.Mult, ast.Div),
            ):
                left_value = visit(node.left)
                right_value = visit(node.right)
                if isinstance(node.op, ast.Add):
                    return left_value + right_value
                if isinstance(node.op, ast.Sub):
                    return left_value - right_value
                if isinstance(node.op, ast.Mult):
                    return left_value * right_value
                if right_value == 0:
                    raise ValueError("division by zero")
                return left_value / right_value
            raise ValueError("unsupported formula")

        try:
            value = visit(tree)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            return None
        if len(inputs) < 2 or not math.isfinite(value):
            return None
        return value, inputs

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
