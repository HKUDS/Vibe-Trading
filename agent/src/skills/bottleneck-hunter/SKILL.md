---
name: bottleneck-hunter
category: strategy
description: "Supply-chain bottleneck arbitrage. Given a super-trend (AI infra, energy transition, defense, semiconductor reshoring, space economy), decompose its physical supply chain down to Layer 2/3 choke points (optics, lasers, InP/SOI substrates, IC substrates, probe cards, specialty fiberglass...) and surface under-the-radar listed companies sitting on each bottleneck. Scores each link on 6 scarcity criteria, applies mandatory valuation gates (PS/PE/safety-margin) via the financial_rigor tool, and Munger-style reverse-validates. Outputs a ranked bottleneck opportunity board. Use when the user wants hidden beneficiaries of a structural trend rather than already-priced leaders."
---

# Supply-Chain Bottleneck Hunter

Decompose a super-trend (user-specified, e.g. "AI infrastructure", "energy transition") into its physical supply chain and hunt for bottleneck-arbitrage opportunities.

## Core Idea

Don't ask "which AI stock to buy" — ask "if this trend keeps expanding, which link runs out first?"

Traditional research chases leaders and known tracks. This skill inverts: **start from the choke points of the physical supply chain and find companies nobody notices but that the whole industry must wait on when they run short.**

The edge: Layer-1 bottlenecks (GPU, HBM, power) are already priced in. The real alpha is in **Layer 2 and Layer 3** — optical modules, lasers, InP substrates, SOI wafers, epitaxy equipment, wafer-level test, IC substrates, specialty fiberglass.

## Step 1: Super-Trend Confirmation

### Trend Filter Criteria

| Criterion | Requirement | How to verify |
|-----------|-------------|---------------|
| Durability | ≥3-5 years of certain growth | Search industry forecasts, capex plans |
| Physicality | Needs real hardware/material/equipment build | Distinguish "software upgrade" from "physical expansion" |
| Scale | Global capex >$50B/year | Search top players' capex guidance |
| Acceleration | Demand growth > supply expansion | Compare demand growth vs capacity plans |

Use `web_search` to verify. Reference super-trends: AI infrastructure, energy transition (nuclear/grid/storage), defense modernization, semiconductor reshoring, space economy.

## Step 2: Physical Supply-Chain Decomposition

Don't stop at concepts — decompose to physical entities.

```
Layer 0 (end): final product/service
Layer 1 (core component): already closely watched  → priced in, limited alpha
Layer 2 (sub-component/material): low attention, alpha-rich
Layer 3 (upstream equipment/raw material)
Layer 4 (infrastructure): power, cooling, land, talent, certifications
```

### AI Infrastructure Example

```
Layer 0: AI model training/inference services
Layer 1: GPU/accelerators, HBM, servers, data centers
Layer 2 (focus zone):
  - Network interconnect: optical modules, fiber, switch ASICs, copper cables
  - Optical comms core: lasers (EML/VCSEL/CW), modulators, photodetectors
  - Semiconductor materials: InP substrates, GaAs substrates, SOI wafers, SiC substrates
  - Advanced packaging: CoWoS interposers, HBM TSV, ABF substrate film
  - PCB/substrate: high-frequency PCB, IC substrates, specialty fiberglass
  - Test: wafer-level test (probe cards), burn-in, ATE
  - Thermal/cooling: liquid cooling, CDU, immersion fluid
  - Power connection: busbars, UPS, distribution, transformers
Layer 3: epitaxy equipment (MOCVD/MBE), lithography/etch, high-purity metals (In/Ga/Ge), specialty gases, sputtering targets, certifications (MSA/Telcordia)
Layer 4: power (nuclear/gas/transmission), cooling water, data-center land/permits
```

For other trends, use `web_search` with queries like `{trend} supply chain bottleneck`, `{trend} shortage critical component`, `{trend} capacity constraint`, `{trend} sole source supplier`.

## Step 3: Bottleneck Identification — Finding "Choke Points"

For each Layer 2-3 link, evaluate 6 criteria:

| # | Criterion | Question | Score |
|---|-----------|----------|-------|
| 1 | Supply concentration | ≤3 global suppliers? | 🔴 ≤2 / 🟡 3-5 / 🟢 >5 |
| 2 | Expansion lead time | How long to add capacity? | 🔴 >2y / 🟡 1-2y / 🟢 <1y |
| 3 | Substitutability | Can other tech/material replace it? | 🔴 irreplaceable / 🟡 partial / 🟢 easy |
| 4 | Capacity utilization | Current utilization? | 🔴 >90% / 🟡 70-90% / 🟢 <70% |
| 5 | Demand growth | Downstream demand growth? | 🔴 >50%/yr / 🟡 20-50% / 🟢 <20% |
| 6 | Customer qualification cycle | How long for a new supplier to qualify? | 🔴 >1y / 🟡 6-12m / 🟢 <6m |

**Bottleneck grade**: 🔴×≥4 → **S-grade** (single-point failure, highest priority); 🔴×3 → **A-grade** (severely constrained); 🔴×1-2 → **B-grade** (stressed but manageable); no 🔴 → not a bottleneck, skip.

## Step 4: Company Screening — From Bottleneck to Tickers

For each S/A-grade bottleneck, use `web_search` / `screen_market` to find listed companies.

### Initial Screen

| Criterion | Requirement |
|-----------|-------------|
| Listing status | Listed (A/HK/US/JP/TW/EU) |
| Bottleneck revenue share | >30% of revenue from the bottleneck link |
| Market cap | Prefer <$10B (large caps already priced) |
| Liquidity | Average daily turnover >$1M |

