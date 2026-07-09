# SBOM Summary

Evidence date: 2026-07-09

This is a repository-level dependency source summary, not a generated CycloneDX
or SPDX machine artifact. `pip-audit` was installed and run against the
sanitized Python requirements file.

## Python Sources

- `pyproject.toml`
- `agent/requirements.txt`

Primary direct runtime dependencies include: `rich`, `pyyaml`, `langchain`,
`langgraph`, `python-dotenv`, `httpx`, `defusedxml`, `oauth-cli-kit`, `pandas`,
`numpy`, `scipy`, `duckdb`, `scikit-learn`, `joblib`, `tushare`, `requests`,
`yfinance`, `akshare`, `ccxt`, `fastapi`, `uvicorn`, `websockets`, `pydantic`,
`python-multipart`, `sse-starlette`, `fastmcp`, `ddgs`, `jinja2`,
`matplotlib`, and `weasyprint`.

## Frontend Sources

- `frontend/package.json`
- `frontend/package-lock.json`

Primary direct frontend dependencies include: `react`, `react-dom`,
`react-router-dom`, `echarts`, `highlight.js`, `i18next`, `lucide-react`,
`clsx`, and `tailwind-merge`. Development dependencies include Vite,
TypeScript, Vitest, Testing Library, Tailwind, PostCSS, and jsdom.

## Security Tool Status

- `semgrep`: installed locally, AGS paths scanned, 0 findings.
- `bandit`: installed locally, AGS Python paths scanned, no issues identified.
- `pip-audit`: installed locally, requirements audit found no known
  vulnerabilities.
- `gitleaks`: unavailable locally.
