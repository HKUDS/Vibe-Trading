"""Independent numeric and latency checks over persisted execution artifacts."""

from __future__ import annotations

import csv
import json
import math
from pathlib import PurePosixPath

from .artifacts import ArtifactBundle, JSON_LIMIT_BYTES
from .schema import HarnessCase, Verdict, VerdictStatus

OPERATORS = {"approx", "equals", "gte", "lte", "finite"}


def validate_measurements(values) -> None:
    """Refuse ambiguous, unbounded or escaping evaluator specifications."""
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError("measurements must contain at most 100 assertions")
    for entry in values:
        if not isinstance(entry, dict):
            raise ValueError("measurement must be an object")
        path = PurePosixPath(str(entry.get("artifact", "")))
        if path.is_absolute() or ".." in path.parts or path.suffix not in {".json", ".csv"}:
            raise ValueError("measurement artifacts must be relative JSON/CSV paths inside the run")
        if not isinstance(entry.get("field"), str) or not entry["field"]:
            raise ValueError("measurement field is required")
        if entry.get("operator") not in OPERATORS:
            raise ValueError("unsupported measurement operator")
        if entry["operator"] != "finite" and "expected" not in entry:
            raise ValueError("measurement expected value is required")
        if entry["operator"] in {"approx", "gte", "lte"}:
            expected = entry["expected"]
            if type(expected) not in (int, float) or not math.isfinite(expected):
                raise ValueError("numeric expectations must be finite numbers")
        tolerance = entry.get("absolute_tolerance", 1e-8)
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance)
            or tolerance < 0
        ):
            raise ValueError("measurement tolerance must be finite and non-negative")
        row = entry.get("row", 0)
        if type(row) is not int or not 0 <= row < 100000:
            raise ValueError("measurement row must be an integer in [0, 100000)")


def _lookup(value, field):
    for part in field.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def measurement_verdicts(case: HarnessCase, bundle: ArtifactBundle) -> list[Verdict]:
    """Compare stored measurements to case-owned expectations, never to themselves."""
    verdicts = []
    for index, entry in enumerate(case.expect.get("measurements", [])):
        code = f"financial.measurement.{index}"
        relative = entry["artifact"]
        path = (bundle.run_dir / relative).resolve()
        observed = None
        detail = None
        try:
            if not path.is_relative_to(bundle.run_dir):
                raise ValueError("measurement path escapes the run")
            if not path.exists():
                status = VerdictStatus.NOT_EVALUABLE
                detail = "required measurement artifact was not persisted"
            else:
                if path.stat().st_size > JSON_LIMIT_BYTES:
                    raise ValueError("measurement artifact exceeds the read limit")
                if path.suffix == ".json":
                    value = json.loads(path.read_text(encoding="utf-8"))
                else:
                    with path.open(encoding="utf-8-sig", newline="") as stream:
                        reader = csv.DictReader(stream)
                        value = next((row for i, row in enumerate(reader) if i == entry.get("row", 0)), None)
                    if value is None:
                        raise ValueError("measurement row is missing")
                observed = _lookup(value, entry["field"])
                operator = entry["operator"]
                expected = entry.get("expected")
                if operator == "equals":
                    passed = observed == expected and (
                        type(observed) is type(expected)
                        if isinstance(observed, bool) or isinstance(expected, bool)
                        else True
                    )
                else:
                    if isinstance(observed, bool):
                        raise ValueError("a boolean is not a numeric measurement")
                    number = float(observed)
                    if not math.isfinite(number):
                        passed = False
                    elif operator == "finite":
                        passed = True
                    elif operator == "approx":
                        passed = math.isclose(
                            number, float(expected), rel_tol=0, abs_tol=entry.get("absolute_tolerance", 1e-8)
                        )
                    elif operator == "gte":
                        passed = number >= float(expected)
                    else:
                        passed = number <= float(expected)
                status = VerdictStatus.PASS if passed else VerdictStatus.FAIL
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            status = VerdictStatus.INVALID_ARTIFACT
            detail = str(exc)
        if type(observed) is float and not math.isfinite(observed):
            observed = str(observed)
        verdicts.append(Verdict(status, code, entry, observed, (f"{relative}#/{entry['field']}",), detail))
    timing = case.expect.get("timing")
    if timing is not None:
        starts = [row.get("ts") for row in bundle.trace if row.get("type") == "start"]
        ends = [row.get("ts") for row in bundle.trace if row.get("type") == "end"]
        observed = None
        status = VerdictStatus.NOT_EVALUABLE
        if starts and ends:
            first, last = starts[0], ends[-1]
            if (
                type(first) in (int, float)
                and type(last) in (int, float)
                and math.isfinite(first)
                and math.isfinite(last)
                and last >= first
            ):
                observed = last - first
                status = VerdictStatus.PASS if observed <= timing["max_seconds"] else VerdictStatus.FAIL
            else:
                status = VerdictStatus.INVALID_ARTIFACT
        verdicts.append(Verdict(status, "latency.total_seconds", timing, observed, ("trace.jsonl:start/end.ts",)))
    return verdicts
