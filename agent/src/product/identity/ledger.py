"""Instrument identity: symbol shapes, resolution, and tool authorization.

Symbol normalisation and venue/currency/type inference are pure helpers.
IdentityLedger owns resolver state and tool authorization. It has no numeric
evidence scanner, answer validator, or text-rewriting interface.
"""

from __future__ import annotations

import copy
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from src.product.identity.authorization import (
    ToolAuthorization,
    authorize_symbols,
    extract_symbol_arguments,
    match_authorized_symbol,
    venue_mismatch_hints,
)
from src.product.identity.constraints import ResolutionContext, candidate_market
from src.product.identity.normalize import (
    _CANONICAL_SYMBOL_RE,
    _infer_currency,
    _infer_instrument_type,
    _infer_venue,
    _normalize_symbol,
    _query_key,
    _scan_symbols,
)

_RESOLVER_TOOL = "search_symbol"
IDENTITY_ARTIFACT = "identity_evidence.json"
# Version of IdentityLedger.export_state(); a different version is not restored.
_STATE_SCHEMA_VERSION = 1

# A canonical symbol the USER typed is locked as their assertion. A request
# another model wrote (a delegated sub-agent task) carries no such authority:
# the parent could put an unresolved or wrong code there, and seeding it would
# authorize data calls the parent's own gate refused.
_REQUEST_IS_USER_AUTHORED: ContextVar[bool] = ContextVar(
    "identity_request_is_user_authored", default=True
)


@contextmanager
def agent_authored_request() -> Iterator[None]:
    """Mark ledgers created in this context as serving an agent-written request.

    Symbols in such a request are not seeded; the run resolves each one
    through the resolver like any other name. Resolution constraints read from
    the text still apply, because they only narrow what the resolver accepts.

    Yields:
        None, while the marking is active in the current context.
    """
    token = _REQUEST_IS_USER_AUTHORED.set(False)
    try:
        yield
    finally:
        _REQUEST_IS_USER_AUTHORED.reset(token)


