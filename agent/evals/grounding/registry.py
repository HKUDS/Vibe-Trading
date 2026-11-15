"""Declared grounding checks: one registry entry per check (#1622).

The grounding verifier used to grow by editing shared control flow in
``policies.py``; every incident landed as another inline rule. This registry
makes a check a declared row instead: a stable name, the issue code it emits
(the release decision tables key on codes, so they stay the single decision
owner), a description, and the predicate. Adding a check is adding a row plus
a fixture pair, not touching call flow.

Migration is golden-pass: existing suites must pass unchanged while checks
move over one at a time. ``GROUNDING_CHECKS`` walks in registration order;
the gate walks ordered phases and per-role predicates at their original
positions. All current checks block; severity describes the gate verdict,
not the independent repair/redaction decision owned by release.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

if TYPE_CHECKING:
    from evals.grounding.ledger import GroundingLedger

# A predicate gets the ledger (identity/figure state lives there) and the
# candidate answer, and returns issue dicts in the existing shape.
GroundingPredicate = Callable[..., list[dict[str, Any]]]


@dataclass(frozen=True)
class GroundingCheck:
    """One declared grounding check.

    Attributes:
        name: Stable identifier, shown when a run card lists fired checks.
        code: The issue code the predicate emits. Release decisions key on
            codes, so a registered check never invents a new one without a
            matching decision entry.
        description: What the check rejects, for the run card and docs.
        predicate: The check itself, with phase-specific arguments.
        severity: Block the draft, or record a warning/log finding only.
        phase: Ordered execution phase; manual predicates are dispatched by role.
        order: Order within a phase, preserving short-circuit semantics.
        additional_codes: Other issue codes this predicate can emit.
    """

    name: str
    code: str
    description: str
    predicate: GroundingPredicate
    severity: Literal["block", "warn", "log"] = "block"
    phase: str = "manual"
    order: int = 0
    additional_codes: tuple[str, ...] = ()


class GroundingRegistry:
    """Ordered registry of grounding checks. Duplicate names are rejected."""

    def __init__(self) -> None:
        self._checks: dict[str, GroundingCheck] = {}

    def register(self, check: GroundingCheck) -> GroundingCheck:
        if check.severity not in {"block", "warn", "log"}:
            raise ValueError(f"invalid grounding severity: {check.severity}")
        if check.name in self._checks:
            raise ValueError(f"duplicate grounding check: {check.name}")
        self._checks[check.name] = check
        return check

    def get(self, name: str) -> GroundingCheck:
        return self._checks[name]

    def run(self, name: str, ledger: "GroundingLedger", *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Run a declared predicate and record its actual findings, not code guesses."""
        check = self._checks[name]
        issues = check.predicate(ledger, *args, **kwargs)
        if issues:
            undeclared = {str(issue.get("code")) for issue in issues} - {check.code, *check.additional_codes}
            if undeclared:
                raise ValueError(f"{name} emitted undeclared grounding codes: {sorted(undeclared)}")
            findings = getattr(ledger, "_active_check_findings", None)
            if findings is not None:
                findings.append({"name": name, "severity": check.severity, "issues": issues})
        return issues if check.severity == "block" else []

    def walk(self, ledger: "GroundingLedger", *args: Any, phase: str = "manual", **kwargs: Any):
        """Run one ordered phase; role predicates receive their own typed arguments."""
        checks = sorted((c for c in self._checks.values() if c.phase == phase), key=lambda c: c.order)
        return [(check, self.run(check.name, ledger, *args, **kwargs)) for check in checks]

    def run_phase(self, phase: str, ledger: "GroundingLedger", *args: Any, **kwargs: Any):
        """Flatten findings without changing predicate or issue order."""
        return [issue for _, issues in self.walk(ledger, *args, phase=phase, **kwargs) for issue in issues]

    def names_for_codes(self, codes: set[str]) -> list[str]:
        """Names of registered checks emitting any of ``codes``, in registration order.

        Catalog lookup only. Never use this to attribute actual execution: several
        predicates can emit the same code.
        """
        return [check.name for check in self._checks.values() if codes.intersection((check.code, *check.additional_codes))]

    def describe(self) -> list[dict[str, Any]]:
        """The check catalog for run cards and docs, in registration order."""
        return [{"name": c.name, "code": c.code, "additional_codes": list(c.additional_codes),
                 "description": c.description, "severity": c.severity, "phase": c.phase}
                for c in self._checks.values()]

    def __len__(self) -> int:
        return len(self._checks)


GROUNDING_CHECKS = GroundingRegistry()


def grounding_check(
    *, name: str, code: str, description: str,
    severity: Literal["block", "warn", "log"] = "block", phase: str = "manual",
    order: int = 0, additional_codes: tuple[str, ...] = (),
):
    """Decorator: register a predicate as a declared grounding check."""

    def wrap(predicate: GroundingPredicate) -> GroundingPredicate:
        GROUNDING_CHECKS.register(GroundingCheck(
            name=name, code=code, description=description, predicate=predicate,
            severity=severity, phase=phase, order=order, additional_codes=additional_codes,
        ))
        return predicate

    return wrap
