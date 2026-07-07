---
name: private-company-research
category: analysis
description: "Deep research framework for pre-IPO / private companies (Ant Group, SpaceX, Stripe, ByteDance...). Six analyst lenses — business model, financial forensics, competitive landscape, risk & governance, tech & IP, alternative-data signals — run in parallel via run_swarm, then cross-validated for signal consistency before any verdict. Built around the core challenge of private-company work: information is scarce, so every data point carries a confidence label (high / medium / low), inference is shown separately from fact, and 'I don't know' is a valid output. Outputs a fair-value range, exit-path analysis, and an information-gap map. Use for any unlisted company where you need to judge what the business is actually worth."
---

# Private-Company Research: Multi-Lens Deep Framework

Deep research on an unlisted company (e.g. Ant Group, ByteDance, SpaceX, Stripe).

**Ultimate goal**: under information scarcity, recover the company's **true value** — not the market valuation, but what the business is actually worth.

## Framework Characteristics

Private vs public research: no standardized financials (multi-source patchwork + cross-validation); few valuation anchors (funding rounds, comparables, scenarios); large information asymmetry ("jigsaw" research); uncertain exit path (IPO / M&A / secondary).

## AI Research Bias Self-Check (core premise)

Private companies are where AI bias is worst. Watch for:

- **False conservatism** — with little data, AI gives conservative/vague conclusions, but scarce data ≠ bad company.
- **False precision** — to fill the template, AI disguises "reasonable guess" as "sourced analysis".
- **Comparables trap** — forcing a public-comp overlay inherits public-market logic and misses private-specific value.
- **Survivorship bias** — what's searchable online is mostly company-propagated good news.

**Counter**: prefer leaving blanks ("I don't know") over filling tables with speculation to fake certainty; label every data point with confidence (🟢high/🟡medium/🔴low); separate verifiable fact from inference; when information is extremely scarce, switch to "first-principles mode" and answer only: ① what real problem does this business solve? ② why this team? ③ ceiling if it succeeds / how it dies if it fails? ④ the key validation node at this stage?

> Invert the asymmetry: the market knows little about private companies → pricing is inefficient → that's exactly where alpha may live.

## Execution

Six lenses, best run **in parallel** (via `run_swarm`, one worker per lens; or sequentially via `web_search`):

| Role | Lens |
|------|------|
| business-decoder | Business model + product/user analysis: "what is this business, essentially" |
| financial-detective | Financial patchwork + valuation: "recover the true financial picture under missing data" |
| competitive-mapper | Industry + competition + substitution: "who competes, who could disrupt" |
| risk-governance-analyst | Risk全景 + management/governance/investors: "what could go wrong, who's at the helm" |
| tech-ip-analyst | Tech stack / patents / R&D / moat: "is the tech barrier real and durable" |
| signal-miner | Alternative data (hiring / patents / litigation / app / supply chain): "clues beyond the usual sources" |

You (team-lead) integrate, patch the picture, cross-validate, output the final report.

## Lens 1: Business Model & Users (business-decoder)

- **Core business definition**: one sentence (Duan Yongping style: plain language to a smart layperson). What problem? For whom? If the company didn't exist, what would users do? Is demand rigid (cut in a downturn)?
- **Revenue model**: ads/commission/subscription/take-rate/financial/SaaS/hardware; mix and trend; monetization efficiency (ARPU / take rate / conversion); recurring vs one-off; concentration; predictability.
- **Unit economics**: CAC (paid vs organic, by channel, trend), LTV, LTV/CAC, payback, marginal cost, scale-inflection point.
- **Product matrix & flywheel**: core + extension + incubation; network/data/scale flywheel; iteration speed.
- **Users**: MAU/DAU (from QuestMobile/Sensor Tower/SimilarWeb), S-curve stage, stickiness (DAU/MAU, retention), profile, reputation (App Store trend, social sentiment).
- **Moat (6 dimensions, ★1-5)**: network effects, switching costs, brand mind, data barrier, regulatory license, scale economies — each with evidence + trend (widening/stable/narrowing) + durability. Overall: wide/narrow/none.

## Lens 2: Financial Detective

No standard financials; multi-source patchwork + cross-validation. **Every data point: source, time, confidence, derivation.**

**Source priority**: 🟢 prospectus/regulatory filings, parent-company annual report disclosure, regulatory penalties, bond/ABS offering documents → 🟡 business registry, funding news, third-party reports, deep media (LatePost/The Information/36Kr/Bloomberg) → 🔴 industry extrapolation, ex-employee leaks.

