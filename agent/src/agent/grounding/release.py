"""What happens after a rejection: correction, recovery, repair, redaction."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Sequence

from src.agent.grounding.identity import (
    _CANONICAL_SYMBOL_RE,
    _RESOLVER_TOOL,
    _normalize_symbol,
    _utc_now,
)
from src.agent.grounding.evidence import EvidenceRecord
from src.agent.grounding.figures import (
    BLOCK_LANGUAGE,
    Figure,
    _lines_with_offsets,
    parse_figures_block,
    scan_figures,
    strip_figures_block,
)
from src.agent.grounding.policies import ValidationResult

# Bounded read-only recovery (#1081) through `search_symbol` / `get_market_data`,
# budgeted separately from rejected drafts so real progress is never cut off.
MAX_GROUNDING_RECOVERY_ROUNDS = 6

# Rejected drafts before the run stops revising: the first gets a correction
# prompt, the second is released with its rejected figures cut (spec §0).
MAX_GROUNDING_REVISIONS = 2

# Issue codes whose figure can be cut out and the draft released.
_REDACTABLE_CODES = frozenset(
    {
        "numeric_claim_conflict",
        "numeric_claim_unavailable",
        "unsourced_symbol_figures",
        "figure_undeclared",
    }
)

# Provenance codes a data note repairs deterministically. The symbol is absent
# on purpose: it is the figure's subject, and a footnote naming it under a draft
# about another instrument would bless a misattribution.
_REPAIRABLE_PROVENANCE_CODES = frozenset(
    {"data_source_not_surfaced", "currency_not_surfaced"}
)

_MAX_REDACTION_PASSES = 3

# The omission mark replaces the number and its glued unit so the sentence still
# reads ("0.95 元" → "（略※）"); ※ points at the single footnote.
_REDACTION_MARKER_ZH = "（略※）"

_REDACTION_MARKER_EN = "(omitted※)"

MAX_SYMBOL_RESOLUTION_ATTEMPTS = 2

MAX_PRICE_EVIDENCE_ATTEMPTS = 3


def _format_price(value: float) -> str:
    """Render a price without scientific notation (``%g`` gives "1.23457e+06")."""
    return format(value, ".10g")


#: What the evidence says about a figure, keyed on the validator's reason: a
#: state of the check, never a word read from the answer.
_CORRECTION_REASONS = {
    "undeclared": "it is not declared at all",
    "no_evidence": "this session holds no evidence of that kind to check it against",
    "value_mismatch": "the observed evidence is {range}",
    "not_in_referenced_call": "call {ref} returned no such value",
    "no_formula": "its note states no arithmetic",
    "formula_not_evaluable": "its note is not an arithmetic expression over two or more operands",
    "formula_not_anchored": "no operand of its note is a value this session observed",
    "no_symbol": "the run holds evidence for more than one instrument and the note names none",
    "derivation_result_mismatch": "its own note evaluates to {result}",
    "outside_observed_range": "it is outside the observed range {range} and its note derives no value",
    "citation_without_source": "its note names no source",
    "cited_as_observed": "it is presented as an observed value of this instrument",
    "unparseable_declaration": "the declaration line could not be read as `value | role | note | ref`",
    "symbol_never_handled": "no tool call in this session passed in or returned that symbol",
    "additive_operand_not_observed": "a number its note adds or subtracts is not a value this session observed",
    "role_in_price_column": "it sits in a price column, which holds only observed prints",
    "proposed_not_a_price": "a proposed level is a price, not a percentage; state the price it implies",
    "symbol_mismatch": "it is declared for one instrument but the sentence writes it about another",
    "citation_not_visible": "its source is not named on the figure's own line, and the note is stripped before the user reads the answer",
}


def _correction_line(issue: dict[str, Any]) -> str:
    """Render one rejected figure as `written | declared role | evidence`.

    Args:
        issue: One figure-scoped validation issue.

    Returns:
        The line the correction prompt shows for that figure.
    """
    role = issue.get("role")
    declared = f"declared {role}" if role else "not declared"
    if issue.get("code") == "figure_undeclared":
        declared = "not declared"
    reason = str(issue.get("reason") or "")
    template = _CORRECTION_REASONS.get(reason, reason or "it could not be verified")
    low, high = issue.get("observed_min"), issue.get("observed_max")
    span = (
        f"{_format_price(float(low))}\u2013{_format_price(float(high))}"
        if isinstance(low, (int, float)) and isinstance(high, (int, float))
        else "empty"
    )
    result = issue.get("derived_result")  # already rendered in the figure's own units
    evidence = template.format(
        range=span,
        ref=issue.get("source_tool_call_ids", [""])[0] if issue.get("source_tool_call_ids") else "",
        result=result if result else "a different value",
    )
    nearest = issue.get("observed_nearest") or []
    if nearest:
        evidence += "; nearest observed " + ", ".join(_format_price(float(item)) for item in nearest)
    symbol = issue.get("symbol")
    subject = f"{issue.get('value')} ({symbol})" if symbol else str(issue.get("value"))
    return f"{subject} | {declared} | {evidence}"


def _strip_release_markers(content: str) -> str:
    """Remove redaction markers and ※ note lines the model wrote itself.

    Those are the gate's own statements about what it cut; a model-written copy
    contradicts the real footnote or claims a redaction that never happened.

    Args:
        content: The rejected draft.

    Returns:
        The draft with every marker and note-shaped line removed.
    """
    stripped = content.replace(_REDACTION_MARKER_ZH, "").replace(
        _REDACTION_MARKER_EN, ""
    )
    return "\n".join(
        line for line in stripped.splitlines() if not line.lstrip().startswith("※")
    )


class _ReleaseMixin:
    """Release behaviour of :class:`GroundingLedger`."""

    def correction_prompt(self, validation: ValidationResult) -> str:
        """Build per-figure feedback for one rejected model draft (spec 6).

        Each rejected figure gets one line: the figure as written, the role it
        was declared under, and what the evidence says. The three ways out are
        stated once.

        Args:
            validation: The rejected draft's validation result.

        Returns:
            The system message handed back to the model.
        """
        lines = [
            "[GROUNDING GATE] The previous draft was rejected and was not released to the user.",
            "Every figure below, exactly as you wrote it, with what you declared and what the evidence says:",
        ]
        figures, others = [], []
        for issue in validation.issues[:24]:
            (figures if issue.get("value") is not None else others).append(issue)
        lines.extend(f"- {_correction_line(issue)}" for issue in figures)
        lines.extend(
            f"- {issue.get('message', issue.get('code', 'grounding error'))}" for issue in others
        )
        if figures:
            lines.extend(
                [
                    "Fix EVERY figure above in one of exactly three ways:",
                    "  (1) DECLARE it with the role it really has, in the figures block;",
                    "  (2) REWRITE it to a value this session's tools actually returned;",
                    "  (3) REMOVE it from the answer.",
                    "Restating a rejected value in another format is none of the three and fails again.",
                ]
            )
            repeated = self._repeatedly_rejected(figures)
            if repeated:
                lines.append(
                    "These value(s) have now been rejected across more than one draft: "
                    + ", ".join(repeated)
                    + ". Take option (2) or (3) for them."
                )
        lines.extend(
            [
                "End the answer with a ```figures``` block declaring every number that "
                "carries a decimal point, a percent sign, a currency mark or a table "
                "cell, one per line as `value | role | note | ref`, where role is one "
                "of observed / derived / proposed / cited / count.",
                "observed must appear in the tool results; derived needs a note that is "
                "the arithmetic itself, with one operand this session observed; "
                "proposed must be derived or lie inside the observed price range; "
                "cited needs a source in its note; count is not checked.",
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
                    "Do NOT ask the user to confirm or continue while this read-only recovery "
                    "remains available.",
                ]
            )
        elif recovery == "get_market_data":
            lines.extend(
                [
                    "Identity is locked but price evidence is missing. Call `get_market_data` "
                    "for the locked canonical symbol and venue in a separate tool-call turn, "
                    "then regenerate and re-validate the final answer.",
                    "Do NOT ask the user to confirm or continue while this read-only recovery "
                    "remains available.",
                ]
            )
        else:
            lines.append(
                "If evidence is genuinely unavailable or conflicting and recovery is "
                "exhausted, say so and ask for clarification; do not guess."
            )
        return "\n".join(lines)

    def _repeatedly_rejected(self, issues: Sequence[dict[str, Any]]) -> list[str]:
        """Figures in this draft that an earlier draft was already refused for.

        Args:
            issues: The current draft's figure issues.

        Returns:
            The repeated figures as written, in order, without duplicates.
        """
        current = {str(issue.get("value")) for issue in issues}
        repeated = [
            str(prior_issue.get("value"))
            for prior in self._validations[:-1]
            for prior_issue in prior.get("issues", [])
            if str(prior_issue.get("value")) in current
        ]
        return list(dict.fromkeys(repeated))

    def recovery_action(self, validation: ValidationResult) -> str | None:
        """Decide the next safe read-only recovery step for a rejected draft (#1081).

        Returns:
            ``search_symbol`` when identity is unresolved and resolution attempts
            remain; ``get_market_data`` when identity is locked, a price claim
            lacks evidence and fetch attempts remain; otherwise None, and the
            loop must ask the user or fail closed.
        """
        if self._recovery_rounds >= MAX_GROUNDING_RECOVERY_ROUNDS:
            return None
        if self._identity_required and self.identity_status == "unresolved":
            if self._symbol_resolution_attempts < MAX_SYMBOL_RESOLUTION_ATTEMPTS:
                return _RESOLVER_TOOL
            return None
        if self.identity_status == "locked" and any(
            issue.get("code") in {"numeric_claim_unavailable", "unsourced_symbol_figures"}
            for issue in validation.issues
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
        is_zh = self._user_writes_chinese()
        joined = self._observed_range_summary(is_zh)
        if joined is not None:
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
        # No observed price: tell unresolved identity apart from a draft citing
        # prices this session never observed.
        issue_codes = {
            code
            for validation in self._validations
            for code in (issue.get("code") for issue in validation.get("issues", []))
        }
        if issue_codes & _REDACTABLE_CODES:
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
            return (
                "当前无法安全确认标的身份或价格证据，因此没有生成交易结论。"
                "请确认候选证券代码和交易所后再继续。"
            )
        return (
            "I could not safely lock the instrument identity or price evidence, so I did not "
            "produce a trading conclusion. Please confirm the candidate symbol and venue."
        )

    def _user_writes_chinese(self) -> bool:
        """Return whether user-facing gate text should be Chinese."""
        return bool(re.search(r"[\u3400-\u9fff]", self.user_message))

    def _observed_range_summary(self, is_zh: bool, content: str | None = None) -> str | None:
        """Summarise the observed OHLC range per symbol, or None without prices.

        Args:
            is_zh: Whether to join the facts with Chinese punctuation.
            content: The answer the summary is attached to, if any; the symbol
                is then printed the way that answer spells it.

        Returns:
            One fact per symbol, or None when the run observed no price.
        """
        price_records = self._price_records()
        if not price_records:
            return None
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
                f"{self._answer_symbol_spelling(symbol, content)}: "
                f"{_format_price(min(values))}–{_format_price(max(values))}{unit} "
                f"(source: {source_label}; currency conversion: none)"
            )
        return "；".join(facts) if is_zh else "; ".join(facts)

    @staticmethod
    def _answer_symbol_spelling(canonical: str, content: str | None) -> str:
        """Return the spelling ``content`` uses for a canonical symbol."""
        if not content:
            return canonical
        for match in _CANONICAL_SYMBOL_RE.finditer(content):
            if _normalize_symbol(match.group(0)) == canonical:
                return match.group(0)
        return canonical

    def _provenance_note(self, content: str | None = None) -> str | None:
        """Build the one-line data note that satisfies the provenance checks.

        Args:
            content: The answer the note is appended to, so the symbol is
                printed the way that answer spells it.

        Returns:
            The note, or None when the run observed no price.
        """
        price_records = self._price_records()
        if not price_records:
            return None
        is_zh = self._user_writes_chinese()
        by_symbol: dict[str, list[EvidenceRecord]] = {}
        for record in price_records:
            by_symbol.setdefault(record.symbol or "unknown", []).append(record)
        parts = []
        for symbol, records in sorted(by_symbol.items()):
            sources = sorted(
                {
                    record.source
                    for record in records
                    if record.source and record.source.casefold() not in {"auto", "unknown"}
                }
            )
            currency = next((record.currency for record in records if record.currency), None)
            source_label = "/".join(sources) if sources else ("未知" if is_zh else "unknown")
            currency_label = currency or ("未知" if is_zh else "unknown")
            spelling = self._answer_symbol_spelling(symbol, content)
            parts.append(
                f"{spelling}：行情来源 {source_label}，计价货币 {currency_label}"
                if is_zh
                else f"{spelling}: price source {source_label}, quote currency {currency_label}"
            )
        if is_zh:
            return "数据说明：" + "；".join(parts) + "。"
        return "Data note: " + "; ".join(parts) + "."

    def repair_provenance(
        self,
        content: str,
        validation: ValidationResult,
    ) -> str | None:
        """Append a data note when the only defects are missing provenance words.

        Source and currency are known to the ledger, so naming them should not
        cost a model round. Any other issue returns None so the numeric checks
        keep their round; see ``_REPAIRABLE_PROVENANCE_CODES`` for why a missing
        symbol is not repaired.

        Args:
            content: The rejected draft.
            validation: Its validation result.

        Returns:
            The draft with a provenance note appended, or None when the issues
            are not provenance-only or there is no price evidence to cite.
        """
        codes = {issue.get("code") for issue in validation.issues}
        if not codes or not codes <= _REPAIRABLE_PROVENANCE_CODES:
            return None
        note = self._provenance_note(content)
        if note is None:
            return None
        return content.rstrip() + "\n\n" + note

    def redacted_release(self, content: str, validation: ValidationResult) -> str | None:
        """Release the last rejected draft with its unverified figures cut out.

        Each rejected figure becomes a marker at its own span, missing provenance
        is appended, unchecked restatements of a cut figure (bare, or inside a
        code fence, compared by normalized digits) are swept, and the result and
        its footnote are re-validated by the same gate. A block with an
        unreadable declaration line is dropped first, so every measured figure is
        checked as observed; if that alone passes, nothing is footnoted.
        Fail-closed: None when a market answer observed no price, an issue cannot
        be cut (an identity finding), a flagged figure cannot be located, or the
        text still fails. A general answer with no tool evidence is released cut,
        with a footnote that names no range.

        Args:
            content: The rejected draft.
            validation: Its validation result.

        Returns:
            The redacted, re-validated answer without its declaration block and
            with a note stating how many figures were removed, or None.
        """
        # A market answer with no observed price has nothing to stand on once its
        # figures are cut; a general answer (no instrument asked about) does.
        if self._identity_required and not self._price_records():
            return None
        text = _strip_release_markers(content)
        # Stripping shifts offsets and the cuts anchor on issue spans, so the
        # verdict is retaken on the stripped text.
        check = validation if text == content else self._validate(text, record=False)
        # An unreadable declaration cannot be cut, but the block is not answer
        # text either: without it the draft is checked in undeclared mode.
        dropped_block = any(
            issue.get("code") == "figures_block_malformed" for issue in check.issues
        )
        if dropped_block:
            text = strip_figures_block(text, parse_figures_block(text))
            check = self._validate(text, record=False)
        removed = 0
        keys: set[str] = set()
        for _ in range(_MAX_REDACTION_PASSES):
            if check.valid:
                break
            codes = {issue.get("code") for issue in check.issues}
            if not codes <= (_REDACTABLE_CODES | _REPAIRABLE_PROVENANCE_CODES):
                return None
            cut, cut_keys = self._cut_flagged(text, check.issues)
            if cut is None:
                return None
            if cut_keys:
                text = cut
                removed += len(cut_keys)
                keys.update(cut_keys)
                check = self._validate(text, record=False)
                if check.valid:
                    break
            repaired = self.repair_provenance(text, check)
            if repaired is None:
                if not cut_keys:
                    return None
                continue
            text = repaired
            check = self._validate(text, record=False)
        if not check.valid or (removed == 0 and not dropped_block):
            return None
        # A cut figure can still be standing where the shape rules never look.
        swept, swept_keys = self._sweep_same_values(text, keys - {""})
        if swept_keys:
            recheck = self._validate(swept, record=False)
            if not recheck.valid:
                return None
            text, check, removed = swept, recheck, removed + len(swept_keys)
        body = check.released_text
        released = body
        if removed:
            note = self._release_note(removed, body)
            # The note is answer text too (range, symbols), so it passes the
            # same gate, in undeclared mode.
            if not self._validate(note, record=False).valid:
                return None
            released = body.rstrip() + "\n\n" + note
        # Recorded beside the drafts, not as one: every recheck here is
        # unrecorded, so this is the artifact's only evidence of the release.
        self._released = {
            "released_at": _utc_now(),
            "content_sha256": hashlib.sha256(released.encode("utf-8")).hexdigest(),
            "figures_removed": removed,
            "revalidated": True,
        }
        self.persist()
        return released

    @staticmethod
    def _issue_span(text: str, issue: dict[str, Any]) -> tuple[int, int] | None:
        """Locate the flagged figure in ``text`` by its recorded character span.

        The span is the only reliable anchor: a bare cell "1.10" also matches
        inside "21.10".

        Args:
            text: The document the issue was raised against.
            issue: One validation issue.

        Returns:
            ``(start, end)`` or None when the issue carries no usable span.
        """
        span = issue.get("span")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            return None
        try:
            start, end = int(span[0]), int(span[1])
        except (TypeError, ValueError):
            return None
        if 0 <= start <= end <= len(text):
            return start, end
        return None

    def _cut_flagged(
        self,
        text: str,
        issues: Sequence[dict[str, Any]],
    ) -> tuple[str | None, list[str]]:
        """Replace every flagged figure with the omission marker.

        An issue without a value (``unsourced_symbol_figures``) cuts every
        measured figure inside its span; any other issue must name the span of
        a figure the scan located.

        Args:
            text: The document to rewrite.
            issues: The issues raised against it.

        Returns:
            ``(rewritten text, normalized digits of each figure cut)``, or
            ``(None, [])`` when a flagged figure cannot be located and release
            must fail closed.
        """
        figures = scan_figures(text, parse_figures_block(text))
        located = {(figure.start, figure.end): figure for figure in figures}
        cuts: dict[tuple[int, int], Figure] = {}
        for issue in issues:
            if issue.get("code") not in _REDACTABLE_CODES:
                continue
            span = self._issue_span(text, issue)
            if span is None:
                return None, []
            if issue.get("value") is None:
                cuts.update(
                    ((figure.start, figure.end), figure)
                    for figure in figures
                    if figure.shape == "measured"
                    and span[0] <= figure.start
                    and figure.end <= span[1]
                )
            elif span in located:
                cuts[span] = located[span]
            else:
                return None, []
        return self._apply_cuts(text, cuts.values())

    def _sweep_same_values(self, text: str, keys: set[str]) -> tuple[str, list[str]]:
        """Cut every unchecked restatement of a figure that was already cut.

        After "回撤 37%" is cut, "回撤 37 个百分点" still carries an unchecked bare
        "37", and a code fence can still print it. Figures compare by normalized
        digits, so an escaped spelling is the same restatement. Measured prose
        survivors were checked and grounded, and the figures block is not
        answer text, so neither is swept. A single-digit figure is never a
        sweep key.

        Args:
            text: The already-cut document.
            keys: Normalized digits of the figures that were cut.

        Returns:
            ``(rewritten text, normalized digits of each figure swept)``.
        """
        # One digit restates nothing: every "2" and "3" on the page shares it, and
        # sweeping them took list references and counts with the figure (#1471).
        keys = {key for key in keys if len(key) > 1}
        if not keys:
            return text, []
        stale = [
            figure
            for figure in scan_figures(text, parse_figures_block(text))
            if figure.digits in keys
            and (
                figure.shape == "bare"
                or (figure.fence is not None and figure.fence != BLOCK_LANGUAGE)
            )
        ]
        return self._apply_cuts(text, stale)

    def _apply_cuts(
        self,
        text: str,
        figures: Iterable[Figure],
    ) -> tuple[str, list[str]]:
        """Replace each figure and its glued marks with the marker in its line's script.

        Args:
            text: The document to rewrite.
            figures: The figures to remove.

        Returns:
            ``(rewritten text, normalized digits of each figure removed)``.
        """
        pieces: list[str] = []
        removed: list[str] = []
        cursor = 0
        for figure in sorted(figures, key=lambda item: (item.start, item.end)):
            if figure.start < cursor:
                continue
            removed.append(figure.digits)
            start, end = figure.extent or (figure.start, figure.end)
            start = max(cursor, start)
            marker = self._marker_for(text, start)
            if marker is _REDACTION_MARKER_ZH:
                # "建议买入价 0.95 元" → "建议买入价（略※）": flush against the word,
                # but not against a table pipe, which would break the row's padding.
                while (
                    start > cursor
                    and text[start - 1] == " "
                    and text[:start - 1].rstrip(" ")[-1:] not in {"|", ""}
                ):
                    start -= 1
            pieces.append(text[cursor:start])
            pieces.append(marker)
            cursor = end
        pieces.append(text[cursor:])
        return "".join(pieces), removed

    def _marker_for(self, text: str, position: int) -> str:
        """Pick the omission marker in the script of the line being cut.

        A line with neither script (a numeric table row) uses the user's language.
        """
        line = ""
        for candidate, start in _lines_with_offsets(text):
            if start <= position <= start + len(candidate):
                line = candidate
                break
        if any("\u3400" <= char <= "\u9fff" for char in line):
            return _REDACTION_MARKER_ZH
        if any(char.isascii() and char.isalpha() for char in line):
            return _REDACTION_MARKER_EN
        return (
            _REDACTION_MARKER_ZH
            if self._user_writes_chinese()
            else _REDACTION_MARKER_EN
        )

    def _release_note(self, removed: int, content: str | None = None) -> str:
        """Explain the redaction to the user, with the observed range."""
        is_zh = self._user_writes_chinese()
        joined = self._observed_range_summary(is_zh, content)
        if joined is None:
            if is_zh:
                return f"※ 略去 {removed} 处无法与本会话工具数据对上的数值。"
            return (
                f"※ {removed} figure(s) that could not be matched to this session's "
                "tool data were omitted."
            )
        if is_zh:
            return (
                f"※ 略去 {removed} 处无法与本会话工具数据对上的数值。"
                f"已观测 OHLC 范围：{joined}。"
                "如需买入价，请让我基于已观测的收盘价或均线给出带公式的推导。"
            )
        return (
            f"※ {removed} figure(s) that could not be matched to this session's tool data "
            f"were omitted. Observed OHLC range: {joined}. "
            "For an entry price, ask me to derive one with a visible formula from an "
            "observed close or moving average."
        )
