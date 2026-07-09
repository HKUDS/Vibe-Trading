# Known Limitations

- Alpha Genesis decisions remain research labels only. They do not authorize,
  prepare, submit, cancel, flatten, or route live orders.
- Demo data is deterministic fixture data, not live market data.
- PBO/DSR support is advisory proxy coverage in this package, not full CSCV
  PBO.
- External PIT data vendor adapters and production data governance workflows
  are not completed here.
- `semgrep`, `bandit`, and `pip-audit` were installed and run locally for this
  validation pass. `gitleaks` was not installed; Semgrep `p/secrets` and
  repository redaction tests provide the current secret-scan evidence.
- GitHub CLI was not installed locally, so PR creation may require the GitHub
  web compare flow unless a GitHub app tool is available.
- `rg` was denied by the sandbox; changed-file boundary search used
  PowerShell `Select-String`.
- Frontend build passes but Vite reports large bundle chunks. This is a
  performance warning, not a failed build.
- The forward store is append-only by code contract; external backup,
  retention, and disaster recovery are operator responsibilities.
