"""Small validators and matchers shared by Harness assertions."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def contains(observed: Any, expected_subset: Any) -> bool:
    """Recursively match an evaluator-declared subset against an observation."""
    if expected_subset in (None, {}):
        return True
    if isinstance(expected_subset, Mapping):
        if not isinstance(observed, Mapping):
            return False
        return all(
            key in observed and contains(observed[key], value)
            for key, value in expected_subset.items()
        )
    if isinstance(expected_subset, list):
        if not isinstance(observed, list) or len(observed) < len(expected_subset):
            return False
        return all(
            any(contains(candidate, item) for candidate in observed)
            for item in expected_subset
        )
    return observed == expected_subset


def mapping(value: Any) -> Mapping[str, Any]:
    """Return a mapping view or an empty mapping for malformed optional data."""
    return value if isinstance(value, Mapping) else {}


def string_list(value: Any) -> list[str] | None:
    """Return a validated string list."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


def successful_tool_records(
    trace: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Return executed or cached successful tool outcomes."""
    return [
        record
        for record in trace
        if (record.get("type") == "tool_result" and record.get("status") == "ok")
        or record.get("type") == "tool_result_cached"
    ]


def tool_spec(
    value: Any,
    *,
    default_minimum: int = 1,
) -> tuple[str, int, Mapping[str, Any]] | None:
    """Normalize one required or forbidden tool expectation."""
    if isinstance(value, str):
        return value, default_minimum, {}
    if not isinstance(value, Mapping) or not isinstance(value.get("name"), str):
        return None
    minimum = value.get("min_calls", default_minimum)
    arguments = value.get("arguments", {})
    if (
        not isinstance(minimum, int)
        or minimum < 0
        or not isinstance(arguments, Mapping)
    ):
        return None
    return value["name"], minimum, arguments


def usage_error(usage: Mapping[str, Any]) -> str | None:
    """Reconcile provider totals with per-iteration usage records."""
    totals = usage.get("totals")
    iterations = usage.get("per_iteration")
    if not isinstance(totals, Mapping) or not isinstance(iterations, list):
        return "totals must be an object and per_iteration must be an array"
    fields = ("input_tokens", "output_tokens", "total_tokens")
    if any(
        not isinstance(totals.get(field), int)
        or isinstance(totals[field], bool)
        or totals[field] < 0
        for field in (*fields, "calls")
    ):
        return "usage totals must contain non-negative integer token counts and calls"
    sums = Counter({field: 0 for field in fields})
    for item in iterations:
        if not isinstance(item, Mapping):
            return "per_iteration entries must be objects"
        for field in fields:
            value = item.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                return f"per_iteration {field} must be a non-negative integer"
            sums[field] += value
    if any(sums[field] != totals[field] for field in fields):
        return f"provider totals disagree with per_iteration sums: {dict(sums)}"
    if totals["calls"] != len(iterations):
        return "totals.calls disagrees with the number of per_iteration records"
    return None


def within_limit(observed: Any, limit: Any) -> bool:
    """Compare non-boolean integer observations and limits."""
    return (
        isinstance(observed, int)
        and not isinstance(observed, bool)
        and isinstance(limit, int)
        and not isinstance(limit, bool)
        and observed <= limit
    )