**Key metrics**: revenue (scale/growth/mix/quantity×price), cost (gross margin/R&D/sales/G&A rates, vs peers), profit (EBITDA/net income/profitability timeline), cash flow (operating/burn rate/runway), efficiency (per-capita revenue, capital efficiency).

**Cross-validation**: list every source for the same metric; check convergence across methods; flag single-source ("isolated evidence") data.

**Funding history**: full timeline (round/amount/valuation/lead investor); health of the curve, interval, down-rounds, whether existing investors keep participating; latest-round terms (liquidation preference / anti-dilution / ratchet) and their effect on common-share value.

**Valuation (multi-method)**: ① last-round (adjust for liquidation prefs, 20-40% discount); ② comparable public comps (3-5, PS/PE/EV-EBITDA, liquidity discount 20-30%); ③ DCF scenarios (bear/base/bull, each assumption grounded); ④ terminal-value rollback (5/10y terminal state → implied IRR); ⑤ transaction comps (recent M&A/funding multiples).

**Valuation synthesis**: do the methods converge? If divergent, explain. Distinguish "fair value" and "conservative (margin-of-safety) value".

## Lens 3: Competitive Landscape (competitive-mapper)

- **Market**: TAM/SAM/SOM, penetration, stage (emergence/growth/mature/decline), growth drivers.
- **Value chain** (text map): upstream → company's link (profit pool share) → downstream; bargaining power; structural shifts.
- **Porter's five forces** (★1-5): rivalry, new entrants, substitutes, supplier power, buyer power.
- **Competitor scan**: direct/indirect/substitute/potential entrants (giants) — share, funding, strengths, weaknesses, threat level. Multi-dimensional compare with 2-3 closest competitors.
- **Dynamics**: last-12-month changes; infer competitor strategy from hiring/patents/products; tech (esp. AI) and regulation effects; winner-take-all vs oligopoly.
- **Scenarios**: company wins / coexistence / disrupted — conditions and probabilities.
- **Global benchmarks**: overseas analogs, path, valuation, post-IPO performance, and benchmark limitations.

## Lens 4: Risk & Governance (risk-governance-analyst)

- **Founder/CEO**: background, foresight (3-year prediction accuracy), execution (promise delivery), values, controversies. ★1-5.
- **Core team**: backgrounds, 2-year talent flow (who left/joined, net), complementarity, culture signals (Glassdoor trends), key-person dependency.
- **Equity & governance**: founder control (dual-class / concerted action / VIE), dilution trend, employee equity; board, related-party, same-industry competition, majority/minority conflicts.
- **Investor roster**: lead-investor brand, strategic capital synergy, exit pressure (fund life / secondary sales / ratchet maturity), red flags.
- **Risk matrix**: regulatory / competition / tech / talent / funding / IPO / geopolitical / monetization / governance / compliance / macro / ESG — each probability × impact × severity × hedgeability × monitor.
- **Exit paths**: A/HK/US IPO, M&A, secondary, SPAC, stay-private — probability, window, valuation, preconditions, obstacles.
- **Worst case (Munger inversion)**: 3 specific failure paths + probabilities; liquidation value; why smart money doesn't invest (≥5 reasons); failed analogs; the "thesis broken" signal.

## Lens 5: Tech & IP (tech-ip-analyst)

- **Tech stack**: inferred from hiring/blog/open-source/talks; tech-debt signals (refactor hiring, stack switches, outage complaints).
- **Patents** (Google Patents/CNIPA/USPTO): total/pending/last-2y/field/citation/international; quality (core patents? aligned to business? litigation?); trend; vs competitors.
- **R&D**: investment (headcount/expense rate vs peers), output (papers/conferences/open-source/blog), efficiency (research-to-product, commercialization).
- **Tech talent**: core leaders' backgrounds, density (top-institution share), comp competitiveness, attrition signals, hiring direction (→ strategy).
- **Tech moat (★1-5)**: algorithm/model, data, engineering, talent, ecosystem — each with durability (AI-era half-life may be short).
- **AI/new-tech impact**: is the company a beneficiary or a target of disruption?

## Lens 6: Alternative-Data Signals (signal-miner)

> Private companies have limited conventional info; alt-data often beats news.

