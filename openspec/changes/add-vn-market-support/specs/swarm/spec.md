# Delta for swarm

## ADDED Requirements

### Requirement: Three Vietnam Swarm Presets
The package MUST ship at least 3 VN-focused swarm presets bundled in `src.swarm`:

1. `vn_investment_committee` — multi-agent VN equity research desk
2. `vn_derivatives_desk` — VN30 spot vs VN30F basis arbitrage workflow
3. `vn_value_screener` — VAS fundamental screening + TA timing

#### Scenario: Discoverability after install
- GIVEN a fresh `pip install vibe-trading-ai`
- WHEN the user runs `vibe-trading --swarm-presets`
- THEN the 3 VN presets are listed alongside the existing 29
- AND the total presets count is at least 32

### Requirement: VN Investment Committee DAG
The `vn_investment_committee` preset MUST define a DAG with: a root research node, parallel bull and bear analyst nodes, a VAS fundamentals node, a foreign-room/margin risk-review node, and a terminal recommendation node.

#### Scenario: Parallel bull/bear with VN risk review
- GIVEN the preset runs with `vars_json = {"topic":"FPT Q2 outlook"}`
- WHEN the swarm executes
- THEN bull and bear nodes execute in parallel after research
- AND the risk-review node receives outputs from BOTH plus foreign-room data
- AND the final recommendation explicitly cites foreign room and margin status

### Requirement: VN Locale in Swarm Output
When the harness locale is set to `vi-VN`, swarm preset prompts and final reports MUST render in Vietnamese with appropriate finance terminology.
