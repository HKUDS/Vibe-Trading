"""Opt-in financial facts envelope for immutable research artifact content.

Validation is structural and does not independently verify issuer statements.
"""

from __future__ import annotations

import json
import math
from datetime import date
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = "financial-facts/v1"
STATUSES = {"verified", "partial", "unavailable"}
KINDS = {"duration", "instant"}
MAX_FACTS = 1000
# Currency may be null only when units unambiguously denote non-money.
# Scale-only units such as "millions" can describe money or shares.
NON_MONETARY_UNITS = frozenset({
    "share", "shares", "thousand shares", "thousands of shares",
    "million shares", "millions of shares", "%", "percent",
    "percentage", "percentage point", "percentage points", "pp",
    "basis point", "basis points", "bps", "ratio", "times", "x",
    "day", "days", "year", "years", "employee", "employees",
    "person", "people",
})


def _currency_optional(unit: str) -> bool:
    """Accept missing currency only for clearly non-monetary units."""
    return unit.strip().casefold() in NON_MONETARY_UNITS



def _date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be an ISO date")
    return parsed


def _url(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an HTTPS URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or any(ch.isspace() for ch in value)
    ):
        raise ValueError(f"{field} must be an HTTPS URL")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value


def validate_financial_facts(document: object) -> dict[str, Any]:
    """Validate shape, temporal identity and internal evidence consistency.

    A 'verified' label remains an assertion by the research author, not
    independent confirmation of a number from the cited filing.
    """
    if not isinstance(document, dict):
        raise ValueError("financial facts document must be an object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported financial facts schema_version")
    subject = _text(document.get("subject"), "subject").strip()
    sources = document.get("sources")
    if not isinstance(sources, list):
        raise ValueError("sources must be a list")
    indexed_sources: dict[str, str] = {}
    for i, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"sources[{i}] must be an object")
        source_id = _text(source.get("id"), f"sources[{i}].id")
        source_url = _url(source.get("url"), f"sources[{i}].url")
        if source_id in indexed_sources:
            raise ValueError(f"duplicate source id: {source_id}")
        indexed_sources[source_id] = source_url

    facts = document.get("facts")
    if not isinstance(facts, list) or not 1 <= len(facts) <= MAX_FACTS:
        raise ValueError("facts must contain between 1 and 1000 records")
    seen: set[tuple[object, ...]] = set()
    normalized: list[dict[str, Any]] = []
    for i, fact in enumerate(facts):
        prefix = f"facts[{i}]"
        if not isinstance(fact, dict):
            raise ValueError(f"{prefix} must be an object")
        required = (
            "metric",
            "period_kind",
            "scope",
            "definition",
            "verification_status",
            "value",
            "currency",
            "unit",
            "source_id",
            "source_section",
        )
        missing = [key for key in required if key not in fact]
        if missing:
            raise ValueError(f"{prefix} missing fields: {', '.join(missing)}")
        for key in ("metric", "scope", "definition"):
            _text(fact[key], f"{prefix}.{key}")
        kind = fact["period_kind"]
        if kind not in KINDS:
            raise ValueError(f"{prefix}.period_kind must be duration or instant")
        if kind == "duration":
            start = _date(fact.get("period_start"), f"{prefix}.period_start")
            end = _date(fact.get("period_end"), f"{prefix}.period_end")
            if start > end or fact.get("as_of_date") is not None:
                raise ValueError(f"{prefix}: invalid duration dates")
            period_identity = (start.isoformat(), end.isoformat())
        else:
            as_of = _date(fact.get("as_of_date"), f"{prefix}.as_of_date")
            if (
                fact.get("period_start") is not None
                or fact.get("period_end") is not None
            ):
                raise ValueError(f"{prefix}: instant facts cannot have duration dates")
            period_identity = (as_of.isoformat(),)

        status = fact["verification_status"]
        if status not in STATUSES:
            raise ValueError(f"{prefix}.verification_status is invalid")
        value = fact["value"]
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(f"{prefix}.value must be finite numeric or null")
        if status == "unavailable" and value is not None:
            raise ValueError(f"{prefix}: unavailable facts must have null value")
        if status == "verified" and value is None:
            raise ValueError(f"{prefix}: verified facts require a numeric value")

        for key in ("currency", "unit", "source_id", "source_section"):
            item = fact[key]
            if item is not None:
                _text(item, f"{prefix}.{key}")
        source_id = fact["source_id"]
        if source_id is not None and source_id not in indexed_sources:
            raise ValueError(f"{prefix}: source_id not found in sources")
        if status == "verified" and (
            not source_id
            or not fact["source_section"]
            or not fact["unit"]
        ):
            raise ValueError(f"{prefix}: verified facts require provenance and units")
        if (
            status == "verified"
            and not fact["currency"]
            and not _currency_optional(fact["unit"])
        ):
            raise ValueError(
                f"{prefix}: verified monetary or ambiguous units require currency"
            )
        page = fact.get("source_page")
        if page is not None and (
            isinstance(page, bool) or not isinstance(page, (str, int))
        ):
            raise ValueError(f"{prefix}.source_page must be string, integer or null")

        # One fact per metric, time window, accounting scope and unit.
        # Distinct definitions must not silently mask contradictory values.
        identity = (
            fact["metric"],
            kind,
            period_identity,
            fact["scope"],
            fact["currency"],
            fact["unit"],
        )
        if identity in seen:
            raise ValueError(f"{prefix}: duplicate financial fact identity")
        seen.add(identity)
        normalized.append(dict(fact))
    return {
        "schema_version": SCHEMA_VERSION,
        "subject": subject,
        "sources": [dict(source) for source in sources],
        "facts": normalized,
    }


def encode_financial_facts(document: object) -> str:
    """Serialize a validated envelope for ResearchArtifactStore.save(content=...)."""
    return json.dumps(
        validate_financial_facts(document),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def decode_financial_facts(content: str) -> dict[str, Any]:
    """Read an envelope from a research revision; reject legacy narrative."""
    try:
        document = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "research content is not a financial facts JSON envelope"
        ) from exc
    return validate_financial_facts(document)
