# Alpha Genesis Known Limitations

- The A-share demo data is deterministic fixture data, not a live market data feed.
- PBO/DSR support is proxy-only in this phase and is reported as advisory.
- The forward tracking store is append-only for observations, but external backup and retention are operator concerns.
- Candidate promotion stops at research/paper-style states; production readiness is intentionally unreachable.
- Financial-quality PIT data adapters are not completed in this package.
- The read-only API exposes stored artifacts only; it does not start mining jobs.
- `mutmut` is installed for mutation testing, but it explicitly does not support native Windows execution. Run mutation testing from WSL/Linux for a CI mutation score gate.
