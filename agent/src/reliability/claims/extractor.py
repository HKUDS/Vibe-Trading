"""Deterministic structured claim extraction for v1.2.1 research cards."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping
from typing import Any

from src.governance.evidence_identity import canonical_json
from src.reliability.claims.model import ClaimSet, ClaimSource, ClaimType, ResearchClaim
from src.reliability.claims.validators import validate_claim_set

EXTRACTOR_VERSION = "deterministic-v1.2.1"
_CONCLUSION_RANK = {
    "not_reliable": 0,
    "exploratory": 1,
    "research_candidate": 2,
    "paper_trade_candidate": 3,
    "production_ready": 4,
}
_CLAIM_TYPES: tuple[ClaimType, ...] = (
    "tradable",
    "alpha",
    "generalization",
    "paper_trade_candidate",
    "production_ready",
    "factor_novelty",
    "risk_reduction",
    "data_quality",
    "execution_realism",
)


def build_claim_set_from_research_card(
    research_card: Mapping[str, Any],
    *,
    validate: bool = True,
    llm_hook: Callable[[Mapping[str, Any]], list[Mapping[str, Any]]] | None = None,
) -> ClaimSet:
    """Build a ClaimSet from structured card fields only.

    The optional LLM hook is intentionally disabled under CI and is not used by
    default. Phase 3 records claims; Phase 4 enforces gates over them.
    """
    if llm_hook is not None and _ci_enabled():
        raise RuntimeError("LLM-assisted claim extraction is disabled in CI")
    run_id = str(research_card.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("research_card.run_id is required")

    claims = _extract_structured_claims(research_card, run_id=run_id)
    if llm_hook is not None:
        for item in llm_hook(research_card):
            claim = _claim_from_mapping(item, run_id=run_id, default_source_ref="llm_hook")
            if claim is not None:
                claims.append(claim)
    if not claims and _conclusion_at_least_research_candidate(research_card.get("conclusion_level")):
        claims.append(_implicit_research_candidate_claim(research_card, run_id=run_id))

    deduped = _dedupe_claims(claims)
    claim_set = ClaimSet(
        claim_set_id=_claim_set_id(run_id, deduped),
        run_id=run_id,
        claims=deduped,
        extractor_version=EXTRACTOR_VERSION,
        generated_by="research_card.claim_extractor",
    )
    if validate:
        validate_claim_set(claim_set)
    return claim_set


def _extract_structured_claims(research_card: Mapping[str, Any], *, run_id: str) -> list[ResearchClaim]:
    claims: list[ResearchClaim] = []
    for index, item in enumerate(_as_list(research_card.get("structured_claims"))):
        claim = _claim_from_mapping(
            item,
            run_id=run_id,
            default_source_ref=f"research_card.structured_claims[{index}]",
        )
        if claim is not None:
            claims.append(claim)
    claims.extend(_claims_from_claim_map(research_card.get("claims"), run_id=run_id))
    for claim_type in _CLAIM_TYPES:
        field_name = f"{claim_type}_claim"
        value = research_card.get(field_name)
        if isinstance(value, str) and value.strip():
            claims.append(
                _make_claim(
                    run_id=run_id,
                    claim_type=claim_type,
                    claim_text=value,
                    source="research_card",
                    source_ref=f"research_card.{field_name}",
                    confidence=None,
                    requires_gate=True,
                    evidence_refs=[],
                )
            )
    return claims


def _claims_from_claim_map(value: Any, *, run_id: str) -> list[ResearchClaim]:
    if not isinstance(value, Mapping):
        return []
    claims: list[ResearchClaim] = []
    for claim_type, item in value.items():
        if claim_type not in _CLAIM_TYPES:
            continue
        if isinstance(item, str):
            claims.append(
                _make_claim(
                    run_id=run_id,
                    claim_type=claim_type,  # type: ignore[arg-type]
                    claim_text=item,
                    source="research_card",
                    source_ref=f"research_card.claims.{claim_type}",
                    confidence=None,
                    requires_gate=True,
                    evidence_refs=[],
                )
            )
        elif isinstance(item, Mapping):
            claim = _claim_from_mapping(
                {"claim_type": claim_type, **dict(item)},
                run_id=run_id,
                default_source_ref=f"research_card.claims.{claim_type}",
            )
            if claim is not None:
                claims.append(claim)
    return claims


def _claim_from_mapping(
    item: Mapping[str, Any],
    *,
    run_id: str,
    default_source_ref: str,
) -> ResearchClaim | None:
    raw_type = item.get("claim_type", item.get("type"))
    raw_text = item.get("claim_text", item.get("text"))
    if raw_type not in _CLAIM_TYPES or not isinstance(raw_text, str) or not raw_text.strip():
        return None
    source = item.get("source", "research_card")
    if source not in {"user_prompt", "assistant_final", "tool_output", "research_card", "manual_review"}:
        source = "research_card"
    return _make_claim(
        run_id=run_id,
        claim_type=raw_type,  # type: ignore[arg-type]
        claim_text=raw_text,
        source=source,  # type: ignore[arg-type]
        source_ref=item.get("source_ref") or default_source_ref,
        confidence=item.get("confidence"),
        requires_gate=bool(item.get("requires_gate", True)),
        evidence_refs=[str(ref) for ref in _as_list(item.get("evidence_refs"))],
    )


def _make_claim(
    *,
    run_id: str,
    claim_type: ClaimType,
    claim_text: str,
    source: ClaimSource,
    source_ref: str | None,
    confidence: Any,
    requires_gate: bool,
    evidence_refs: list[str],
) -> ResearchClaim:
    numeric_confidence = float(confidence) if confidence is not None else None
    payload = {
        "run_id": run_id,
        "claim_type": claim_type,
        "claim_text": claim_text.strip(),
        "source": source,
        "source_ref": source_ref,
        "evidence_refs": evidence_refs,
    }
    claim_id = f"claim_{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()[:32]}"
    return ResearchClaim(
        claim_id=claim_id,
        claim_type=claim_type,
        claim_text=claim_text,
        source=source,
        source_ref=source_ref,
        confidence=numeric_confidence,
        requires_gate=requires_gate,
        evidence_refs=evidence_refs,
    )


def _implicit_research_candidate_claim(
    research_card: Mapping[str, Any],
    *,
    run_id: str,
) -> ResearchClaim:
    conclusion = str(research_card.get("conclusion_level") or "research_candidate")
    claim_type = _implicit_claim_type_for_conclusion(conclusion)
    return _make_claim(
        run_id=run_id,
        claim_type=claim_type,
        claim_text=f"Research card conclusion '{conclusion}' implies a {claim_type} claim requiring methodology gates.",
        source="research_card",
        source_ref="research_card.conclusion_level",
        confidence=None,
        requires_gate=True,
        evidence_refs=[str(ref) for ref in _as_list(research_card.get("evidence_refs"))],
    )


def _claim_set_id(run_id: str, claims: list[ResearchClaim]) -> str:
    payload = {
        "run_id": run_id,
        "claims": [
            {
                "claim_id": claim.claim_id,
                "claim_type": claim.claim_type,
                "source_ref": claim.source_ref,
            }
            for claim in claims
        ],
        "extractor_version": EXTRACTOR_VERSION,
    }
    return f"claim_set_{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()[:32]}"


def _dedupe_claims(claims: list[ResearchClaim]) -> list[ResearchClaim]:
    deduped: list[ResearchClaim] = []
    seen: set[str] = set()
    for claim in claims:
        if claim.claim_id not in seen:
            deduped.append(claim)
            seen.add(claim.claim_id)
    return deduped


def _conclusion_at_least_research_candidate(value: Any) -> bool:
    return _CONCLUSION_RANK.get(str(value or "").strip().lower(), -1) >= _CONCLUSION_RANK["research_candidate"]


def _implicit_claim_type_for_conclusion(value: Any) -> ClaimType:
    conclusion = str(value or "").strip().lower()
    if conclusion in {"paper_trade_candidate", "production_ready"}:
        return conclusion  # type: ignore[return-value]
    return "generalization"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _ci_enabled() -> bool:
    return os.getenv("CI", "").strip().lower() in {"1", "true", "yes"}
