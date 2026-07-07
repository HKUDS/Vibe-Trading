# Agent Eval and Regression

Agent eval verifies that the agent obeys IRR-AGL boundaries under deterministic
record/replay conditions. It must not depend on real LLMs, real brokers, real
external market data, or user secrets.

## Components

- `agent/src/evals/agent_eval/case_schema.py`: schema-versioned eval cases.
- `agent/src/evals/agent_eval/runner.py`: deterministic runner.
- `agent/src/evals/agent_eval/scorer.py`: expected event and policy scoring.
- `agent/tests/agent_eval`: regression tests.

## Case Design

Cases should specify:

- prompt or event input,
- tool manifests and surface,
- expected policy decisions,
- expected allowed or denied tool calls,
- expected structured warnings or hard failures,
- replay fixtures instead of live LLM/broker/network calls.

## Required Regression Themes

- R4/R5 shadow deny in observe and warn.
- Remote API and channel bot shell denial.
- Scheduler live-write denial.
- Prompt-injected MCP URL denial for swarm.
- Agent inability to commit live mandates.
- Scorecard and Research Card hard-failure visibility.
- Old traces and run cards remain readable when reliability flags are off.

## CI Rules

Agent eval should run in normal CI as a deterministic unit test suite. Do not
add tests that require live credentials or network access. If a new case needs a
large fixture, keep it sanitized and schema-versioned.
