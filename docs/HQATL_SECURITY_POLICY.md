# HQATL Security Policy

## Defaults

- HQATL is analysis-only by default.
- Live execution is disabled.
- Order-capable development requires a separate, explicit human approval before work begins.

## Secrets and credentials

- Never commit credentials, tokens, account identifiers, private keys, or secret configuration to Git.
- Use `.env` locally and keep it ignored.
- Provide only placeholder names in `.env.example`; never include real or realistic secret values.
- Never place secrets in prompts, logs, screenshots, test fixtures, issue text, commit messages, or documentation.
- Rotate and revoke any secret suspected of exposure; do not merely delete it from the latest commit.

## Public repository warning

Treat the current repository as public. Private proprietary research, account information, licensed datasets, private scripts, and restricted source material must not be committed without explicit legal, security, and human review.

## Dependency and supply-chain controls

- Review package necessity, provenance, license, maintenance, vulnerabilities, checksums/locks, and transitive risk before adoption.
- Prefer pinned/locked reproducible dependencies and minimal privileges.
- Do not install packages during documentation or audit-only phases.

## Provider and execution controls

- Separate provider adapters from strategy logic and isolate execution capability.
- Use least-privilege practice/demo credentials during any later approved integration.
- Require visible environment and account-mode indicators, audit logging that redacts secrets, and explicit human confirmation before order-capable development or activation.
- Never infer live-trading authorization from approval of analysis, historical data, practice data, or dashboard work.

## Review

Security review is required before provider integration, dependency changes, handling proprietary data, or any order-capable work.
