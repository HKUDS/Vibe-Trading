"""Explicit identity constraints carried beside the original conversation.

This module deliberately performs no query rewrite. It keeps the exact current
user message in memory and extracts only literal market words with source spans
that the grounding state machine can audit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

_CLAUSE_BOUNDARY_RE = re.compile(r"[,，;；。.!！?？\n]")
_MARKET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "cn",
        re.compile(
            r"(?<![A-Za-z])A\s*股|沪深(?:市场)?|上交所|深交所|上海证券交易所|深圳证券交易所|"
            r"\bA[- ]?shares?\b|\bmainland China (?:stock|listing|market)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hk",
        re.compile(
            r"港股|港交所|香港(?:市场|上市)|\bHK[- ]?(?:listed|stocks?|shares?)\b|"
            r"\bHong Kong (?:stock|listing|market)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "us",
        re.compile(
            r"美股|纳斯达克|纽交所|美国(?:市场|上市)|"
            r"\bU\.?S\.?[- ]?(?:listed|stocks?|shares?|market)\b|\bNASDAQ\b|\bNYSE\b",
            re.IGNORECASE,
        ),
    ),
)
# Letter boundaries keep a ticker's last letter out: "NVDA股票" is not A股,
# "NVDA和HOOD" / "NVDA/HOOD" are not an A/H cross-listing.
_CROSS_LISTING_RE = re.compile(
    r"(?<![A-Za-z])(?:A\s*股?\s*[/／和与、]\s*H\s*股?|H\s*股?\s*[/／和与、]\s*A\s*股?|A\s*H\s*股)"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)
_NEGATED_RE = re.compile(
    r"(?:不要|不看|不分析|排除|剔除|非).{0,12}$",
    re.IGNORECASE,
)
_HISTORY_RESET_RE = re.compile(
    r"忽略之前|不用之前|取消.{0,8}(?:限制|市场)|不限制市场|重新选择市场",
    re.IGNORECASE,
)
_SUBJECT_NOISE_RE = re.compile(
    r"我的|我们|请|想要|需要|持仓|标的|公司|股票|证券|市场|"
    r"包括|都是|均为|全部|这些|上述|以下|只看|都看|看|"
    r"分析|比较|两地|上市|表现|以及|和|与|及|的",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IdentityConstraint:
    """One explicit identity restriction found without rewriting the request."""

    subject_text: str | None
    dimension: str
    value: str
    source_message_id: str
    source_span: tuple[int, int]
    explicit: bool = True

    def audit_record(self) -> dict[str, Any]:
        """Return a trace-safe record without copying conversation text."""
        return {
            "dimension": self.dimension,
            "value": self.value,
            "source_message_id": self.source_message_id,
            "source_span": list(self.source_span),
            "explicit": self.explicit,
        }


@dataclass(frozen=True)
class ResolutionContext:
    """Immutable original request plus narrow, auditable identity constraints."""

    raw_user_message: str
    constraints: tuple[IdentityConstraint, ...] = ()

    @classmethod
    def from_messages(
        cls,
        raw_user_message: str,
        history: Sequence[Mapping[str, Any]] | None = None,
        *,
        enabled: bool = True,
    ) -> ResolutionContext:
        """Build context from user-authored text while preserving that text verbatim."""
        if not enabled:
            return cls(raw_user_message=raw_user_message)
        extracted: list[IdentityConstraint] = []
        retained_history = (
            () if _HISTORY_RESET_RE.search(raw_user_message) else history or ()
        )
        for index, message in enumerate(retained_history):
            if str(message.get("role") or "").casefold() != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                extracted.extend(
                    _extract_market_constraints(content, f"history:user:{index}")
                )
        extracted.extend(
            _extract_market_constraints(raw_user_message, "current_user_message")
        )
        return cls(raw_user_message=raw_user_message, constraints=tuple(extracted))

    def constraints_for(self, query: str) -> tuple[IdentityConstraint, ...]:
        """Return only constraints that can be tied to this resolver query."""
        normalized_query = _comparable_text(query)
        ranked: list[tuple[tuple[int, int], IdentityConstraint]] = []
        for constraint in self.constraints:
            if constraint.subject_text is not None:
                subject = _comparable_text(constraint.subject_text)
                if normalized_query and normalized_query in subject:
                    ranked.append(((_source_rank(constraint), 1), constraint))
                continue
            # A subject-free constraint is safe only in the current turn. Old
            # global instructions must not silently authorize a new subject.
            if constraint.source_message_id == "current_user_message":
                ranked.append(((_source_rank(constraint), 0), constraint))
        best_by_dimension: dict[str, tuple[int, int]] = {}
        for score, constraint in ranked:
            best_by_dimension[constraint.dimension] = max(
                score,
                best_by_dimension.get(constraint.dimension, score),
            )
        return tuple(
            constraint
            for score, constraint in ranked
            if score == best_by_dimension[constraint.dimension]
        )


def candidate_market(candidate: Mapping[str, Any]) -> str | None:
    """Normalize a resolver candidate's market without provider coupling."""
    symbol = str(candidate.get("symbol") or "").strip().upper()
    if symbol.endswith(".SS"):
        symbol = f"{symbol[:-3]}.SH"
    suffix = symbol.rsplit(".", 1)[-1] if "." in symbol else ""
    if suffix in {"SH", "SZ", "BJ"}:
        return "cn"
    if suffix == "HK":
        return "hk"
    if suffix == "US":
        return "us"
    raw = (
        str(candidate.get("market") or candidate.get("exchange") or "")
        .strip()
        .casefold()
    )
    return {
        "cn": "cn",
        "china": "cn",
        "a": "cn",
        "a-share": "cn",
        "hk": "hk",
        "hong kong": "hk",
        "us": "us",
        "usa": "us",
    }.get(raw)


