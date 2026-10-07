"""Declared grounding checks: one registry entry per check (#1622).

The grounding verifier used to grow by editing shared control flow in
``policies.py``; every incident landed as another inline rule. This registry
makes a check a declared row instead: a stable name, the issue code it emits
(the release decision tables key on codes, so they stay the single decision
owner), a description, and the predicate. Adding a check is adding a row plus
a fixture pair, not touching call flow.

Migration is golden-pass: existing suites must pass unchanged while checks
move over one at a time. ``GROUNDING_CHECKS`` walks in registration order;
the gate in ``ledger.py`` keeps built-ins first and walks the registry where
each migrated check used to run inline, so issue order is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src.agent.grounding.ledger import GroundingLedger

# A predicate gets the ledger (identity/figure state lives there) and the
# candidate answer, and returns issue dicts in the existing shape.
GroundingPredicate = Callable[["GroundingLedger", str], list[dict[str, Any]]]


@dataclass(frozen=True)
class GroundingCheck:
    """One declared grounding check.

    Attributes:
        name: Stable identifier, shown when a run card lists fired checks.
        code: The issue code the predicate emits. Release decisions key on
            codes, so a registered check never invents a new one without a
            matching decision entry.
        description: What the check rejects, for the run card and docs.
        predicate: The check itself.
    """

    name: str
    code: str
    description: str
    predicate: GroundingPredicate


class GroundingRegistry:
    """Ordered registry of grounding checks. Duplicate names are rejected."""

    def __init__(self) -> None:
        self._checks: dict[str, GroundingCheck] = {}

    def register(self, check: GroundingCheck) -> GroundingCheck:
        if check.name in self._checks:
            raise ValueError(f"duplicate grounding check: {check.name}")
        self._checks[check.name] = check
        return check

    def get(self, name: str) -> GroundingCheck:
        return self._checks[name]

    def run(self, name: str, ledger: "GroundingLedger", content: str) -> list[dict[str, Any]]:
        return self._checks[name].predicate(ledger, content)

    def walk(self, ledger: "GroundingLedger", content: str) -> list[tuple[GroundingCheck, list[dict[str, Any]]]]:
        """Every check with its issues, in registration order."""
        return [(check, check.predicate(ledger, content)) for check in self._checks.values()]

    def names_for_codes(self, codes: set[str]) -> list[str]:
        """Names of registered checks emitting any of ``codes``, in registration order.

        Codes from rules that still run inline resolve to no name; they get one
        when the check is migrated.
        """
        return [check.name for check in self._checks.values() if check.code in codes]

    def describe(self) -> list[dict[str, str]]:
        """The check catalog for run cards and docs, in registration order."""
        return [{"name": c.name, "code": c.code, "description": c.description} for c in self._checks.values()]

    def __len__(self) -> int:
        return len(self._checks)


GROUNDING_CHECKS = GroundingRegistry()


def grounding_check(*, name: str, code: str, description: str):
    """Decorator: register a predicate as a declared grounding check."""

    def wrap(predicate: GroundingPredicate) -> GroundingPredicate:
        GROUNDING_CHECKS.register(GroundingCheck(name=name, code=code, description=description, predicate=predicate))
        return predicate

    return wrap
