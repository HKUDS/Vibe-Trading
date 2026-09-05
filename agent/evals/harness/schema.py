"""Versioned models for deterministic Harness evaluation cases and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping


class VerdictStatus(str, Enum):
    """A single assertion outcome."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    INVALID_ARTIFACT = "INVALID_ARTIFACT"


@dataclass(frozen=True)
class HarnessCase:
    """One natural-language prompt plus evaluator-only expectations."""

    schema_version: int
    case_id: str
    scenario: str
    prompt: str
    history: tuple[Mapping[str, Any], ...]
    data_snapshot: str | None
    expect: Mapping[str, Any]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "HarnessCase":
        """Validate and construct schema version 1."""
        if not isinstance(data, Mapping):
            raise ValueError("case must be a JSON object")
        if data.get("schema_version") != 1:
            raise ValueError("unsupported case schema_version; expected 1")
        case_id = data.get("case_id")
        scenario = data.get("scenario")
        prompt = data.get("prompt")
        history = data.get("history", [])
        expect = data.get("expect")
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be a non-empty string")
        if not isinstance(scenario, str) or not scenario.strip():
            raise ValueError("scenario must be a non-empty string")
        if not isinstance(prompt, str):
            raise ValueError("prompt must be a string")
        if not isinstance(history, list) or not all(
            isinstance(item, Mapping) for item in history
        ):
            raise ValueError("history must be an array of objects")
        if not isinstance(expect, Mapping):
            raise ValueError("expect must be an object")
        _validate_expectations(expect)

        snapshot = data.get("data_snapshot")
        if snapshot is not None:
            if not isinstance(snapshot, str) or not snapshot:
                raise ValueError(
                    "data_snapshot must be a non-empty relative path or null"
                )
            path = PurePosixPath(snapshot)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("data_snapshot must stay inside the case fixture tree")

        return cls(
            schema_version=1,
            case_id=case_id,
            scenario=scenario,
            prompt=prompt,
            history=tuple(history),
            data_snapshot=snapshot,
            expect=expect,
        )


def _validate_expectations(expect: Mapping[str, Any]) -> None:
    for name in ("execution", "completion", "safety"):
        section = expect.get(name)
        if section is None:
            continue
        if not isinstance(section, Mapping) or not _is_string_list(
            section.get("allowed")
        ):
            raise ValueError(f"expect.{name}.allowed must be an array of strings")
        if section.get("on_missing", "not_evaluable") != "not_evaluable":
            raise ValueError(
                f"expect.{name}.on_missing currently supports only not_evaluable"
            )

    tools = expect.get("tools")
    if tools is not None:
        if not isinstance(tools, Mapping):
            raise ValueError("expect.tools must be an object")
        for key in ("required", "forbidden"):
            values = tools.get(key, [])
            if not isinstance(values, list):
                raise ValueError(f"expect.tools.{key} must be an array")
            for value in values:
                if isinstance(value, str):
                    continue
                if not isinstance(value, Mapping) or not isinstance(
                    value.get("name"), str
                ):
                    raise ValueError(f"expect.tools.{key} entries must name a tool")
                minimum = value.get("min_calls", 1)
                arguments = value.get("arguments", {})
                if not _is_non_negative_int(minimum) or not isinstance(
                    arguments, Mapping
                ):
                    raise ValueError(
                        f"expect.tools.{key} has invalid min_calls or arguments"
                    )
        maximum = tools.get("max_false_skips")
        if maximum is not None and not _is_non_negative_int(maximum):
            raise ValueError(
                "expect.tools.max_false_skips must be a non-negative integer or null"
            )

    identity = expect.get("identity")
    if identity is not None:
        if not isinstance(identity, Mapping):
            raise ValueError("expect.identity must be an object")
        if "status" in identity and not isinstance(identity["status"], str):
            raise ValueError("expect.identity.status must be a string")
        for key in ("authorized_symbols", "forbidden_symbols"):
            if key in identity and not _is_string_list(identity[key]):
                raise ValueError(f"expect.identity.{key} must be an array of strings")
        if "constraint" in identity and not isinstance(identity["constraint"], Mapping):
            raise ValueError("expect.identity.constraint must be an object")

    evidence = expect.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, Mapping):
            raise ValueError("expect.evidence must be an object")
        for key in ("required_symbols", "forbidden_issue_codes"):
            if key in evidence and not _is_string_list(evidence[key]):
                raise ValueError(f"expect.evidence.{key} must be an array of strings")

    budget = expect.get("budget")
    if budget is not None:
        if not isinstance(budget, Mapping):
            raise ValueError("expect.budget must be an object")
        for key in (
            "max_llm_calls",
            "max_input_tokens",
            "max_iterations",
            "max_visible_tools",
            "max_tool_schema_tokens",
        ):
            if budget.get(key) is not None and not _is_non_negative_int(budget[key]):
                raise ValueError(
                    f"expect.budget.{key} must be a non-negative integer or null"
                )

    risk = expect.get("risk")
    if risk is not None:
        if not isinstance(risk, Mapping):
            raise ValueError("expect.risk must be an object")
        if not _is_string_list(risk.get("forbidden_successful_tools", [])):
            raise ValueError(
                "expect.risk.forbidden_successful_tools must be an array of strings"
            )
        maximum = risk.get("max_authorization_bypasses")
        if maximum is not None and not _is_non_negative_int(maximum):
            raise ValueError(
                "expect.risk.max_authorization_bypasses must be a non-negative integer or null"
            )


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class Verdict:
    """Machine-readable result for one deterministic assertion."""

    status: VerdictStatus
    code: str
    expected: Any
    observed: Any
    evidence_refs: tuple[str, ...] = ()
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload


@dataclass(frozen=True)
class EvaluationReport:
    """All verdicts for one case against one artifact bundle."""

    schema_version: int
    case_id: str
    scenario: str
    artifact_root: str
    verdicts: tuple[Verdict, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def status_counts(self) -> dict[str, int]:
        """Count outcomes without hiding unevaluated coverage."""
        counts = {status.value: 0 for status in VerdictStatus}
        for verdict in self.verdicts:
            counts[verdict.status.value] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON report."""
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "scenario": self.scenario,
            "artifact_root": self.artifact_root,
            "status_counts": self.status_counts,
            "verdicts": [verdict.to_dict() for verdict in self.verdicts],
            "metadata": dict(self.metadata),
        }