def _comparable_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]", "", str(value or "").casefold())


def _source_rank(constraint: IdentityConstraint) -> int:
    if constraint.source_message_id == "current_user_message":
        return 1_000_000_000
    try:
        return int(constraint.source_message_id.rsplit(":", 1)[-1])
    except ValueError:
        return -1


def _constraint_clause(text: str, start: int, end: int) -> str:
    left = 0
    right = len(text)
    for match in _CLAUSE_BOUNDARY_RE.finditer(text):
        if match.end() <= start:
            left = match.end()
        elif match.start() >= end:
            right = match.start()
            break
    return text[left:right].strip()


def _constraint_is_negated(text: str, start: int) -> bool:
    clause_start = 0
    for match in _CLAUSE_BOUNDARY_RE.finditer(text[:start]):
        clause_start = match.end()
    return bool(_NEGATED_RE.search(text[clause_start:start]))


def _constraint_subject(clause: str) -> str | None:
    """Keep a named clause; collapse a pure follow-up like ``都只看 A 股``."""
    remainder = _CROSS_LISTING_RE.sub("", clause)
    for _, pattern in _MARKET_PATTERNS:
        remainder = pattern.sub("", remainder)
    remainder = _SUBJECT_NOISE_RE.sub("", remainder)
    return clause if len(_comparable_text(remainder)) >= 2 else None


def _extract_market_constraints(
    text: str,
    source_message_id: str,
) -> list[IdentityConstraint]:
    constraints: list[IdentityConstraint] = []
    cross_spans: list[tuple[int, int]] = []
    for match in _CROSS_LISTING_RE.finditer(text or ""):
        if _constraint_is_negated(text, match.start()):
            continue
        cross_spans.append(match.span())
        clause = _constraint_clause(text, *match.span())
        subject = _constraint_subject(clause)
        constraints.extend(
            IdentityConstraint(
                subject_text=subject,
                dimension="market",
                value=value,
                source_message_id=source_message_id,
                source_span=match.span(),
            )
            for value in ("cn", "hk")
        )
    for value, pattern in _MARKET_PATTERNS:
        for match in pattern.finditer(text or ""):
            if _constraint_is_negated(text, match.start()):
                continue
            if any(
                start <= match.start() and match.end() <= end
                for start, end in cross_spans
            ):
                continue
            clause = _constraint_clause(text, *match.span())
            constraints.append(
                IdentityConstraint(
                    subject_text=_constraint_subject(clause),
                    dimension="market",
                    value=value,
                    source_message_id=source_message_id,
                    source_span=match.span(),
                )
            )
    return constraints


__all__ = ["IdentityConstraint", "ResolutionContext", "candidate_market"]