### Valuation Gate (mandatory, never skip)

**A real bottleneck ≠ an investment opportunity.** For every company, compute PE/PB/ROE/FCF yield with `financial_rigor` (`command=verify_valuation`), and run `financial_rigor` (`command=three_scenario`) for scenario valuation:

- **Red light** (any one → signal strength capped at ★★, flag "valuation stretched"): market cap >20% of TAM; PS>30x with revenue growth <100%; market cap >10× 5-year optimistic revenue forecast; stock doubled within 60 days of a follow-on offering.
- **Yellow light** (needs extra justification, else downgrade): loss-making + PS>15x; PS >5× a profitable peer; PE>80x (compute PEG).
- **Green light** (bonus): PS<10x with revenue growing; PE<30x with a moat (flag "margin of safety").

**Sanity check (mandatory)**: with `financial_rigor` (`command=three_scenario`), answer — "buying at current market cap, if the most optimistic scenario fully plays out and I exit at 25× PE in 10 years, what's the annualized return?" <10%/yr → flag "no margin of safety at current price".

## Step 5: Cross-Validation — Don't Trust a Single Story

### Positive checks

| Check | Question |
|-------|----------|
| Customer validation | Have top customers signed/imported? (check announcements, customer filings) |
| Revenue validation | Is the bottleneck already showing in revenue growth? (last 2-3 quarters) |
| Price validation | Is the product raising price? (industry quotes, analyst reports) |
| Capacity validation | Is capacity really tight? (lead times, customer complaints) |
| Capital validation | Is there expansion capex? (company guidance) |

Use `get_financial_statements` / `get_stock_news` / `web_search`.

### Reverse checks (Munger inversion)

- Why don't smart people buy this stock?
- Can the bottleneck be bypassed? Alternative routes?
- Can China / other players quickly replicate capacity?
- If end-demand drops 50%, what happens to this company?
- Has management diluted at highs before?
- What growth assumption does the current valuation imply?

## Step 6: Output — Bottleneck Opportunity Board

### Ranking Table

| Rank | Company | Ticker | Mkt Cap | Revenue | PS | PE | Bottleneck link | Grade | Share | Growth | Signal | Valuation |
|------|---------|--------|---------|---------|-----|-----|-----------------|-------|-------|--------|--------|-----------|

**Market cap, revenue, PS, PE are mandatory** — never skip with "TBD". If financials can't be obtained, signal strength ≤★★.

Signal strength (valuation gate directly affects):
- ★★★★★ multi-cross-validated + customers imported + revenue confirmed + valuation green
- ★★★★ most checks pass + valuation green/yellow (with explanation)
- ★★★ logic holds but parts unverified + valuation yellow acceptable
- ★★ early signal, or logic holds but valuation red
- ★ pure concept, unverified

After drafting, run `report_audit` (`command=extract` → verify each point → `command=verdict`) as a quality gate to ensure no hallucinated numbers.

### One-Pager Template

```
🎯 {Company} ({Ticker}) — {one-line bottleneck positioning}

Why it's a bottleneck: (2-3 sentences)
Why this company: (2-3 sentences)

Catalyst timeline:
- Near-term (1-3m): [earnings / capacity / customer win]
- Mid-term (3-12m): [industry trend / expansion node]

Key risks: 1.  2.

Key data: market cap / revenue / PS / PE / growth / bottleneck revenue share
Margin of safety: 10y 25× PE exit method, annualized return XX%. Conclusion: yes/no.

Cross-validation status: ✅ customer / ✅ revenue / ⚠️ valuation stretched / ❌ unverified

Conclusion: deep research / watchlist / skip
```

Save with `write_file` to the reports directory (e.g. `reports/bottleneck-map/{trend}-bottleneck-{YYYYMMDD}.md`).

## Step 7: Inventory Update — Maintain the Bottleneck Map

On each run: ① re-check identified bottlenecks (new suppliers? capacity expanded? substitute breakthrough?); ② scan new bottlenecks (`web_search` last 7 days supply chain / shortage / bottleneck news); ③ update grades (upgrade/downgrade/relieve).

## AI Research Bias Self-Check

| Bias | Symptom | Counter |
|------|---------|---------|
| Leader-bias | Search dominated by large caps | Deliberately search small-cap suppliers, add "small cap" |
| English-bias | Miss JP/KR/TW players | Must search JP/KR/TW market suppliers |
| Narrative-bias | Drawn to "AI concept" labels | Look only at actual supply-chain position, not market labels |
| Confirmation-bias | After finding a bottleneck, only seek positive evidence | Force Step 5 reverse checks |
| Recency-bias | Rely on stale info | Prefer last 30 days of data |

## Core Principles (highest priority)

1. **Don't ask the AI to recommend stocks — ask it to decompose supply chains.** The question matters more than the answer.
2. **Physical first** — only links that need real physical product/material/equipment.
3. **Layer 2 and Layer 3** — don't chase already-priced leaders.
4. **Cross-validate** — every conclusion needs ≥2 independent sources.
5. **Be honest about uncertainty** — if data is missing, say so; don't fill with speculation.
6. **Bottlenecks are temporary** — every bottleneck gets resolved; the key is timing the window.
7. **Small cap ≠ good opportunity** — a small cap can also be a bad company; it must pass financial quality.
8. **A real bottleneck ≠ an investment** — at PS>30x or still loss-making, the current price is not a buy. **Valuation is a hard gate that cannot be overridden by bottleneck purity, signal strength, or narrative appeal.** Better to miss a bottleneck stock that ran than buy a loss-making company at 100× sales.
