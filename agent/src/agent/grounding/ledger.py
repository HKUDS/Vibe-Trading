"""The :class:`GroundingLedger` facade the agent loop drives."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.agent.resolution_context import ResolutionContext

from src.agent.grounding.identity import (
    IdentityRecord,
    _IdentityMixin,
    _RESOLVER_TOOL,
    _scan_symbols,
    _utc_now,
)
from src.agent.grounding.evidence import EvidenceRecord, _EvidenceMixin, _json_object
from src.agent.grounding.figures import parse_figures_block, scan_figures, strip_figures_block
from src.agent.grounding.policies import ValidationResult, _PolicyMixin
from src.agent.grounding.release import (
    MAX_GROUNDING_RECOVERY_ROUNDS,
    MAX_PRICE_EVIDENCE_ATTEMPTS,
    MAX_SYMBOL_RESOLUTION_ATTEMPTS,
    _ReleaseMixin,
)

GROUNDING_ARTIFACT = "grounding_evidence.json"


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
    _IdentityMixin,
    _EvidenceMixin,
    _PolicyMixin,
    _ReleaseMixin,
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
        self._tool_failures: list[dict[str, Any]] = []
        self._analysis_completed: list[dict[str, Any]] = []
        self._analysis_metrics: list[dict[str, Any]] = []
        self._validations: list[dict[str, Any]] = []
        # The one document that actually shipped through the release path, if
        # any. Not a draft, so it stays out of ``validation_count``.
        self._released: dict[str, Any] | None = None
        self._recovery_rounds = 0
        self._symbol_resolution_attempts = 0
        self._price_evidence_attempts = 0
        # #GGAL-D: the rejected draft + validation a still-outstanding
        # recovery request (search_symbol/get_market_data) was issued for.
        # Set by ``record_recovery``, cleared here when that exact tool
        # succeeds, or consumed once by ``pending_recovery_stub``.
        self._pending_recovery: dict[str, Any] | None = None
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

    @property
    def figures_removed(self) -> int:
        """Return how many figures the discounted release cut, or 0."""
        return int((self._released or {}).get("figures_removed", 0))

    @staticmethod
    def streamable_length(text: str) -> int:
        """Return how much of a streaming answer may be shown live.

        Held back: everything from the figures block's fence on (the model's
        declaration to the gate), a last line that could still become that fence,
        everything from the first measurement-shaped number (the gate has not
        checked it, and a rejected draft must not have shown it), and a number
        still being written ("0." before "666").

        Args:
            text: The answer streamed so far.

        Returns:
            The length of the prefix that is safe to emit.
        """
        span = parse_figures_block(text).span
        limit = len(text)
        if span is not None:
            limit = span[0]
        else:
            line_start = text.rfind("\n") + 1
            if text[line_start:].lstrip()[:1] in ("`", "~"):
                limit = line_start
        prefix = text[:limit]
        measured = GroundingLedger.measurement_start(prefix)
        if measured is not None:
            return measured
        trimmed = prefix.rstrip(" \t")
        cursor = len(trimmed)
        while cursor and (trimmed[cursor - 1].isdigit() or trimmed[cursor - 1] in ".,"):
            cursor -= 1
        if any(char.isdigit() for char in trimmed[cursor:]):
            return cursor
        return limit

    @staticmethod
    def measurement_start(text: str) -> int | None:
        """Where the first measurement-shaped number in ``text`` starts, or None."""
        for figure in scan_figures(text, parse_figures_block(text)):
            if figure.shape == "measured":
                return figure.start
        return None

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

        # #GGAL-D: the recovery this run was waiting on just happened —
        # whatever the model answers next is a real revision attempt, not a
        # stub standing in for one.
        if self._pending_recovery is not None and tool_name == self._pending_recovery["action"]:
            self._pending_recovery = None
        self._track_session_symbols(arguments, result)
        if tool_name in _ANALYSIS_TOOLS:
            self._ingest_analysis_result(tool_name, arguments, payload, call_id)
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
        return self._validate(content, record=True)

    def revalidate(self, content: str) -> ValidationResult:
        """Validate text WITHOUT counting it as a rejected draft.

        For the recheck that follows a deterministic repair or redaction. No
        model round produced that text, so recording it would count a
        rejected draft nobody wrote and add an artifact attempt no draft
        stands behind.

        Args:
            content: The repaired or redacted answer.

        Returns:
            A deterministic validation result.
        """
        return self._validate(content, record=False)

    def _validate(self, content: str, *, record: bool) -> ValidationResult:
        """Run the gate, optionally without recording the attempt.

        ``validation_count`` is the run's checked-DRAFT count: the degraded-run
        reason prints it and the ``grounding_status`` round follows it (the
        revision cap itself is counted in ``loop.py``). The release path's own
        rechecks are not drafts, so they pass ``record=False``.

        Args:
            content: Candidate assistant answer.
            record: Whether to append the attempt to the persisted ledger.

        Returns:
            A deterministic validation result.
        """
        self._ingest_run_dir_ohlc_csvs()
        block = parse_figures_block(content)
        figures = scan_figures(content, block)
        issues: list[dict[str, Any]] = []
        issues.extend(self._validate_identity(content))
        issues.extend(self._validate_unsourced_symbols(content, figures, block))
        issues.extend(self._validate_figures(content, block, figures))
        issues = self._dedupe_issues(issues)
        result = ValidationResult(
            valid=not issues,
            issues=issues,
            released_text=strip_figures_block(content, block),
        )
        if not record:
            return result
        self._validations.append(
            {
                "attempt": len(self._validations) + 1,
                "checked_at": _utc_now(),
                "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "valid": result.valid,
                "issues": issues,
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
                "tool_failures": list(self._tool_failures),
                "analysis_completed": list(self._analysis_completed),
                "analysis_evidence": list(self._analysis_metrics),
                "validations": list(self._validations),
                "released": dict(self._released) if self._released else None,
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
