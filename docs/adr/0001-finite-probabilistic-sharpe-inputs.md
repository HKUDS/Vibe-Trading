# Reject undefined probabilistic Sharpe summaries

## Context

The public probabilistic Sharpe helper validates the observed ratio but permits non-finite benchmarks, observation counts, skew and kurtosis. NaN inputs can return NaN; infinite benchmarks or counts can return zero or one, making undefined summaries look like confidence estimates. The helper is exported through the existing quantlib tool allowlist. This is ordinary numerical input validation, not an authentication or execution-boundary finding.

## Decision

Require finite values for every scalar summary before the existing minimum sample, moment-range and positive variance checks. Consolidate the previous observed-Sharpe check in this admission loop. Leave valid finite-input calculations and count typing unchanged.

## Alternatives

Let SciPy propagate undefined inputs, or mask undefined outputs after computation. Neither explains which supplied summary is invalid; masking a numeric zero or one would fail to distinguish an infinite input from a legitimate probability.

## Consequences

Invalid summaries raise a field-specific ValueError before producing research confidence. Finite inputs retain the same formula, Gaussian reference checks and existing moment constraints. Derived overflow from extreme finite inputs and integer-only observation counts remain outside this patch.

## Validation

Frozen base300c6aa6989fcf2ec1cb052c89237b48fabdb524 with the same regression matrix produced45 passes and12 failures. Three observed-Sharpe rejection controls passed; two already rejected cases failed the stronger field-specific diagnostic, and the remaining ten were admitted incorrectly. Candidate multiple-testing and benchmark integration suites passed64 tests. Compile and whitespace checks passed. Synthetic summaries only; no market-data download, credential, broker, provider, external server, or live trading path. Full application suite was not run; the contributor guide permits narrow checks matching changed files. Dependency installation and unsuccessful initial missing-pydantic test collection are retained separately.

Actual public-tool replay used a valid JSON numeric exponent `benchmark_sharpe: -1e309`: Python decoded it to negative infinity. Frozen QuantlibCallTool returned `ok=true, result=1.0`; candidate returned `ok=false` with the field-specific finite-input error. Only the pure calculation tool was invoked. All four open PR file inventories were checked; none changes multipletesting.py or its tests. Closest merged contract analogue is Rudy PR1659 (non-finite attribution input rejection, merged2026-10-04), distinct module and tests.
