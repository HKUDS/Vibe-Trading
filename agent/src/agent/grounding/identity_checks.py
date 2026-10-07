"""Declared identity checks for the grounding gate (#1622).

First checks migrated off the inline rule list in ``policies.py``; the
predicates are byte-for-byte the logic that used to run inline, now declared
with a stable name so run cards can say what fired.
"""

from __future__ import annotations

import re
from typing import Any

from src.agent.grounding.registry import grounding_check

#: An answer that relabels a locked listed identity as private contradicts the
#: resolver, which is an identity finding rather than a figure finding.
_PRIVATE_ASSERTION_RE = re.compile(
    r"(?:\b(?:is|remains|still)\s+(?:an?\s+)?(?:private company|privately held)\b|"
    r"\bnot publicly traded\b|\bunlisted company\b|"
    r"(?:是|仍是|属于)(?:一家)?(?:私人|私营|非上市)公司|未上市|没有上市)",
    re.IGNORECASE,
)


@grounding_check(
    name="listed-identity-relabelled-private",
    code="listed_identity_relabelled_private",
    description=(
        "A locked listed identity (security or fund) was relabelled as "
        "private or unlisted in the answer without a conflicting resolver result."
    ),
)
def _listed_identity_relabelled_private(ledger: Any, content: str) -> list[dict[str, Any]]:
    listed = [
        record
        for record in ledger._identities.values()
        if record.status == "locked" and record.instrument_type in {"listed_security", "fund"}
    ]
    if not listed or not _PRIVATE_ASSERTION_RE.search(content):
        return []
    symbols = sorted(record.symbol for record in listed if record.symbol)
    return [
        {
            "code": "listed_identity_relabelled_private",
            "symbols": symbols,
            "value": None,
            "role": None,
            "span": None,
            "symbol": None,
            "reason": "listed_relabelled_private",
            "message": (
                f"Locked listed identity {', '.join(symbols)} was relabelled as "
                "private/unlisted without a conflicting resolver result."
            ),
        }
    ]