def _utc_now() -> str:
    """Return an audit-friendly UTC timestamp."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

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


class IdentityLedger:
    """Instrument resolution and tool authorization; no answer inspection."""

    def __init__(
        self,
        *,
        run_dir: Path,
        user_message: str,
        history: Sequence[Mapping[str, Any]] | None = None,
        contextual_identity_constraints: bool = True,
        restored_state: Mapping[str, Any] | None = None,
        seed_prompt_symbols: bool = True,
    ) -> None:
        """Initialize identity state from explicit symbols and relevant constraints.

        Args:
            run_dir: Directory for the identity diagnostic artifact.
            user_message: Current request; explicit canonical symbols seed state
                unless the request was written by an agent
                (:func:`agent_authored_request`).
            history: Prior messages used for subject-specific resolver constraints.
                They only ever narrow a resolver query; no symbol in them is
                authorized.
            contextual_identity_constraints: Enable those contextual constraints.
            seed_prompt_symbols: Only a direct request can introduce an explicit symbol.
            restored_state: This conversation's earlier ledger, exactly as
                :meth:`export_state` returned it. It is the only source of
                carried-over authorization.
        """
        self.run_dir = Path(run_dir)
        self.resolution_context = ResolutionContext.from_messages(
            user_message,
            history,
            enabled=contextual_identity_constraints,
        )
        self._identities: dict[str, IdentityRecord] = {}
        self._identity_required = False
        if restored_state is not None:
            self._restore_state(restored_state)
        if seed_prompt_symbols and _REQUEST_IS_USER_AUTHORED.get():
            self._seed_symbols(user_message, source="user_message")
        self.persist()

    def export_state(self) -> dict[str, Any]:
        """Return the ledger's records, keyed as held, for a later turn to restore.

        Returns:
            JSON-serialisable ledger state.
        """
        return {
            "schema_version": _STATE_SCHEMA_VERSION,
            "identity_required": self._identity_required,
            "records": [
                {"key": key, **asdict(record)} for key, record in self._identities.items()
            ],
        }

    def _restore_state(self, state: Mapping[str, Any]) -> None:
        """Restore only records with the exported shape.

        Args:
            state: Exported ledger state.
        """
        if not isinstance(state, Mapping) or state.get("schema_version") != _STATE_SCHEMA_VERSION:
            return
        records = state.get("records")
        if not isinstance(records, list):
            return
        names = set(IdentityRecord.__dataclass_fields__)
        for entry in records:
            if not isinstance(entry, Mapping):
                continue
            key = entry.get("key")
            fields = {name: entry[name] for name in names if name in entry}
            if not isinstance(key, str) or not key or set(entry) - names - {"key"}:
                continue
            if not isinstance(fields.get("query"), str) or not isinstance(fields.get("status"), str):
                continue
            try:
                self._identities[key] = IdentityRecord(**copy.deepcopy(fields))
            except TypeError:
                continue
        self._identity_required = bool(state.get("identity_required"))

    def pending_resolution_query(self, arguments: Mapping[str, Any], field: str) -> str | None:
        """Find a new dependency without re-resolving a failed query or a contradiction."""
        query = arguments.get(field)
        if not isinstance(query, str) or not query.strip():
            return None
        query = query.strip()
        if self.identity_status == "conflicting":
            return None
        if match_authorized_symbol(query, self.authorized_symbols) is not None:
            return None
        if _query_key(query) in self._identities or venue_mismatch_hints(query, self.authorized_symbols):
            return None
        return query

    def reusable_resolution(self, arguments: Mapping[str, Any]) -> str | None:
        """Reuse settled exact identities without changing their source of authority."""
        if arguments.get("refresh") or self.identity_status != "locked":
            return None
        query = str(arguments.get("query") or "").strip()
        symbol = _normalize_symbol(query)
        if _scan_symbols(query) != {symbol} or query.upper() != symbol:
            return None
        if self.resolution_context.constraints_for(query):
            return None
        records = [r for r in self._identities.values() if r.symbol == symbol]
        if not records or any(r.status != "locked" for r in records):
            return None
        record = records[0]
        return json.dumps({
            "ok": True, "source": "session_identity", "reused": True,
            "network_lookup_performed": False,
            "data": {"query": query, "count": 1, "candidates": [{
                "symbol": symbol, "venue": record.venue,
                "instrument_type": record.instrument_type, "currency": record.currency,
                "source": record.source,
            }], "identity_version": record.version},
            "message": "Reused the existing identity only; no fresh listing or issuer metadata was fetched. Set refresh=true for resolver verification through the gateway, with its normal cache/freshness policy.",
        }, ensure_ascii=False)

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
            self._record_unsettled(str(arguments.get("query") or ""), call_id, "unresolved")
            return ToolAuthorization(allowed=True)

        # Reading methodology does not choose or change an instrument identity.
        if tool_name == "load_skill":
            return ToolAuthorization(allowed=True)

        symbols = tuple(extract_symbol_arguments(arguments))
        if not symbols:
            return ToolAuthorization(allowed=True)

        self._identity_required = True
        authorized = {_normalize_symbol(item) for item in batch_authorized_symbols}
        return authorize_symbols(symbols, authorized, batch_identity_status or self.identity_status)

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
        """Keep the existing lock or contradiction when the resolver supplies no new evidence.

        Args:
            existing: The record for this query key, if any.

        Returns:
            True when the caller must leave the record untouched.
        """
        if existing is not None and existing.status in {"locked", "conflicting"}:
            self.persist()
            return True
        return False

    def _record_unsettled(self, query: str, call_id: str, status: str) -> None:
        key = _query_key(query) or f"call:{call_id}"
        existing = self._identities.get(key)
        if not self._hold_locked(existing):
            self._identities[key] = IdentityRecord(
                query=query, status=status, source_tool_call_id=call_id,
                version=existing.version + 1 if existing else 1,
            )
            if status == "unresolved":
                self.persist()

    def _finish_failed_resolution(self, arguments: Mapping[str, Any], call_id: str) -> None:
        self._record_unsettled(str(arguments.get("query") or ""), call_id, "invalidated")

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
            self._record_unsettled(query, call_id, "invalidated")
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
            # Every applicable source must answer before an empty result counts as not found.
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

        def record_candidates(status: str, options: list[dict[str, Any]]) -> None:
            self._identities[key] = IdentityRecord(
                query=query, status=status, source_tool_call_id=call_id,
                candidates=options, resolution_constraints=constraint_audit, version=version,
            )

        market_values = {item.value for item in relevant_constraints if item.dimension == "market" and item.explicit}
        if market_values:
            candidates = [candidate for candidate in candidates if candidate_market(candidate) in market_values]

        # A shortlist that misses the explicit market constraint may be truncated.
        chosen = self._choose_candidate(query, candidates)
        if chosen is None:
            record_candidates("ambiguous", resolver_candidates)
            return

        symbol = _normalize_symbol(chosen.get("symbol"))
        if not symbol:
            record_candidates("invalidated", resolver_candidates)
            return

        asserted = _scan_symbols(query)
        if asserted and symbol not in asserted:
            record_candidates("conflicting", [
                *candidates, *({"symbol": item, "source": ["query"]} for item in sorted(asserted)),
            ])
            return
        if existing and existing.status == "locked" and existing.symbol != symbol:
            record_candidates("conflicting", [{"symbol": existing.symbol, "source": existing.source}, *candidates])
            return
        if existing and existing.status == "conflicting":
            # A repeated query cannot settle its own contradiction.
            conflicting = list(candidates)
            for item in existing.candidates:
                if item not in conflicting:
                    conflicting.append(item)
            record_candidates("conflicting", conflicting)
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
        """Retire ambiguous shortlists that a narrower resolution has now answered.

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
        """Choose a unique or corroborated candidate, collapsing provider aliases first."""
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

    @property
    def authorized_symbols(self) -> set[str]:
        """Return exact symbols locked before the next tool batch."""
        return {record.symbol for record in self._identities.values() if record.status == "locked" and record.symbol}

    @property
    def identity_status(self) -> str:
        """Rank contradictions above locks; a failed side query cannot retract a lock."""
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
