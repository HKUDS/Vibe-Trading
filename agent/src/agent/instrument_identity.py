"""Instrument identity: symbol shapes, resolution, and tool authorization.

Symbol normalisation and venue/currency/type inference are pure helpers.
IdentityLedger owns resolver state and tool authorization. It has no numeric
evidence scanner, answer validator, or text-rewriting interface.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from src.agent.resolution_context import ResolutionContext, candidate_market
from src.market_data import canonical_fx_pair

_RESOLVER_TOOL = "search_symbol"
IDENTITY_ARTIFACT = "identity_evidence.json"


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


# Project-style canonical symbols. A bare model-generated ticker is still
# checked when it appears under a symbol argument key, but it is not accepted
# as user-provided identity because it lacks venue information.
#
# A joined crypto pair (``BTCUSDT``, ``ETHUSDT`` …) is recognized alongside
# the dashed/slashed form so a user message like ``Get BTCUSDT spot price``
# seeds an asserted identity and the asserted-symbol conflict check at
# ``_ingest_resolution`` runs against it. The base is restricted to alpha
# so a numeric prefix cannot masquerade as a joined pair, and the suffix
# list is the unambiguous stablecoin set (``USDT`` / ``USDC`` / ``BUSD`` /
# ``TUSD``) — ``USD`` is excluded because too many non-crypto strings end
# in those three letters and over-matching would lock the wrong identity.
_JOINED_CRYPTO_QUOTE_SUFFIXES = ("USDT", "USDC", "BUSD", "TUSD")


# A dashed / slashed pair is crypto when its quote leg is unambiguously a
# crypto quote asset, or when a USD quote sits on one of these bases. Both
# sets MUST agree with ``_CRYPTO_QUOTE_ASSETS`` / ``_CRYPTO_USD_BASES`` in
# ``src.tools.symbol_search_tool`` — that module is the resolver, and a venue
# inferred here that disagrees with the identity it locks is a contradictory
# identity, which outranks every later lock and blocks all market tools. The
# tool imports this module, so the sets are duplicated rather than imported;
# ``test_crypto_pair_tables_match_the_resolver`` fails if they drift. ``USD``
# is the one quote the resolver accepts that is NOT unambiguous, so it is
# excluded here and decided by the base whitelist below instead.
_CRYPTO_QUOTE_ASSETS = frozenset({"USDT", "USDC", "BUSD", "TUSD", "FDUSD", "BTC", "ETH", "BNB"})


_CRYPTO_USD_BASES = frozenset(
    {
        "BTC",
        "ETH",
        "BNB",
        "SOL",
        "ADA",
        "XRP",
        "DOGE",
        "TRX",
        "DOT",
        "MATIC",
        "AVAX",
        "LINK",
        "LTC",
        "BCH",
        "ETC",
        "XLM",
        "ATOM",
        "FIL",
        "APT",
        "NEAR",
        "ALGO",
        "SAND",
        "MANA",
        "AXS",
        "XAUT",
        "PAXG",
    }
)


# Spot precious metals quoted in USD collide with the TUSD suffix: XPTUSD is
# XPT + USD (platinum), but stripping "TUSD" leaves the alpha base "XP" and
# folds it to XP-TUSD — a crypto pair that does not exist, and the same class
# of misresolution the USD exclusion above exists to prevent. XAU/XAG/XPD do
# not collide today; they are listed together because they are the same kind
# of symbol and a future suffix would collide with them the same way.
_METAL_USD_PAIR_RE = re.compile(r"^(?:XAU|XAG|XPT|XPD)USD$", re.IGNORECASE)


_JOINED_CRYPTO_RE = re.compile(
    r"(?<![A-Za-z0-9_])[A-Z]{2,15}(?:" + "|".join(_JOINED_CRYPTO_QUOTE_SUFFIXES) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


_CANONICAL_SYMBOL_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"\d{3,6}\.(?:SH|SZ|BJ|SS|HK|KS|KQ)|"
    # Futu writes the venue as a PREFIX (HK.00700 / SH.600519 / US.AAPL). The
    # suffix branch above cannot see it, so a user who pasted a connector code
    # got no identity lock at all and every market tool answered
    # identity_required. Handled for the whole prefix set, not just HK: the
    # connector emits all four, and one venue's fix leaves the same hole open
    # in the next.
    r"(?:HK|SH|SZ|BJ|SS)\.\d{3,6}|"
    # Case-SENSITIVE (the connector writes it uppercase): a case-folded
    # match turns any "…/us.reuters/…" host inside a source URL into the
    # symbol REUTERS.US and fails the answer for an unsourced figure.
    r"(?-i:US\.[A-Z][A-Z0-9&-]{0,19})|"
    # Every equity suffix the market-data layer routes (backtest.engines.
    # _market_hooks._MARKET_PATTERNS); test_market_identity_parity keeps the
    # two in step, because .L / .VN / .BA each landed there without landing here.
    r"[A-Z][A-Z0-9&.-]{0,19}\.(?:US|NS|BO|FX|TO|V|BA|SA|L|VN)|"
    r"[A-Z0-9]{2,15}(?:-|/)(?:USDT|USDC|USD|BTC|ETH)|"
    r"[A-Z]{2,15}(?:" + "|".join(_JOINED_CRYPTO_QUOTE_SUFFIXES) + r")|"
    r"\^[A-Z0-9&.\-]{1,20}|"
    r"[A-Z0-9]{2,15}=[FX]"
    r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


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


# The dotted form of the same idea, as the Futu connector spells it
# (``HK.00700`` / ``US.AAPL``). ``SS`` is Yahoo's Shanghai alias and folds
# onto ``SH`` exactly as the suffix spelling does.
_VENUE_PREFIXES = frozenset({"HK", "SH", "SZ", "BJ", "SS", "US"})


_US_TICKER_RE = re.compile(r"[A-Z][A-Z0-9&-]{0,19}")


def _normalize_symbol(value: Any) -> str:
    """Normalize a symbol onto one canonical identity for exact comparison.

    Args:
        value: Any provider- or model-supplied symbol spelling.

    Returns:
        The canonical spelling — uppercased, with Shanghai's ``.SS`` alias
        folded onto ``.SH``, an exchange prefix rewritten as a suffix, a Hong
        Kong code zero-padded, and a crypto pair hyphenated. A joined crypto
        pair with no separator (``BTCUSDT``) is rewritten as the dashed form
        (``BTC-USDT``) so every downstream check sees one identity. Text that
        is not a symbol is returned uppercased and otherwise untouched.
    """
    # A fiat/fiat pair is one FX instrument regardless of spelling: ``GBP/USD``
    # and ``GBPUSD`` are both ``GBPUSD=X``. Checked BEFORE the slash is
    # rewritten ("GBP/USD" -> "GBP-USD", the crypto-pair spelling), which
    # disagreed with the resolver's ``GBPUSD=X`` answer — a contradictory
    # identity that outranked every later lock and blocked all further tools.
    raw = str(value or "").strip().upper()
    fx = canonical_fx_pair(raw)
    if fx is not None:
        return fx
    symbol = raw.replace("/", "-")
    if not symbol:
        return ""

    prefixed = _EXCHANGE_PREFIXED_RE.match(symbol)
    if prefixed:
        return f"{prefixed.group(2)}.{prefixed.group(1)}"
    base, dot, suffix = symbol.rpartition(".")
    if not dot:
        # No separator at all: rewrite a joined crypto pair (``BTCUSDT``)
        # as the dashed form so the dash/slash branch and the canonical
        # regex both match. The base must be all-alpha so a numeric prefix
        # cannot collide with another numeric-code branch downstream.
        joined = _JOINED_CRYPTO_RE.fullmatch(symbol)
        if joined and not _METAL_USD_PAIR_RE.fullmatch(symbol):
            for quote in _JOINED_CRYPTO_QUOTE_SUFFIXES:
                if symbol.endswith(quote) and len(symbol) > len(quote):
                    base_part = symbol[: -len(quote)]
                    if base_part.isalpha():
                        return f"{base_part}-{quote}"
        return symbol
    # Venue-prefixed listing (Futu connector format: HK.06693 / SH.600519 /
    # SZ.000001 / US.AAPL): rewrite to the canonical suffix spelling so
    # identity matching agrees with the market-data chain (06693.HK) that
    # get_market_data uses. Shanghai's .SS alias is folded onto .SH here too,
    # the same way the suffix branch below does it.
    if base in _VENUE_PREFIXES and suffix:
        venue = "SH" if base == "SS" else base
        if venue == "US":
            if _US_TICKER_RE.fullmatch(suffix):
                return f"{suffix}.US"
        elif suffix.isdigit():
            digits = suffix.zfill(5) if venue == "HK" else suffix
            return f"{digits}.{venue}"
    if suffix == "SS":
        suffix = "SH"
    if suffix == "HK" and base.isdigit():
        base = base.zfill(5)
    return f"{base}.{suffix}"


def _query_key(value: Any) -> str:
    """Normalize resolver queries into stable state-machine keys."""
    return " ".join(str(value or "").casefold().split())


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
        ".BA": "buenos_aires",
        ".SA": "b3",
        ".L": "lse",
        ".VN": "hose",
    }
    for suffix, venue in suffixes.items():
        if upper.endswith(suffix):
            return venue
    # Yahoo's continuous-front-month futures notation (GC=F, CL=F, SI=F, ...).
    # The exchange category is the venue class. The engine and the
    # correlation helper mirror this pattern; this is the third copy.
    if upper.endswith("=F"):
        return "futures"
    # Yahoo's forex notation (XAUUSD=X, EURUSD=X) is FX.
    if re.match(r"^[A-Z]{6}=X$", upper):
        return "forex"
    # Bare 6-character precious-metal / FX symbols. The whitelist is
    # ISO 4217 metals + G10 currencies; it intentionally does NOT include
    # any US-equity prefix. Mirroring the engine ``_MARKET_PATTERNS``.
    if re.match(
        r"^(?:XAU|XAG|XPT|XPD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|USD)[A-Z]{3}$",
        upper,
    ):
        return "forex"
    # Dashed / slashed symbols are NOT categorically crypto: a USD quote is
    # crypto only on a whitelisted base (``_CRYPTO_USD_BASES``), so
    # ``XAU-USD`` / ``EUR-USD`` / ``GBP-USD`` are forex. Without this guard a
    # spot-gold pair surfaced as a crypto-or-fx hybrid in the runtime
    # registry, contradicting the engine classifier that already routes it to
    # ``forex`` (#1280).
    if "-" in upper or "/" in upper:
        base, _, quote = upper.partition("-") if "-" in upper else upper.partition("/")
        if quote in _CRYPTO_QUOTE_ASSETS:
            return "crypto_or_fx"
        if quote == "USD" and base in _CRYPTO_USD_BASES:
            return "crypto_or_fx"
        # Any other dashed / slashed pair is forex-shaped (e.g. ``XAU-USD``,
        # ``EUR-USD``, ``GBP-USD``); the per-pair engine classifier decides
        # ``forex`` vs ``crypto`` vs ``futures`` downstream.
        return "forex"
    return None


def _infer_currency(symbol: str) -> str | None:
    """Infer quote currency without performing an implicit conversion."""
    upper = _normalize_symbol(symbol)
    # HKEX assigns the currency by code range (RMB counters 80000-89999, a few
    # USD ranges), so 80700.HK is a CNY line beside 00700.HK in HKD. One table,
    # shared with the backtest's currency guard.
    from backtest.engines._market_hooks import hk_counter_currency

    hk_currency = hk_counter_currency(upper)
    if hk_currency is not None:
        return hk_currency
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
        ".BA": "ARS",
        ".SA": "BRL",
        # The UK loaders admit only a declared GBP / GBp quote and hand back
        # GBP, the same contract as the backtest's _MARKET_CURRENCY.
        ".L": "GBP",
        ".VN": "VND",
    }
    for suffix, currency in suffixes.items():
        if upper.endswith(suffix):
            return currency
    for separator in ("-", "/"):
        if separator in upper:
            quote = upper.rsplit(separator, 1)[-1]
            if 3 <= len(quote) <= 5:
                return quote
    if upper.endswith("=X"):
        pair = upper[:-2]
        if len(pair) == 6:
            return pair[3:6]
    return None


def _infer_instrument_type(symbol: str, candidate_type: Any = None) -> str:
    """Normalize provider types into the identity contract."""
    raw = str(candidate_type or "").strip().casefold()
    if raw == "cfd":
        return "cfd"
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
    if "index" in raw:
        return "index"
    upper = _normalize_symbol(symbol)
    if upper.endswith("=F"):
        return "future"
    if upper.endswith(".FX"):
        return "forex"
    # Yahoo's continuous-front-month futures notation (GC=F, CL=F, ...).
    # Mirrors the engine ``_MARKET_PATTERNS`` and the correlation helper.
    if re.match(r"^[A-Z]{2,5}=F$", upper):
        return "future"
    # Yahoo's forex notation (XAUUSD=X, EURUSD=X).
    if re.match(r"^[A-Z]{6}=X$", upper):
        return "forex"
    # Bare 6-character precious-metal / FX symbols (whitelist).
    if re.match(
        r"^(?:XAU|XAG|XPT|XPD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|USD)[A-Z]{3}$",
        upper,
    ):
        return "forex"
    # Dashed / slashed symbols: crypto only when the quote leg is a
    # stablecoin OR the base is in the USD-whitelist. The whitelist
    # mirrors ``_canonical_crypto_pair`` in
    # ``src.tools.symbol_search_tool``. ``XAU-USD`` / ``EUR-USD`` /
    # ``GBP-USD`` are NOT crypto and resolve as ``forex`` (the per-pair
    # engine classifier decides the final market downstream).
    if "-" in upper or "/" in upper:
        base, _, quote = upper.partition("-") if "-" in upper else upper.partition("/")
        if quote in _CRYPTO_QUOTE_ASSETS:
            return "crypto"
        if quote == "USD" and base in _CRYPTO_USD_BASES:
            return "crypto"
        return "forex"
    if upper.startswith("^"):
        return "index"
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
    resolution_constraints: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1
    updated_at: str = field(default_factory=_utc_now)


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
                    "Call search_symbol first and wait for "
                    "its result, then reuse the exact locked symbol and venue. If the "
                    "resolver answers with a shortlist rather than one instrument, "
                    "show the candidates and ask the user which one to use — narrowing "
                    "the query again will not turn a genuine dual listing into one."
                ),
            },
            ensure_ascii=False,
        )


class IdentityLedger:
    """Instrument resolution and tool authorization; no answer inspection."""

    def __init__(
        self,
        *,
        run_dir: Path,
        user_message: str,
        history: Sequence[Mapping[str, Any]] | None = None,
        contextual_identity_constraints: bool = True,
    ) -> None:
        """Initialize identity state from explicit symbols and relevant constraints.

        Args:
            run_dir: Directory for the identity diagnostic artifact.
            user_message: Current request; explicit canonical symbols seed state.
            history: Prior messages used for subject-specific resolver constraints.
            contextual_identity_constraints: Enable those contextual constraints.
        """
        self.run_dir = Path(run_dir)
        self.resolution_context = ResolutionContext.from_messages(
            user_message,
            history,
            enabled=contextual_identity_constraints,
        )
        self._identities: dict[str, IdentityRecord] = {}
        self._identity_required = False
        self._seed_symbols(user_message, source="user_message")
        self.persist()

    def authorize_tool_call(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        batch_authorized_symbols: Iterable[str],
        call_id: str,
        batch_identity_status: str | None = None,
    ) -> ToolAuthorization:
        """Authorize against the identity state before this execution segment.

        Args:
            tool_name: Requested tool.
            arguments: Model-supplied arguments.
            batch_authorized_symbols: Snapshot taken before processing any call
                from this execution segment.
            call_id: Provider tool-call identity.
            batch_identity_status: Aggregate identity status from the same
                pre-batch snapshot. Defaults to the current state for direct
                callers outside the Agent loop.

        Returns:
            An allow/block decision. Resolver calls are allowed but their result
            can affect dependent calls scheduled in the next execution segment.
        """
        if tool_name == _RESOLVER_TOOL:
            self._identity_required = True
            self._begin_resolution(str(arguments.get("query") or ""), call_id)
            return ToolAuthorization(allowed=True)

        # Reading methodology does not choose or change an instrument identity.
        if tool_name == "load_skill":
            return ToolAuthorization(allowed=True)

        symbols = tuple(self._extract_symbol_arguments(arguments))
        if not symbols:
            return ToolAuthorization(allowed=True)

        self._identity_required = True
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
                    "A canonical, non-conflicting identity has not been resolved for this "
                    "call. Resolve the instrument before requesting its data."
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
                    f"call search_symbol('{requested_symbol}') before this data call "
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

    def _hold_locked(self, existing: IdentityRecord | None) -> bool:
        """Whether a settled record must survive a non-conclusive resolver step.

        A repeat resolution that fails, is refused or comes back empty carries
        no evidence about the entity, and replacing the record would erase the
        contradiction anchor an earlier successful resolution established. A
        ``conflicting`` record is settled in the same sense: the anchor is the
        only record of which symbols disagreed.

        Args:
            existing: The record for this query key, if any.

        Returns:
            True when the caller must leave the record untouched.
        """
        if existing is not None and existing.status in {"locked", "conflicting"}:
            self.persist()
            return True
        return False

    def _begin_resolution(self, query: str, call_id: str) -> None:
        """Enter unresolved state before the resolver executes."""
        key = _query_key(query) or f"call:{call_id}"
        existing = self._identities.get(key)
        if self._hold_locked(existing):
            return
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
        if self._hold_locked(existing):
            return
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
            if self._hold_locked(existing):
                return
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
        resolver_candidates = candidates
        relevant_constraints = self.resolution_context.constraints_for(query)
        constraint_audit = [item.audit_record() for item in relevant_constraints]
        sources = data.get("sources") if isinstance(data.get("sources"), dict) else {}
        if not candidates:
            if self._hold_locked(existing):
                return
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
                resolution_constraints=constraint_audit,
                version=version,
            )
            return

        market_values = {item.value for item in relevant_constraints if item.dimension == "market" and item.explicit}
        if market_values:
            constrained = [candidate for candidate in candidates if candidate_market(candidate) in market_values]
            if constrained:
                candidates = constrained
            else:
                # A mismatch with an explicit constraint must stay fail closed.
                # The candidate list may be truncated, so this is ambiguity,
                # not proof that the requested listing does not exist.
                self._identities[key] = IdentityRecord(
                    query=query,
                    status="ambiguous",
                    source_tool_call_id=call_id,
                    candidates=resolver_candidates,
                    resolution_constraints=constraint_audit,
                    version=version,
                )
                return

        chosen = self._choose_candidate(query, candidates)
        if chosen is None:
            self._identities[key] = IdentityRecord(
                query=query,
                status="ambiguous",
                source_tool_call_id=call_id,
                candidates=resolver_candidates,
                resolution_constraints=constraint_audit,
                version=version,
            )
            return

        symbol = _normalize_symbol(chosen.get("symbol"))
        if not symbol:
            self._identities[key] = IdentityRecord(
                query=query,
                status="invalidated",
                source_tool_call_id=call_id,
                candidates=resolver_candidates,
                resolution_constraints=constraint_audit,
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
                resolution_constraints=constraint_audit,
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
                resolution_constraints=constraint_audit,
                version=version,
            )
            return

        if existing and existing.status == "conflicting":
            # Re-answering one side of a contradiction is not evidence that
            # settles it: the same query through the same resolver returns the
            # same opinion it did a moment ago, so promoting it to ``locked``
            # would drop the anchor and authorize a symbol the run had already
            # found contradicted. Only a different query (a new key, e.g. a
            # disambiguated name) can answer this.
            conflicting = list(candidates)
            for item in existing.candidates:
                if item not in conflicting:
                    conflicting.append(item)
            self._identities[key] = IdentityRecord(
                query=query,
                status="conflicting",
                source_tool_call_id=call_id,
                candidates=conflicting,
                resolution_constraints=constraint_audit,
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
            candidates=resolver_candidates,
            resolution_constraints=constraint_audit,
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

    def identity_summary(self) -> dict[str, Any]:
        """Return instrument state for tool errors and persisted traces."""
        return {
            "status": self.identity_status,
            "authorized_symbols": sorted(self.authorized_symbols),
            "records": [asdict(record) for record in self._identities.values()],
        }

    def ingest_tool_result(
        self, *, tool_name: str, arguments: Mapping[str, Any], result: str, call_id: str, success: bool
    ) -> None:
        """Update resolution from a resolver result; other tools cannot lock identities."""
        if tool_name != _RESOLVER_TOOL:
            return
        if success:
            try:
                payload = json.loads(result)
            except (ValueError, TypeError):
                payload = None
            self._ingest_resolution(arguments, payload if isinstance(payload, dict) else None, call_id)
        else:
            self._finish_failed_resolution(arguments, call_id)
        self.persist()

    def persist(self) -> None:
        """Atomically save identity state without an answer-validation ledger."""
        try:
            path = self.run_dir / "artifacts" / IDENTITY_ARTIFACT
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "identity": self.identity_summary(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError:
            # A failed diagnostic write must not interrupt research.
            return
