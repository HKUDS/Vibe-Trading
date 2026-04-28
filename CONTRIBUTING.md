# Contributing to Vibe-Trading

Thanks for your interest in contributing! This guide will help you get started.

## Quick Links

- [Discord](https://discord.gg/2vDYc2w5) — ask questions, discuss ideas
- [Issues](https://github.com/HKUDS/Vibe-Trading/issues) — bug reports & feature requests
- [Good First Issues](https://github.com/HKUDS/Vibe-Trading/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — great starting points

## Development Setup

```bash
git clone https://github.com/HKUDS/Vibe-Trading.git
cd Vibe-Trading
python -m venv .venv
source .venv/bin/activate      # Linux/macOS
# .venv\Scripts\Activate.ps1   # Windows

pip install -e ".[dev]"
cp agent/.env.example agent/.env
# Edit agent/.env — set your LLM provider
```

### Run tests

```bash
pytest --ignore=agent/tests/e2e_backtest --tb=short -q
```

### Start dev servers

```bash
# Terminal 1: API server
vibe-trading serve --port 8899

# Terminal 2: Frontend
cd frontend && npm install && npm run dev
```

## Project Structure

| Directory | What lives here | Open to contribute? |
|-----------|----------------|:-------------------:|
| `agent/src/skills/` | 69 finance skill definitions (SKILL.md) | Yes |
| `agent/src/tools/` | 21 agent tools | Yes |
| `agent/backtest/` | Backtest engines, loaders, optimizers | Yes |
| `agent/src/swarm/presets/` | 29 swarm preset YAMLs | Yes |
| `frontend/` | React 19 + Vite web UI | Yes |
| `agent/src/agent/` | ReAct agent core (loop, context, skills) | Ask first |
| `agent/src/session/` | Session management | Ask first |
| `agent/src/providers/` | LLM provider abstraction | Ask first |

> **Core modules** (`agent/`, `session/`, `providers/`) are protected — please open an issue to discuss before modifying.

## How to Contribute

### Reporting Bugs

Use the [Bug Report](https://github.com/HKUDS/Vibe-Trading/issues/new?template=bug_report.yml) template. Include:

- Steps to reproduce
- Expected vs actual behavior
- Your environment (OS, Python version, provider)
- Error logs if available

### Suggesting Features

Use the [Feature Request](https://github.com/HKUDS/Vibe-Trading/issues/new?template=feature_request.yml) template.

### Submitting Code

1. **Fork & branch** — create a feature branch from `main`
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Make changes** — follow the code standards below

3. **Test** — add or update tests, ensure `pytest` passes
   ```bash
   pytest --ignore=agent/tests/e2e_backtest --tb=short -q
   ```

4. **Commit** — use [Conventional Commits](https://www.conventionalcommits.org/)
   ```
   feat: add RSI divergence skill
   fix: handle empty DataFrame in backtest loader
   docs: update CLI reference table
   test: add crypto engine edge cases
   ```

5. **Pull Request** — open a PR against `main` with:
   - Summary of changes
   - Related issue number (e.g., `Closes #42`)
   - Test plan

## Code Standards

- **Python**: Google-style docstrings, type hints encouraged
- **No hardcoding**: config via `.env`, YAML, or constants
- **Delete unused code** — don't comment-preserve
- **OKX pairs**: use `BTC-USDT` format (hyphen, uppercase)
- **UI text**: English. LLM output follows user language
- **File size**: aim for < 400 lines, max 800

## Contribution Roadmap

### Easy: New Skill

Each skill is a single `SKILL.md` file in `agent/src/skills/<category>/<skill-name>/`. Categories: `data-source`, `strategy`, `analysis`, `asset-class`, `crypto`, `flow`, `tool`. Look at existing skills for the format.

### Easy: New Swarm Preset

A YAML file in `agent/src/swarm/presets/` defining agents, roles, and DAG workflow. See existing presets.

### Medium: New Data Source Loader

1. Create `agent/backtest/loaders/<source>.py`
2. Implement the `DataLoader` Protocol (see `agent/backtest/loaders/base.py`)
3. Register in `agent/backtest/loaders/registry.py`
4. Add tests in `agent/tests/`

### Medium: Portfolio Optimizer Constraints

Current optimizers (`agent/backtest/optimizers/`) support basic weight optimization. We need:
- **Leverage constraints** — max gross exposure limits
- **Sector/group caps** — weight limits per sector or asset group
- **Turnover penalties** — transaction cost-aware rebalancing
- Extend `BaseOptimizer` interface, keep backward compatibility

### Medium: Correlation Heatmap Dashboard

Add a cross-asset correlation matrix component to the frontend:
- Time-window slider (30d / 60d / 90d / 1Y)
- Hierarchical clustering for sector grouping
- ECharts heatmap or custom canvas renderer
- Wire to a new API endpoint that computes rolling correlations

### Hard: Intraday Backtest Engine

Current engines run on daily bars. We need sub-daily execution:
- Support 1m / 5m / 15m / 30m / 1H / 4H intervals
- Handle market session boundaries (pre-market, after-hours, overnight gaps)
- Intraday margin / buying power tracking
- Integrate with minute-level data loaders (OKX klines, yfinance intraday)
- Start from `BaseEngine` — see `agent/backtest/engines/base.py` for the abstract interface

### Hard: Options Volatility Surface & Greeks Visualization

Build 3D implied-vol surface and Greeks charts in the frontend:
- **Vol surface**: strike vs. expiry vs. implied vol (3D mesh or contour)
- **Greeks dashboard**: delta, gamma, theta, vega curves across strikes
- **Skew chart**: 25-delta risk reversal over time
- Backend: extend `options_pricing_tool.py` to return surface data
- Frontend: ECharts GL for 3D, or custom WebGL renderer

### Hard: Monte Carlo & Stress Testing

Add scenario simulation and tail-risk analysis:
- **Monte Carlo**: generate N return paths from fitted distribution, compute VaR/CVaR confidence intervals
- **Historical stress tests**: replay specific crisis periods (2008, 2020 COVID, 2022 crypto winter)
- **Regime switching**: HMM-based regime detection (bull/bear/sideways), conditional risk metrics
- Output: distribution plots, drawdown probability curves, worst-case tables
- Can be a new tool in `agent/src/tools/` or an extension to the backtest engine

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
