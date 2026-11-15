"""Offline evidence replay and diagnostics, independent of answer delivery."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.agent.resolution_context import ResolutionContext

from src.agent.instrument_identity import (
    IdentityRecord,
    IdentityLedger,
    _RESOLVER_TOOL,
    _scan_symbols,
    _utc_now,
)
from evals.grounding.evidence import EvidenceRecord, _EvidenceMixin, _json_object
from evals.grounding.document_quotes import DocumentIntegerQuote
from evals.grounding.figures import Figure, FiguresBlock, parse_figures_block, scan_figures
from evals.grounding.policies import ValidationResult, _PolicyMixin
from evals.grounding.registry import GROUNDING_CHECKS

GROUNDING_ARTIFACT = "grounding_evidence.json"
_MAX_TRACKED_SYMBOLS = 5_000


# Tools whose successful completion can ground backtest/analysis metric claims
# (#1336). Success alone is not authority: only results that actually carried
# metric output (parsed from the result or its run-dir artifacts) raise
# ``analysis_claim_unavailable``. A deduplicated ("skipped") call is never a
# completion.
_ANALYSIS_TOOLS = frozenset(
    {"backtest", "factor_analysis", "run_shadow_backtest", "quantlib_call"}
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


class GroundingLedger(
    IdentityLedger,
    _EvidenceMixin,
    _PolicyMixin,
):
    """Run-scoped identity state machine and evidence ledger."""

    def __init__(
        self,
        *,
        run_dir: Path,
        user_message: str,
        history: Sequence[Mapping[str, Any]] | None = None,
        contextual_identity_constraints: bool = True,
    ) -> None:
        """Create a ledger and seed only authoritative prior identities.

        Args:
            run_dir: Active run directory.
            user_message: Current user request.
            history: Optional prior message history. It remains available to
                the model. Only explicit constraints whose clause names the
                current resolver subject may carry forward; stale global
                instructions cannot authorize a new subject.
            contextual_identity_constraints: Whether explicit market words in
                the original conversation may narrow resolver candidates.
        """
        self.run_dir = Path(run_dir)
        self.user_message = user_message
        self.resolution_context = ResolutionContext.from_messages(
            user_message,
            history,
            enabled=contextual_identity_constraints,
        )
        self._identities: dict[str, IdentityRecord] = {}
        self._evidence: list[EvidenceRecord] = []
        self._document_integer_quotes: list[DocumentIntegerQuote] = []
        self._tool_failures: list[dict[str, Any]] = []
        self._analysis_completed: list[dict[str, Any]] = []
        self._analysis_metrics: list[dict[str, Any]] = []
        self._validations: list[dict[str, Any]] = []
        # Parsed figures state of the answer under validation. Declared checks
        # receive only (ledger, content), so the gate stashes it here for the
        # walk; that is what the registry contract means by figure state
        # living on the ledger.
        self._active_block: FiguresBlock | None = None
        self._active_figures: Sequence[Figure] = ()
        self._ingested_csvs: set[str] = set()
        # Per-bar tables completed backtests wrote: resolved path -> (sha256,
        # backtest scope), so a later read of one can be recognised as engine
        # output. Files the model wrote itself never qualify.
        self._engine_tables: dict[str, tuple[str, str]] = {}
        self._model_written: set[str] = set()
        # Backtest call -> its run directory, and each directory's latest call.
        self._backtest_scopes: dict[str, str] = {}
        self._scope_latest: dict[str, str] = {}
        self._identity_required = bool(_ACTIONABLE_MARKET_RE.search(user_message))
        # Every instrument this run is entitled to write about: the ones the
        # user named, plus the ones a succeeding tool call passed in or returned.
        self._session_symbols: set[str] = _scan_symbols(user_message)
        # Bare tickers a succeeding call passed in, e.g. "AAPL" for the nine
        # tools whose contract is a bare US ticker. "AAPL.US" in the answer then
        # names an instrument the run really handled.
        self._session_symbol_roots: set[str] = set()

        self._seed_symbols(user_message, source="user_message")
        self.persist()


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
            elif tool_name == "get_market_data" and payload is not None and payload.get("_unresolved"):
                # A fetch where no symbol returned data is a failed call, but
                # each symbol is still recorded as unavailable, as it was
                # when this envelope counted as a success.
                self._ingest_market_data(arguments, payload, call_id)
            self.persist()
            return

        if tool_name == "get_br_market_data":
            # This tool serves B3 identifiers; bare native tickers must not be
            # mistaken for US symbols by generic evidence ingestion.
            tickers = arguments.get("tickers")
            if isinstance(tickers, list):
                arguments = {**arguments, "tickers": [
                    str(ticker).strip().upper() if str(ticker).strip().upper().endswith(".SA")
                    else str(ticker).strip().upper() + ".SA"
                    for ticker in tickers
                ]}
        self._track_session_symbols(arguments, result)
        self._note_model_write(tool_name, arguments, payload)
        if tool_name in _ANALYSIS_TOOLS:
            self._ingest_analysis_result(tool_name, arguments, payload, call_id)
        if tool_name == _RESOLVER_TOOL:
            self._ingest_resolution(arguments, payload, call_id)
        elif tool_name == "get_market_data":
            self._ingest_market_data(arguments, payload, call_id)
        elif (tool_name == "get_br_market_data" and payload is not None
              and isinstance(payload.get("data"), dict)
              and payload["data"].get("action") == "quotes"):
            data = payload["data"]
            if data.get("currency") == "BRL":
                quotes: dict[str, Any] = {"_provenance": {}}
                for row in data.get("rows", []):
                    if not isinstance(row, dict) or not row.get("ticker"):
                        continue
                    ticker = str(row["ticker"]).strip().upper()
                    symbol = ticker if ticker.endswith(".SA") else ticker + ".SA"
                    quotes.setdefault(symbol, []).append({
                        key: row[key] for key in ("trade_date", "open", "high", "low", "close", "volume")
                        if key in row
                    })
                    quotes["_provenance"][symbol] = {"source": "b3_cotahist", "quote_currency": "BRL"}
                self._ingest_market_data(arguments, quotes, call_id, tool_name=tool_name)
        elif tool_name == "read_file" and payload is not None:
            self._ingest_engine_table(payload, call_id)
        elif tool_name == "read_run_artifact" and payload is not None:
            self._adopt_prior_backtest(arguments.get("run_dir") or payload.get("run_dir"), call_id)
            self._ingest_engine_table(payload, call_id, tool_name=tool_name)
        elif tool_name == "read_document" and payload is not None:
            # A document answers in prose, so the numeric-leaf walk below never
            # reached its numbers: every figure quoted from an uploaded PDF came
            # back as unsourced (#2050).
            self._ingest_document_text(arguments, payload, call_id)
        elif payload is not None:
            self._ingest_generic_numeric(tool_name, arguments, payload, call_id)
        self.persist()

    def validate_final_answer(self, content: str) -> ValidationResult:
        """Validate identity assertions and numeric price claims.

        Args:
            content: Candidate assistant answer.

        Returns:
            A deterministic validation result. A record containing the answer
            hash, structured issues, and the names of the declared checks that
            fired is appended to the artifact.
        """
        return self._validate(content)


    def _validate(self, content: str) -> ValidationResult:
        """Record diagnostic findings without changing the supplied text."""
        self._ingest_run_dir_ohlc_csvs()
        block = parse_figures_block(content)
        figures = scan_figures(content, block)
        self._active_check_findings: list[dict[str, Any]] = []
        self._active_block = block
        self._active_figures = figures
        issues: list[dict[str, Any]] = []
        issues.extend(self._validate_identity(content))
        issues.extend(GROUNDING_CHECKS.run_phase("answer", self, content))
        issues.extend(self._validate_figures(content, block, figures))
        issues = self._dedupe_issues(issues)
        result = ValidationResult(
            valid=not issues,
            issues=issues,
        )
        self._validations.append(
            {
                "attempt": len(self._validations) + 1,
                "checked_at": _utc_now(),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "valid": result.valid,
                "issues": issues,
                # Attribute the predicates that actually returned a finding;
                # role checks share issue codes and must not implicate each other.
                "fired_checks": list(dict.fromkeys(row["name"] for row in self._active_check_findings)),
                "check_findings": self._active_check_findings,
                "figures_block": block.raw,
            }
        )
        self.persist()
        return result

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
                "document_integer_quotes": [asdict(quote) for quote in self._document_integer_quotes],
                "tool_failures": list(self._tool_failures),
                "analysis_completed": list(self._analysis_completed),
                "analysis_evidence": list(self._analysis_metrics),
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
        the canonical spelling the rest of this module demands — see
        ``canonical_symbol_not_surfaced`` — would be the one spelling this gate
        rejects.

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

