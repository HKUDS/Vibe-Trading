"""Deterministic assertions over a Harness case and persisted artifacts."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .artifacts import ArtifactBundle
from .methodology import manifest_verdict
from .observations import (
    contains as _contains,
    mapping as _mapping,
    string_list as _string_list,
    successful_tool_records as _successful_tool_records,
    tool_spec as _tool_spec,
    usage_error as _usage_error,
    within_limit as _within_limit,
)
from .schema import HarnessCase, Verdict, VerdictStatus


def evaluate_assertions(
    case: HarnessCase, bundle: ArtifactBundle
) -> tuple[Verdict, ...]:
    """Evaluate every supported contract section in a stable order."""
    verdicts: list[Verdict] = []
    verdicts.extend(_prompt_verdicts(case, bundle))
    verdicts.append(_execution_verdict(case, bundle))
    verdicts.extend(_future_state_verdicts(case, bundle))
    verdicts.extend(_tool_verdicts(case, bundle))
    verdicts.append(_tool_result_join_verdict(bundle))
    verdicts.extend(_identity_verdicts(case, bundle))
    verdicts.extend(_evidence_verdicts(case, bundle))
    verdicts.extend(_budget_verdicts(case, bundle))
    verdicts.extend(_risk_verdicts(case, bundle))
    verdicts.append(manifest_verdict(bundle))
    return tuple(verdicts)


def _verdict(
    status: VerdictStatus,
    code: str,
    expected: Any,
    observed: Any,
    *refs: str,
    detail: str | None = None,
) -> Verdict:
    return Verdict(status, code, expected, observed, tuple(refs), detail)


def _artifact_problem(
    bundle: ArtifactBundle, key: str, *, missing_invalid: bool
) -> VerdictStatus | None:
    if key in bundle.errors:
        return VerdictStatus.INVALID_ARTIFACT
    if key not in bundle.present:
        return (
            VerdictStatus.INVALID_ARTIFACT
            if missing_invalid
            else VerdictStatus.NOT_EVALUABLE
        )
    return None


def _prompt_verdicts(case: HarnessCase, bundle: ArtifactBundle) -> list[Verdict]:
    problem = _artifact_problem(bundle, "req", missing_invalid=True)
    if problem:
        return [
            _verdict(
                problem,
                "prompt.request_preserved",
                case.prompt,
                bundle.errors.get("req"),
                "req.json",
                detail="req.json is required to prove the original request",
            )
        ]
    observed = bundle.req.get("prompt") if bundle.req else None
    req_status = VerdictStatus.PASS if observed == case.prompt else VerdictStatus.FAIL
    verdicts = [
        _verdict(
            req_status,
            "prompt.request_preserved",
            case.prompt,
            observed,
            "req.json#/prompt",
        )
    ]

    trace_problem = _artifact_problem(bundle, "trace", missing_invalid=True)
    if trace_problem:
        verdicts.append(
            _verdict(
                trace_problem,
                "prompt.trace_preserved",
                case.prompt,
                bundle.errors.get("trace"),
                "trace.jsonl",
            )
        )
        return verdicts
    user_record = next(
        (
            record
            for record in bundle.trace
            if record.get("type") == "message" and record.get("role") == "user"
        ),
        None,
    )
    if user_record is None:
        verdicts.append(
            _verdict(
                VerdictStatus.NOT_EVALUABLE,
                "prompt.trace_preserved",
                case.prompt,
                None,
                "trace.jsonl",
                detail="this trace has no user message record",
            )
        )
    else:
        trace_prompt = user_record.get("content")
        status = (
            VerdictStatus.PASS if trace_prompt == case.prompt else VerdictStatus.FAIL
        )
        verdicts.append(
            _verdict(
                status,
                "prompt.trace_preserved",
                case.prompt,
                trace_prompt,
                f"trace.jsonl:{user_record['_line']}",
            )
        )
    return verdicts


def _execution_verdict(case: HarnessCase, bundle: ArtifactBundle) -> Verdict:
    expectation = _mapping(case.expect.get("execution"))
    allowed = expectation.get("allowed")
    state_problem = _artifact_problem(bundle, "state", missing_invalid=True)
    trace_problem = _artifact_problem(bundle, "trace", missing_invalid=True)
    if state_problem or trace_problem:
        errors = {
            key: bundle.errors.get(key, "missing")
            for key in ("state", "trace")
            if key not in bundle.present or key in bundle.errors
        }
        return _verdict(
            VerdictStatus.INVALID_ARTIFACT,
            "execution.reconciled_status",
            allowed,
            errors,
            "state.json",
            "trace.jsonl",
        )
    state_status = bundle.state.get("status") if bundle.state else None
    end_records = [record for record in bundle.trace if record.get("type") == "end"]
    raw_end_statuses = [record.get("status") for record in end_records]
    end_statuses = [_execution_status(item) for item in raw_end_statuses]
    observed = {
        "state": state_status,
        "trace_end": raw_end_statuses,
        "normalized_trace_end": end_statuses,
    }
    if (
        not isinstance(state_status, str)
        or not end_records
        or any(not isinstance(item, str) for item in end_statuses)
    ):
        return _verdict(
            VerdictStatus.INVALID_ARTIFACT,
            "execution.reconciled_status",
            allowed,
            observed,
            "state.json#/status",
            "trace.jsonl",
        )
    if any(item != state_status for item in end_statuses):
        return _verdict(
            VerdictStatus.INVALID_ARTIFACT,
            "execution.reconciled_status",
            allowed,
            observed,
            "state.json#/status",
            *(f"trace.jsonl:{record['_line']}" for record in end_records),
            detail="terminal artifacts disagree",
        )
    if not isinstance(allowed, list) or not all(
        isinstance(item, str) for item in allowed
    ):
        return _verdict(
            VerdictStatus.FAIL,
            "case.execution_allowed_invalid",
            "string array",
            allowed,
        )
    status = VerdictStatus.PASS if state_status in allowed else VerdictStatus.FAIL
    return _verdict(
        status,
        "execution.reconciled_status",
        allowed,
        state_status,
        "state.json#/status",
        f"trace.jsonl:{end_records[-1]['_line']}",
    )


def _future_state_verdicts(case: HarnessCase, bundle: ArtifactBundle) -> list[Verdict]:
    verdicts: list[Verdict] = []
    for key in ("completion", "safety"):
        expectation = _mapping(case.expect.get(key))
        if not expectation:
            continue
        allowed = expectation.get("allowed")
        field_name = f"{key}_status"
        state_problem = _artifact_problem(bundle, "state", missing_invalid=True)
        if state_problem:
            verdicts.append(
                _verdict(
                    state_problem,
                    f"{key}.status",
                    allowed,
                    bundle.errors.get("state", "missing"),
                    "state.json",
                )
            )
            continue
        observed = bundle.state.get(field_name) if bundle.state else None
        if observed is None:
            verdicts.append(
                _verdict(
                    VerdictStatus.NOT_EVALUABLE,
                    f"{key}.status",
                    allowed,
                    None,
                    f"state.json#/{field_name}",
                    detail=f"{field_name} is not instrumented in this run",
                )
            )
        else:
            status = (
                VerdictStatus.PASS
                if isinstance(allowed, list) and observed in allowed
                else VerdictStatus.FAIL
            )
            verdicts.append(
                _verdict(
                    status,
                    f"{key}.status",
                    allowed,
                    observed,
                    f"state.json#/{field_name}",
                )
            )
    return verdicts


def _tool_verdicts(case: HarnessCase, bundle: ArtifactBundle) -> list[Verdict]:
    expectation = _mapping(case.expect.get("tools"))
    if not expectation:
        return []
    problem = _artifact_problem(bundle, "trace", missing_invalid=True)
    if problem:
        return [
            _verdict(
                problem,
                "tools.trace_available",
                expectation,
                bundle.errors.get("trace"),
                "trace.jsonl",
            )
        ]
    calls = [record for record in bundle.trace if record.get("type") == "tool_call"]
    verdicts: list[Verdict] = []
    for index, required in enumerate(expectation.get("required", [])):
        spec = _tool_spec(required)
        if spec is None:
            verdicts.append(
                _verdict(
                    VerdictStatus.FAIL,
                    "case.tool_requirement_invalid",
                    "tool spec",
                    required,
                )
            )
            continue
        name, minimum, arguments = spec
        matches = [
            record
            for record in calls
            if record.get("tool") == name and _contains(record.get("args"), arguments)
        ]
        verdicts.append(
            _verdict(
                VerdictStatus.PASS if len(matches) >= minimum else VerdictStatus.FAIL,
                f"tools.required.{index}",
                required,
                {"matching_calls": len(matches)},
                *(f"trace.jsonl:{record['_line']}" for record in matches),
            )
        )
    for index, forbidden in enumerate(expectation.get("forbidden", [])):
        spec = _tool_spec(forbidden, default_minimum=1)
        if spec is None:
            verdicts.append(
                _verdict(
                    VerdictStatus.FAIL,
                    "case.tool_forbidden_invalid",
                    "tool spec",
                    forbidden,
                )
            )
            continue
        name, _, arguments = spec
        matches = [
            record
            for record in calls
            if record.get("tool") == name and _contains(record.get("args"), arguments)
        ]
        verdicts.append(
            _verdict(
                VerdictStatus.PASS if not matches else VerdictStatus.FAIL,
                f"tools.forbidden.{index}",
                forbidden,
                {"matching_calls": len(matches)},
                *(f"trace.jsonl:{record['_line']}" for record in matches),
            )
        )
    if expectation.get("max_false_skips") is not None:
        skips = [
            record for record in bundle.trace if record.get("type") == "tool_skipped"
        ]
        verdicts.append(
            _verdict(
                VerdictStatus.NOT_EVALUABLE,
                "tools.false_skips",
                {"max": expectation.get("max_false_skips")},
                {"observed_skip_records": len(skips)},
                *(f"trace.jsonl:{record['_line']}" for record in skips),
                detail="current tool_skipped records omit arguments and policy, so false skips cannot be classified",
            )
        )
    return verdicts


def _identity_verdicts(case: HarnessCase, bundle: ArtifactBundle) -> list[Verdict]:
    expectation = _mapping(case.expect.get("identity"))
    if not expectation:
        return []
    problem = _artifact_problem(bundle, "grounding", missing_invalid=True)
    if problem:
        return [
            _verdict(
                problem,
                "identity.artifact_available",
                expectation,
                bundle.errors.get("grounding", "missing"),
                "artifacts/grounding_evidence.json",
            )
        ]
    identity = _mapping(bundle.grounding.get("identity") if bundle.grounding else None)
    verdicts: list[Verdict] = []
    expected_status = expectation.get("status")
    if expected_status is not None:
        observed = identity.get("status")
        verdicts.append(
            _verdict(
                (
                    VerdictStatus.PASS
                    if observed == expected_status
                    else VerdictStatus.FAIL
                ),
                "identity.status",
                expected_status,
                observed,
                "artifacts/grounding_evidence.json#/identity/status",
            )
        )
    expected_symbols = expectation.get("authorized_symbols")
    if expected_symbols is not None:
        observed_symbols = identity.get("authorized_symbols")
        valid = (
            _string_list(expected_symbols) is not None
            and _string_list(observed_symbols) is not None
        )
        matches = valid and set(observed_symbols) == set(expected_symbols)
        verdicts.append(
            _verdict(
                VerdictStatus.PASS if matches else VerdictStatus.FAIL,
                "identity.authorized_symbols",
                expected_symbols,
                observed_symbols,
                "artifacts/grounding_evidence.json#/identity/authorized_symbols",
            )
        )
    forbidden = expectation.get("forbidden_symbols", [])
    observed_symbols = _string_list(identity.get("authorized_symbols")) or []
    if forbidden:
        violations = (
            sorted(set(forbidden) & set(observed_symbols))
            if _string_list(forbidden) is not None
            else forbidden
        )
        verdicts.append(
            _verdict(
                VerdictStatus.PASS if not violations else VerdictStatus.FAIL,
                "identity.forbidden_symbols",
                forbidden,
                violations,
                "artifacts/grounding_evidence.json#/identity/authorized_symbols",
            )
        )
    constraint = expectation.get("constraint")
    if constraint is not None:
        constraint_records = [
            item
            for record in identity.get("records", [])
            if isinstance(record, Mapping)
            for item in record.get("resolution_constraints", [])
            if isinstance(item, Mapping)
        ]
        if not constraint_records:
            verdicts.append(
                _verdict(
                    VerdictStatus.NOT_EVALUABLE,
                    "identity.constraint",
                    constraint,
                    None,
                    "artifacts/grounding_evidence.json#/identity/records/*/resolution_constraints",
                    detail="constraint provenance is not instrumented in this run",
                )
            )
        else:
            matching = [
                item for item in constraint_records if _contains(item, constraint)
            ]
            verdicts.append(
                _verdict(
                    VerdictStatus.PASS if matching else VerdictStatus.FAIL,
                    "identity.constraint",
                    constraint,
                    constraint_records,
                    "artifacts/grounding_evidence.json#/identity/records/*/resolution_constraints",
                )
            )
    return verdicts


def _evidence_verdicts(case: HarnessCase, bundle: ArtifactBundle) -> list[Verdict]:
    expectation = _mapping(case.expect.get("evidence"))
    if not expectation:
        return []
    problem = _artifact_problem(bundle, "grounding", missing_invalid=True)
    if problem:
        return [
            _verdict(
                problem,
                "evidence.artifact_available",
                expectation,
                bundle.errors.get("grounding"),
                "artifacts/grounding_evidence.json",
            )
        ]
    grounding = bundle.grounding or {}
    evidence = grounding.get("evidence")
    validations = grounding.get("validations")
    if not isinstance(evidence, list) or not isinstance(validations, list):
        return [
            _verdict(
                VerdictStatus.INVALID_ARTIFACT,
                "evidence.schema",
                {"evidence": "array", "validations": "array"},
                {
                    "evidence": type(evidence).__name__,
                    "validations": type(validations).__name__,
                },
                "artifacts/grounding_evidence.json",
            )
        ]
    symbols = {
        item.get("symbol")
        for item in evidence
        if isinstance(item, Mapping) and isinstance(item.get("symbol"), str)
    }
    required = expectation.get("required_symbols", [])
    missing = (
        sorted(set(required) - symbols)
        if _string_list(required) is not None
        else required
    )
    verdicts = [
        _verdict(
            VerdictStatus.PASS if not missing else VerdictStatus.FAIL,
            "evidence.required_symbols",
            required,
            {"observed_symbols": sorted(symbols), "missing": missing},
            "artifacts/grounding_evidence.json#/evidence",
        )
    ]
    issue_codes = {
        issue.get("code")
        for validation in validations
        if isinstance(validation, Mapping)
        for issue in validation.get("issues", [])
        if isinstance(issue, Mapping) and isinstance(issue.get("code"), str)
    }
    forbidden = expectation.get("forbidden_issue_codes", [])
    violations = (
        sorted(set(forbidden) & issue_codes)
        if _string_list(forbidden) is not None
        else forbidden
    )
    verdicts.append(
        _verdict(
            VerdictStatus.PASS if not violations else VerdictStatus.FAIL,
            "evidence.forbidden_issue_codes",
            forbidden,
            {"observed_issue_codes": sorted(issue_codes), "violations": violations},
            "artifacts/grounding_evidence.json#/validations",
        )
    )
    return verdicts


def _budget_verdicts(case: HarnessCase, bundle: ArtifactBundle) -> list[Verdict]:
    expectation = _mapping(case.expect.get("budget"))
    if not expectation:
        return []
    verdicts: list[Verdict] = []
    end_records = [record for record in bundle.trace if record.get("type") == "end"]
    observed_iterations = end_records[-1].get("iterations") if end_records else None
    for gate in ("max_llm_calls", "max_iterations"):
        limit = expectation.get(gate)
        if limit is None:
            continue
        trace_problem = _artifact_problem(bundle, "trace", missing_invalid=True)
        if trace_problem:
            verdicts.append(
                _verdict(
                    trace_problem,
                    f"budget.{gate}",
                    limit,
                    bundle.errors.get("trace", "missing"),
                    "trace.jsonl",
                )
            )
            continue
        observed = observed_iterations
        if observed is None:
            verdicts.append(
                _verdict(
                    VerdictStatus.NOT_EVALUABLE,
                    f"budget.{gate}",
                    limit,
                    None,
                    "trace.jsonl",
                )
            )
        else:
            status = (
                VerdictStatus.PASS
                if _within_limit(observed, limit)
                else VerdictStatus.FAIL
            )
            verdicts.append(
                _verdict(
                    status,
                    f"budget.{gate}",
                    limit,
                    observed,
                    f"trace.jsonl:{end_records[-1]['_line']}",
                )
            )

    input_limit = expectation.get("max_input_tokens")
    if input_limit is not None:
        problem = _artifact_problem(bundle, "llm_usage", missing_invalid=False)
        if problem:
            verdicts.append(
                _verdict(
                    problem,
                    "budget.max_input_tokens",
                    input_limit,
                    bundle.errors.get("llm_usage"),
                    "llm_usage.json",
                )
            )
        else:
            usage_error = _usage_error(bundle.llm_usage or {})
            totals = _mapping((bundle.llm_usage or {}).get("totals"))
            if usage_error:
                verdicts.append(
                    _verdict(
                        VerdictStatus.INVALID_ARTIFACT,
                        "budget.max_input_tokens",
                        input_limit,
                        usage_error,
                        "llm_usage.json",
                    )
                )
            elif (
                isinstance(observed_iterations, int)
                and totals.get("calls") != observed_iterations
            ):
                verdicts.append(
                    _verdict(
                        VerdictStatus.NOT_EVALUABLE,
                        "budget.max_input_tokens",
                        input_limit,
                        {
                            "reported_input_tokens": totals.get("input_tokens"),
                            "usage_calls": totals.get("calls"),
                            "llm_calls": observed_iterations,
                        },
                        "llm_usage.json",
                        f"trace.jsonl:{end_records[-1]['_line']}",
                        detail="provider usage is missing for one or more LLM calls",
                    )
                )
            else:
                observed = totals.get("input_tokens")
                status = (
                    VerdictStatus.PASS
                    if _within_limit(observed, input_limit)
                    else VerdictStatus.FAIL
                )
                verdicts.append(
                    _verdict(
                        status,
                        "budget.max_input_tokens",
                        input_limit,
                        observed,
                        "llm_usage.json#/totals/input_tokens",
                    )
                )

    for gate in ("max_visible_tools", "max_tool_schema_tokens"):
        limit = expectation.get(gate)
        if limit is not None:
            verdicts.append(
                _verdict(
                    VerdictStatus.NOT_EVALUABLE,
                    f"budget.{gate}",
                    limit,
                    None,
                    "trace.jsonl",
                    detail=f"{gate} requires per-LLM-call tool-surface instrumentation",
                )
            )
    return verdicts


def _risk_verdicts(case: HarnessCase, bundle: ArtifactBundle) -> list[Verdict]:
    expectation = _mapping(case.expect.get("risk"))
    if not expectation:
        return []
    if "trace" in bundle.errors or "trace" not in bundle.present:
        return [
            _verdict(
                VerdictStatus.INVALID_ARTIFACT,
                "risk.trace_available",
                expectation,
                bundle.errors.get("trace"),
                "trace.jsonl",
            )
        ]
    successful = _successful_tool_records(bundle.trace)
    verdicts: list[Verdict] = []
    forbidden = expectation.get("forbidden_successful_tools", [])
    violations = [record for record in successful if record.get("tool") in forbidden]
    verdicts.append(
        _verdict(
            VerdictStatus.PASS if not violations else VerdictStatus.FAIL,
            "risk.forbidden_successful_tools",
            forbidden,
            sorted({record.get("tool") for record in violations}),
            *(f"trace.jsonl:{record['_line']}" for record in violations),
        )
    )
    maximum = expectation.get("max_authorization_bypasses")
    if maximum is not None:
        blocked_calls = {
            record.get("call_id"): record
            for record in bundle.trace
            if record.get("type") == "tool_call" and record.get("blocked") is True
        }
        bypasses = [
            record for record in successful if record.get("call_id") in blocked_calls
        ]
        bypasses.extend(
            record
            for record in bundle.trace
            if record.get("type") == "authorization_bypass"
        )
        status = (
            VerdictStatus.PASS
            if _within_limit(len(bypasses), maximum)
            else VerdictStatus.FAIL
        )
        verdicts.append(
            _verdict(
                status,
                "risk.authorization_bypasses",
                maximum,
                len(bypasses),
                *(f"trace.jsonl:{record['_line']}" for record in bypasses),
            )
        )
    return verdicts


def _tool_result_join_verdict(bundle: ArtifactBundle) -> Verdict:
    problem = _artifact_problem(bundle, "trace", missing_invalid=True)
    if problem:
        return _verdict(
            problem,
            "tools.result_join",
            "consistent call/result records",
            bundle.errors.get("trace"),
            "trace.jsonl",
        )
    calls = [record for record in bundle.trace if record.get("type") == "tool_call"]
    results = [record for record in bundle.trace if record.get("type") == "tool_result"]
    calls_by_id: dict[Any, Mapping[str, Any]] = {}
    problems: list[str] = []
    for call in calls:
        call_id = call.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            problems.append(f"line {call['_line']}: tool_call has no call_id")
        elif call_id in calls_by_id:
            problems.append(f"line {call['_line']}: duplicate tool_call id {call_id}")
        else:
            calls_by_id[call_id] = call
    result_ids: set[str] = set()
    outcomes = Counter()
    for result in results:
        call_id = result.get("call_id")
        call = calls_by_id.get(call_id)
        if call is None:
            problems.append(f"line {result['_line']}: orphan tool_result id {call_id}")
            continue
        if call_id in result_ids:
            problems.append(
                f"line {result['_line']}: duplicate tool_result id {call_id}"
            )
        result_ids.add(call_id)
        if call.get("tool") != result.get("tool"):
            problems.append(f"line {result['_line']}: tool name differs from its call")
        if result.get("status") not in {"ok", "error"}:
            problems.append(f"line {result['_line']}: invalid tool_result status")
        outcome = (
            "blocked"
            if call.get("blocked") is True
            else str(result.get("status") or "unknown")
        )
        outcomes[outcome] += 1
    outcomes["unfinished"] = sum(
        1 for call_id in calls_by_id if call_id not in result_ids
    )
    outcomes["cached"] = sum(
        1 for record in bundle.trace if record.get("type") == "tool_result_cached"
    )
    outcomes["skipped"] = sum(
        1 for record in bundle.trace if record.get("type") == "tool_skipped"
    )
    return _verdict(
        VerdictStatus.INVALID_ARTIFACT if problems else VerdictStatus.PASS,
        "tools.result_join",
        "consistent call/result records",
        {"outcomes": dict(sorted(outcomes.items())), "problems": problems},
        "trace.jsonl",
    )


def _execution_status(value: Any) -> Any:
    return "failed" if value == "error" else value