- **Hiring** (LinkedIn/Boss/Indeed): scale/trend, structure (R&D/product/sales/data/international/compliance/IR — IR hiring = IPO signal; compliance = regulatory or IPO; JD tech stack = strategy).
- **App/product** (App Store/七麦/SimilarWeb): rank, rating trend, downloads, update frequency, complaint themes, web traffic.
- **Social sentiment** (Weibo/Zhihu/Xiaohongshu/X/Reddit): official engagement, organic discussion, KOL views, negative events, insider leaks.
- **Business/legal** (天眼查/企查查): registry/paid-in/equity changes/subsidiaries (new = new biz; deregistered = contraction)/scope changes; litigation/arbitration/penalties/enforcement.
- **Supply chain**: known suppliers (if listed, check their filings), procurement, partner evaluation.
- **Digital footprint**: registered domains (new = new biz), subdomains (api/pay → architecture), trademarks (new brands).
- **Industry exposure**: exec talks, awards, government/association interaction, media frequency/quality.
- **Secondary-market signals** (if any): SharesPost/EquityZen, implied valuation vs last round, employee selling.

**Anomaly list (most important)**: things inconsistent with the company's narrative; inconsistent with industry norms; sudden changes (hiring freeze / executive departures); unexplained.

## Cross-Validation (team-lead, mandatory)

Before synthesis, the team-lead must:

1. **Data conflict arbitration**: same metric across sources — list all, state which is adopted and why.
2. **Signal consistency matrix**: business-growth signal vs hiring trend? tech-leadership narrative vs patent/talent data? valuation level vs competitive position? management narrative vs action signals? (contradictions must be explained)
3. **Information jigsaw**: white zones (known) / gray (clues but uncertain) / black (unknown).
4. **Bias check**: is positive info detailed while negative is brief? Does every positive judgment have a reverse check?

## Final Report Structure

1. **One-line conclusion** (50-100 words): what's it worth, why.
2. **Company snapshot** (with confidence column).
3. **Six-lens scorecard** (★1-5 + core judgment + confidence + completeness), overall score.
4. **Key data jigsaw** (only cross-validated, with source count + confidence).
5. **Signal-consistency matrix**.
6. **Per-lens summary** (3-5 top findings each).
7. **Fair value assessment**: business essence + 7-dimension moat card + 5-method valuation + **fair value range** (conservative/reasonable/optimistic + current market valuation + margin of safety %).
8. **Investment thesis**: bull 5-7 (with sources) vs bear 5-7 (with sources), which side is stronger.
9. **Risk matrix** (top 3 + mitigation).
10. **Exit-path assessment**.
11. **Investment decision table** (one-pager: core logic 3 sentences + value range + key assumptions & validation nodes + fatal risks & "thesis broken" signals + conclusion + expected return/timeline).
12. **Information-gap map** (dimension / known / missing / missing-impact / how-to-get): does the gap affect the core conclusion? If yes, state "under missing X, conclusion confidence is Y".
13. **Tracking checklist** (item / frequency / source / metric / alert threshold).
14. **Summary paragraph** (150-250 words).

Save via `write_file` to `reports/{company}/{company}-private-{YYYYMMDD}.md`. Run `report_audit` on the numbers as a quality gate.

## Data Labeling Standard (strict)

- Every key data point: **source** (specific to media + article), **time** (year/month), **confidence** (🟢 prospectus/official / 🟡 credible media / 🔴 estimate/rumor).
- Conflicting data: **list all** + explain difference and adoption.
- **Separate fact from inference**: fact in normal text; inference in *italics* with derivation.
- Missing info: explicitly mark "data missing"; never fabricate.

## Key Principles

1. **6 lenses in parallel** (`run_swarm`, or sequential).
2. **Transparent derivation** — show the math and assumptions; don't hand-wave numbers.
3. **Cross-validate** — key data ≥2 sources; conflicts all listed.
4. **Signal-consistency check** — mandatory cross-lens check at synthesis.
5. **Clear conclusion** — don't dodge invest/watch/avoid; state confidence.
6. **Search in both EN and CN** — private-company info spans both.
7. **Honest blanks** — distinguish "sourced analysis" from "speculative fill"; "this dimension lacks data, no meaningful conclusion" is acceptable.
8. **Alt-data is not noise** — hiring/patents/litigation/app data may be closer to truth than news.
9. **True-value focus** — the goal is what the business is worth, not a pretty report. If info can't support a reliable valuation, say so.
10. **Scarce data ≠ bad company** — short AI output ≠ low certainty. Under extreme scarcity, switch to first-principles mode.
